"""
Purged + embargoed K-fold cross-validation (López de Prado, AFML Ch. 7).

Ordinary k-fold LIES on financial data: because a label spans a window of time
(entry -> barrier touch), a training sample whose window overlaps the test set
leaks future information, making junk features look predictive. PurgedKFold
fixes this by (1) PURGING training samples whose label window overlaps the test
window, and (2) EMBARGOING a small slice of samples right after the test set.

Folds are contiguous in time (never shuffled) so the splits respect causality.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.model_selection import BaseCrossValidator


class PurgedKFold(BaseCrossValidator):
    def __init__(self, n_splits: int = 5, t1: pd.Series | None = None, embargo_pct: float = 0.01):
        self.n_splits = n_splits
        self.t1 = t1                  # label resolution time per sample (index == X.index)
        self.embargo_pct = embargo_pct

    def get_n_splits(self, X=None, y=None, groups=None) -> int:
        return self.n_splits

    def split(self, X, y=None, groups=None):
        if self.t1 is None:
            raise ValueError("PurgedKFold requires t1 (label end times)")
        times = X.index
        t1 = self.t1.reindex(times)
        n = len(times)
        idx = np.arange(n)
        embargo = int(n * self.embargo_pct)

        for fold in np.array_split(idx, self.n_splits):
            start, end = fold[0], fold[-1] + 1
            test_idx = idx[start:end]
            t0_test = times[start]
            t1_test = t1.iloc[test_idx].max()

            train = []
            emb_end = min(n, end + embargo)
            embargo_times = set(times[end:emb_end])
            for i in idx:
                if start <= i < end:
                    continue                      # in test
                ti0, ti1 = times[i], t1.iloc[i]
                # purge: skip if this sample's label window overlaps the test window
                if (ti1 >= t0_test) and (ti0 <= t1_test):
                    continue
                # embargo: skip samples immediately after the test block
                if times[i] in embargo_times:
                    continue
                train.append(i)
            yield np.array(train, dtype=int), test_idx
