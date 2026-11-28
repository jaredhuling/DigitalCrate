"""The embedding trial (docs/plans/recommend.md, "More embeddings"): does a music-trained audio embedding predict which
samples you star better than CLAP, or add to it?

    python -m digitalcrate.reco.embed_trial embed mert|effnet [--limit N]   embed the samples the trial needs
    python -m digitalcrate.reco.embed_trial eval dev|confirm [--models a,b]  measure on the harness's sample_taste task

Only the samples that matter are embedded: every sample of the sample_taste task (heard or starred), every sample the
taste model takes as evidence, and the taste model's 400 kernel landmarks. Embeddings are kept in
_data/reco/embed_trial/<name>.npz (paths + a float16 matrix), written every chunk so a pass can be stopped and resumed.

Embeddings
  mert     m-a-p/MERT-v1-95M (digitalcrate/mert.py's loader): the hidden states of all 13 layers, averaged over time,
           and their standard deviation over time; a view picks a layer (or the layer average) and the pooling
  effnet   Essentia's Discogs-EffNet (styles.py's model) per sample instead of per song: the 1280-d embedding, the
           mean over its ~2 s patches
  clap     the app's own CLAP embedding (from the samples table), for the probe
Every clip is the sample's middle 10 seconds, mono, as the stored CLAP embeddings were made.

Models (harness Models, samples as evidence; the Mashup evidence is left out since stems have no new embedding)
  trial.clap      reco.taste's model (sound directions + kernel + metadata + song and artist effects) on CLAP
  trial.swap:V    the same with CLAP's sound directions and kernel replaced by embedding V's
  trial.add:V     CLAP's as in trial.clap, plus V's principal directions as one more block with its own prior
  probe:V         a plain logistic regression on V alone (64 whitened principal directions, L2 chosen by inner CV)

Protocol (the one reco.taste was chosen by): choices are made on the development folds (k-fold seed 0; the odd forward
folds) and confirmed once on fresh seeds (2, 3, 4) and the even forward folds.
"""
import argparse
import json
import os
import time

import numpy as np

from .. import config as C
from .eval import Model, Source, forward, kfold, score_folds, summarize
from .models import taste as T
from .tasks import SampleTaste

STORE = C.DATA_DIR / "reco" / "embed_trial"
CLIP_S = 10.0
K_PROBE = 64
_EMB = {}


# ---------------------------------------------------------------- audio and embedders

