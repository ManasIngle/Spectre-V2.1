"""
Unified inference for the overnight Nifty system.

Loads the v3 stacked direction ensemble + the v3 regression close-price model
and produces a single prediction for the next NSE trading day.

Output schema (returned by `predict()` and persisted by `predict_and_log()`):
    prediction_date     ISO date the prediction was generated for (today / IST)
    target_date         ISO date the prediction is FOR (next NSE session)
    prev_close          Last known Nifty close (₹)
    predicted_close     Model's point prediction for next close (₹)
    predicted_change_pct  (predicted_close - prev_close) / prev_close * 100
    direction           "UP" / "DOWN" / "FLAT"
    direction_confidence  0..1 calibrated probability of the predicted direction
    direction_probs     full dist {DOWN, FLAT, UP}
    magnitude_bucket    "TINY" / "SMALL" / "MEDIUM" / "LARGE"
    abs_change_pct      |predicted_change_pct| (used to derive magnitude)
    model_version       "v3"
    feature_freshness   per-feature most-recent observation date (sanity check)

The prediction is generated EVERY day (no confidence threshold). The user
decides whether to act on each one based on the confidence number.
"""
from __future__ import annotations

import io
import json
import os
import sys
from datetime import date, datetime, timedelta

import joblib
import numpy as np
import pandas as pd

if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

THIS_DIR = os.path.dirname(__file__)
DATA_DIR = os.path.join(THIS_DIR, "data")
RAW_PATH = os.path.join(DATA_DIR, "overnight_raw.parquet")
PRED_LOG_CSV = os.path.join(DATA_DIR, "overnight_predictions.csv")

DIR_LABELS = ["DOWN", "FLAT", "UP"]
MAG_BUCKETS_PCT = [0.25, 0.75, 1.5]   # |change %| boundaries
MAG_LABELS = ["TINY", "SMALL", "MEDIUM", "LARGE"]


_LOADED = {"loaded": False}


def _paths():
    return {
        "xgb":  os.path.join(THIS_DIR, "stacked_v3_xgb.pkl"),
        "lgb":  os.path.join(THIS_DIR, "stacked_v3_lgb.pkl"),
        "meta": os.path.join(THIS_DIR, "stacked_v3_meta.pkl"),
        "cal":  os.path.join(THIS_DIR, "stacked_v3_calibrators.pkl"),
        "reg":  os.path.join(THIS_DIR, "regression_v3_xgb.pkl"),
        "metadata": os.path.join(THIS_DIR, "stacked_v3_metadata.json"),
    }


def load_models():
    if _LOADED["loaded"]:
        return _LOADED
    p = _paths()
    for k, path in p.items():
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"Missing artifact '{k}': {path}. "
                f"Run train_stacked_v3.py and train_regression_v3.py first.")
    _LOADED["xgb"] = joblib.load(p["xgb"])
    _LOADED["lgb"] = joblib.load(p["lgb"])
    _LOADED["meta"] = joblib.load(p["meta"])
    _LOADED["cal"] = joblib.load(p["cal"])
    _LOADED["reg"] = joblib.load(p["reg"])
    with open(p["metadata"]) as f:
        meta = json.load(f)
    _LOADED["feature_columns"] = meta["feature_columns"]
    _LOADED["model_version"] = meta.get("version", "v3")
    _LOADED["loaded"] = True
    print(f"Loaded overnight Nifty v3 ensemble — {len(_LOADED['feature_columns'])} features")
    return _LOADED


def _bucket_magnitude(abs_change_pct: float) -> str:
    if abs_change_pct < MAG_BUCKETS_PCT[0]:
        return MAG_LABELS[0]
    if abs_change_pct < MAG_BUCKETS_PCT[1]:
        return MAG_LABELS[1]
    if abs_change_pct < MAG_BUCKETS_PCT[2]:
        return MAG_LABELS[2]
    return MAG_LABELS[3]


def _next_nse_trading_day(d: date) -> date:
    """Skip weekends. Doesn't account for NSE holidays — those will just appear
    as no actual_close to backfill, which is fine for advisory output."""
    nxt = d + timedelta(days=1)
    while nxt.weekday() >= 5:  # Sat=5, Sun=6
        nxt += timedelta(days=1)
    return nxt


