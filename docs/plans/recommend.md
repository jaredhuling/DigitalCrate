# Plan: one recommendation system

Status: phases 1-3 done. The shared taste model ranks the samples surfaces, the Mashup dice adds its taste term to
the starting guesses, and parts you turned down are dealt less. Phase 4 waits for impression data. Findings below.

## Where things stand

Eight places recommend something, each with its own data, label rules and model, and only one is measured.

| Surface | Model today | Learns from | Measured |
| --- | --- | --- | --- |
| Samples: "for you", discover | Bayesian logistic regression + trees + nearest favorite + song effect, on CLAP | `events`, `favorites`, collections (about 200 stars, 90 ✕, 5,800 listens) | yes: held-out AUC about 0.81, kept in `taste_history` |
| Mashup dice (stems) | 6 weights, ridge logistic pulled toward guesses; liked/disliked sound as two centroids | `stem_events` (about 420 saved parts, 735 re-rolls), features frozen when logged | no |
| Mashup one-shots and pads | harmony fit + capped sample taste score | nothing of its own | no |
| Edit suggestions | Beta prior per move family + a small regression | `edit_ratings` (39) | arm comparison only |
| Goes well with | two-tower network trained on same-song samples | none of your votes (126 `pair_votes` exist) | one blind test |
| Sets, Fits my track, drum kits | reuse the sample taste score | - | no |
| Scout | a taste vector (mean of favorites) | `yt_scout` marks | no |
| Mining "like my favorites", styles | style profile of liked songs | favorites | no |

What this costs:

- **Nothing transfers.** A song whose samples you starred gets no lift in Mashup; 420 saved Mashup parts teach the
  sample ranking nothing; the scout knows neither.
- **What was offered is not recorded.** A re-roll is logged, but not what else could have been dealt or how likely
  it was. Without that, a model can't be tested against a different way of dealing.
- **Label rules differ and are hand-set** (a star is 1.5, a re-roll within seconds is a weak no, ...).
- **Only the sample model is measured**, so every other change is judged by ear.

## Design

A package, `digitalcrate/reco/`, that every surface goes through.

**1. One log (`reco/log.py`).** One record shape for everything you do:
`(time, surface, item, action, value, context, session)`. An item is a sample, a stem part (song, stem, bars), a
song, an edit move, or a pair. Old tables are read through adapters (nothing is migrated or deleted), so all the
history counts from day one. New: an **impressions** table. Each time something is dealt or listed, what was
shown, the alternatives, each one's score and chance of being picked, the model version, and the context (for
Mashup: tempo, key and the other parts playing).

Mashup writes these already (ahead of the rest, since the data only starts accumulating once it is logged): one
impression per deal (`mashup.dice`, `mashup.find`, `mashup.best`, `mashup.oneshot`, `mashup.pad`, and
`mashup.best_list` for the best-fits list), with each song's best part and its exact chance of being drawn (the top
40, plus the count and total chance of the rest), and a `reco_outcomes` table of what became of each dealt part
(replaced, removed, heard past 30 s ... 10 min, locked, rated, snapped, saved once per part per mix, exported, undone,
restored), each with the seconds it was actually heard. A re-save no longer logs every slot again.

**2. One item store (`reco/items.py`).** Features for any item, from what exists: CLAP sound embeddings (samples
and stems share that space), the song's style embedding, song and artist ids, category, key, tempo, quality,
grain. Sample → song → artist links are what let a like travel between surfaces.

**3. One evaluation harness (`reco/eval.py`).** The centerpiece. For each task, a fixed way to answer "is model B
better than model A?":

| Task | Question asked of held-out data | Split |
| --- | --- | --- |
| sample taste | rank favorites above heard-not-starred | by song (5 folds × 2), and forward in time |
| new songs | the same, on songs with no ratings at all | by song |
| Mashup part | rank the part you saved or kept above the ones you re-rolled, in the same slot | by song, and forward in time |
| edit move | applied or saved above dismissed | by sample |
| pair | your 1-5 pair votes | by sample |
| scout | ingested above skipped | forward in time |

