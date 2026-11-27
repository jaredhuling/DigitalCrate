# Plan: chord variants of a part in Mashup

Status: researched, not built.

## The idea

From one part you like (a pad, say), get a handful of variants that are the same sound on a different chord and
still fit everything else in the mashup. Switch between them by hand, keep them in snapshots, or have the track
step through them as it loops.

## What was looked at

One real case: CFCF, *The Colours of Life*, the Other stem at bar 997.

- The loop there is **A minor** (bars 997 to 999), then F, then C.
- The 110 bars around it use only four chords in the same sound: C (59 bars), G (24), Am (20), F (19). So this
  song already holds the pad on I, V, vi and IV of C major.
- The song is filed as **F minor**, which is right for other stretches of its 40 minutes but wrong here. The mixer
  shifts the part by the filed key, so this stretch is currently shifted as if it were in F minor. Long pieces that
  change key need a key per stretch (below).

Ways to make a variant:

| Way | What it gives | Quality |
| --- | --- | --- |
| **Other bars of the same stem** on a different chord | The same instruments playing another chord of the song | As good as the original: nothing is processed |
| **Transposing the part** to another chord of the key with the same quality (a minor chord to the key's other minor chords, a major to its other majors) | Chords the song never plays | Good within about 5 semitones; the sound's character shifts with it |
| **Changing notes inside the chord** (major to minor, as Melodyne DNA or Pitchmap do) | Any chord | No open-source tool does this well; a student project and research code only. Not pursued |
| **Replaying it**: the pad as a sampler instrument with the chords as MIDI (the existing playable-pads export) | Any chord | Sounds like a sampler, not the record; useful in Live, not in the mixer |

Transposing a sampled chord and keeping to the same chord quality is the long-standing sampler practice (a chain
of the key's major chords, a chain of its minor chords).

## Design

1. **Know the chords.** When a song is prepared, run the chord recognizer already used for pads over its Other and
   Bass stems and keep one chord per bar in its meta. A pass fills this in for songs already prepared.
2. **Local key.** From those chords, a key per stretch of the song (the key whose chords cover the surrounding 16
   to 32 bars best). A part uses its stretch's key, not the song's one filed key.
3. **Variants of a part.** For the part in a track, offer:
   - the same stem's other stretches of the same length that sit on one chord, a different one, in the same local
     key, where the stem is active (most like the current part first, by sound);
   - transpositions of the current part to the key's other chords of the same quality, by the shorter way up or
     down, at most 5 semitones.
   Each is named by its chord and its place in the mashup's key (Am · vi, F · IV), and scored against what the other
   tracks play, as the dice scores parts.
4. **Using them.**
   - A **Chords** entry under the track's ⋯ opens a row of the variants; a click swaps the part in (it goes into
     the track's history, so ↶ returns).
   - **Snapshots** already keep a track's part and pitch, so a variant per snapshot needs nothing new.
   - **A sequence** (later): a track holds up to four variants and steps to the next each time its loop comes
     round, so one track plays a progression. The server renders each; the browser already schedules loops on the
     bar clock.

## Order

1. Chords per bar and the local key (also fixes parts of long pieces being shifted by the wrong key).
2. The Chords row with same-song variants.
3. Transposed variants.
4. The sequence.

## Risks

- The chord recognizer names major and minor triads only; sevenths and suspended chords come out as the nearest
  triad, which is fine for grouping but not for naming.
- A bass line under a variant still plays the old root. The fit score will show it; the variants could be offered
  for the Bass track in the same step.
