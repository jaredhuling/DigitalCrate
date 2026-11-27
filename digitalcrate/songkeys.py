"""A song's chords bar by bar, and the key of each stretch of it.

A song has one key on file, which is wrong for the stretches of a long piece that are in another key (a 40-minute
piece filed as F minor has a hundred bars of C, G, Am, F near its end). Mashup shifts a part by its key, so it needs
the key of the bars the part comes from.

    bar_chords(chords, bars)         -> one chord a bar ("Am", "D♭", None), from pads.chords' [(start, end, name)]
    local_keys(per_bar, filed)       -> [[first bar, pc, scale], ...]: the key of each stretch
    key_at(m, bar0, ns)              -> (pc, scale) of those bars of a prepared song (its filed key if not analysed)

The key of a stretch is the one whose chords cover it best. A key and its relative minor have the same chords; which
of the two a stretch is called follows which tonic chord it plays more. The filed key is believed unless the chords
clearly say otherwise, and a change of key has to hold for a while (a borrowed chord isn't a modulation).
"""
import numpy as np

NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
_ROOT = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
# how strongly a chord says "this major key" (by its root's distance above the tonic, and whether it is minor)
_WEIGHT = {(0, False): 1.0, (9, True): 1.0, (7, False): 0.9, (5, False): 0.8, (2, True): 0.8, (4, True): 0.7}
WINDOW = 8      # bars either side that vote on a bar's key
SWITCH = 6.0    # what a change of key costs: it must fit better by this much, summed over its bars
PRIOR = 0.2    # the filed key's head start, per bar (on 15 songs: it loses only where it fits none of the chords)
MIN_CHORDS = 4  # fewer chord bars than this in the window: no opinion
AGREE = 0.05    # how much better the notes must fit a new key than the filed one
AGREE_PARALLEL = 0.15  # ... and when the new key is the same tonic in the other mode: the recognizer's usual mistake


def parse(name):
    """'B♭m' -> (10, True); None for anything that isn't a major or minor triad's name."""
    if not name or name[0] not in _ROOT:
        return None
    pc, rest = _ROOT[name[0]], name[1:]
    while rest and rest[0] in "♭b♯#":
        pc += -1 if rest[0] in "♭b" else 1
        rest = rest[1:]
    if rest not in ("", "m"):
        return None
    return pc % 12, rest == "m"


def bar_chords(chords, bars):
    """The chord that fills most of each bar (None where no chord covers a quarter of it)."""
    out, j = [], 0
    for a, b in zip(bars[:-1], bars[1:]):
        while j < len(chords) and chords[j][1] <= a:
            j += 1
        best, k = (0.25 * (b - a), None), j
        while k < len(chords) and chords[k][0] < b:
            ov = min(b, chords[k][1]) - max(a, chords[k][0])
            if ov > best[0]:
                best = (ov, chords[k][2])
            k += 1
        out.append(best[1])
    return out


def _major_of(pc, scale):
    return (pc + 3) % 12 if scale == "minor" else pc % 12


_MAJ = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])  # Krumhansl's key profiles
_MIN = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


def notes_fit(chroma, K):
    """How well a stretch's notes (a 12-note chroma) sit in the major key K or its relative minor: -1..1."""
    c = np.asarray(chroma, float)
    if not np.any(c):
        return 0.0
    r = lambda prof, pc: float(np.corrcoef(c, np.roll(prof, pc))[0, 1])
    return max(r(_MAJ, K), r(_MIN, (K + 9) % 12))