Metrics: AUC, average precision, NDCG@k, calibration, each with a bootstrap interval, and a paired comparison with
the current model. Runs are kept as files under `_data/reco/runs/`, read-only on the library database.
`digitalcrate reco eval` runs it; the Taste page shows every task, not just samples. Once impressions exist:
off-policy estimates (inverse propensity) of how a new dealing rule would have done.

**4. Models (`reco/models/`), each one tested by the harness against what it replaces.**

- *Shared taste.* One Bayesian model over sound embeddings with song and artist effects, fitted on all surfaces at
  once: a starred sample, a saved Mashup part and an ingested scout result are all evidence about the same taste,
  each surface with its own offset and trust (learned, not hand-set). Uncertainty kept, for exploration.
- *Labels from behavior.* The hand-set weights for listens, skips and re-rolls replaced by weights fitted to
  predict the explicit signals (stars, saves, ✕).
- *Unheard is not disliked.* Exposure-aware treatment of unrated items (heard-not-starred differs from never seen).
- *Mashup choice in context.* A model of "kept over re-rolled, given what else was playing": harmony fit, stretch,
  activity, plus the shared taste score of the stem's sound and its song. Trained on pairs from the same slot.
- *More embeddings (measured first).* A music model (MERT or similar) beside CLAP, tried on the rated samples
  only. A library-wide pass is a heavy job and only proposed if the harness shows a clear gain.
- *Small-data surfaces (edits, pairs, scout).* Brought under the harness with their current models as baselines;
  they get the shared taste score as a feature, and are replaced only where that measures better.

**5. One way in (`reco.score(...)`, `reco.choose(...)`).** Surfaces ask for scores with uncertainty and for a
draw; exploration (how often to deal something uncertain) is one setting, logged with its probabilities.

## Rule for switching

A new model replaces the current one on a surface only if it is better on that surface's task with the interval
clear of zero, and no worse on the others. The old one stays selectable until you've used the new one.

## Phases

1. **Foundation:** the log with adapters, the item store, the harness, with today's models wrapped as baselines.
   Result: a first table of how every surface does now. No behavior changes.
2. **Models:** shared taste, behavior-fitted labels, Mashup choice, the embedding trial. In parallel, each
   reported against the baselines.
3. **Switch-over:** surfaces call `reco`; impressions logged everywhere; the winners turned on; the Taste page
   shows all tasks; old learning code removed.
4. **Later, with impression data:** off-policy testing of dealing rules, exploration tuned by measurement.

## Findings

Measured with `digitalcrate reco eval` (runs under `_data/reco/runs/`), 193 favorites and 3,390 heard-and-not-starred
samples, 675 Mashup events (78 kept or saved) after dropping re-saves. At the switch-over the full harness gave, for the sample
ranking against the earlier blend: by sample 0.819 vs 0.816 (+0.003 [-0.018, +0.026]), by song 0.798 vs 0.781
(+0.018 [-0.009, +0.041]), forward 0.756 vs 0.682 (+0.074 [+0.022, +0.122]).

**Samples: switched to the shared taste model.** Against the earlier blend (taste.py): AUC forward in time 0.758 vs
0.680 (+0.078 [+0.023, +0.126]); songs it never saw 0.801 vs 0.771 on confirmation seeds (+0.029 [+0.001, +0.053]); by
sample no worse; expected calibration error 0.03 vs 0.15. A fit takes 5-13 s depending on the load (5 s at the switch-over), scoring
25,000 samples 0.6 s. It is refitted in the background, never on a request; the previous fit serves meanwhile, and
the earlier model until the first fit lands. "Discover" is a Thompson draw per sample from the posterior (mean + sd x
a standard normal), standardized like the score. "Today's vibe" stays on the earlier model (it weighs recent events).
The served score is the posterior mean standardized over the library, so every surface that reads it (and caps it at
-2..3) sees the same scale as before.

