"""One log of everything you did, read from the tables each surface already keeps (nothing is migrated or copied).

A record: Interaction(ts, surface, kind, item, action, value, weight, context, session)
  ts        unix seconds (tables that keep a text timestamp are read as UTC, which is what SQLite writes)
  surface   samples | mashup | edits | pairs | scout
  kind      the item's kind: item[0]
  item      a tuple that addresses one thing anywhere in the app:
              ("sample", path)  ("part", track, stem, bar0, n)  ("song", track_id)  ("move", sample path, move id)
              ("pair", path a, path b)  ("video", youtube id)
  action    what happened, in the source's own words: listen, star, unstar, dislike, favorite, collect (samples);
            save, reroll, kept, lock, remove, snap, like, dislike, in_saved_mix (mashup); shown, play, apply, save,
            dismiss, rate (edits); vote, pair (pairs); ingested, skipped, scored, filtered (scout)
  value     the source's number: listen fraction, star/dislike flag, Mashup y, edit rating (+1/-1), pair rating 1-5,
            scout score
  weight    the hand-set weight the source attached, where it has one (Mashup's w); else None. Raw, not re-weighted:
            fitting label weights is a model's job (phase 2)
  context   what else the source kept (Mashup's frozen features x, an edit's family / arm / material, where a sample
            was played from...), plus "_src": (table, rowid) so a row can be traced (and hidden by the harness)
  session   index of the session: interactions less than 10 minutes apart, across every surface (as taste.py does)

Facts about the legacy tables worth knowing before learning from them are in docs/plans/recommend.md and in the
harness's notes; e.g. a Mashup save logged every slot again each time the mix was saved (now once per part per mix).

Impressions: what a surface showed, each option's score and chance of being picked, the policy, the context and what
was chosen. `impression()` writes one; the table is created on first use. Mashup writes one per deal (stems.py).

Outcomes (`reco_outcomes`, read by the adapter like any other table): what then happened to what was dealt, tied to
its impression where there is one. Mashup's verbs are past tense so they never merge with the legacy stem_events
counts (which go on being written for the live model): replaced (context.by: dice, all, down, new, find, best, add,
role, alt, history), removed (by: clear, new, or the track's ✕), heard (value: the seconds of listening it passed:
30, 60, 120, 300, 600), locked, unlocked, rated (+1 / -1 / 0 taken back), rated_mix (the whole combination, +1 / -1),
starred and nope (a one-shot's sample, 1 / 0), snapped, saved (once per part per mix), exported, undone (left by an
undo or redo: not a judgment), restored (came back by an undo, redo or the slot's history: the replaced before it is
not a judgment either), left (another mix was opened over it). Every Mashup outcome carries secs: how long the part
was heard in that slot (playing, not muted, not soloed away), not wall time.
"""
import calendar
import json
import time
from collections import Counter, namedtuple

Interaction = namedtuple("Interaction", "ts surface kind item action value weight context session")
SESSION_GAP = 600  # seconds: a new session after 10 minutes without anything happening (taste.item_labels)


def utc(text):
    """'YYYY-MM-DD HH:MM:SS' (SQLite's CURRENT_TIMESTAMP, UTC) -> unix seconds; None stays None."""
    if not text:
        return None
    try:
        return float(calendar.timegm(time.strptime(str(text)[:19], "%Y-%m-%d %H:%M:%S")))
    except ValueError:
        return None


def _has(con, table):
    """Is there such a table (in any attached database)?"""
    try:
        con.execute(f"SELECT 1 FROM {table} LIMIT 0")
        return True
    except Exception:
        return False


def _json(s):
    try:
        return json.loads(s) if s else {}
    except (TypeError, ValueError):
        return {}


def _rows(con, table):
    if not _has(con, table):
        return []
    return con.execute(f"SELECT rowid AS _rowid, * FROM {table}").fetchall()


def _I(ts, surface, item, action, value=None, weight=None, context=None, src=None):
    c = dict(context or {})
    if src:
        c["_src"] = src
    return Interaction(float(ts or 0), surface, item[0], tuple(item), action, value, weight, c, None)


# ---------------------------------------------------------------- adapters: one per legacy table
# Each yields the interactions one row stands for. A row may stand for several (a saved mix: one per part).

