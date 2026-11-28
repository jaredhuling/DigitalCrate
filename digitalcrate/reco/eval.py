"""The evaluation harness: one fixed way to answer "is model B better than model A?" for every surface.

    python -m digitalcrate reco eval [--task T] [--model M] [--split S] [--quick]

Pieces
  Source     the library database opened read-only, a snapshot of its feature tables (everything but the label
             tables) in memory, and `masked(hide, until)`: a fresh in-memory database holding copies of the label
             tables (log.ADAPTERS) without the held-out items' rows (nor rows about them: log.about) and without anything
             from after `until`, with the
             feature snapshot attached. Unqualified table names resolve to the copies first, then the features.
  Task       builds Examples from the log (item, label, weight, group, ts, query, context) and its splits:
             grouped k-fold with seeds, and forward in time. Optional per-fold test filter and slices.
  Model      fit(train) -> scorer(items, contexts) -> scores (NaN where it can't score). train.con is the masked
             database, train.examples the training examples. That is all a model ever sees, so it cannot read a
             held-out label: every label of a held-out item is gone from its database (for the sample task: stars,
             ✕, listens and collections, as taste_report.accuracy hides them), and in a forward split everything
             from after the cut is too. Contexts carry only label-free facts (Mashup's frozen features, an edit's
             family and its sound difference).
  Metrics    AUC and average precision; within-query AUC, NDCG@k and recall@k where examples have a query (a Mashup
             slot in a session, a pair test's source sample); log loss and expected calibration error for models whose
             scores are probabilities. Each is the mean over folds, with a 95% bootstrap interval from resampling
             groups (songs, sources...); paired comparison of each model with the task's reference model (the current
             one) on the same folds and resamples: the difference, its interval and the folds won.
  Results    <DATA_DIR>/reco/runs/<timestamp>-<task>.json; latest() reads the newest per task; table() prints them.

A task with too few positives or negatives (fewer than min_class) reports that instead of a number.
"""
import hashlib
import json
import sqlite3
import subprocess
import time
import zlib
from contextlib import contextmanager
from dataclasses import dataclass, field

import numpy as np

from .. import config as C
from . import log as L

RUNS = C.DATA_DIR / "reco" / "runs"
BOOT = 1000
LABEL_TABLES = set(L.ADAPTERS) | {"collections", "taste_history", "reco_impressions", "shootout_votes", "drum_labels"}


def open_ro(path=None):
    """The library database, read-only (writes raise)."""
    con = sqlite3.connect(f"file:{path or C.DB_PATH}?mode=ro", uri=True, timeout=60)
    con.row_factory = sqlite3.Row
    return con


@contextmanager
def using(module, name, value):
    """Temporarily replace module.name (e.g. taste._db, so existing code reads the masked database)."""
    old = getattr(module, name)
    setattr(module, name, value)
    try:
        yield
    finally:
        setattr(module, name, old)


# ---------------------------------------------------------------- the source and masked views

