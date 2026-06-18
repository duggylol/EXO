"""
ML Meta-Filter — the live meta-labeling strategy.

Runs a base rule strategy to decide the SIDE, then uses a model trained by
`research/train_meta.py` to decide whether each entry is worth TAKING and how
BIG. The model never picks direction, so the worst it can do is filter poorly —
and the engine's hard risk guard still caps everything.

Config (in config.yaml strategies:):
  - {strategy: ml_meta, symbol: MES, params: {base: ma_cross, threshold: 0.55, size_by_prob: true}}

If the model file or ML deps (pandas/scikit-learn/joblib) are missing, it safely
falls back to PASSTHROUGH — emitting the base strategy's signals unchanged — so
the app never breaks. Train a model first:
  python -m research.train_meta --strategy ma_cross --symbol MES --csv data/MES_1min.csv
"""
from __future__ import annotations

import sys
from collections import deque
from pathlib import Path

from core.enums import IntentType, OrderSide
from core.models import Position
from core.strategy import Strategy, StrategyContext, create_strategy, register

MODELS_DIR = Path(__file__).resolve().parent.parent / "models"


@register
class MLMetaFilter(Strategy):
    key = "ml_meta"
    display_name = "ML Meta-Filter"
    description = "Runs a base strategy; a trained model takes/sizes only its high-quality signals."
    params = {"base": "ma_cross", "base_params": {}, "model": "",
              "threshold": None, "size_by_prob": True, "max_contracts": 3}

    def setup(self) -> None:
        self.passthrough = False
        self._win: deque = deque(maxlen=400)
        base_key = self.params.get("base", "ma_cross")
        if base_key == self.key:
            raise ValueError("ml_meta cannot wrap itself")
        self.base = create_strategy(base_key, f"{self.instance_id}:base",
                                    self.symbol, self.params.get("base_params") or {})
        self.base_pos = Position(symbol=self.symbol)
        self.threshold = 0.5
        self._load_model()

    def _load_model(self) -> None:
        try:
            import joblib  # noqa
            import numpy  # noqa
            import pandas  # noqa
            from research.features import compute_features
            self._compute = compute_features
            self._pd = pandas
        except Exception as e:
            self._warn(f"ML deps unavailable ({e}); running in PASSTHROUGH mode")
            self.passthrough = True
            return
        path = self.params.get("model") or str(MODELS_DIR / f"meta_{self.base.key}_{self.symbol}.joblib")
        if not Path(path).exists():
            self._warn(f"no model at {path}; PASSTHROUGH (train one with research.train_meta)")
            self.passthrough = True
            return
        bundle = joblib.load(path)
        if bundle.get("needs_orderflow"):
            self._warn("model needs a live order-flow feed (not wired yet — Phase 4); PASSTHROUGH")
            self.passthrough = True
            return
        self.model = bundle["model"]
        self.feat_cols = bundle["features"]
        self.warmup = bundle.get("warmup", 60)
        thr = self.params.get("threshold")
        self.threshold = float(thr) if thr is not None else float(bundle.get("threshold", 0.5))
        self._warn(f"loaded meta-model {Path(path).name} (threshold={self.threshold:.2f})")

    def _warn(self, msg: str) -> None:
        print(f"[ml_meta:{self.instance_id}] {msg}", file=sys.stderr)

    def on_session_start(self) -> None:
        self.base.on_session_start()
        self.base_pos = Position(symbol=self.symbol)

    def on_bar(self, bar, ctx: StrategyContext) -> None:
        self._win.append(bar)
        base_ctx = StrategyContext(self.base_pos)
        self.base._feed_bar(bar, base_ctx)
        for intent in base_ctx.intents:
            self._mirror_base(intent, bar)
            self._route(intent, bar, ctx)

    def _mirror_base(self, intent, bar) -> None:
        """Keep the base strategy's own position consistent with its signals."""
        if intent.type is IntentType.EXIT:
            if not self.base_pos.is_flat:
                self.base_pos.apply_fill(
                    OrderSide.SELL if self.base_pos.is_long else OrderSide.BUY,
                    abs(self.base_pos.qty), bar.close)
            return
        want_long = intent.type is IntentType.ENTER_LONG
        if (want_long and self.base_pos.is_long) or (not want_long and self.base_pos.is_short):
            return
        self.base_pos.apply_fill(OrderSide.BUY if want_long else OrderSide.SELL,
                                 abs(self.base_pos.qty) + 1, bar.close)

    def _route(self, intent, bar, ctx: StrategyContext) -> None:
        if intent.type is IntentType.EXIT:
            ctx.close(intent.reason or "base exit")
            return
        want_long = intent.type is IntentType.ENTER_LONG
        if self.passthrough:
            (ctx.buy if want_long else ctx.sell)(intent.reason)
            return
        p = self._predict()
        if p < self.threshold:
            return  # filtered out — the model thinks this signal is low quality
        qty = self._size(p)
        reason = f"meta p={p:.2f} ({intent.reason})" if intent.reason else f"meta p={p:.2f}"
        (ctx.buy if want_long else ctx.sell)(reason, qty=qty)

    def _size(self, p: float) -> int:
        if not self.params.get("size_by_prob", True):
            return 1
        mx = int(self.params.get("max_contracts", 3))
        span = max(1e-9, 1.0 - self.threshold)
        return max(1, min(mx, 1 + int((p - self.threshold) / span * (mx - 1))))

    def _predict(self) -> float:
        if len(self._win) < self.warmup + 1:
            return -1.0
        b = list(self._win)
        idx = self._pd.to_datetime([x.ts for x in b], unit="s")
        df = self._pd.DataFrame(
            {"open": [x.open for x in b], "high": [x.high for x in b],
             "low": [x.low for x in b], "close": [x.close for x in b],
             "volume": [x.volume for x in b]}, index=idx)
        feats = self._compute(df)
        row = feats.iloc[-1].reindex(self.feat_cols)
        if row.isna().any():
            return -1.0
        return float(self.model.predict_proba(row.values.reshape(1, -1))[:, 1][0])
