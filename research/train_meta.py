"""
Train a meta-labeling model for one EXO strategy, validated honestly.

Pipeline:
  1. Load bars (real CSV, or synthetic for a smoke test only).
  2. Replay the rule strategy -> entry signals (the "side").
  3. Triple-barrier label each entry (volatility-scaled).
  4. Build features at each entry (no lookahead).
  5. Purged + embargoed K-fold CV of a gradient-boosted classifier; out-of-fold
     predictions drive a realistic "take only approved trades" simulation.
  6. Deflated Sharpe Ratio on the filtered trades -> is the edge real?
  7. Fit final model on all data and save a self-describing bundle to models/.

Usage:
  python -m research.train_meta --strategy ma_cross --symbol MES --csv data/MES_1min.csv
  python -m research.train_meta --strategy rsi_reversion --symbol MNQ --synthetic 20000   # smoke test
  python -m research.train_meta --list
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import f1_score, roc_auc_score

from strategies import load_all
from core.strategy import registry
from . import metrics
from .cv import PurgedKFold
from .data import load_ohlcv, synthetic_ohlcv
from .features import WARMUP, compute_features
from .labeling import rolling_volatility, triple_barrier_labels
from .orderflow import compute_orderflow_features
from .signals import replay_entries

MODELS_DIR = Path(__file__).resolve().parent.parent / "models"


def _make_model() -> HistGradientBoostingClassifier:
    # Shallow + regularized on purpose: limits overfitting on noisy market data.
    return HistGradientBoostingClassifier(
        max_depth=3, learning_rate=0.05, max_iter=250,
        l2_regularization=1.0, min_samples_leaf=50, random_state=0)


def train(strategy_key: str, symbol: str, df: pd.DataFrame, *, pt: float, sl: float,
          max_holding: int, threshold, margin: float, folds: int, n_trials: int,
          orderflow_path: str = "", start=None, end=None) -> dict:
    feats = compute_features(df)

    # Optionally join order-flow features (Phase: order-flow research).
    use_of = bool(orderflow_path)
    if use_of:
        of_raw = pd.read_csv(orderflow_path)
        of_raw["timestamp"] = pd.to_datetime(of_raw["timestamp"])
        of_raw = of_raw.set_index("timestamp").sort_index()
        of_feats = compute_orderflow_features(of_raw)
        feats = feats.join(of_feats, how="left")
        print(f"order-flow features joined: {list(of_feats.columns)}")

    entries = replay_entries(strategy_key, {}, df, symbol)
    if start is not None:
        entries = entries[entries.index >= pd.Timestamp(start)]
    if end is not None:
        entries = entries[entries.index <= pd.Timestamp(end)]
    if len(entries) < 100:
        raise SystemExit(f"only {len(entries)} entries in window — widen the date range")

    vol = rolling_volatility(df["close"])
    labels = triple_barrier_labels(df["close"], entries, vol, pt=pt, sl=sl, max_holding=max_holding)

    # Align features <-> labels at entry times; drop warmup/NaN rows.
    X = feats.reindex(labels.index)
    keep = X.notna().all(axis=1) & labels["bin"].notna()
    X, L = X[keep], labels[keep]
    feat_cols = list(X.columns)
    y = L["bin"].astype(int).values
    rets = L["ret"].astype(float).values

    base_winrate = float(y.mean())
    print(f"\nEntries: {len(entries)}  usable: {len(X)}  "
          f"base win-rate (take all): {base_winrate:6.1%}")
    if y.sum() in (0, len(y)):
        raise SystemExit("labels are single-class — adjust barriers/holding period")

    # Threshold: a trade is worth taking if the model rates its win-probability
    # ABOVE the base rate (+margin). Derived per-fold from TRAINING labels only
    # (leakage-safe). A fixed --threshold overrides this.
    fixed_thr = threshold

    # --- Purged CV: out-of-fold predictions only (no leakage) ---
    cv = PurgedKFold(n_splits=folds, t1=L["t1"], embargo_pct=0.01)
    oof_p = np.full(len(X), np.nan)
    thr_row = np.full(len(X), np.nan)
    fold_sharpes = []
    aucs = []
    for tr, te in cv.split(X):
        if len(tr) < 50 or len(te) == 0 or y[tr].sum() in (0, len(tr)):
            continue
        m = _make_model().fit(X.iloc[tr].values, y[tr])
        p = m.predict_proba(X.iloc[te].values)[:, 1]
        thr = fixed_thr if fixed_thr is not None else float(y[tr].mean()) + margin
        oof_p[te] = p
        thr_row[te] = thr
        try:
            aucs.append(roc_auc_score(y[te], p))
        except ValueError:
            pass
        take = p >= thr
        if take.sum() >= 2:
            fold_sharpes.append(metrics.sharpe(rets[te][take]))

    mask = np.isfinite(oof_p)
    resolved_thr = fixed_thr if fixed_thr is not None else round(base_winrate + margin, 4)
    taken = mask & (oof_p >= thr_row)
    n_taken = int(taken.sum())
    filt_ret = rets[taken]
    filt_winrate = float((filt_ret > 0).mean()) if n_taken else float("nan")

    sr_all = metrics.sharpe(rets[mask])
    sr_filt = metrics.sharpe(filt_ret) if n_taken >= 2 else float("nan")
    # Variance of Sharpe across folds approximates the trial dispersion for DSR.
    sr_var = float(np.var(fold_sharpes, ddof=1)) if len(fold_sharpes) > 1 else max(sr_all ** 2, 0.01)
    dsr, sr0 = metrics.deflated_sharpe(filt_ret, n_trials=n_trials, sr_variance=sr_var) \
        if n_taken >= 3 else (float("nan"), float("nan"))
    auc = float(np.mean(aucs)) if aucs else float("nan")
    f1 = f1_score(y[mask], (oof_p[mask] >= thr_row[mask]).astype(int), zero_division=0)

    print("── Honest out-of-fold validation ─────────────────────────")
    print(f"  take threshold (prob)  : {resolved_thr:.3f}"
          f"{'' if fixed_thr is not None else f'  (base {base_winrate:.3f} + margin {margin:.3f})'}")
    print(f"  trades taken by filter : {n_taken} / {int(mask.sum())} "
          f"({n_taken/max(mask.sum(),1):.0%} of signals)")
    print(f"  win-rate  all -> filter: {base_winrate:6.1%} -> {filt_winrate:6.1%}")
    print(f"  per-trade Sharpe all->filt: {sr_all:+.3f} -> {sr_filt:+.3f}")
    print(f"  AUC: {auc:.3f}   F1: {f1:.3f}")
    print(f"  Deflated Sharpe (N={n_trials} trials): {dsr:.3f}   (SR0 bar={sr0:+.3f})")
    verdict = ("LIKELY REAL edge (DSR>0.95)" if dsr > 0.95
               else "NOT significant — treat as noise" if np.isfinite(dsr)
               else "too few trades to judge")
    print(f"  VERDICT: {verdict}")
    print("  Reminder: DSR assumes you reported ALL variants tried. If you've")
    print("  run this many times, bump --trials so the bar stays honest.\n")

    # --- Fit final model on everything, save bundle ---
    final = _make_model().fit(X.values, y)
    MODELS_DIR.mkdir(exist_ok=True)
    bundle = {
        "model": final, "features": feat_cols, "base_key": strategy_key,
        "base_params": {}, "symbol": symbol, "threshold": resolved_thr,
        "pt": pt, "sl": sl, "max_holding": max_holding,
        "warmup": WARMUP, "trained_rows": len(X), "needs_orderflow": use_of,
        "validation": {"dsr": dsr, "sr_filtered": sr_filt, "sr_all": sr_all,
                       "auc": auc, "f1": f1, "filter_winrate": filt_winrate},
    }
    import joblib
    out = MODELS_DIR / f"meta_{strategy_key}_{symbol}.joblib"
    joblib.dump(bundle, out)
    print(f"saved model -> {out}")
    return bundle


def main() -> None:
    ap = argparse.ArgumentParser(description="Train an EXO meta-labeling model")
    ap.add_argument("--strategy"); ap.add_argument("--symbol", default="MES")
    ap.add_argument("--csv", help="historical OHLCV CSV (data/...). Omit to use --synthetic")
    ap.add_argument("--synthetic", type=int, default=0, help="N synthetic bars (smoke test only)")
    ap.add_argument("--pt", type=float, default=2.0, help="profit-take barrier (x volatility)")
    ap.add_argument("--sl", type=float, default=1.0, help="stop-loss barrier (x volatility)")
    ap.add_argument("--max-hold", type=int, default=30, help="time barrier (bars)")
    ap.add_argument("--threshold", type=float, default=None,
                    help="fixed min model prob to take a trade (default: base win-rate + margin)")
    ap.add_argument("--margin", type=float, default=0.05,
                    help="how far above the base win-rate the model must rate a signal")
    ap.add_argument("--folds", type=int, default=6)
    ap.add_argument("--trials", type=int, default=20,
                    help="total strategy/param variants you've tried (for Deflated Sharpe)")
    ap.add_argument("--orderflow", default="", help="order-flow CSV (data/<sym>_orderflow_1min.csv)")
    ap.add_argument("--start", default=None, help="restrict entries to >= this date (YYYY-MM-DD)")
    ap.add_argument("--end", default=None, help="restrict entries to <= this date (YYYY-MM-DD)")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    load_all()
    if args.list:
        for k, c in sorted(registry().items()):
            print(f"  {k:<18} {c.display_name}")
        return
    if not args.strategy:
        ap.error("provide --strategy KEY (see --list)")

    if args.csv:
        df = load_ohlcv(args.csv)
        print(f"loaded {len(df):,} real bars from {args.csv}")
    else:
        n = args.synthetic or 20000
        df = synthetic_ohlcv(args.symbol, n)
        print(f"⚠️  SYNTHETIC {n:,} bars — pipeline smoke test only; results are MEANINGLESS.")

    train(args.strategy, args.symbol, df, pt=args.pt, sl=args.sl,
          max_holding=args.max_hold, threshold=args.threshold, margin=args.margin,
          folds=args.folds, n_trials=args.trials,
          orderflow_path=args.orderflow, start=args.start, end=args.end)


if __name__ == "__main__":
    main()