class Source:
    """The library, read-only, and masked copies of its label tables for training."""
    _n = 0

    def __init__(self, path=None):
        self.path = str(path or C.DB_PATH)
        self.con = open_ro(self.path)
        Source._n += 1
        self._feat_uri = f"file:reco_features_{id(self)}_{Source._n}?mode=memory&cache=shared"
        self._feat = None
        self._rows = {}
        self._its = {}

    def features(self):
        """The in-memory snapshot of every non-label table (made once; held open while this Source lives)."""
        if self._feat is None:
            f = sqlite3.connect(self._feat_uri, uri=True)
            self.con.backup(f)
            for (t,) in f.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
                if t in LABEL_TABLES:
                    f.execute(f"DROP TABLE [{t}]")
            f.commit()
            self._feat = f
        return self._feat

    def label_rows(self, table):
        if table not in self._rows:
            if not L._has(self.con, table):
                self._rows[table] = None
            else:
                sql = self.con.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()[0]
                cols = [r[1] for r in self.con.execute(f"PRAGMA table_info([{table}])")]
                rows = self.con.execute(f"SELECT rowid, {', '.join(f'[{c}]' for c in cols)} FROM [{table}]").fetchall()
                self._rows[table] = (sql, cols, [tuple(r) for r in rows])
                self._its[table] = [(it.context["_src"][1], L.about(it.item), it.ts) for it in L.ADAPTERS[table](self.con)]
        return self._rows[table]

    def masked(self, hide=(), until=None):
        """A connection on which the label tables hold only what a model may learn from."""
        self.features()
        hide = set(hide)
        m = sqlite3.connect("file::memory:", uri=True)
        m.row_factory = sqlite3.Row
        m.execute("ATTACH DATABASE ? AS lib", (self._feat_uri,))
        for t in L.ADAPTERS:
            got = self.label_rows(t)
            if got is None:
                continue
            sql, cols, rows = got
            bad = {rid for rid, about, ts in self._its[t] if about & hide or (until is not None and (ts or 0) >= until)}
            m.execute(sql)
            names = ", ".join(f"[{c}]" for c in cols)
            ins = f"INSERT INTO [{t}] (rowid, {names}) VALUES ({', '.join('?' * (len(cols) + 1))})"
            blank = L.HIDE.get(t)
            if blank:  # keep the row, drop its label
                ix = [cols.index(c) + 1 for c in blank if c in cols]
                rows = [tuple(None if (r[0] in bad and k in ix) else v for k, v in enumerate(r)) for r in rows]
            else:
                rows = [r for r in rows if r[0] not in bad]
            m.executemany(ins, rows)
        m.commit()
        return m

    def signature(self):
        """What the labels were when measured: row counts and last rowids of the label tables, and a short hash."""
        sig = {}
        for t in L.ADAPTERS:
            if L._has(self.con, t):
                sig[t] = list(self.con.execute(f"SELECT COUNT(*), MAX(rowid) FROM [{t}]").fetchone())
        return dict(tables=sig, hash=hashlib.sha1(json.dumps(sig, sort_keys=True).encode()).hexdigest()[:10])

    def close(self):
        for c in (self.con, self._feat):
            if c is not None:
                c.close()


# ---------------------------------------------------------------- examples, folds, training views

@dataclass
class Example:
    item: tuple
    label: float
    weight: float = 1.0
    group: object = None       # what is resampled for intervals (and split on, unless the split says otherwise)
    ts: float = None
    query: object = None       # ranking within a query: a Mashup slot in a session, a pair test's source
    context: dict = field(default_factory=dict)  # label-free facts the scorer may use


@dataclass
class Fold:
    split: str
    name: str
    test: list                 # example indices
    train: list
    until: float = None        # forward split: only what was known before this time
    seed: int = None

    def hide(self, examples):
        return {examples[i].item for i in self.test}


def kfold(examples, k=5, seeds=(0, 1), key=lambda e: e.group, split="song"):
    """Grouped k-fold: the groups (sorted, then shuffled per seed) dealt round-robin into k folds. Deterministic.
    With key = the item and k=5, seeds (0, 1) these are exactly taste_report.accuracy's folds."""
    keys = [key(e) for e in examples]
    uniq = sorted(set(keys), key=lambda g: (str(type(g)), g) if isinstance(g, (int, float, str)) else (str(type(g)), str(g)))
    out = []
    for seed in seeds:
        arr = np.array(uniq) if all(isinstance(g, str) for g in uniq) else np.array(uniq + [None], dtype=object)[:-1]
        np.random.default_rng(seed).shuffle(arr)
        for f in range(k):
            held = set(arr[f::k].tolist())
            test = [i for i, g in enumerate(keys) if g in held]
            out.append(Fold(split, f"s{seed}k{f}", test, [i for i in range(len(keys)) if keys[i] not in held], seed=seed))
    return out


def forward(examples, min_pos=18, split="forward", pos=lambda e: e.label > 0):
    """Forward in time: examples in time order, cut into chunks of about min_pos positives; each chunk is tested on a
    model trained only on what happened before its first example (the first chunk has nothing before it). A last
    chunk with fewer positives is dropped (as taste_report.forward does)."""
    order = sorted(range(len(examples)), key=lambda i: examples[i].ts or 0)
    chunks, cur = [], []
    for i in order:
        cur.append(i)
        if sum(pos(examples[j]) for j in cur) >= min_pos:
            chunks.append(cur)
            cur = []
    out = []
    for c, ch in enumerate(chunks[1:], 1):
        cut = examples[ch[0]].ts
        out.append(Fold(split, f"t{c}", ch, [i for i in order if (examples[i].ts or 0) < cut], until=cut))
    return out


