"""Features for any item, from what the app already computed, and the links between items.

    it = Items(con)
    it.clap(items)    -> (E, mask)    unit-length CLAP embeddings (512): samples from the samples table, stem parts from
                                      the stem's own embedding (stems._emb), a song: the mean of its samples, a move:
                                      its sample, a pair: the mean of its two, a video: the scout's preview embedding.
                                      Samples and stems live in the same CLAP space, which is what lets a like travel.
    it.style(items)   -> (S, mask)    the song's Discogs-EffNet style embedding (1280; styles.py)
    it.meta(items)    -> [dict]       kind, track, artist, category, sample kind, stem, key, scale, bpm, quality, grain
    it.numeric(items) -> (X, mask, names)   quality, grain, bpm, key strength, duration as columns (standardized)
    links: song_of(item), artist_of(item), samples_of(track), songs_of(artist), sample(path), track(tid)

Missing pieces are zeros with mask False, never an error: a part whose song lost its stems, a song that was never
style-tagged, a sample deleted since you rated it. Everything is cached per library state (sample and track counts).
"""
import numpy as np

_CACHE = {}


def artist_key(name):
    """One artist however the tags spell it (case, spacing)."""
    return " ".join((name or "").lower().split()) or None


def _unit(E):
    n = np.linalg.norm(E, axis=-1, keepdims=True)
    return np.where(n > 0, E / np.maximum(n, 1e-9), 0).astype(np.float32)