def load_clip(path, sr, max_s=CLIP_S, min_s=0.0):
    """The middle max_s seconds of a file, mono, at sr; zero-padded to min_s."""
    import soundfile as sf
    from scipy.signal import resample_poly
    y, r = sf.read(str(path), dtype="float32", always_2d=True)
    m = y.mean(1)
    if len(m) > r * max_s:
        mid = len(m) // 2
        m = m[mid - int(r * max_s / 2): mid + int(r * max_s / 2)]
    if r != sr:
        g = np.gcd(int(sr), int(r))
        m = resample_poly(m, sr // g, r // g).astype(np.float32)
    if len(m) < int(sr * min_s):
        m = np.pad(m, (0, int(sr * min_s) - len(m)))
    return np.ascontiguousarray(m, dtype=np.float32)


class Mert:
    """MERT-v1-95M: per layer (13), the time mean and the time standard deviation of the hidden states -> (2 x 13 x 768)."""
    name, layers, width = "mert", 13, 768
    dim = 2 * 13 * 768

    def embed(self, path):
        import torch
        from .. import mert
        from ..models import DEVICE
        x = load_clip(path, mert.SR, min_s=0.5)
        x = (x - x.mean()) / (x.std() + 1e-7)  # what MERT's feature extractor does
        with torch.no_grad():
            o = mert.model()(torch.from_numpy(x[None]).to(DEVICE), output_hidden_states=True, return_dict=True)
            h = torch.stack(o.hidden_states)[:, 0].float()
            out = torch.cat([h.mean(1), h.std(1, unbiased=False)]).cpu().numpy()
        return out.reshape(-1)


class Effnet:
    """Discogs-EffNet per sample: the mean of its patches' 1280-d embeddings (short samples zero-padded to one patch)."""
    name, dim = "effnet", 1280

    def embed(self, path):
        from .. import styles
        y = load_clip(path, styles.SR, min_s=(styles.PATCH + 2) * styles.HOP / styles.SR)
        m = styles.melspec(y)
        P = np.stack([m[a:a + styles.PATCH] for a in range(0, len(m) - styles.PATCH + 1, styles.PATCH_HOP)])
        _, e = styles._session().run(["activations", "embeddings"], {"melspectrogram": P})
        return e.mean(0)


EMBEDDERS = {"mert": Mert, "effnet": Effnet}


# ---------------------------------------------------------------- which samples, and the store

def targets(con):
    """The samples the trial needs, sorted: sample_taste's examples, the taste model's evidence, its landmarks."""
    paths = {e.item[1] for e in SampleTaste().examples(con)}
    lib = T.library(con)
    paths |= {p for p in T.evidence(con)[0] if p in lib["pos"]}
    paths |= set(landmark_paths(lib))
    return sorted(paths)


def landmark_paths(lib, seed=0):
    """The library samples reco.taste uses as kernel landmarks (the same draw as taste.library)."""
    rng = np.random.default_rng(seed)
    E = lib["E"]
    idx = rng.choice(len(E), min(T.N_LANDMARKS, len(E)), replace=False)
    return [lib["paths"][i] for i in idx]


def store_path(name, store=None):
    return (store or STORE) / f"{name}.npz"


def load(name, store=None):
    """(paths, float32 matrix) of an embedding pass so far, or ([], None)."""
    f = store_path(name, store)
    if not f.exists():
        return [], None
    d = np.load(f, allow_pickle=False)
    return [str(p) for p in d["paths"]], d["X"].astype(np.float32)


def _save(name, paths, X, failed, store=None):
    f = store_path(name, store)
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_name(f.stem + ".tmp.npz")
    np.savez(tmp, paths=np.array(paths), X=np.asarray(X, np.float16), failed=np.array(sorted(failed)))
    os.replace(tmp, f)


def run(name, paths, root=None, embedder=None, chunk=250, store=None, breathe=True, verbose=True):
    """Embed paths (relative to root, the library) with the named embedder, skipping those already stored; saved
    after every chunk. -> dict(done, new, failed, seconds, per_s)"""
    root = root or C.LIB_ROOT
    emb = embedder or EMBEDDERS[name]()
    have, X = load(name, store)
    f = store_path(name, store)
    failed = set(str(p) for p in np.load(f)["failed"]) if f.exists() else set()
    done = set(have)
    todo = [p for p in paths if p not in done and p not in failed]
    rows, X = list(have), ([] if X is None else list(X))
    t0, n_new = time.time(), 0
    for a in range(0, len(todo), chunk):
        if breathe:
            from ..memguard import breathe as _b
            _b()
        for p in todo[a:a + chunk]:
            try:
                v = np.asarray(emb.embed(root / p), np.float32)
                if not np.all(np.isfinite(v)):
                    raise ValueError("not finite")
            except Exception as e:
                if verbose:
                    print(f"  {p}: {type(e).__name__}: {e}", flush=True)
                failed.add(p)
                continue
            rows.append(p)
            X.append(v)
            n_new += 1
        _save(name, rows, np.stack(X) if X else np.zeros((0, emb.dim)), failed, store)
        if verbose:
            dt = time.time() - t0
            print(f"  {name}: {len(rows)} stored, {n_new} new in {dt:.0f} s ({n_new / max(dt, 1e-9):.2f}/s), "
                  f"{len(failed)} failed", flush=True)
    dt = time.time() - t0
    return dict(done=len(rows), new=n_new, failed=len(failed), seconds=round(dt, 1), per_s=n_new / max(dt, 1e-9))


# ---------------------------------------------------------------- views of an embedding

def view(spec, con=None, store=None):
    """-> {path: vector} for a view: 'clap', 'effnet', 'mert:avg', 'mert:6' (a layer), 'mert:avg+std' (the layer
    average of the time mean and of the time sd)."""
    key = (spec, str(store))
    if key in _EMB:
        return _EMB[key]
    name, _, how = spec.partition(":")
    if name == "clap":
        lib = T.library(con)
        out = {p: lib["E"][i] for i, p in enumerate(lib["paths"])}
    else:
        paths, X = load(name, store)
        if X is None:
            raise FileNotFoundError(f"no {name} embeddings yet: run embed {name}")
        if name == "mert":
            H = X.reshape(len(X), 2, Mert.layers, Mert.width)
            parts = how.split("+") if how else ["avg"]
            cols = []
            for part in parts:
                if part == "std":
                    cols.append(H[:, 1].mean(1))
                elif part == "avg":
                    cols.append(H[:, 0].mean(1))
                else:
                    cols.append(H[:, 0, int(part)])
            X = np.hstack([_std(c) for c in cols]) if len(cols) > 1 else cols[0]
        out = dict(zip(paths, X))
    _EMB[key] = out
    return out


def _std(X):
    return (X - X.mean(0)) / (X.std(0) + 1e-6)


class Space:
    """An embedding prepared over the trial's samples (label-free): centered, unit length, whitened principal directions,
    and an RBF kernel through landmarks with its length scale set relative to the median squared distance (as reco.taste's
    0.5 is to CLAP's 1.6)."""

    def __init__(self, vecs, paths, landmarks, k=T.K_SOUND, center=True):
        paths = [p for p in paths if p in vecs]
        E = np.stack([vecs[p] for p in paths]).astype(np.float64)
        self.mu0 = E.mean(0) if center else np.zeros(E.shape[1])
        E = _unit(E - self.mu0)
        self.pos = {p: i for i, p in enumerate(paths)}
        self.E = E
        self.mu = E.mean(0)
        Zc = E - self.mu
        w, V = np.linalg.eigh(Zc.T @ Zc)
        k = min(k, len(E) - 1, E.shape[1])
        self.P = V[:, ::-1][:, :k]
        self.sd = np.sqrt(np.maximum(w[::-1][:k], 1e-12) / len(E)) + 1e-9
        rng = np.random.default_rng(0)
        sub = E[rng.choice(len(E), min(2000, len(E)), replace=False)]
        d2 = np.maximum(0, 2 - 2 * sub @ sub.T)[np.triu_indices(len(sub), 1)]
        self.ell2 = T.ELL2 * float(np.median(d2)) / 1.6
        Lm = np.stack([E[self.pos[p]] for p in landmarks if p in self.pos])
        ev, U = np.linalg.eigh(np.exp(-(2 - 2 * Lm @ Lm.T) / (2 * self.ell2)))
        keep = ev > 1e-6 * ev.max()
        self.Lm, self.T = Lm, U[:, keep] / np.sqrt(ev[keep])

    def rows(self, paths):
        """(Z whitened directions, F kernel features, ok) for paths (zeros where a path has no embedding)."""
        idx = [self.pos.get(p) for p in paths]
        ok = np.array([i is not None for i in idx])
        E = np.zeros((len(paths), self.E.shape[1]))
        if ok.any():
            E[ok] = self.E[[i for i in idx if i is not None]]
        Z = ((E - self.mu) @ self.P) / self.sd
        F = np.exp(-(2 - 2 * E @ self.Lm.T) / (2 * self.ell2)) @ self.T
        Z[~ok], F[~ok] = 0, 0
        return Z, F, ok


def _unit(E):
    return E / (np.linalg.norm(E, axis=1, keepdims=True) + 1e-9)


_SPACE = {}


def space(spec, con, k=T.K_SOUND, store=None):
    key = (spec, k, str(store))
    if key not in _SPACE:
        lib = T.library(con)
        _SPACE[key] = Space(view(spec, con, store), trial_paths(lib, store), landmark_paths(lib), k=k,
                            center=not spec.startswith("clap"))
    return _SPACE[key]


def trial_paths(lib, store=None):
    """The samples every embedding is prepared over: those a pass embedded (the same for every embedding, and fixed
    whatever a fold hides, so no fold's held-out samples drop out), else the whole library."""
    got = set()
    for f in sorted((store or STORE).glob("*.npz")) if (store or STORE).exists() else []:
        if not f.name.endswith(".tmp.npz"):
            got |= {str(p) for p in np.load(f, allow_pickle=False)["paths"]}
    return sorted(p for p in got if p in lib["pos"]) if got else list(lib["paths"])


# ---------------------------------------------------------------- the variant models

def _evidence_rows(train, lib):
    samples, _ = T.evidence(train.con, train.until)
    lab = [(p, y) for p, y in sorted(samples.items()) if p in lib["pos"]]
    return [p for p, _ in lab], np.array([y for _, y in lab], float)


def fit_variant(train, mode="clap", spec=None, k_add=T.K_SOUND, kernel_add=False):
    """reco.taste's model on the training fold's sample evidence, with CLAP's sound terms (mode 'clap'), the
    embedding's instead ('swap'), or both, the embedding's as an extra block ('add'). -> scorer(items) -> predictive
    logit (the posterior mean shrunk by its sd, as reco.taste ranks)."""
    con = train.con
    lib = T.library(con)
    paths, ys = _evidence_rows(train, lib)
    S = space(spec, con, k=k_add if mode == "add" else T.K_SOUND) if mode != "clap" else None
    if S is not None:
        keep = np.array([p in S.pos for p in paths])
        paths, ys = [p for p, g in zip(paths, keep) if g], ys[keep]

    def design(ps):
        r = np.array([lib["pos"][p] for p in ps])
        base = T._design(lib, r)  # [1 | CLAP directions | CLAP kernel | metadata]
        k, nk = lib["P"].shape[1], lib["T"].shape[1]
        one, Zc, Fc, M = base[:, :1], base[:, 1:1 + k], base[:, 1 + k:1 + k + nk], base[:, 1 + k + nk:]
        if mode == "clap":
            blocks = [Zc, Fc, M]
        else:
            Z, F, _ = S.rows(ps)
            blocks = [Z, F, M] if mode == "swap" else [Zc, Fc, M, Z] + ([F] if kernel_add else [])
        return np.hstack([one] + blocks), [b.shape[1] for b in blocks]

    X, widths = design(paths)
    off = np.cumsum([1] + widths)
    bl = [slice(int(a), int(b)) for a, b in zip(off[:-1], off[1:])]
    songs = [int(lib["tid"][lib["pos"][p]]) for p in paths]
    arts = [lib["t2a"].get(s) for s in songs]
    lv_s = {v: j for j, v in enumerate(sorted(set(songs)))}
    lv_a = {v: j for j, v in enumerate(sorted({a for a in arts if a}))}
    ones = np.ones(len(paths))
    groups = [(np.array([lv_s[s] for s in songs]), len(lv_s), ones),
              (np.array([lv_a.get(a, -1) if a else -1 for a in arts]), len(lv_a), ones)]
    th, Sig, al, allb = T.glmm(X, groups, ys, bl)
    pf = X.shape[1]
    kern = [(bl[i], 1 / al[i]) for i in ([1] + ([4] if mode == "add" and kernel_add else []))]  # (block, residual)
    gs, ga = allb[-2], allb[-1]
    a_s, a_a = al[-2], al[-1]

    def score(items, ctx=None):
        ps = [it[1] for it in items]
        ok = np.array([p in lib["pos"] and (S is None or p in S.pos) for p in ps])
        out = np.full(len(ps), np.nan)
        if not ok.any():
            return out
        q = [p for p, g in zip(ps, ok) if g]
        Xq, _ = design(q)
        mean = Xq @ th[:pf]
        var = ((Xq @ Sig[:pf, :pf]) * Xq).sum(1)
        for b, r in kern:  # each kernel beyond its landmarks
            var += r * np.maximum(0, 1 - (Xq[:, b] ** 2).sum(1))
        sq = [int(lib["tid"][lib["pos"][p]]) for p in q]
        js = []
        for keys, lv, b, a in ((sq, lv_s, gs, a_s), ([lib["t2a"].get(s) for s in sq], lv_a, ga, a_a)):
            j = np.array([lv.get(x, -1) if x is not None else -1 for x in keys], int)
            h = j >= 0
            jj = np.where(h, b.start + np.maximum(j, 0), -1)
            mean[h] += th[jj[h]]
            var[h] += Sig[jj[h], jj[h]] + 2 * (Xq[h] * Sig[:pf, jj[h]].T).sum(1)
            var[~h] += 1 / a
            js.append(jj)
        both = (js[0] >= 0) & (js[1] >= 0)
        var[both] += 2 * Sig[js[0][both], js[1][both]]
        out[ok] = T._probit(mean, np.sqrt(np.maximum(var, 0)))
        return out
    score.alpha = al
    return score


def variant_model(mode, spec=None, **kw):
    name = "trial.clap" if mode == "clap" else f"trial.{mode}:{spec}" + "".join(f"/{k}={v}" for k, v in kw.items())
    return Model(name, lambda train: fit_variant(train, mode, spec, **kw),
                 about=f"reco.taste's model, samples only, sound terms: {mode} {spec or ''}")


def probe_model(spec, k=K_PROBE):
    """A plain L2 logistic regression on the embedding alone: the same for every embedding."""
    def fit(train):
        from sklearn.linear_model import LogisticRegressionCV
        con = train.con
        lib = T.library(con)
        S = space(spec, con, k=k)
        paths, ys = _evidence_rows(train, lib)
        Z, _, ok = S.rows(paths)
        clf = LogisticRegressionCV(Cs=np.logspace(-4, 1, 11), cv=3, scoring="roc_auc", max_iter=2000,
                                   l1_ratios=(0,), use_legacy_attributes=False)
        clf.fit(Z[ok], ys[ok])

        def score(items, ctx=None):
            Zq, _, okq = S.rows([it[1] for it in items])
            s = clf.decision_function(Zq)
            s[~okq] = np.nan
            return s
        return score
    return Model(f"probe:{spec}" + (f"@{k}" if k != K_PROBE else ""), fit, about=f"L2 logistic on {k} whitened directions of {spec}")


def reco_taste():
    return T.harness_models()[0]


# ---------------------------------------------------------------- the task, with development and confirmation folds

class TrialTask(SampleTaste):
    """sample_taste with the trial's folds: phase 'dev' (k-fold seed 0, odd forward folds) or 'confirm' (seeds 2, 3,
    4; even forward folds)."""
    reference = "reco.taste"

    def __init__(self, phase="dev"):
        super().__init__()
        self.phase = phase

    def folds(self, examples, split, quick=False):
        seeds = (0,) if self.phase == "dev" else (2, 3, 4)
        if split == "forward":
            fs = forward(examples, self.min_pos)
            return [f for f in fs if (int(f.name[1:]) % 2 == 1) == (self.phase == "dev")]
        if split == "sample":
            return kfold(examples, 5, seeds, key=lambda e: e.item[1], split="sample")
        return kfold(examples, 5, seeds, split=split)

    def models(self):
        return []


def measure(models, phase="dev", splits=("sample", "song", "forward"), refs=("reco.taste", "trial.clap"), src=None,
            boot=1000, verbose=True):
    """Score the models on the trial folds; summaries against each reference model present. -> result dict"""
    own = src is None
    src = src or Source()
    task = TrialTask(phase)
    try:
        ex = task.examples(src.con)
        task._models = {m.name: m for m in models}
        res = dict(phase=phase, when=time.time(), n=len(ex), n_pos=int(sum(e.label for e in ex)), splits={})
        for sp in splits:
            folds = task.folds(ex, sp)
            t0 = time.time()
            scored = score_folds(task, ex, folds, models, src, verbose)
            res["splits"][sp] = dict(folds=len(folds), seconds=round(time.time() - t0),
                                     by_ref={r: summarize(task, ex, scored, r, boot) for r in refs if r in scored})
        return res
    finally:
        if own:
            src.close()


def table(res, ref="reco.taste"):
    lines = [f"phase {res['phase']}: {res['n']} examples, {res['n_pos']} favorites; differences vs {ref}"]
    for sp, e in res["splits"].items():
        lines.append(f"\n  {sp} ({e['folds']} folds)" + " " * 20 + "AUC                  AP          d AUC [95%]          d AP [95%]")
        ms = e["by_ref"].get(ref) or next(iter(e["by_ref"].values()))
        for name, v in ms.items():
            m = v["metrics"]
            fmt = lambda x: f"{x['mean']:.3f}" if x and x.get("mean") is not None else "  -  "
            d = v.get("vs_ref") or {}
            fd = lambda x: (f"{x['diff']:+.3f} [{x['ci'][0]:+.3f},{x['ci'][1]:+.3f}] {x['won']}/{x['of']}"
                            if x and x.get("ci") else "")
            lines.append(f"    {name[:40]:40s} {fmt(m.get('auc'))}  {fmt(m.get('ap'))}   {fd(d.get('auc')):28s} "
                         f"{fd(d.get('ap'))}")
    return "\n".join(lines)


def _models(names):
    out = []
    for n in names:
        if n == "reco.taste":
            out.append(reco_taste())
        elif n == "trial.clap":
            out.append(variant_model("clap"))
        elif n.startswith("probe:"):  # probe:V or probe:V@k (k whitened directions)
            spec, _, k = n[6:].partition("@")
            out.append(probe_model(spec, int(k)) if k else probe_model(spec))
        elif n.startswith("swap:") or n.startswith("add:"):
            mode, _, spec = n.partition(":")
            spec, *opts = spec.split("/")  # options: add:V/k_add=16/kernel_add=1
            kw = {}
            for o in opts:
                k, _, v = o.partition("=")
                kw[k] = int(v) if v.isdigit() else v == "1" if k == "kernel_add" else v
            out.append(variant_model(mode, spec, **kw))
        else:
            raise SystemExit(f"unknown model {n!r}")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m digitalcrate.reco.embed_trial")
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("embed")
    e.add_argument("name", choices=sorted(EMBEDDERS))
    e.add_argument("--limit", type=int)
    e.add_argument("--chunk", type=int, default=250)
    v = sub.add_parser("eval")
    v.add_argument("phase", choices=["dev", "confirm"])
    v.add_argument("--models", default="reco.taste,trial.clap,probe:clap")
    v.add_argument("--splits", default="sample,song,forward")
    v.add_argument("--out")
    a = ap.parse_args(argv)
    if a.cmd == "embed":
        src = Source()
        try:
            paths = targets(src.con)
        finally:
            src.close()
        print(f"{len(paths)} samples to embed with {a.name}", flush=True)
        print(run(a.name, paths[:a.limit], chunk=a.chunk))
        return
    res = measure(_models(a.models.split(",")), a.phase, tuple(a.splits.split(",")))
    print(table(res))
    if "trial.clap" in a.models.split(","):
        print(table(res, "trial.clap"))
    out = STORE / "results" / (a.out or f"{time.strftime('%Y%m%d-%H%M%S')}-{a.phase}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=1, default=lambda o: o.tolist() if hasattr(o, "tolist") else str(o)))
    print(f"saved {out}")


if __name__ == "__main__":
    main()
