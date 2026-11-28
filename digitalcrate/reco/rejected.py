"""Parts you turned down, so the Mashup dice stops dealing them again (docs/guide.md, "Mashup").

A part (a song's stem, some bars) you re-rolled away quickly or rated down, and never kept, gets a penalty on its
dice score: one per time you turned it down, fading by half every PART_HALF_LIFE days, capped. A part that overlaps
the bars you turned down counts as the same part. The song's other parts of that stem get a milder version (you may
have turned down that song's sound, not just those bars). Anything you kept, locked, snapshotted, saved, rated up or
listened to for a minute clears it: for that part, and for the song's milder penalty.

    rj = Rejections.load(con)            # reads reco_outcomes (Mashup) and the legacy stem_events
    rj.penalty(track, stem, bar0, n)     # -> subtract from the part's dice score (0 for anything never turned down)

Before this, a part re-rolled away was dealt again and re-rolled again 118 of 127 times.
"""
import json
import time

PART_PENALTY = 1.0         # per time a part was turned down (the dice scores of the top songs span about 2)
PART_HALF_LIFE = 7.0       # days for a rejection to count half
PART_CAP = 3.0             # however often: at most this
SONG_PENALTY = 0.25        # the song's other parts of that stem, per rejection
SONG_HALF_LIFE = 7.0
SONG_CAP = 0.75
QUICK_SECS = 20            # replaced by another deal within this many seconds of listening: turned down
MERGE_SECS = 60            # the same part turned down twice within this (an outcome and its legacy event): once
DEALT_AWAY = {"dice", "all", "down", "find", "best", "alt"}  # what a part was replaced by when that is a judgment
DOWN = {"reroll": 1.0, "remove": 1.0, "dislike": 0.5}        # legacy stem_events (dislike: the whole combination)
KEPT = {"save", "kept", "lock", "snap", "like"}              # legacy stem_events that clear a part
KEPT_OUT = {"saved", "locked", "snapped", "exported"}         # reco_outcomes that clear it ("rated" +1 and "heard" 60+
                                                              # too)


def _rows(con, q):
    try:
        return con.execute(q).fetchall()
    except Exception:  # no such table yet
        return []


class Rejections:
    def __init__(self, down, kept, now=None):
        """down: [(ts, track, stem, bar0, n, weight)]; kept: [(track, stem, bar0, n)]."""
        self.now = time.time() if now is None else now
        self.kept = {}
        for tr, st, b0, n in kept:
            self.kept.setdefault((int(tr), st), []).append((int(b0), int(b0) + int(n)))
        self.down = {}
        last = {}
        for ts, tr, st, b0, n, w in sorted(down):
            k = (int(tr), st, int(b0), int(n))
            if ts - last.get(k, -1e18) < MERGE_SECS:
                continue
            last[k] = ts
            self.down.setdefault((int(tr), st), []).append((int(b0), int(b0) + int(n), float(ts), float(w)))

    @classmethod
    def load(cls, con, now=None):
        down, kept = [], []
        for r in _rows(con, "SELECT ts, kind, stem, track, bar0, n FROM stem_events"):
            if r[1] in DOWN:
                down.append((r[0], r[3], r[2], r[4], r[5], DOWN[r[1]]))
            elif r[1] in KEPT:
                kept.append((r[3], r[2], r[4], r[5]))
        for r in _rows(con, "SELECT ts, item, action, value, context FROM reco_outcomes WHERE surface='mashup'"):
            try:
                it = json.loads(r[1])
                ctx = json.loads(r[4] or "{}")
            except (TypeError, ValueError):
                continue
            if not it or it[0] != "part":
                continue
            _, tr, st, b0, n = it[:5]
            act, v = r[2], r[3]
            if act in KEPT_OUT or (act == "rated" and (v or 0) > 0) or (act == "heard" and (v or 0) >= 60):
                kept.append((tr, st, b0, n))
            elif (act == "rated" and (v or 0) < 0) or \
                    (act == "replaced" and ctx.get("by") in DEALT_AWAY and (ctx.get("secs") or 0) < QUICK_SECS):
                down.append((r[0], tr, st, b0, n, 1.0))
        return cls(down, kept, now)

    def __len__(self):
        return sum(len(v) for v in self.down.values())

    def penalty(self, track, stem, bar0, n):
        """How much less this part should score: 0 unless it (or its song's stem) was turned down and never kept."""
        key = (int(track), stem)
        got = self.down.get(key)
        if not got:
            return 0.0
        a, b = int(bar0), int(bar0) + int(n)
        keeps = self.kept.get(key, [])
        part_kept = any(x < b and a < y for x, y in keeps)
        part = song = 0.0
        for x, y, ts, w in got:
            age = max(0.0, self.now - ts) / 86400
            if x < b and a < y:
                if not part_kept:
                    part += w * 0.5 ** (age / PART_HALF_LIFE)
            song += w * 0.5 ** (age / SONG_HALF_LIFE)
        out = min(PART_CAP, PART_PENALTY * part)
        if not keeps:
            out += min(SONG_CAP, SONG_PENALTY * song)
        return out