def _events(con):
    for r in _rows(con, "events"):
        ctx, t = _json(r["context"]), r["type"]
        src = ("events", r["_rowid"])
        if t == "suggest":  # edit suggestions: shown / play / apply / save / dismiss (suggest.feedback)
            yield _I(r["ts"], "edits", ("move", r["path"], ctx.get("move")), ctx.get("action") or "suggest", r["value"],
                     None, {k: ctx.get(k) for k in ("family", "arm", "material")}, src)
        elif t == "pair":
            yield _I(r["ts"], "pairs", ("pair", r["path"], ctx.get("with")), "pair", r["value"], None, ctx, src)
        else:  # listen (value: fraction played), star, unstar, dislike (value 1 / 0)
            yield _I(r["ts"], "samples", ("sample", r["path"]), t, r["value"], None, ctx, src)


def _favorites(con):
    for r in _rows(con, "favorites"):  # the current state: a star taken back is gone from here (its events remain)
        yield _I(utc(r["added_at"]), "samples", ("sample", r["path"]), "favorite", 1, None, {}, ("favorites", r["_rowid"]))


def _collections(con):
    for r in _rows(con, "collection_items"):
        yield _I(r["added_at"], "samples", ("sample", r["path"]), "collect", 1, None, {},
                 ("collection_items", r["_rowid"]))


def part(track, stem, bar0, n):
    return ("part", int(track), str(stem), int(bar0), int(n))


def _stem_events(con):
    for r in _rows(con, "stem_events"):
        x = _json(r["x"]) or None
        yield _I(r["ts"], "mashup", part(r["track"], r["stem"], r["bar0"], r["n"]), r["kind"], r["y"], r["w"], dict(x=x),
                 ("stem_events", r["_rowid"]))


def mix_parts(state):
    """[(slot id, part item, slot dict)] of a saved Mashup state and its snapshots (stem slots only, not one-shots)."""
    out = []
    for mix in [state, *(state.get("snaps") or [])]:
        slots = mix.get("slots") or {}
        if not isinstance(slots, dict):
            continue
        for sid, p in slots.items():
            if not isinstance(p, dict) or p.get("track") is None or p.get("bar0") is None:
                continue
            try:
                out.append((sid, part(p["track"], p.get("stem") or sid, p["bar0"], p.get("n") or 4), p))
            except (TypeError, ValueError):
                continue
    return out


def _stem_mixes(con):
    for r in _rows(con, "stem_mixes"):  # the name is not carried: it can be a working title
        seen = set()
        for sid, it, p in mix_parts(_json(r["state"])):
            if it in seen:
                continue
            seen.add(it)
            yield _I(utc(r["updated_at"]), "mashup", it, "in_saved_mix", 1, None,
                     dict(k=p.get("k"), off=p.get("off"), lock=p.get("lock")), ("stem_mixes", r["_rowid"]))


def _edit_ratings(con):
    for r in _rows(con, "edit_ratings"):
        yield _I(r["ts"], "edits", ("move", r["path"], r["move"]), "rate", r["rating"], None,
                 dict(family=r["family"], material=r["material"], arm=r["arm"], source=r["source"], reason=r["reason"],
                      close=r["close"]), ("edit_ratings", r["_rowid"]))


def _id_paths(con):
    return dict(con.execute("SELECT id, path FROM samples").fetchall()) if _has(con, "samples") else {}


def _pair_votes(con):
    rows = _rows(con, "pair_votes")
    paths = _id_paths(con) if rows else {}
    for r in rows:  # trial = "<source sample id>-<partner sample id>" (listening.py)
        a, _, b = str(r["trial"]).partition("-")
        yield _I(r["ts"], "pairs", ("pair", paths.get(a, a), paths.get(b, b)), "vote", r["rating"], None,
                 dict(trial=r["trial"]), ("pair_votes", r["_rowid"]))


def _yt_scout(con):
    for r in _rows(con, "yt_scout"):  # the time is when it was found: when you added or skipped it isn't kept
        keys = r.keys()
        ctx = {k: r[k] for k in ("mode", "seen", "auto", "taste", "vocal", "neg") if k in keys}
        yield _I(utc(r["created_at"]), "scout", ("video", r["id"]), r["status"] or "scored", r["score"], None, ctx,
                 ("yt_scout", r["_rowid"]))