@dataclass
class Train:
    con: object                # the masked database
    examples: list             # the training examples (labels included)
    fold: Fold
    task: str
    cache: dict = field(default_factory=dict)  # shared by the models of one fold (e.g. one taste fit, many parts)

    @property
    def until(self):
        return self.fold.until

    def items(self):
        from .items import Items
        if "_items" not in self.cache:
            self.cache["_items"] = Items(self.con)
        return self.cache["_items"]


class Model:
    """A baseline or a candidate. fit(train) -> scorer(items, contexts) -> np.array of scores (higher = more likely
    positive; NaN where it can't score: those get the fold's mean score and count against coverage)."""
    proba = False

    def __init__(self, name, fit, proba=False, about=""):
        self.name, self._fit, self.proba, self.about = name, fit, proba, about

    def fit(self, train):
        return self._fit(train)


def random_model(name="random"):
    def fit(train):
        rng = np.random.default_rng(zlib.crc32(f"{train.task}/{train.fold.split}/{train.fold.name}".encode()))
        return lambda items, ctx: rng.random(len(items))
    return Model(name, fit, about="a coin: what guessing scores")


# ---------------------------------------------------------------- metrics (weighted: the bootstrap's weights)

def auc(y, s, w=None):
    """Weighted Mann-Whitney AUC with ties counted half. None without both classes."""
    y = np.asarray(y, bool); s = np.asarray(s, float)
    w = np.ones(len(y)) if w is None else np.asarray(w, float)
    W1, W0 = w[y].sum(), w[~y].sum()
    if W1 <= 0 or W0 <= 0:
        return None
    u, inv = np.unique(s, return_inverse=True)
    wp = np.bincount(inv, w * y, len(u)); wn = np.bincount(inv, w * ~y, len(u))
    below = np.cumsum(wn) - wn
    return float((wp * (below + 0.5 * wn)).sum() / (W1 * W0))


def average_precision(y, s, w=None):
    y = np.asarray(y, bool); s = np.asarray(s, float)
    w = np.ones(len(y)) if w is None else np.asarray(w, float)
    W1 = w[y].sum()
    if W1 <= 0 or w[~y].sum() <= 0:
        return None
    u, inv = np.unique(-s, return_inverse=True)  # tied scores share the precision at the end of their tie
    wp = np.bincount(inv, w * y, len(u)); wa = np.bincount(inv, w, len(u))
    cp, ca = np.cumsum(wp), np.cumsum(wa)
    return float((wp * cp / np.maximum(ca, 1e-12)).sum() / W1)


def _order(s, tie):
    return np.lexsort((tie, -s))  # by score, ties in a fixed random order (a constant model doesn't win by index)


def ndcg_at(gain, s, k, tie):
    o = _order(s, tie)
    disc = 1 / np.log2(np.arange(2, k + 2))
    dcg = (gain[o][:k] * disc[:min(k, len(o))]).sum()
    ideal = (np.sort(gain)[::-1][:k] * disc[:min(k, len(o))]).sum()
    return float(dcg / ideal) if ideal > 0 else float("nan")


def recall_at(y, s, k, tie):
    if not y.any():
        return float("nan")
    return float(y[_order(s, tie)][:k].sum() / y.sum())


def log_loss(y, p, w):
    p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
    return float(-(w * (y * np.log(p) + (1 - y) * np.log(1 - p))).sum() / w.sum()) if w.sum() > 0 else None


def ece(y, p, w, bins=10):
    p = np.asarray(p, float)
    b = np.minimum((p * bins).astype(int), bins - 1)
    W = w.sum()
    if W <= 0:
        return None
    tot = 0.0
    for k in range(bins):
        m = b == k
        if w[m].sum() > 0:
            tot += w[m].sum() / W * abs(np.average(y[m], weights=w[m]) - np.average(p[m], weights=w[m]))
    return float(tot)


