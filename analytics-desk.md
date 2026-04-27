# Analytics Desk — Implementation Plan

Status: **Backend service partially built (uncommitted in `services/analytics.go`). All handlers + frontend pending.** Paused to ship Auth first.

Goal: a single top-level **Analytics** tab that consolidates everything analytical about logged trades and signals. Simulator tab gets slimmed to "live state only" (Positions). Journal + Scorecard move *into* Analytics.

---

## Architecture

```
Top-level tabs:  ... Simulator | Analytics | Download | Overnight
                              ↓
                  Simulator: Positions only (open + today's closed)
                              ↓
                  Analytics: 6 sub-tabs
                    ├── Journal           ← moved from Simulator
                    ├── Equity            ← new
                    ├── Suppressed        ← new
                    ├── Scorecard         ← moved from Simulator
                    ├── A/B Compare       ← new
                    └── Daily Reports     ← new
```

Why this split: Simulator answers *"what's happening right now"*. Analytics answers *"look back and learn"*. Journal-as-sub-tab-of-Simulator (current shipped state) is the wrong taxonomy.

---

## Done so far

- `services/analytics.go` (uncommitted, builds clean) — backend logic for:
  - `LoadEquityCurve(days)` → daily P&L aggregates with running cumulative
  - `LoadSuppressedSignals(date)` → minutes where raw was BUY but stable was NO TRADE, with forward-looking move at +5/+15/+30min and a verdict (`FILTER_RIGHT`/`FILTER_WRONG`/`FILTER_NEUTRAL`)
  - `LoadSuppressedDetail(date, time)` → single suppressed signal + spot trajectory for charting
  - `CompareScorecard(startA, endA, startB, endB)` → per-model accuracy aggregated across two date ranges with delta

---

## Remaining work

### Backend — ~2 hours

**1. `services/grader.go` — add `writeDailyReport(date)`**
At the end of `GradeDay()`, write a markdown summary to `data/reports/YYYY-MM-DD.md`:
- Total signals, signals taken, suppressed count
- Top 3 winning trades, top 3 losing trades (from `executed_trades.csv`)
- Per-model accuracy summary (compact view of scorecard)
- Conviction-filter retention rate (`stable signals / raw signals`)
- Notable suppressions: the 3 suppressed signals with biggest `Move30m` (filter was most wrong)

**2. `services/journal.go` — augment `LoadTradeDetail` with what-if scenarios**
Walk the premium trajectory once, compute and add to the response:
```go
type WhatIfScenarios struct {
    Hold50PnL    float64  // exited at hold_min/2
    Trail30PnL   float64  // 30% trailing stop from peak
    OptimalPnL   float64  // best minute (already computed as bestPnL)
}
```
Pure derivation from existing `prem_series`.

**3. `api/handlers/analytics.go` — new file**
```
GET  /api/analytics/equity?days=N
GET  /api/analytics/suppressed?date=YYYY-MM-DD
GET  /api/analytics/suppressed/detail?date=&time=
GET  /api/analytics/scorecard/compare?start_a=&end_a=&start_b=&end_b=
GET  /api/analytics/reports/list                    → ["2026-04-28.md", ...]
GET  /api/analytics/reports?date=YYYY-MM-DD         → markdown body
```

**4. `api/router.go`** — register the 6 routes above.

### Frontend — ~4 hours

**5. `frontend/src/components/AnalyticsDeskView.jsx` (new container)**
Top-level component. Renders sub-tab nav and switches between 6 views. Pattern matches existing `SimulatorView.jsx`.

**6. Move existing components**
- Move `JournalView.jsx` rendering OUT of `SimulatorView.jsx` and INTO `AnalyticsDeskView.jsx`
- Extract scorecard rendering from `SimulatorView.jsx` into a new `ScorecardView.jsx`, mount in Analytics
- Strip `SimulatorView.jsx` down to Positions-only

**7. New components**
- `EquityCurveView.jsx` — uses `TradeChart` with daily P&L bars + cumulative line. Toggle: `%` vs `₹`. Date range selector.
- `SuppressedSignalsView.jsx` — table mirroring Journal: time, raw signal, conf, Move30m%, verdict badge (red = filter wrong, green = filter right, gray = neutral). Click row → expand with `TradeChart` of spot trajectory.
- `ScorecardCompareView.jsx` — two date-range pickers + side-by-side scorecard table with delta column color-coded by sign.
- `DailyReportsView.jsx` — list of available reports (newest first) + markdown viewer pane. Use [marked](https://marked.js.org) or roll a tiny markdown renderer (~100 lines for headers/lists/tables only).

**8. Augment Journal detail panel** (still in `JournalView.jsx`):
- **What-if comparison block** — small table:
  | Strategy | P&L |
  |---|---|
  | Actual exit | +12.5% |
  | Hold-50% | +8.2% |
  | Trail-30% | +14.8% ← would have been better |
  | Optimal | +18.0% |
- **Trade narrative** — auto-generated 1-line sentence at top of detail:
  > "10:23 BUY CE 24100 fired (47% conf, Rolling+Direction agreed). Spot rallied 12pts to Target by 10:48. Best exit was 18m @ +18%; you took +12.5% (eff 69%)."

**9. `frontend/src/App.jsx`**
- Add `'analytics'` to TABS array between Simulator and Download
- Add view branch: `view === 'analytics' ? <AnalyticsDeskView /> : ...`
- Add to no-auto-refresh exclusion list (Analytics manages its own polling)

### Wiring + polish — ~1 hour

**10.** Path constants: `services/grader.go` should export `DailyReportsDir() string` returning `data/reports/`. Ensure dir exists on first write.

**11.** Verify chart axes handle negative cumulative P&L (losing weeks should render below zero clearly).

**12.** Add Analytics tab key to `App.jsx` auto-refresh exclusion check.

---

## Total effort estimate

~7 hours focused work. Single feature commit when done. No new dependencies (markdown can be hand-rolled, `TradeChart` is reused everywhere).

---

## Out of scope (deferred — bigger plays)

- **Backtest replay tool** (item #6 from previous plan) — needs C2 (Parquet daily archive) as foundation. Separate 2-day effort.
- **Live position panel inside Cockpit** (F2) — different surface, lives outside Analytics.
- **Trade narrative as a generated field server-side** — keeping it client-side is simpler and avoids a stored-data churn point.

---

## Pickup checklist

When resuming this work:

1. Open `services/analytics.go` — verify it still builds (`go build ./...`)
2. Build `services/grader.go writeDailyReport` first (item 1 above) — needed by item 8 narrative wording reference
3. Build handlers (item 3) — verify each endpoint manually with `curl`
4. Build frontend container (item 5) and move existing views (item 6) — get the shell working before adding new sub-tabs
5. Add new sub-tabs one at a time: Equity → Suppressed → Reports → A/B Compare
6. Last: augment Journal detail with what-if + narrative
7. Single commit at the end with a clear message listing all 6 sub-tabs
