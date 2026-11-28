"""The questions the harness asks of held-out data, one per surface (docs/plans/recommend.md, "Design" 3).

    sample_taste   rank favorites above heard-not-starred samples          by sample (as the Taste page), by song, forward
    new_songs      the same, only on samples whose song has nothing rated in training                 by sample
    mashup_part    a Mashup part saved / kept / locked / snapshotted above one re-rolled / removed     by song, forward
                   (and within its slot: the same stem in the same session)
    edit_move      an edit suggestion applied / saved / 👍 above one 👎'd, dismissed or shown and left  by sample
    pair           your 1-5 "goes well with" votes (4-5 = good), ranked within each source sample      by source
    scout          a scout find you added above one you skipped or saw and left                       forward, by video

Each task's baselines (reco/baselines.py) are today's models, called unchanged; its reference is the one in use.
"""
import numpy as np

from . import log as L
from .eval import Example, forward, kfold


class Task:
    name = about = ""
    splits = ("song",)
    reference = None
    primary = ("auc",)
    ks = (5, 10)
    min_class = 10  # fewer positives or negatives than this measured: "too little data", not a number
    ranking = False

    def __init__(self):
        self.notes = []

    def examples(self, con):
        raise NotImplementedError

    def folds(self, examples, split, quick=False):
        seeds = (0,) if quick else (0, 1)
        if split == "forward":
            return forward(examples, self.min_pos)
        return kfold(examples, 5, seeds, split=split)

    def keep(self, train, example):
        """Is this held-out example part of the measurement (new_songs: only songs untouched in training)?"""
        return True

    def slices(self):
        return {}

    def models(self):
        return []

    def positive(self, e):
        return e.label > 0

    def gain(self, e):
        return float(self.positive(e))


# ---------------------------------------------------------------- samples

def _library_paths(con):
    return dict(con.execute("""SELECT s.path, s.track_id FROM samples s JOIN tracks t ON t.id=s.track_id
                               WHERE s.path NOT LIKE '_Reference/%'""").fetchall())


class SampleTaste(Task):
    name = "sample_taste"
    about = "favorites ranked above samples you heard and didn't star"
    splits = ("sample", "song", "forward")
    reference = "taste"
    min_pos = 18

    def examples(self, con):
        lib = _library_paths(con)
        fav = {r[0]: L.utc(r[1]) for r in con.execute("SELECT path, added_at FROM favorites") if r[0] in lib}
        first = {r[0]: r[1] for r in con.execute("""SELECT path, MIN(ts) FROM events WHERE type IN ('listen','star')
                                                    GROUP BY path""")}
        heard = {r[0] for r in con.execute("SELECT DISTINCT path FROM events WHERE type='listen'") if r[0] in lib}
        return [Example(("sample", p), float(p in fav), 1.0, lib[p], first.get(p, fav.get(p)))
                for p in sorted(heard | set(fav))]

    def folds(self, examples, split, quick=False):
        if split == "sample":  # taste_report.accuracy's folds exactly: every sample its own group, 5 folds x 2 seeds
            return kfold(examples, 5, (0,) if quick else (0, 1), key=lambda e: e.item[1], split="sample")
        return super().folds(examples, split, quick)

    def slices(self):
        return {}

    def models(self):
        from . import baselines as B
        return B.sample_models()


class NewSongs(SampleTaste):
    name = "new_songs"
    about = "the same, on samples whose song has nothing you rated or heard in training"
    splits = ("sample",)

    def examples(self, con):
        self.notes.append("held-out favorites from a song with nothing else heard are rare; sample_taste / song asks "
                          "the same question (every held-out song unseen) with far more data")
        return super().examples(con)

    def keep(self, train, example):
        if "touched" not in train.cache:
            q = """SELECT DISTINCT s.track_id FROM {} x JOIN samples s ON s.path=x.path"""
            got = set()
            for t in ("events", "favorites", "collection_items"):
                try:
                    got |= {r[0] for r in train.con.execute(q.format(t))}
                except Exception:
                    pass
            train.cache["touched"] = got
        return example.group not in train.cache["touched"]


# ---------------------------------------------------------------- Mashup

class MashupPart(Task):
    name = "mashup_part"
    about = "parts saved / kept / locked / snapshotted above parts re-rolled or removed, overall and within a slot"
    splits = ("song", "forward")
    reference = "mashup.learned"
    primary = ("qauc", "auc")
    ks = (3, 5)
    ranking = True
    min_pos = 15
    STEMS = ("drums", "bass", "vocals", "other")

    def examples(self, con):
        """One example per logged event, except: a save of a part already saved before (saving a mix again logs
        every slot again) and the same event on the same part twice in one session."""
        out, saved, seen = [], set(), set()
        dup_save = dup_sess = short = 0
        for it in L.interactions(con, tables=["stem_events"]):
            if it.action == "save":
                if it.item in saved:
                    dup_save += 1
                    continue
                saved.add(it.item)
            k = (it.session, it.action, it.item)
            if k in seen:
                dup_sess += 1
                continue
            seen.add(k)
            x = it.context.get("x")
            short += bool(x) and len(x) < 6
            out.append(Example(it.item, float(it.value or 0), float(it.weight or 1), it.item[1], it.ts,
                               (it.session, it.item[2]), dict(x=x, stem=it.item[2])))
        self.notes.append(f"stem_events: dropped {dup_save} re-saves of an already saved part and {dup_sess} repeats "
                          f"of the same event on the same part in one session; {short} kept examples have the older "
                          f"5-feature x (no 'still')")
        self.notes.append("'sound' in the frozen x was computed from every earlier event, including earlier events on "
                          "the same song: under the by-song split that is information from held-out labels "
                          "(mashup.sound_frozen vs mashup.sound_train shows how much)")
        return out

    def slices(self):
        return {s: (lambda e, s=s: e.item[2] == s) for s in self.STEMS}

    def models(self):
        from . import baselines as B
        return B.mashup_models()


