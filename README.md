# DigitalCrate

<img src="digitalcrate/static/icon.png" alt="DigitalCrate icon" width="140" align="right">

[![tests](https://github.com/jaredhuling/DigitalCrate/actions/workflows/tests.yml/badge.svg)](https://github.com/jaredhuling/DigitalCrate/actions/workflows/tests.yml)

**Turn your record collection into a playable sample library.** DigitalCrate listens to the music you own, cuts out the
clean moments (exposed vocals, pads, chords, textures, drum hits), tags them by key, tempo, instrument and mood, and
gives you a studio to find, combine and shape them before they go into Ableton Live.

![Browsing: category tabs, ↓ to preview, why the taste model picked a sample, "goes well with", the Artists view](docs/img/browse-2.gif)

- **Mine** vocals, pads, chords, melodies, textures and drums from your own music.
- **Find** sounds by category, key or mood, by describing them, or by what fits a track you're making.
- **Combine** them in a sketchpad that keeps everything in key and on the grid, with a drum sequencer and chord
  suggestions.
- **Export** to Ableton: organized folders, stems, MIDI, Drum Racks and Live sets.
- **Learn your taste** from stars, skips and listening, and rank what you haven't heard yet.

## Quick start

Mac with Apple Silicon. Paste into Terminal:

```bash
curl -fsSL https://raw.githubusercontent.com/jaredhuling/DigitalCrate/main/install.sh | bash
```

This installs **DigitalCrate** in Applications. The first time you open it, it asks where your music is and mines a
first batch (10 minutes to an hour). Run the command again to update.

<details>
<summary>Install by hand / command line</summary>

```bash
git clone https://github.com/jaredhuling/DigitalCrate.git digitalcrate && cd digitalcrate
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python --no-deps -r requirements.lock
uv pip install --python .venv/bin/python --no-deps -e .
cp digitalcrate.example.toml digitalcrate.toml      # your music folder, where the library goes

source .venv/bin/activate
digitalcrate scan && digitalcrate scout             # catalog, then rank tracks
digitalcrate process --top 200                      # mine the 200 most promising
digitalcrate build && digitalcrate serve            # → http://localhost:8765
```

`--no-deps` is deliberate: one dependency pins a version that no longer installs. The first run downloads a few GB of
models.
</details>

## Features

### Browse

- Tabs for vocals, pads, strings & orchestral, chords, melodies, textures, bass and drums, plus an **Artists** view (artist → album → song).
- **★** keeps a sample, **✕** hides it; both teach the taste model, which ranks everything you haven't heard yet.
- **Pads** hold one or two chords and loop seamlessly; **🎹 playable** turns one into a Simpler instrument tuned to
  its chord, with its chords as MIDI.
- **Goes well with** lists samples that fit by key, tempo and sound; **⧉** plays a pair together.
- **🎛 Mashup** (prototype) builds a track from stems of different songs; see [Mashup](#mashup).
- **💡 why this?** explains any recommendation; **🕘 recent actions** undoes anything.
- Arrow keys preview as you move; drag any row straight into Live.

### Sketchpad

![Sketchpad: trimming, faders, tempo matching](docs/img/sketch-2.gif)

- Layer up to 8 samples, all conformed to the project key and tempo.
- Trim, fade, loop, solo and mix each lane; match a loop's tempo or re-align it to the beat.
- Lay out sections (`AABA`) and choose which lanes play in each.
- Export as a bounce, stems, or an Ableton Live set. Full undo; ready-made **kits** to start from.

### Drum lane

![Building a kit around one kick, then velocity, a flam and humanize while it plays](docs/img/drumlane-2.gif)

- A 16-step sequencer for mined drum hits: velocity, flams, swing, humanize and choke groups.
- **🔎 complete the kit** finds hits that sound like they were recorded together; **🥁 build a kit around this**
  starts from any one hit.
- **🥁 slice into pads** cuts a drum loop into hits you can re-sequence.
- Export a Drum Rack plus a MIDI clip of the pattern.

### Mashup

**🎛 Mashup** (a prototype) builds a track out of stems from different songs. Each track plays one part (drums, tops,
bass, vocals or other) from a song of yours, all on one tempo and key, up to 16 tracks. The **🎲** deals a part that
fits what's playing, and learns from what you keep and throw out. Mine songs for it with `digitalcrate stems`, or tick
**also prepare them for Mashup** when mining.

- **Best fits…** lists a track's candidate parts in ranked order instead of a random deal.
- **More from this song…** lists the other samples cut from a one-shot's song, best fit first.
- **Splice pieces…** builds a part from pieces of its song: reorder, reverse, stretch, repeat, rests and crossfades.
- **One-shot tracks** and **pad tracks** play library samples on a step grid, shifted to the key.
- **Play it as a one-shot** turns any stem part into a one-shot track.
- **📸 snapshots** keep a mix, and the **▶ play strip** blends from one to the next.
- **+** and **−** rate a part on a track, and teach the dice for that part alone.
- **⇩ Ableton** writes the mashup as a Live set.

The [guide](docs/guide.md#mashup) has the detail.

### Chords

![Chord suggestions with the keyboard following the progression](docs/img/chords-2.gif)

- Progressions that fit any sample's notes, colored by its mood, with a keyboard display.
- Basslines (roots, root–fifth, walking…) to go with them.
- Export as MIDI or render straight into the sketchpad.

### Pads and Drum Racks

![Slicing a vocal into pads and recording a pattern](docs/img/pads-2.gif)

- **🎹 pads** slices a sample onto keys like an MPC; play it and record a quantized pattern.
- **🥁** next to any song, album or artist opens its drums as a playable rack, exportable to Ableton.

![Opening a song's Drum Rack and playing its pads](docs/img/drums-2.gif)

### Search

- **By sound:** "dusty piano chords, melancholy, -drums".
- **🎧 feels like…** a YouTube link or a song; finds samples with the same feel (nothing is sampled from it).
- **🌌 Galaxy** map of every sample, and search through transcribed lyrics.

### Highlights

- **🔭 Scout finds new music to sample.** It searches YouTube and listens to each result, scoring it for raw
  singing, sustained pads, or your styles (400 Discogs styles, learned from the songs you like). **🔭 more** digs
  through a good find's channel, ✕ and adds teach the ranking, and once a day it brings you a few new finds by itself.
- **A taste model that shows its work.** ★, ✕, replays, skips and listening time train it; **💡 why this?** shows
  what pushed a sample up or down and which of your favorites it's closest to. The **🧠 Taste page** reports its
  honest held-out accuracy and lists the samples that would teach it the most. One shared model ranks samples
  and informs the Mashup dice, and `digitalcrate reco eval` measures how well each recommender predicts you
  ([plan](docs/plans/recommend.md)).
- **Kits that sound recorded together.** **🔎 complete the kit** compares how hits were recorded, not
  what drum they are, so a kick, snare and hat from different songs sit together.
- **✨ Suggested edits judged by your ears.** A dozen candidate edits (stretch, tape pitch, filters, your own AU/VST3
  plugins) are rendered and scored by the taste model; you hear the best few, rate them, and it learns how strong you
  like each move.
- **🎚 Fits my track.** Drop in a bounce of your own song: samples come back ranked by how far they'd need to be
  shifted and stretched and how well they match its sound, each saying why. Your file is analyzed and deleted.
- **Clean sources.** Songs that MusicBrainz lists as sample-based are skipped, so you're never re-sampling a sample.

### And more

- **Collections**, **sets** of favorites that fit together, and a daily **🎲 Crate**.
- **Mining controls** with a preview: new artists, most promising tracks, or more like your favorites.
- MIDI-controller mapping and nightly backups.

## Pipeline

Each track is analyzed for tempo, beats and key, split into stems when drums or bass are in the way, and cut into
phrases, chops, loops and one-shots. Each candidate is scored for how clean and exposed it is, and only the good ones
are kept. CLAP embeddings power search, the taste model and "goes well with"; everything runs locally.

The **[guide](docs/guide.md)** covers every feature, how it works, the command line and configuration.

## Limitations

- **macOS on Apple Silicon only.**
- Built for **Ableton Live 12** (Drum Racks and Live sets use its own templates).
- Separation is very good, not perfect: listen before you commit.
- Local and single-user.

## Tests

```bash
uv pip install --python .venv/bin/python -e ".[dev]"
pytest            # unit tests (seconds)
pytest --slow     # end to end on a synthetic track
pytest --ui       # the app in a real browser (once: playwright install chromium)
```

## Credits and license

Built on [Demucs](https://github.com/facebookresearch/demucs),
[audio-separator](https://github.com/nomadkaraoke/python-audio-separator),
[LAION CLAP](https://github.com/LAION-AI/CLAP), [Essentia](https://essentia.upf.edu), [librosa](https://librosa.org),
[Rubber Band](https://breakfastquay.com/rubberband/), [Signalsmith Stretch](https://signalsmith-audio.co.uk/code/stretch/),
[WORLD](https://github.com/mmorise/World), [OpenVPI vocoders](https://github.com/openvpi/vocoders),
[basic-pitch](https://github.com/spotify/basic-pitch), [aalink](https://github.com/artfwo/aalink),
[yt-dlp](https://github.com/yt-dlp/yt-dlp), [Parselmouth](https://github.com/YannickJadoul/Parselmouth),
[mlx-whisper](https://github.com/ml-explore/mlx-examples), [Beat This!](https://github.com/CPJKU/beat_this),
[Pedalboard](https://github.com/spotify/pedalboard), [MusicBrainz](https://musicbrainz.org) and
[ListenBrainz](https://listenbrainz.org). Model licenses: [`models/README.md`](models/README.md).

**License:** [AGPL-3.0](LICENSE) (Essentia is AGPL-3.0).