Old and new "for you" (top 50 of the samples not starred or ✕'d): 14 in common (53 of the top 200, 466 of the top
1,000; rank correlation over the library 0.63). The new top 50 is narrower: 26 songs, 19 artists, 4 categories
(old: 36, 33, 7), at most 6 samples from one song (old: 4). Not collapsed onto a few songs, so no diversity guard was
added to the ranking; the crate still takes at most one sample a song and two an artist.

**Mashup: switched to W0 + the shared taste term.** The live learned weights were no better than random out of
sample (inflated by duplicate save rows, since fixed). The learned corrections of `mashup.chooser` flip the sign of
activity, stretch and stillness, most likely what the old dice dealt rather than a preference, so the dice keeps the
starting guesses exactly and learns only the taste term's weight: `mashup.taste` (reco/models/mashup.taste_only), the
shared model fitted on the fold's masked data (no Mashup evidence about the held-out songs). Within-slot AUC (qauc):

| | by song | forward in time |
| --- | --- | --- |
| mashup.taste vs mashup.learned | 0.658 vs 0.454, +0.205 [+0.051, +0.358], 9/9 folds | 0.620 vs 0.646, -0.027 [-0.182, +0.171] |
| mashup.taste vs mashup.W0 (paired run) | +0.180 [+0.030, +0.344], 9/9 folds | +0.060 [-0.108, +0.320], 3/4 folds |

Clear of zero by song, not worse forward: the rule is met. Per stem (by song, vs W0): vocals +0.275 [+0.024, +0.532],
other +0.145 [+0.010, +0.354], drums +0.192 and bass +0.224 with intervals across zero; forward, bass is worse (2
folds, -0.24 [-0.53, +0.11] vs W0) and drums even. Fitted on everything, the taste weight is about 1.13 for every
stem (the evidence chose no per-stem departures). The 'sound' feature (closeness to the stems kept minus those thrown
out) stays in x as logged; the dice computes it with the candidate's own song left out (measured: by song identical,
forward 0.613 vs 0.621 with own-song events in and 0.603 without the feature: a wash, so it was kept honest rather
than dropped). With the taste samples-only (no Mashup evidence in the shared model) it measured lower: 0.650 by song.

The taste term spreads the scores of the best songs over 2-4 logits. Drawn by score as well as by rank, it narrowed
the dice to a handful: in 200 rolls the five most dealt songs took 138-160 (old: 79-118). So the taste term orders
the candidates but stays out of the draw's score factor: 93-110 of 200, as wide as before. A dice roll takes about
the same time (13-19 ms for drums, 160-390 ms for pitched stems on a loaded machine; old 28 ms and 140-270 ms; the old
one refitted the learned weights on every roll).

**Parts you turned down** (reco/rejected.py): a part re-rolled away within 20 s of listening, removed or rated down,
and never kept, loses 1.0 per time (fading by half in 7 days, at most 3.0), the song's other parts of that stem 0.25
per time (at most 0.75); anything kept clears it. Before, a re-rolled part was dealt again and re-rolled again 118 of
127 times. 672 rejections in the legacy log today (230 song stems).

**Not switched:** edit suggestions, goes-well-with pairs and the scout keep their models (too little data to tell;
they stay registered in the harness). Harmony fit as computed barely separates saved mixes from random compatible
parts (0.77 vs 0.81): a question for later.

**What is logged now:** every Mashup deal (policy version 2, with `mashup: new | w0 | old` and the taste weights),
and the "for you" and discover rankings as the page was served (`samples.for_you`, `samples.discover`: the top 50
with scores and the model; one impression per ranking, deduplicated by content), recorded once the page reports it
has them. The switch lives in `_data/reco/settings.json` and on the Taste page.

## Limits

- The data is small (hundreds of explicit ratings). Simple models with good priors will beat large ones; the
  harness says so honestly through its intervals.
- Past Mashup events hold no context beyond six frozen features, so the in-context model starts thin and improves
  as impressions accumulate.
- Offline accuracy is not the same as liking what you're dealt. The last check is still your ears.