class Items:
    def __init__(self, con):
        self.con = con
        key = tuple(con.execute("SELECT COUNT(*), MAX(rowid) FROM samples").fetchone()) + \
            tuple(con.execute("SELECT COUNT(*), MAX(rowid) FROM tracks").fetchone())
        if _CACHE.get("key") != key:
            _CACHE.clear()
            _CACHE["key"] = key
        self._c = _CACHE

    # ---------------------------------------------------------------- tables, loaded once
    def _samples(self):
        if "samples" not in self._c:
            cols = {r[1] for r in self.con.execute("PRAGMA table_info(samples)")}
            opt = lambda c: c if c in cols else f"NULL AS {c}"
            rows = self.con.execute(f"""SELECT path, id, track_id, category, kind, key, scale, bpm, quality, dur,
                                         key_strength, {opt('grain')}, clap FROM samples""").fetchall()
            paths = [r["path"] for r in rows]
            E = np.zeros((len(rows), 512), np.float32)
            have = np.zeros(len(rows), bool)
            for i, r in enumerate(rows):
                if r["clap"]:
                    E[i] = np.frombuffer(r["clap"], np.float16).astype(np.float32)
                    have[i] = True
            meta = {r["path"]: dict(id=r["id"], track=r["track_id"], category=r["category"], skind=r["kind"],
                                    key=r["key"], scale=r["scale"], bpm=r["bpm"], quality=r["quality"], dur=r["dur"],
                                    key_strength=r["key_strength"], grain=r["grain"]) for r in rows}
            by_track = {}
            for p, m in meta.items():
                by_track.setdefault(m["track"], []).append(p)
            self._c["samples"] = dict(pos={p: i for i, p in enumerate(paths)}, E=_unit(E), have=have, meta=meta,
                                      by_track=by_track, by_id={m["id"]: p for p, m in meta.items()})
        return self._c["samples"]

    def _tracks(self):
        if "tracks" not in self._c:
            rows = self.con.execute("SELECT id, artist, bpm, key, scale FROM tracks").fetchall()
            t = {r["id"]: dict(artist=r["artist"], artist_key=artist_key(r["artist"]), bpm=r["bpm"], key=r["key"],
                               scale=r["scale"]) for r in rows}
            by_artist = {}
            for tid, m in t.items():
                by_artist.setdefault(m["artist_key"], []).append(tid)
            self._c["tracks"] = dict(t=t, by_artist=by_artist)
        return self._c["tracks"]

    def _styles(self):
        if "styles" not in self._c:
            try:
                from ..styles import embeddings
                ids, S, _ = embeddings(self.con)
            except Exception:
                ids, S = [], np.zeros((0, 1280), np.float32)
            self._c["styles"] = ({t: i for i, t in enumerate(ids)}, S)
        return self._c["styles"]

    def _videos(self):
        if "videos" not in self._c:
            v = {}
            try:
                for r in self.con.execute("SELECT id, emb FROM yt_scout WHERE emb IS NOT NULL"):
                    v[r["id"]] = _unit(np.frombuffer(r["emb"], np.float16).astype(np.float32))
            except Exception:
                pass
            self._c["videos"] = v
        return self._c["videos"]

    # ---------------------------------------------------------------- links
    def sample(self, path):
        return self._samples()["meta"].get(path)

    def track(self, tid):
        return self._tracks()["t"].get(tid)

    def path_of_id(self, sample_id):
        return self._samples()["by_id"].get(sample_id)

    def song_of(self, item):
        """The song (track id) an item comes from; for a pair, its first sample's; None for a video."""
        k = item[0]
        if k == "song":
            return item[1]
        if k == "part":
            return item[1]
        if k in ("sample", "move", "pair"):
            m = self.sample(item[1])
            return m["track"] if m else None
        return None

    def artist_of(self, item):
        t = self.track(self.song_of(item))
        return t["artist_key"] if t else None

    def samples_of(self, track):
        return list(self._samples()["by_track"].get(track, []))

    def songs_of(self, artist):
        return list(self._tracks()["by_artist"].get(artist_key(artist), []))

    # ---------------------------------------------------------------- features
    def _clap1(self, item):
        S = self._samples()
        k = item[0]
        if k in ("sample", "move"):
            i = S["pos"].get(item[1])
            return (S["E"][i], True) if i is not None and S["have"][i] else (None, False)
        if k == "part":
            from .. import stems
            try:
                e = stems._emb(item[1], item[2])
            except Exception:
                return None, False
            return (e.astype(np.float32), True) if np.any(e) else (None, False)
        if k == "song":
            idx = [S["pos"][p] for p in S["by_track"].get(item[1], []) if S["have"][S["pos"][p]]]
            return (_unit(S["E"][idx].mean(0)), True) if idx else (None, False)
        if k == "pair":
            a, b = self._clap1(("sample", item[1])), self._clap1(("sample", item[2]))
            return (_unit((a[0] + b[0]) / 2), True) if a[1] and b[1] else (None, False)
        if k == "video":
            e = self._videos().get(item[1])
            return (e, True) if e is not None else (None, False)
        return None, False

    def clap(self, items):
        E = np.zeros((len(items), 512), np.float32)
        mask = np.zeros(len(items), bool)
        for i, it in enumerate(items):
            e, ok = self._clap1(tuple(it))
            if ok:
                E[i], mask[i] = e, True
        return E, mask

    def style(self, items):
        at, SE = self._styles()
        S = np.zeros((len(items), SE.shape[1] if len(SE) else 1280), np.float32)
        mask = np.zeros(len(items), bool)
        for i, it in enumerate(items):
            j = at.get(self.song_of(tuple(it)))
            if j is not None:
                S[i], mask[i] = SE[j], True
        return S, mask

    def meta(self, items):
        out = []
        for it in items:
            it = tuple(it)
            tid = self.song_of(it)
            t = self.track(tid) or {}
            d = dict(kind=it[0], track=tid, artist=t.get("artist_key"))
            if it[0] in ("sample", "move", "pair"):
                m = self.sample(it[1]) or {}
                d.update(category=m.get("category"), skind=m.get("skind"), key=m.get("key"), scale=m.get("scale"),
                         bpm=m.get("bpm"), quality=m.get("quality"), grain=m.get("grain"), dur=m.get("dur"),
                         key_strength=m.get("key_strength"))
            elif it[0] in ("part", "song"):
                d.update(stem=it[2] if it[0] == "part" else None, key=t.get("key"), scale=t.get("scale"),
                         bpm=t.get("bpm"))
            out.append(d)
        return out

    NUMERIC = ("quality", "grain", "bpm", "key_strength", "dur")

    def numeric(self, items):
        """(X, mask, names): the numeric metadata as columns, standardized over the library's samples; a missing
        value is 0 (the mean) with mask False."""
        if "num_stats" not in self._c:
            M = list(self._samples()["meta"].values())
            st = {}
            for c in self.NUMERIC:
                v = np.array([m[c] for m in M if m.get(c) is not None], float)
                st[c] = (float(v.mean()), float(v.std() + 1e-9)) if len(v) else (0.0, 1.0)
            self._c["num_stats"] = st
        st = self._c["num_stats"]
        md = self.meta(items)
        X = np.zeros((len(items), len(self.NUMERIC)), np.float32)
        mask = np.zeros_like(X, bool)
        for i, d in enumerate(md):
            for j, c in enumerate(self.NUMERIC):
                if d.get(c) is not None:
                    X[i, j] = (d[c] - st[c][0]) / st[c][1]
                    mask[i, j] = True
        return X, mask, list(self.NUMERIC)
