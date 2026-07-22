import pandas as pd, numpy as np, os, json, gc, warnings, time, joblib
from datetime import date, datetime, timedelta
import zoneinfo
warnings.filterwarnings("ignore")
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import f1_score
from sklearn.preprocessing import LabelEncoder
import xgboost as xgb

IST = zoneinfo.ZoneInfo("Asia/Kolkata")
ART = "artifacts"
REP = "reports"
SEED = 42
PURGE = 30
EMBARGO = 1
os.makedirs(ART, exist_ok=True)
os.makedirs(REP, exist_ok=True)

t0 = time.time()
print("Loading...")
df = pd.read_parquet("data/training_v2.parquet")
print(f"{len(df):,} rows")

DROP = {"feat_hour","feat_minutes_since_open","feat_day_of_week","feat_session_position",
        "feat_equity_weighted_ret","feat_equity_advance_pct","feat_equity_momentum"}
V2F = [c for c in df.columns if c.startswith("feat_") and c not in DROP]
print(f"Features: {len(V2F)}")

X = df[V2F].values.astype(np.float32)
y = df["label"].values.astype(int)
ad = pd.Series(df.index.date).values
le = LabelEncoder()
ye = le.fit_transform(y)

XP = {"n_estimators":300,"max_depth":6,"learning_rate":0.05,"subsample":0.8,
      "colsample_bytree":0.8,"min_child_weight":5,"objective":"multi:softprob",
      "eval_metric":"mlogloss","random_state":SEED,"n_jobs":4,"tree_method":"hist","verbosity":0}

md, Md = min(ad), max(ad)
bnd = []
te = date(md.year+2, 1, 1)
while True:
    ts = te + timedelta(days=EMBARGO)
    mo = ts.month+6; yr = ts.year+(mo-1)//12; mo = ((mo-1)%12)+1
    te2 = date(yr, mo, 1) - timedelta(days=1)
    if te2 > Md: te2 = Md
    if ts >= Md: break
    bnd.append((te, ts, te2))
    te = te2
    if te2 >= Md: break
print(f"Folds: {len(bnd)}")

oof_p = np.zeros((len(y), 3), dtype=np.float32)
oof_d = np.full(len(y), -1, dtype=int)
fmasks = []
model = None
fms = []

for fi, (ted, tsd, te2d) in enumerate(bnd):
    tr = ad <= ted
    ti = np.where(tr)[0]
    if len(ti) > PURGE: ti = ti[:-PURGE]
    tem = (ad >= tsd) & (ad <= te2d)
    tei = np.where(tem)[0]
    if len(tei) < 100:
        continue
    fmasks.append(tei)
    
    m = xgb.XGBClassifier(**XP)
    m.fit(X[ti], ye[ti], eval_set=[(X[tei], ye[tei])], verbose=False)
    p = m.predict_proba(X[tei])
    d = m.predict(X[tei])
    oof_p[tei] = p
    oof_d[tei] = d
    old_model = model; model = m; del old_model
    
    f1 = f1_score(ye[tei], d, average="macro")
    br = np.mean((p - np.eye(3)[ye[tei]]) ** 2)
    
    prec = []
    rec = []
    for c in range(3):
        tp = ((d == c) & (ye[tei] == c)).sum()
        fp = ((d == c) & (ye[tei] != c)).sum()
        fn = ((d != c) & (ye[tei] == c)).sum()
        prec.append(round(tp/(tp+fp), 3) if (tp+fp) > 0 else 0)
        rec.append(round(tp/(tp+fn), 3) if (tp+fn) > 0 else 0)
    
    hf = {}
    if "feat_hour" in df.columns:
        hrs = df.iloc[tei]["feat_hour"].values
        for h in sorted(set(hrs)):
            hm = hrs == h
            if hm.sum() >= 20:
                hf[int(h)] = round(f1_score(ye[tei][hm], d[hm], average="macro", zero_division=0), 3)
    
    fms.append({"fi": fi+1, "n": len(tei), "f1": round(f1, 4), "brier": round(br, 4),
                 "pd": prec[0], "ps": prec[1], "pu": prec[2],
                 "rd": rec[0], "rs": rec[1], "ru": rec[2], "hf": hf})
    print(f"  f{fi+1}: {tsd}->{te2d}, n={len(tei)}, f1={f1:.3f}")
    del m; gc.collect()

print("Causal calibration...")
cp = np.zeros_like(oof_p)
for k in range(len(fmasks)):
    tei_k = fmasks[k]
    pm = np.zeros(len(y), dtype=bool)
    for j in range(k):
        pm[fmasks[j]] = True
    if pm.sum() < 100:
        cp[tei_k] = oof_p[tei_k]
        continue
    for c in range(3):
        iso = IsotonicRegression(out_of_bounds="clip")
        iso.fit(oof_p[pm, c], (ye[pm] == c).astype(float))
        cp[tei_k, c] = iso.transform(oof_p[tei_k, c])
