# Trained models

`research/train_meta.py` saves meta-labeling model bundles here as
`meta_<strategy>_<symbol>.joblib`. Each bundle is self-describing (model +
feature list + base strategy + barrier config + validation stats), and the live
`ml_meta` strategy loads the matching file automatically.

Model files are git-ignored (they're build artifacts derived from your data).