def local_keys(per_bar, filed=None, chroma=None):
    """per_bar: a chord name (or None) a bar. filed: the song's (pc, scale) on file. chroma: the notes of every bar (12
    values each), a second opinion: a stretch leaves the filed key only if its notes fit the new key at least as well
    (the chord recognizer mistakes major for minor at times, which would read as a change of key three semitones off).
    -> [[first bar, pc, scale], ...] covering every bar; [] if the chords say nothing (too few of them)."""
    n = len(per_bar)
    ch = [parse(c) for c in per_bar]
    if sum(c is not None for c in ch) < MIN_CHORDS:
        return []
    # how well each bar's chord sits in each of the 12 major keys (a relative minor shares its major's chords)
    fitb = np.zeros((n, 12))
    has = np.zeros(n)
    for b, c in enumerate(ch):
        if c is None:
            continue
        has[b] = 1
        for K in range(12):
            fitb[b, K] = _WEIGHT.get(((c[0] - K) % 12, c[1]), 0.0)
    # a bar's evidence: the mean over its window's chord bars
    cs = np.vstack([np.zeros((1, 12)), np.cumsum(fitb, 0)])
    ch_n = np.r_[0, np.cumsum(has)]
    lo = np.clip(np.arange(n) - WINDOW, 0, n)
    hi = np.clip(np.arange(n) + WINDOW, 0, n)
    cnt = ch_n[hi] - ch_n[lo]
    e = (cs[hi] - cs[lo]) / np.maximum(cnt, 1)[:, None]
    e[cnt < MIN_CHORDS] = 0.0
    if filed:
        e[:, _major_of(*filed)] += PRIOR
    # the best path through the keys, a change costing SWITCH
    score, back = e[0].copy(), np.zeros((n, 12), int)
    for b in range(1, n):
        stay, best = score, int(np.argmax(score))
        jump = score[best] - SWITCH
        back[b] = np.where(stay >= jump, np.arange(12), best)
        score = np.maximum(stay, jump) + e[b]
    path = np.zeros(n, int)
    path[-1] = int(np.argmax(score))
    for b in range(n - 1, 0, -1):
        path[b - 1] = back[b, path[b]]
    out, b0 = [], 0
    for b in range(1, n + 1):
        if b == n or path[b] != path[b0]:
            K = int(path[b0])
            seg = [c for c in ch[b0:b] if c is not None]
            major, minor = sum(c == (K, False) for c in seg), sum(c == ((K + 9) % 12, True) for c in seg)
            if filed and _major_of(*filed) == K:  # the filed key's chords: its name for them too
                scale = filed[1]
            else:
                scale = "minor" if minor > 1.25 * major else "major"  # (by a clear margin: a bar more is chance)
            if filed and chroma is not None and K != _major_of(*filed):
                notes = np.asarray(chroma[b0:b], float).sum(0) if len(chroma[b0:b]) else np.zeros(12)
                parallel = (K - _major_of(*filed)) % 12 in (3, 9)  # the same tonic in the other mode (F minor / F major)
                if notes_fit(notes, K) < notes_fit(notes, _major_of(*filed)) + (AGREE_PARALLEL if parallel else AGREE):
                    K, scale = _major_of(*filed), filed[1]  # the notes don't back the chords: the filed key stands
            key = [b0, (K + 9) % 12 if scale == "minor" else K, scale]
            if out and out[-1][1:] == key[1:]:
                pass  # the same key as the stretch before (after a stretch fell back to the filed key)
            else:
                out.append(key)
            b0 = b
    return out


def key_at(m, bar0=None, ns=None):
    """The key of a prepared song's bars bar0..bar0+ns (the key most of them are in); its filed key when the song has
    no keys worked out, or for the song as a whole."""
    keys = m.get("keys")
    if not keys or bar0 is None:
        return m["pc"] % 12, m["scale"]
    a, b = int(bar0), int(bar0) + max(1, int(ns or 1))
    nb = max(b, len(m["bars"]) - 1)
    best, top = None, 0
    for i, (s, pc, scale) in enumerate(keys):
        e = keys[i + 1][0] if i + 1 < len(keys) else nb
        ov = min(b, e) - max(a, s)
        if ov > top:
            best, top = (pc, scale), ov
    return best or (m["pc"] % 12, m["scale"])


def name(pc, scale):
    return NOTES[pc % 12] + ("m" if scale == "minor" else "")