def _reco_outcomes(con):
    for r in _rows(con, "reco_outcomes"):
        try:
            it = tuple(json.loads(r["item"]))
        except (TypeError, ValueError):
            continue
        if not it:
            continue
        c = _json(r["context"])
        c["imp"] = r["imp"]
        yield _I(r["ts"], r["surface"], it, r["action"], r["value"], None, c, ("reco_outcomes", r["_rowid"]))


def about(item):
    """The items an interaction is evidence about: itself, and for a move or a pair the samples it involves (hiding a
    sample from a model hides what you did with its edits and its pairings too)."""
    out = {item}
    if item[0] == "move":
        out.add(("sample", item[1]))
    elif item[0] == "pair":
        out |= {("sample", item[1]), ("sample", item[2])}
    return out


ADAPTERS = dict(events=_events, favorites=_favorites, collection_items=_collections, stem_events=_stem_events,
                stem_mixes=_stem_mixes, edit_ratings=_edit_ratings, pair_votes=_pair_votes, yt_scout=_yt_scout,
                reco_outcomes=_reco_outcomes)
# what the harness does to a row whose item is held out (or that came after the cut): drop it, or keep the row and
# blank only its label columns (a scout find is a thing that exists; whether you added it is the label)
HIDE = dict(yt_scout=("status", "seen"))


def interactions(con, until=None, surfaces=None, tables=None):
    """Every past interaction, oldest first, with sessions. until: only those before this time (unix seconds)."""
    out = []
    for name, f in ADAPTERS.items():
        if tables and name not in tables:
            continue
        for it in f(con):
            if until is not None and it.ts >= until:
                continue
            if surfaces and it.surface not in surfaces:
                continue
            out.append(it)
    out.sort(key=lambda i: i.ts)
    return sessions(out)


def sessions(its):
    """The same interactions with their session index (a gap of over 10 minutes starts a new one)."""
    s, last, out = 0, None, []
    for it in its:
        if last is not None and it.ts - last > SESSION_GAP:
            s += 1
        last = it.ts
        out.append(it._replace(session=s))
    return out


def summary(con, until=None):
    """{(surface, action): count} and the number of distinct items per surface."""
    its = interactions(con, until)
    counts = Counter((i.surface, i.action) for i in its)
    items = {}
    for i in its:
        items.setdefault(i.surface, set()).add(i.item)
    return dict(counts=dict(counts), items={k: len(v) for k, v in items.items()},
                sessions=(its[-1].session + 1) if its else 0, n=len(its))


def print_summary(con):
    s = summary(con)
    print(f"{s['n']:,} interactions in {s['sessions']} sessions")
    last = None
    for (surf, act), n in sorted(s["counts"].items()):
        if surf != last:
            print(f"{surf}  ({s['items'][surf]:,} items)")
            last = surf
        print(f"  {act:14s} {n:6,}")
    imps = impression_counts(con)
    if imps:
        print("impressions (what was dealt or listed, with the alternatives)")
        for surf, (n, ch) in sorted(imps.items()):
            print(f"  {surf:18s} {n:6,}  ({ch:,} with what was picked)")
    outs = outcome_counts(con)
    if outs:
        print("outcomes (reco_outcomes; tied to an impression where there is one)")
        for (surf, act), (n, linked) in sorted(outs.items()):
            print(f"  {surf + '.' + act:18s} {n:6,}  ({linked:,} tied to an impression)")


def impression_counts(con):
    """{surface: (impressions, how many have a chosen item)}"""
    if not _has(con, "reco_impressions"):
        return {}
    return {r[0]: (r[1], r[2]) for r in con.execute(
        "SELECT surface, COUNT(*), COUNT(chosen) FROM reco_impressions GROUP BY surface").fetchall()}


def outcome_counts(con):
    """{(surface, action): (outcomes, how many name their impression)}"""
    if not _has(con, "reco_outcomes"):
        return {}
    return {(r[0], r[1]): (r[2], r[3]) for r in con.execute(
        "SELECT surface, action, COUNT(*), COUNT(imp) FROM reco_outcomes GROUP BY surface, action").fetchall()}


# ---------------------------------------------------------------- impressions (written from phase 3 on)

def key(item):
    """An item as a JSON-able list (and back with tuple())."""
    return list(item)


def _imp_db(con):
    con.execute("""CREATE TABLE IF NOT EXISTS reco_impressions (id INTEGER PRIMARY KEY, ts REAL, surface TEXT,
                   policy TEXT, context TEXT, shown TEXT, chosen TEXT)""")
    return con


