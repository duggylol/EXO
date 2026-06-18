"""
ML research pipeline for EXO (offline).

Implements the validation-first, meta-labeling approach (López de Prado,
*Advances in Financial Machine Learning*): the existing rule strategies pick the
SIDE; a gradient-boosted model trained here decides whether to TAKE the trade
and how big — and it's validated with purged/embargoed cross-validation and the
Deflated Sharpe Ratio so a fluke can't masquerade as an edge.

This package is import-light at the top level so the core app never depends on
pandas/sklearn just by existing. Import the submodules only when training.
"""
