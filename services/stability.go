package services

import (
"fmt"
"sync"
"time"

"spectre/models"
)

const (
minTopProb        = 0.42
	minProbGap        = 0.08
	persistenceCount  = 3
	hysteresisMargin  = 0.12
	instantFlipMargin = 0.25
	hysteresisConsec  = 2
	cooldownSecs      = 120 * time.Second
)

type stabilityState struct {
	confirmedDir    string
	confirmedAt     time.Time
	pendingDir      string
	pendingCount    int
	flipPendingDir  string
	flipPendingCnt  int
	cooldownUntil   time.Time
	lastFlipTime    time.Time
	totalRaw        int
	flipsBlocked    int
	confirmedSigs   int
	confirmedFlips  int
	history         []histEntry
}

type histEntry struct {
	t     time.Time
	dir   string
	probs [3]float64
}

var (
	stMu    sync.Mutex
	stState = &stabilityState{}
)

// ProcessPrediction applies the stability engine to a raw 3-class prediction.
// probs: [probDown, probSideways, probUp]
func ProcessPrediction(rawPred int, probs [3]float64, dirScore *float64) models.StabilityInfo {
	stMu.Lock()
	defer stMu.Unlock()

	st := stState
	now := time.Now()
	st.totalRaw++
	dirStrs := [3]string{"DOWN", "SIDEWAYS", "UP"}

	// Record history (keep last 50)
	st.history = append(st.history, histEntry{t: now, dir: dirStrs[rawPred], probs: probs})
	if len(st.history) > 50 { st.history = st.history[1:] }

	// Step 1: Conviction filter
	topIdx := 0
	for i := 1; i < 3; i++ { if probs[i] > probs[topIdx] { topIdx = i } }
	topProb := probs[topIdx]
	secondProb := 0.0
	for i, p := range probs { if i != topIdx && p > secondProb { secondProb = p } }
	gap := topProb - secondProb

	if topProb < minTopProb || gap < minProbGap {
		return buildResult(st, "WEAK", dirStrs[topIdx],
			fmt.Sprintf("Conviction fail: top=%.1f%% gap=%.1f%%", topProb*100, gap*100), gap)
	}

	convDir := dirStrs[topIdx]

	// Step 2: Direction Engine cross-check (veto)
	if dirScore != nil {
		if convDir == "UP" && *dirScore < -20 || convDir == "DOWN" && *dirScore > 20 {
			st.flipsBlocked++
			return buildResult(st, "VETOED", convDir,
				fmt.Sprintf("DirEngine veto: ML=%s score=%.1f", convDir, *dirScore), gap)
		}
	}

	// Step 3: Cooldown
	if now.Before(st.cooldownUntil) {
		rem := st.cooldownUntil.Sub(now).Seconds()
		return buildResultWithCooldown(st, "COOLDOWN", convDir,
			fmt.Sprintf("Cooldown: %.0fs — holding %s", rem, st.confirmedDir), gap, rem)
	}

	// Step 4: No confirmed direction — persistence check
	if st.confirmedDir == "" {
		if convDir == st.pendingDir { st.pendingCount++ } else { st.pendingDir = convDir; st.pendingCount = 1 }
		if st.pendingCount >= persistenceCount {
			st.confirmedDir = convDir; st.confirmedAt = now
			st.confirmedSigs++; st.pendingDir = ""; st.pendingCount = 0
			return buildResult(st, "STABLE", convDir, fmt.Sprintf("Confirmed %s after %d reads", convDir, persistenceCount), gap)
		}
		return buildResult(st, "CONFIRMING", convDir,
			fmt.Sprintf("Confirming %s: %d/%d reads", convDir, st.pendingCount, persistenceCount), gap)
	}

	// Step 5: Holding confirmed direction
	if convDir == st.confirmedDir || convDir == "SIDEWAYS" {
		st.flipPendingDir = ""; st.flipPendingCnt = 0
		return buildResult(st, "STABLE", st.confirmedDir, fmt.Sprintf("Holding %s", st.confirmedDir), gap)
	}

	// Step 6: Opposing direction — hysteresis
	confirmedIdx := 0
	for i, d := range dirStrs { if d == st.confirmedDir { confirmedIdx = i } }
	flipMargin := probs[topIdx] - probs[confirmedIdx]

	if flipMargin < hysteresisMargin {
		st.flipsBlocked++
		st.flipPendingDir = ""; st.flipPendingCnt = 0
		return buildResult(st, "STABLE", st.confirmedDir,
			fmt.Sprintf("Flip BLOCKED: %s margin=%.1f%%<%.0f%%", convDir, flipMargin*100, hysteresisMargin*100), gap)
	}

	// Instant flip?
	if flipMargin >= instantFlipMargin {
		oldDir := st.confirmedDir
		st.confirmedDir = convDir; st.confirmedAt = now
		st.cooldownUntil = now.Add(cooldownSecs)
		st.confirmedFlips++; st.confirmedSigs++
		st.flipPendingDir = ""; st.flipPendingCnt = 0
		return buildResult(st, "FLIPPED", convDir,
			fmt.Sprintf("INSTANT FLIP %s→%s margin=%.1f%%", oldDir, convDir, flipMargin*100), gap)
	}

	// Normal hysteresis count
	if convDir == st.flipPendingDir { st.flipPendingCnt++ } else { st.flipPendingDir = convDir; st.flipPendingCnt = 1 }
	if st.flipPendingCnt >= hysteresisConsec {
		oldDir := st.confirmedDir
		st.confirmedDir = convDir; st.confirmedAt = now
		st.cooldownUntil = now.Add(cooldownSecs)
		st.confirmedFlips++; st.confirmedSigs++
		st.flipPendingDir = ""; st.flipPendingCnt = 0
		return buildResult(st, "FLIPPED", convDir,
			fmt.Sprintf("FLIP %s→%s margin=%.1f%%", oldDir, convDir, flipMargin*100), gap)
	}
	st.flipsBlocked++
	return buildResult(st, "STABLE", st.confirmedDir,
		fmt.Sprintf("Flip pending %s: %d/%d", convDir, st.flipPendingCnt, hysteresisConsec), gap)
}