class Prep:
    """One model's scores on one fold's test examples, prepared so that the metrics under any bootstrap weights are a
    few array operations: metrics(w) -> dict. w: a weight per example (how often its group was drawn; 0 = left out)."""

    def __init__(self, y, s, gain=None, q=None, proba=False, ks=(5, 10), tie=None):
        self.y = np.asarray(y, bool); self.s = np.asarray(s, float)
        self.gain = self.y.astype(float) if gain is None else np.asarray(gain, float)
        self.proba, self.ks = proba, ks
        u, self.inv = np.unique(self.s, return_inverse=True)
        self.nu = len(u)
        self.inv_d = (self.nu - 1) - self.inv  # the same ties, best score first (average precision)
        self.q = q is not None
        if self.q:
            tie = np.arange(len(self.y)) if tie is None else np.asarray(tie)
            pi, pj, c, qid, vals = [], [], [], np.full(len(self.y), -1), []
            for g in sorted(set(q)):
                m = np.flatnonzero(np.asarray(q) == g)
                P, N = m[self.y[m]], m[~self.y[m]]
                if len(m) < 2 or not len(P) or not len(N):
                    continue
                a, b = np.repeat(P, len(N)), np.tile(N, len(P))
                pi.append(a); pj.append(b)
                c.append((self.s[a] > self.s[b]) + 0.5 * (self.s[a] == self.s[b]))
                qid[m] = len(vals)
                vals.append([ndcg_at(self.gain[m], self.s[m], k, tie[m]) for k in ks]
                            + [recall_at(self.y[m], self.s[m], k, tie[m]) for k in ks])
            self.pi = np.concatenate(pi) if pi else np.zeros(0, int)
            self.pj = np.concatenate(pj) if pj else np.zeros(0, int)
            self.c = np.concatenate(c) if c else np.zeros(0)
            self.qid, self.qvals = qid, np.array(vals, float).reshape(len(vals), 2 * len(ks))
            self.qsize = np.bincount(qid[qid >= 0], minlength=len(vals)).astype(float)

    def metrics(self, w=None):
        y, s = self.y, self.s
        w = np.ones(len(y)) if w is None else np.asarray(w, float)
        W1, W0 = w[y].sum(), w[~y].sum()
        out = dict(auc=None, ap=None)
        if W1 > 0 and W0 > 0:
            wp = np.bincount(self.inv, w * y, self.nu); wn = np.bincount(self.inv, w * ~y, self.nu)
            out["auc"] = float((wp * (np.cumsum(wn) - wn + 0.5 * wn)).sum() / (W1 * W0))
            wp = np.bincount(self.inv_d, w * y, self.nu); wa = np.bincount(self.inv_d, w, self.nu)
            out["ap"] = float((wp * np.cumsum(wp) / np.maximum(np.cumsum(wa), 1e-12)).sum() / W1)
        if self.q:
            pw = w[self.pi] * w[self.pj]
            out["qauc"] = float((pw * self.c).sum() / pw.sum()) if pw.sum() > 0 else None
            ok = self.qid >= 0
            qw = np.bincount(self.qid[ok], w[ok], len(self.qsize)) / np.maximum(self.qsize, 1)
            for j, k in enumerate(self.ks):
                for col, name in ((j, f"ndcg@{k}"), (len(self.ks) + j, f"recall@{k}")):
                    v = self.qvals[:, col] if len(self.qvals) else np.zeros(0)
                    m = (qw > 0) & np.isfinite(v)
                    out[name] = float(np.average(v[m], weights=qw[m])) if m.any() else None
            out["queries"] = int((qw > 0).sum())
        if self.proba and w.sum() > 0:
            out["logloss"] = log_loss(y.astype(float), s, w)
            out["ece"] = ece(y.astype(float), s, w)
        return out


# ---------------------------------------------------------------- the run

def code_version():
    try:
        h = subprocess.run(["git", "-C", str(C.PROJECT_DIR), "rev-parse", "--short", "HEAD"], capture_output=True,
                           text=True, timeout=5).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(C.PROJECT_DIR), "status", "--porcelain", "--untracked-files=no"],
                               capture_output=True, text=True, timeout=5).stdout.strip()
        return h + ("+changes" if dirty else "") if h else None
    except Exception:
        return None


def _fill(s):
    s = np.asarray(s, float)
    bad = ~np.isfinite(s)
    if bad.all():
        return np.zeros(len(s)), 0.0
    if bad.any():
        s = s.copy(); s[bad] = np.nanmean(np.where(bad, np.nan, s))
    return s, float(1 - bad.mean())


