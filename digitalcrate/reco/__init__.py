"""One recommendation system (docs/plans/recommend.md).

    log    every past interaction, read from the existing tables through adapters; impressions for later phases
    items  features for any item (sample, stem part, song, move, pair, video) and the sample -> song -> artist links
    eval   the evaluation harness: tasks, honest splits, metrics with intervals, today's models as baselines

    models    the shared taste model (models/taste.py) and the Mashup choice models (models/mashup.py)
    live      what the app serves: the switch (samples: new | old, mashup: new | w0 | old), the shared taste model
              kept fitted in the background, impressions of the sample rankings served
    rejected  the parts you turned down in Mashup, dealt less

The harness only reads. live and rejected are what the surfaces call since the switch-over (docs/plans/recommend.md).
"""