func dirToSignal(dir string) string {
	switch dir {
	case "UP":   return "BUY CE"
	case "DOWN": return "BUY PE"
	}
	return "NO TRADE"
}

func buildResult(st *stabilityState, status, rawDir, detail string, gap float64) models.StabilityInfo {
	return buildResultWithCooldown(st, status, rawDir, detail, gap, 0)
}

func buildResultWithCooldown(st *stabilityState, status, rawDir, detail string, gap, cooldownRem float64) models.StabilityInfo {
	return models.StabilityInfo{
		StableSignal: dirToSignal(st.confirmedDir), StableDirection: st.confirmedDir,
		Status: status, ConvictionOK: status != "WEAK",
		ProbGap: gap * 100, CooldownRemaining: cooldownRem,
		FlipsPrevented: st.flipsBlocked, ConfirmedSignals: st.confirmedSigs,
		ConfirmedFlips: st.confirmedFlips, RawDirection: rawDir, Detail: detail,
	}
}

// GetStabilityState returns the current engine state for the dashboard.
func GetStabilityState() models.StabilityStateResp {
	stMu.Lock()
	defer stMu.Unlock()
	st := stState
	rate := 0.0
	if st.totalRaw > 0 { rate = float64(st.flipsBlocked) / float64(st.totalRaw) * 100 }
	return models.StabilityStateResp{
		ConfirmedDirection: st.confirmedDir, PendingDirection: st.pendingDir,
		ConfirmedAt: float64(st.confirmedAt.UnixNano()) / 1e9,
		CooldownUntil: float64(st.cooldownUntil.UnixNano()) / 1e9,
		PendingCount: st.pendingCount, TotalRaw: st.totalRaw,
		FlipsPrevented: st.flipsBlocked, ConfirmedSignals: st.confirmedSigs,
		ConfirmedFlips: st.confirmedFlips, FlipPreventionRate: rate,
		HistoryDepth: len(st.history),
	}
}

// ResetStability resets the stability engine (call at market open).
func ResetStability() {
	stMu.Lock()
	defer stMu.Unlock()
	stState = &stabilityState{}
}