def impression(con, surface, context, shown, chosen=None, policy=None, ts=None):
    """Record that a surface showed (or dealt) something. shown: [(item, score, probability of being picked)] or
    [dict(item=, score=, p=)] (a dict's other keys, e.g. a candidate's features x, are kept as they are); chosen: the
    item picked, if one was; policy: the model / dealing rule and its version.
    -> the impression's id (to attach the outcome later with `chose`)."""
    rows = []
    for s in shown:
        if isinstance(s, dict):
            it, sc, p = s.get("item"), s.get("score"), s.get("p")
            extra = {k: v for k, v in s.items() if k not in ("item", "score", "p")}
        else:
            it, sc, p = (tuple(s) + (None, None))[:3]
            extra = {}
        rows.append(dict(item=key(it), score=None if sc is None else float(sc), p=None if p is None else float(p),
                         **extra))
    cur = _imp_db(con).execute(
        "INSERT INTO reco_impressions (ts, surface, policy, context, shown, chosen) VALUES (?,?,?,?,?,?)",
        (time.time() if ts is None else ts, surface, json.dumps(policy) if policy is not None else None,
         json.dumps(context or {}), json.dumps(rows), json.dumps(key(chosen)) if chosen is not None else None))
    con.commit()
    return cur.lastrowid


def chose(con, impression_id, item):
    """The outcome of an impression: which of the shown items was picked (kept, played...)."""
    _imp_db(con).execute("UPDATE reco_impressions SET chosen=? WHERE id=?", (json.dumps(key(item)), impression_id))
    con.commit()


def impressions(con, surface=None, until=None):
    """[dict(id, ts, surface, policy, context, shown=[dict(item=tuple, score, p)], chosen=tuple|None)]"""
    if not _has(con, "reco_impressions"):
        return []
    q, a = "SELECT * FROM reco_impressions WHERE 1", []
    if surface:
        q += " AND surface=?"; a.append(surface)
    if until is not None:
        q += " AND ts < ?"; a.append(until)
    out = []
    for r in con.execute(q + " ORDER BY ts", a).fetchall():
        shown = [dict(s, item=tuple(s["item"])) for s in json.loads(r["shown"] or "[]")]
        out.append(dict(id=r["id"], ts=r["ts"], surface=r["surface"], policy=_json(r["policy"]) or r["policy"],
                        context=_json(r["context"]), shown=shown,
                        chosen=tuple(json.loads(r["chosen"])) if r["chosen"] else None))
    return out


# ---------------------------------------------------------------- outcomes: what happened to what was dealt

def _out_db(con):
    con.execute("""CREATE TABLE IF NOT EXISTS reco_outcomes (id INTEGER PRIMARY KEY, ts REAL, imp INTEGER, surface TEXT,
                   item TEXT, action TEXT, value REAL, context TEXT)""")
    return con


def outcome(con, imp, surface, item, action, value=None, context=None, ts=None, commit=True):
    """Record what happened to a shown or dealt item. imp: its impression's id (None when it came from nowhere logged,
    e.g. a mix saved before impressions); surface: the coarse one (samples, mashup, ...); item: as in Interaction.
    -> the outcome's id."""
    cur = _out_db(con).execute(
        "INSERT INTO reco_outcomes (ts, imp, surface, item, action, value, context) VALUES (?,?,?,?,?,?,?)",
        (time.time() if ts is None else ts, None if imp is None else int(imp), surface, json.dumps(key(item)), action,
         None if value is None else float(value), json.dumps(context or {})))
    if commit:
        con.commit()
    return cur.lastrowid


def outcomes(con, imp=None, surface=None, action=None):
    """[dict(id, ts, imp, surface, item=tuple, action, value, context)], oldest first."""
    if not _has(con, "reco_outcomes"):
        return []
    q, a = "SELECT * FROM reco_outcomes WHERE 1", []
    for col, v in (("imp", imp), ("surface", surface), ("action", action)):
        if v is not None:
            q += f" AND {col}=?"; a.append(v)
    return [dict(id=r["id"], ts=r["ts"], imp=r["imp"], surface=r["surface"], item=tuple(json.loads(r["item"])),
                 action=r["action"], value=r["value"], context=_json(r["context"]))
            for r in con.execute(q + " ORDER BY ts, id", a).fetchall()]