def score_folds(task, examples, folds, models, src, verbose=True):
    """For every fold: the masked database, each model's fit and its scores on the fold's test examples.
    -> {model: [(fold, test indices kept, scores, coverage)]}"""
    out = {m.name: [] for m in models}
    for fd in folds:
        t0 = time.time()
        con = src.masked(fd.hide(examples), fd.until)
        train = Train(con, [examples[i] for i in fd.train], fd, task.name)
        test = [i for i in fd.test if task.keep(train, examples[i])]
        items = [examples[i].item for i in test]
        ctx = [examples[i].context for i in test]
        for m in models:
            try:
                s, cov = _fill(m.fit(train)(items, ctx)) if test else (np.zeros(0), 0.0)
            except Exception as e:  # one broken baseline shouldn't sink the table
                if verbose:
                    print(f"  {m.name} failed on {fd.name}: {type(e).__name__}: {e}")
                s, cov = np.zeros(len(test)), 0.0
            out[m.name].append((fd, test, s, cov))
        con.close()
        if verbose:
            print(f"  {task.name}/{fd.split} {fd.name}: {len(test)} test, {len(fd.train)} train, {time.time() - t0:.1f}s",
                  flush=True)
    return out


def _summ(vals):
    v = [x for x in vals if x is not None and np.isfinite(x)]
    return float(np.mean(v)) if v else None


def summarize(task, examples, scored, ref=None, boot=BOOT, seed=0, sl=None):
    """Metrics per model (mean over folds, bootstrap interval by group) and paired comparisons with ref."""
    names = list(scored)
    ref = ref if ref in scored else None
    groups = sorted({str(e.group) for e in examples})
    gi = {g: k for k, g in enumerate(groups)}
    eg = np.array([gi[str(e.group)] for e in examples])
    y_all = np.array([task.positive(e) for e in examples], bool)
    gain_all = np.array([task.gain(e) for e in examples], float)
    q_all = np.array([str(e.query) for e in examples], dtype=object) if task.ranking else None
    tie_all = np.random.default_rng(1).random(len(examples))
    sel = (lambda i: True) if sl is None else (lambda i: sl(examples[i]))

    preps = {}
    for name in names:
        proba = getattr(task._models.get(name), "proba", False)
        for k, (fd, test, s, cov) in enumerate(scored[name]):
            idx = [j for j, i in enumerate(test) if sel(i)]
            ti = np.array(test, int)[idx]
            preps[name, k] = (ti, Prep(y_all[ti], s[idx], gain_all[ti], q_all[ti] if q_all is not None else None,
                                       proba=proba, ks=task.ks, tie=tie_all[ti])) if idx else (ti, None)

    def per_fold(name, w_ex):
        res = []
        for k in range(len(scored[name])):
            ti, p = preps[name, k]
            res.append(p.metrics(w_ex[ti]) if p is not None else None)
        return res

    ones = np.ones(len(examples))
    point = {n: per_fold(n, ones) for n in names}
    keys = sorted({k for n in names for r in point[n] if r for k in r if k != "queries"})
    rng = np.random.default_rng(seed)
    bs = {n: {k: [] for k in keys} for n in names}
    diffs = {n: {k: [] for k in keys} for n in names if n != ref}
    for _ in range(boot):
        cnt = rng.multinomial(len(groups), np.full(len(groups), 1 / len(groups)))
        w = cnt[eg].astype(float)
        got = {n: per_fold(n, w) for n in names}
        for n in names:
            for k in keys:
                bs[n][k].append(_summ([r.get(k) if r else None for r in got[n]]))
        if ref:
            for n in diffs:
                for k in keys:  # the difference on the folds where both are defined in this resample
                    pr = [(a.get(k), b.get(k)) for a, b in zip(got[n], got[ref]) if a and b and a.get(k) is not None
                          and b.get(k) is not None]
                    diffs[n][k].append(float(np.mean([a - b for a, b in pr])) if pr else None)

    def ci(v):
        v = [x for x in v if x is not None]
        return [round(float(np.percentile(v, 2.5)), 4), round(float(np.percentile(v, 97.5)), 4)] if len(v) > 20 else None

    out = {}
    for n in names:
        mets = {}
        for k in keys:
            fv = [r.get(k) if r else None for r in point[n]]
            m = _summ(fv)
            mets[k] = dict(mean=None if m is None else round(m, 4), ci=ci(bs[n][k]),
                           folds=[None if v is None else round(v, 4) for v in fv])
        cov = [c for _, _, _, c in scored[n]]
        out[n] = dict(metrics=mets, coverage=round(float(np.mean(cov)), 3) if cov else None,
                      queries=sum((r or {}).get("queries", 0) for r in point[n]))
        if ref and n != ref:
            pd = {}
            for k in keys:
                pr = [(a.get(k), b.get(k)) for a, b in zip(point[n], point[ref]) if a and b and a.get(k) is not None
                      and b.get(k) is not None]
                if not pr:
                    continue
                d = float(np.mean([a - b for a, b in pr]))
                pd[k] = dict(diff=round(d, 4), ci=ci(diffs[n][k]), won=sum(a > b for a, b in pr),
                             lost=sum(a < b for a, b in pr), of=len(pr))
            out[n]["vs_ref"] = pd
    return out