cp = cp / cp.sum(axis=1, keepdims=True)
cd = np.argmax(cp, axis=1)

print("ATR robustness...")
rob = {}
for pert in [0.85, 1.0, 1.15]:
    Xp = X.copy()
    for vf in ["feat_volatility", "feat_atr_move"]:
        if vf in V2F:
            Xp[:, V2F.index(vf)] *= pert
    dp = model.predict(Xp)
    f1p = f1_score(ye, dp, average="macro")
    ag = (dp == model.predict(X)).mean()
    rob[pert] = {"f1": round(f1p, 4), "agree": round(ag*100, 1)}
    print(f"  x{pert:.2f}: F1={f1p:.3f}, agree={ag*100:.1f}%")

fi = model.feature_importances_
top = np.argsort(fi)[-10:][::-1]
for i in top:
    print(f"  {V2F[i]}: {fi[i]:.4f}")

joblib.dump(model, os.path.join(ART, "nifty_signal_v2.pkl"))
meta = {"feature_columns": V2F, "horizon_bars": 30, "threshold_pct": 0.08,
        "calibration": "causal_per_fold", "dropped": sorted(DROP),
        "folds": len(fms), "seed": SEED, "robustness_atr": rob}
with open(os.path.join(ART, "signal_v2_metadata.json"), "w") as f:
    json.dump(meta, f, indent=2, default=str)

mk = oof_d >= 0
yt = ye[mk]
yp = oof_d[mk]
yc = cd[mk]
cp_m = cp[mk]
f1r = f1_score(yt, yp, average="macro")
f1c = f1_score(yt, yc, average="macro")
br = np.mean((oof_p[mk] - np.eye(3)[yt]) ** 2)

ds = datetime.now(IST).strftime("%Y-%m-%d")
rpt = ["# Step 3b — Signal Model v2 (Clock Features Removed)",
       f"**Date:** {ds}", "",
       "## Configuration",
       f"- Rows: {len(df):,} | Features: {len(V2F)} | Folds: {len(fms)}",
       f"- Dropped: {sorted(DROP)}",
       f"- Labels: DOWN={int((y==0).sum()):,} SIDE={int((y==1).sum()):,} UP={int((y==2).sum()):,}",
       f"- Calibration: causal (fold k on folds < k)",
       f"- Time: {time.time()-t0:.0f}s", "",
       "## Overall OOF",
       "| | Before Cal | After Cal |", "|---|---|---|",
       f"| F1 macro | {f1r:.4f} | {f1c:.4f} |",
       f"| Brier | {br:.4f} | - |", "",
       "## Top 10 Features", "| R | Feature | Imp |", "|---|---|---|"]
for r, i in enumerate(top):
    rpt.append(f"| {r+1} | {V2F[i]} | {fi[i]:.4f} |")

rpt += ["", "## Per-Fold",
        "| F | N | F1 | Brier | Prec D/S/U | Rec D/S/U | Hour F1 |",
        "|---|---|-----|-------|-------------|------------|---------|"]
for fm in fms:
    hfs = " ".join(f"{h}:{v:.2f}" for h, v in sorted(fm["hf"].items())[:5])
    rpt.append(f"| {fm['fi']} | {fm['n']} | {fm['f1']:.3f} | {fm['brier']:.3f} | "
               f"{fm['pd']}/{fm['ps']}/{fm['pu']} | {fm['rd']}/{fm['rs']}/{fm['ru']} | {hfs} |")

rpt += ["", "## Causal Calibration",
        "| Bucket | N | Acc |", "|--------|---|-----|"]
cf = np.max(cp_m, axis=1) * 100
ac = (yc == yt).astype(float)
for lo in range(30, 100, 5):
    mb = (cf >= lo) & (cf < lo+5)
    if mb.sum() > 0:
        rpt.append(f"| {lo}-{lo+5} | {mb.sum():,} | {ac[mb].mean()*100:.1f}% |")

rpt += ["", "## ATR Vendor-Robustness",
        "| Perturb | F1 | Agr% |", "|---------|-----|------|"]
for p in [0.85, 1.0, 1.15]:
    r = rob[p]
    rpt.append(f"| x{p:.2f} | {r['f1']:.4f} | {r['agree']}% |")

rpath = os.path.join(REP, "step3b_signal_v2.md")
with open(rpath, "w") as f:
    f.write("\n".join(rpt))
print(f"Done in {time.time()-t0:.0f}s -> {rpath}")
