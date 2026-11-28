# Plan: Mashup, the stem mixer (recombine drums, bass, vocals and the rest from different songs)

Status: phase 1 built, and from phase 2: half/double time, bar rotation, the still-harmony preference, choosing a song
yourself, saving combinations. Still to do: per-bar warping, grain- and section-aware picking, export.

How a slot looks and is played: [tracks.md](tracks.md).

Snapshots, blends between them and the low-end duck: [blend.md](blend.md).
Tops are the fifth part of a song. See [tracks.md](tracks.md).

## The idea

Slots that each play one stem (**drums**, **bass**, **vocals** or **other**): four to start with, up to eight, and
any slot's role can be changed. Each pulls a few bars of that stem from a different song.
Everything is stretched to one tempo and shifted to one key, loops in sync, and has its own loop position and
length, pitch, volume, EQ and delay. **🎲** on a slot pulls a new part that fits what's playing; **🎲 all** deals a
whole new combination. The mixer recommends parts, and learns from what you keep, rate and throw away.

## Design

**1. A stem library.** Songs are separated once (`htdemucs_ft`) and kept as four full-length FLAC stems under
`_data/stems/t<track>/`, with what the mixer needs to know about them:
- bar lines (Beat This!), tempo and key, as mining finds them;
- per bar and stem: how active the stem is (so loops start where something plays);
- per bar: the harmony (a 12-note chroma of bass + vocals + other), so two songs can be compared bar by bar;
- per stem: a sound embedding (CLAP), for learning what you like.

Songs come from your favorites' sources plus random mined songs. Reference-only artists are never used; hip-hop
contributes vocals only (the source policy).

**2. Rendering a part.** A part is (song, stem, first bar, bars). The server cuts those bars from the stem and
stretches them to exactly that many bars at the mixer's tempo (Signalsmith; Re-Pitch when nothing needs stretching),
shifted by the slot's semitones. Drums are never pitch-shifted. Parts are cached, so a part renders once (well under
a second for 4 bars).

**3. Playing.** The browser loops each rendered part sample-accurately on one shared bar clock (as the sketchpad
does). A new part comes in at the right place in the bar, not from its start. Per slot, live in the browser: volume,
mute, solo, a 3-band EQ, and a tempo-synced delay.

**4. Harmony.** Matching keys is not enough: a bass line follows its own song's chords.
- *Key:* every pitched slot is shifted by the smallest interval that brings its song's key to the mixer's key
  (relative major and minor count as the same), plus your own offset.
- *Fit:* two parts are compared bar by bar: the cosine of their chromas after transposition, looped to a common
  length. 1.0 means the same notes in every bar. The mixer shows the fit of what's playing.
- *Picking:* a new part for a pitched slot is chosen to fit the pitched parts already playing.
- *Rotation:* a candidate is also tried starting 1-3 bars later, and the start whose chords line up best wins.
- *Still harmony:* bass and other parts that sit on one or two chords score higher (they clash less).
- *Tempo:* a song near twice or half the mixer's tempo plays half-time or double-time (two of its bars per bar, or
  one over two), which greatly widens what can combine.
- To do: an option to keep bass and other from one song.

**5. Recommendations that learn.** Every candidate part gets a score:
- how active the stem is in those bars;
- how little it has to be stretched and shifted (drums smear beyond about ±15%; voices beyond about ±3 semitones);
- harmony fit with the pitched parts already playing;
- how close its sound is to parts you liked, minus parts you disliked (CLAP);
- how still its own harmony is (bass and other).

🎲 draws from the best-scoring parts with some randomness, so it explores. What teaches it:
- **👍 / 👎** on the whole combination (strong, every slot);
- **saving** a combination (the strongest yes);
- **re-rolling** a slot within a few seconds, or **removing** a part (weak "not this");
- **keeping** a part playing for a while, and **locking** it (weak "yes").

The weights start as sensible guesses and are refitted (ridge logistic regression, pulled toward the guesses) once
there are a dozen ratings, then after each new one. The mixer says how many ratings it has learned from.

**6. One-shots.** A slot can also play a library sample at chosen steps of a cycle of bars (a vocal chop in the
middle of bar 2, a stab at the end of bar 4). The dice chooses by how well the sample's notes sit on the chords of
some bar, after shifting to the key, plus the sample taste model's score (capped, or your favorites would be all you
get); the first hit goes on the bar it fits best. Hits are scheduled on the mixer's bar clock through the slot's own
chain, so volume, EQ, delay and reverb apply. Not yet: one-shot slots in the play-strip view (snapshots keep them,
the strip doesn't play them), and learning from which one-shots you keep beyond counting as a listen.

**How a sample's fit is scored** (one-shots and pads; `notes.py`, `stems.cycle_target`). Each sample's notes are
measured at 36 positions an octave, which gives its tuning (cents off the grid, and how steady) and the share of its
energy on each note, read on its own grid with the floor taken off. Each bar of the cycle gets a worth per note from
what the other tracks play: 1 for a chord tone (the chords of the stem parts' own bars, shifted as the parts are, and
the notes that stand out in the other one-shot and pad tracks), 0.25 for another note of the key, 0 for a note of
the key a semitone above a chord tone, -1 for a note outside the key. The fit is the sample's shares times those
worths, cut to 0..1. A sample that sits steadily 8 cents or more off the other tracks' tuning is dealt with the cents
that bring it in. The earlier fit (the cosine of two 12-note chromas) matched vague samples to any harmony at
95-98% and ignored tuning; it stays selectable (`fit: old` in `_data/reco/settings.json`). The logged deals can't
tell the two apart yet (14 kept one-shots of 144 dealt): this one is judged by ear. On 40 steady samples the tuning
agreed with a pitch tracker within 15 cents for 85%. Not changed: how stem parts are fitted to each other.

## Limits

- Separation artifacts show more in an exposed stem than in a mix (see separation grain).
- Tempo changes inside the chosen bars are averaged out (one stretch per part, not one per bar).
- A song with a wrong key or downbeat on file gives parts that clash or start mid-bar; the fit score catches the first.

## Phases

1. **Prototype (built):** library pass for ~100 songs, the four slots with 🎲, lock, loop position and length, pitch,
   volume, mute/solo, EQ, delay, harmony fit, 👍/👎 and the learning score.
2. **Smarter:** static-harmony preference, bar rotation for fit, per-bar warping, grain-aware picking, sections
   (prefer exposed sections for vocals), "more like this slot".
3. **Out of the mixer:** bounce a combination to a sample or the sketchpad; export a Live set with each stem on its
   own track, warped.

## Open questions

- Should a liked combination be saved as a sketch, a sample, or its own kind of thing?
- How much should the mixer explore (new songs) against exploit (songs whose parts you've liked)?