def counts(task, examples, folds, sl=None):
    """How much data the measurement rests on: distinct test examples, positives, negatives, groups."""
    idx = sorted({i for f in folds for i in f.test})
    if sl:
        idx = [i for i in idx if sl(examples[i])]
    y = [task.positive(examples[i]) for i in idx]
    return dict(n=len(idx), pos=int(sum(y)), neg=int(len(y) - sum(y)), groups=len({str(examples[i].group) for i in idx}),
                folds=len(folds))


def evaluate(task, models=None, splits=None, quick=False, src=None, boot=None, save=True, verbose=True):
    """Run a task: every split it has (or those asked for), every baseline (or those asked for). -> the result dict
    (also saved under RUNS unless save=False)."""
    own = src is None
    src = src or Source()
    try:
        examples = task.examples(src.con)
        task._models = {m.name: m for m in task.models()}
        ms = [m if isinstance(m, Model) else task._models[m] for m in (models or list(task._models))]
        task._models.update({m.name: m for m in ms})
        res = dict(task=task.name, about=task.about, when=time.time(), code=code_version(), data=src.signature(),
                   reference=task.reference, quick=bool(quick), notes=list(task.notes), splits={})
        for sp in (splits or task.splits):
            folds = task.folds(examples, sp, quick)
            n = counts(task, examples, folds)
            entry = dict(counts=n, slices={})
            if not folds or min(n["pos"], n["neg"]) < task.min_class:
                entry["insufficient"] = (f"too little data to say anything: {n['pos']} positive and {n['neg']} negative "
                                         f"test examples in {len(folds)} folds (needs {task.min_class} of each)")
                res["splits"][sp] = entry
                if verbose:
                    print(f"{task.name}/{sp}: {entry['insufficient']}")
                continue
            scored = score_folds(task, examples, folds, ms, src, verbose)
            first = next(iter(scored.values()), [])
            entry["folds"] = [dict(name=fd.name, until=fd.until, train=len(fd.train), n=len(test),
                                   pos=int(sum(task.positive(examples[i]) for i in test)),
                                   neg=int(sum(not task.positive(examples[i]) for i in test)))
                              for fd, test, _, _ in first]
            # the test filter (new_songs) can shrink what was scored: count what was actually measured
            measured = sorted({i for v in scored.values() for _, test, _, _ in v for i in test})
            y = [task.positive(examples[i]) for i in measured]
            entry["counts"].update(measured=len(measured), measured_pos=int(sum(y)), measured_neg=int(len(y) - sum(y)))
            if min(sum(y), len(y) - sum(y)) < task.min_class:
                entry["insufficient"] = (f"too little data to say anything: {sum(y)} positive and {len(y) - sum(y)} "
                                         f"negative examples measured (needs {task.min_class} of each)")
                res["splits"][sp] = entry
                continue
            b = boot if boot is not None else (200 if quick else BOOT)
            entry["models"] = summarize(task, examples, scored, task.reference, b)
            for name, f in task.slices().items():
                c = counts(task, examples, folds, f)
                if min(c["pos"], c["neg"]) < task.min_class:
                    entry["slices"][name] = dict(counts=c, insufficient=f"too little data ({c['pos']} positive, "
                                                                         f"{c['neg']} negative)")
                else:
                    entry["slices"][name] = dict(counts=c, models=summarize(task, examples, scored, task.reference,
                                                                            max(100, b // 5), sl=f))
            res["splits"][sp] = entry
        if save:
            res["file"] = str(write(res))
        return res
    finally:
        if own:
            src.close()


# ---------------------------------------------------------------- results on disk

def write(res):
    RUNS.mkdir(parents=True, exist_ok=True)
    f = RUNS / f"{time.strftime('%Y%m%d-%H%M%S', time.localtime(res['when']))}-{res['task']}.json"
    f.write_text(json.dumps(res, indent=1, default=lambda o: o.tolist() if hasattr(o, "tolist") else str(o)))
    return f


def latest(task=None):
    """The newest saved run of each task ({task: result}), or of one task (its result, or None)."""
    out = {}
    for f in sorted(RUNS.glob("*.json")) if RUNS.exists() else []:
        try:
            r = json.loads(f.read_text())
        except Exception:
            continue
        out[r["task"]] = r
    return out.get(task) if task else out


def _fmt(m):
    if not m or m.get("mean") is None:
        return "-"
    s = f"{m['mean']:.3f}"
    return s + (f" [{m['ci'][0]:.3f}, {m['ci'][1]:.3f}]" if m.get("ci") else "")


def _fmtd(d):
    if not d:
        return ""
    s = f"{d['diff']:+.3f}"
    if d.get("ci"):
        s += f" [{d['ci'][0]:+.3f}, {d['ci'][1]:+.3f}]"
    return s + f" {d['won']}/{d['of']}"


def table(results, metrics=None, slices=True):
    """Plain-text table of one or more results: per task and split, each model's main metrics with intervals, its
    difference from the reference model (interval, folds won) and the data behind it."""
    if isinstance(results, dict) and "task" in results:
        results = [results]
    elif isinstance(results, dict):
        results = list(results.values())
    lines = []
    for r in results:
        from .tasks import TASKS
        task = TASKS.get(r["task"])
        mets = metrics or (task.primary if task else ["auc"])
        for sp, e in r["splits"].items():
            c = e["counts"]
            lines.append(f"\n{r['task']} / {sp}   ({c.get('measured', c['n'])} examples: {c.get('measured_pos', c['pos'])} "
                         f"positive, {c.get('measured_neg', c['neg'])} negative; {c['groups']} groups; {c['folds']} folds)"
                         + ("   quick" if r.get("quick") else ""))
            if e.get("insufficient"):
                lines.append(f"  {e['insufficient']}")
                continue
            head = f"  {'model':28s}" + "".join(f"{m:>26s}" for m in mets) + f"   vs {r.get('reference')} ({mets[0]})"
            lines.append(head)
            rows = [("", e["models"])] + ([(f"[{k}] ", v.get("models")) for k, v in e.get("slices", {}).items()]
                                         if slices else [])
            for pre, ms in rows:
                if ms is None:
                    k = pre.strip()[1:-1]
                    lines.append(f"  {pre}{e['slices'][k]['insufficient']}")
                    continue
                for name, v in ms.items():
                    lines.append(f"  {(pre + name)[:28]:28s}" + "".join(f"{_fmt(v['metrics'].get(m)):>26s}" for m in mets)
                                 + "   " + _fmtd((v.get("vs_ref") or {}).get(mets[0]))
                                 + (f"  (scored {v['coverage']:.0%})" if (v.get("coverage") or 1) < 0.999 else ""))
        for n in r.get("notes") or []:
            lines.append(f"  note: {n}")
    return "\n".join(lines)



def cli(a):
    """python -m digitalcrate reco eval|log ... (see __main__)."""
    from .tasks import TASKS
    if a.reco_cmd == "log":
        con = open_ro()
        L.print_summary(con)
        return
    if a.show:
        got = latest()
        print(table([got[t] for t in (a.task or TASKS) if t in got]) if got else "no saved runs yet")
        return
    src = Source()
    try:
        for name in a.task or TASKS:
            if name not in TASKS:
                raise SystemExit(f"unknown task {name!r}: {', '.join(TASKS)}")
            task = TASKS[name]()
            ms = None
            if a.model:
                have = [m.name for m in task.models()]
                ms = [m for m in have if m in a.model or m == task.reference]
                if not any(m in a.model for m in have):
                    continue
            splits = [s for s in task.splits if s in a.split] if a.split else None
            if splits == []:
                continue
            res = evaluate(task, ms, splits, a.quick, src)
            print(table(res), flush=True)
            print(f"  saved {res['file']}")
    finally:
        src.close()