def predict(asof_date: date | None = None) -> dict:
    """Generate a prediction for the next NSE trading day after `asof_date`.
    `asof_date` defaults to the most recent date in our raw dataset."""
    from feature_engineering import build_features, split_features_targets

    M = load_models()
    feat_cols = M["feature_columns"]

    raw = pd.read_parquet(RAW_PATH)
    feats = build_features(raw)
    available_cols = [c for c in feat_cols if c in feats.columns]
    if len(available_cols) != len(feat_cols):
        missing = set(feat_cols) - set(available_cols)
        raise RuntimeError(f"Feature drift: training features missing now: {missing}")

    if asof_date is None:
        asof = feats.index.max()
    else:
        asof = pd.Timestamp(asof_date)
        if asof not in feats.index:
            # Use the latest row at/before asof
            asof = feats.index[feats.index <= asof].max()

    row = feats.loc[asof]
    X = row[feat_cols].values.astype(np.float32).reshape(1, -1)

    # Direction
    p_xgb = M["xgb"].predict_proba(X)
    p_lgb = M["lgb"].predict_proba(X)
    Z = np.hstack([p_xgb, p_lgb])
    p_meta = M["meta"].predict_proba(Z)[0]
    p_cal = np.array([M["cal"][k].transform([p_meta[k]])[0] for k in range(3)])
    if p_cal.sum() <= 0:
        p_cal = p_meta
    p_cal = p_cal / p_cal.sum()
    dir_idx = int(np.argmax(p_cal))
    direction = DIR_LABELS[dir_idx]
    direction_confidence = float(p_cal[dir_idx])

    # Close price (regression — log-return %)
    pred_logret_pct = float(M["reg"].predict(X)[0])
    pred_logret = pred_logret_pct / 100.0
    prev_close = float(row["prev_close"])
    # On the latest known day, "prev_close" in the row is yesterday's close;
    # for inference we want the most recent close = nifty's close ON the asof date.
    # That is `next_close` from the perspective of the row's features.
    # But for predicting the NEXT day, we actually want to use today's close as
    # the new "prev". The features were built so that row T predicts close on T,
    # using features known at T-1 evening / T overnight. So at runtime when we
    # feed the latest row, we are essentially predicting the *current* asof
    # day's close — which has already happened. To predict tomorrow, we'd need
    # a brand-new feature row with TONIGHT's overnight cues — and that's what
    # the cron does (refetch data, then call predict()).
    # So `prev_close` here = the close that the model used as anchor. The
    # prediction target is the NEXT NSE day's close.
    last_known_close = float(row["next_close"])
    predicted_close = last_known_close * float(np.exp(pred_logret))
    predicted_change_pct = (predicted_close - last_known_close) / last_known_close * 100
    abs_change_pct = abs(predicted_change_pct)
    magnitude = _bucket_magnitude(abs_change_pct)

    target = _next_nse_trading_day(asof.date())

    return {
        "prediction_date": datetime.utcnow().date().isoformat(),
        "asof_session": asof.date().isoformat(),
        "target_date": target.isoformat(),
        "prev_close": round(last_known_close, 2),
        "predicted_close": round(predicted_close, 2),
        "predicted_change_pct": round(predicted_change_pct, 3),
        "direction": direction,
        "direction_confidence": round(direction_confidence, 3),
        "direction_probs": {
            "DOWN": round(float(p_cal[0]), 3),
            "FLAT": round(float(p_cal[1]), 3),
            "UP":   round(float(p_cal[2]), 3),
        },
        "magnitude_bucket": magnitude,
        "abs_change_pct": round(abs_change_pct, 3),
        "model_version": M["model_version"],
        "feature_freshness": str(asof.date()),
    }


def predict_and_log(asof_date: date | None = None) -> dict:
    """Run predict() and append to overnight_predictions.csv. Returns the prediction."""
    pred = predict(asof_date=asof_date)
    row = {
        "prediction_date":      pred["prediction_date"],
        "asof_session":         pred["asof_session"],
        "target_date":          pred["target_date"],
        "prev_close":           pred["prev_close"],
        "predicted_close":      pred["predicted_close"],
        "predicted_change_pct": pred["predicted_change_pct"],
        "direction":            pred["direction"],
        "direction_confidence": pred["direction_confidence"],
        "p_down":               pred["direction_probs"]["DOWN"],
        "p_flat":               pred["direction_probs"]["FLAT"],
        "p_up":                 pred["direction_probs"]["UP"],
        "magnitude_bucket":     pred["magnitude_bucket"],
        "abs_change_pct":       pred["abs_change_pct"],
        "model_version":        pred["model_version"],
        "actual_close":         None,
        "abs_error_pct":        None,
        "direction_correct":    None,
    }
    df_new = pd.DataFrame([row])
    if os.path.exists(PRED_LOG_CSV):
        existing = pd.read_csv(PRED_LOG_CSV)
        # Replace any existing row for the same target_date (idempotent re-runs)
        existing = existing[existing["target_date"] != row["target_date"]]
        out = pd.concat([existing, df_new], ignore_index=True)
    else:
        out = df_new
    out = out.sort_values("target_date").reset_index(drop=True)
    out.to_csv(PRED_LOG_CSV, index=False)
    print(f"Logged → {PRED_LOG_CSV}")
    return pred


def backfill_actuals():
    """Look up actual closes for any pending target_date rows in the CSV
    and fill actual_close / abs_error_pct / direction_correct."""
    if not os.path.exists(PRED_LOG_CSV):
        print("No prediction log exists yet — nothing to backfill.")
        return 0
    df = pd.read_csv(PRED_LOG_CSV)
    pending = df[df["actual_close"].isna()]
    if pending.empty:
        print("No pending rows to backfill.")
        return 0

    raw = pd.read_parquet(RAW_PATH)
    raw.index = pd.to_datetime(raw.index).tz_localize(None).normalize()
    actuals = raw["nifty_close"]

    n_filled = 0
    for i, row in pending.iterrows():
        td = pd.Timestamp(row["target_date"])
        if td not in actuals.index:
            continue
        actual = float(actuals.loc[td])
        df.at[i, "actual_close"] = round(actual, 2)
        df.at[i, "abs_error_pct"] = round(abs(actual - row["predicted_close"]) / actual * 100, 3)
        # Direction correctness check
        change_pct = (actual - row["prev_close"]) / row["prev_close"] * 100
        if change_pct > 0.30:
            actual_dir = "UP"
        elif change_pct < -0.30:
            actual_dir = "DOWN"
        else:
            actual_dir = "FLAT"
        df.at[i, "direction_correct"] = bool(actual_dir == row["direction"])
        n_filled += 1
    df.to_csv(PRED_LOG_CSV, index=False)
    print(f"Backfilled {n_filled} rows.")
    return n_filled


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", action="store_true", help="Only backfill actuals, skip predict")
    ap.add_argument("--asof", default=None, help="Predict as if asof YYYY-MM-DD (default: latest data)")
    args = ap.parse_args()

    if args.backfill:
        backfill_actuals()
    else:
        asof = pd.Timestamp(args.asof).date() if args.asof else None
        result = predict_and_log(asof_date=asof)
        print(json.dumps(result, indent=2))