# ---------------------------------------------------------------- edits

class EditMove(Task):
    name = "edit_move"
    about = "edit suggestions applied / saved / thumbs-up above those thumbs-down, dismissed, or shown and left"
    splits = ("sample",)
    reference = "edit.priors"
    SHOWN_ONLY = 0.3  # weight of "shown, nothing done": a weak no (not used by the metrics, which are unweighted)

    def examples(self, con):
        by = {}
        for r in con.execute("SELECT ts, path, value, context FROM events WHERE type='suggest' ORDER BY ts"):
            c = L._json(r["context"])
            d = by.setdefault((r["path"], c.get("move")), dict(ts=r["ts"], acts=set(), rate=[], ctx={}))
            d["acts"].add(c.get("action"))
            d["ctx"].update({k: c[k] for k in ("family", "arm", "material") if c.get(k)})
        try:
            rows = con.execute("SELECT * FROM edit_ratings ORDER BY ts").fetchall()
        except Exception:
            rows = []
        for r in rows:
            d = by.setdefault((r["path"], r["move"]), dict(ts=r["ts"], acts=set(), rate=[], ctx={}))
            d["rate"].append(r)
            d["ctx"].update({k: r[k] for k in ("family", "arm", "material") if r[k]})
        out, self.explicit = [], set()
        n_shown = 0
        for (p, mv), d in sorted(by.items(), key=lambda kv: kv[1]["ts"]):
            ctx = dict(d["ctx"], move=mv)
            if d["rate"]:
                last = d["rate"][-1]
                y, w = float(last["rating"] > 0), 1.0
                ctx.update(params=L._json(last["params"]), close=last["close"],
                           delta=np.frombuffer(last["delta"], np.float16).astype(np.float32) if last["delta"] else None)
            elif d["acts"] & {"apply", "save"}:
                y, w = 1.0, 1.0
            elif "dismiss" in d["acts"]:
                y, w = 0.0, 1.0
            else:
                y, w = 0.0, self.SHOWN_ONLY
                n_shown += 1
            if w == 1.0:
                self.explicit.add(("move", p, mv))
            out.append(Example(("move", p, mv), y, w, p, d["ts"], None, ctx))
        self.notes.append(f"{len(out)} (sample, move) pairs: {len(self.explicit)} with a rating, apply, save or dismiss; "
                          f"{n_shown} only shown (counted as a no)")
        return out

    def slices(self):
        return dict(explicit=lambda e: e.item in self.explicit)  # also where edit.model and edit.close can score

    def models(self):
        from . import baselines as B
        return B.edit_models()


# ---------------------------------------------------------------- pairs

class Pair(Task):
    name = "pair"
    about = "blind 'goes well with' votes: pairs rated 4-5 above those rated 1-3, and in order within each source"
    splits = ("source",)
    reference = "pair.clap"
    primary = ("auc", "ndcg@3")
    ks = (3,)
    ranking = True

    def examples(self, con):
        out = []
        for it in L.interactions(con, tables=["pair_votes"]):
            out.append(Example(it.item, float(it.value), 1.0, it.item[1], it.ts, it.item[1], {}))
        return out

    def positive(self, e):
        return e.label >= 4

    def gain(self, e):
        return e.label - 1

    def models(self):
        from . import baselines as B
        return B.pair_models()


# ---------------------------------------------------------------- scout

class Scout(Task):
    name = "scout"
    about = "scout finds you added above finds you skipped, or saw and left"
    splits = ("forward", "video")
    reference = "scout.score"
    min_pos = 4

    def examples(self, con):
        out, n = [], {}
        for it in L.interactions(con, tables=["yt_scout"]):
            st, seen = it.action, it.context.get("seen")
            if st == "ingested":
                y, w = 1.0, 1.0
            elif st == "skipped":
                y, w = 0.0, 1.0
            elif st == "scored" and seen == 1:
                y, w = 0.0, 0.5
            else:
                continue
            n[st] = n.get(st, 0) + 1
            out.append(Example(it.item, y, w, it.item[1], it.ts, None, dict(mode=it.context.get("mode") or "voice")))
        self.notes.append(f"labels: {n.get('ingested', 0)} added, {n.get('skipped', 0)} skipped, {n.get('scored', 0)} "
                          "seen and left (weak no); finds you never saw are left out")
        return out

    def folds(self, examples, split, quick=False):
        if split == "video":
            return kfold(examples, 5, (0,) if quick else (0, 1), split="video")
        return super().folds(examples, split, quick)

    def slices(self):
        return {m: (lambda e, m=m: e.context.get("mode") == m) for m in ("voice", "pads", "guided")}

    def models(self):
        from . import baselines as B
        return B.scout_models()


TASKS = {t.name: t for t in (SampleTaste, NewSongs, MashupPart, EditMove, Pair, Scout)}
