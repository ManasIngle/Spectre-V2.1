package services

import (
	"bytes"
	"encoding/csv"
	"encoding/json"
	"net/http"
	"os"
	"sync"
	"time"

	"spectre/models"
)

// llmClient has a long timeout — the LLM call can take 10-30s.
var llmClient = &http.Client{Timeout: 40 * time.Second}

// latestIntradayRead caches the most recent advisory read for the frontend.
var (
	latestIntradayRead   map[string]any
	latestIntradayReadMu sync.RWMutex
)

func intradayReadCSVPath() string { return DataPath("intraday_reads.csv") }

// FetchIntradayRead assembles EVERYTHING the system knows and POSTs it to the
// sidecar's /intraday_read endpoint, which adds the effectiveness gauge, global
// cross-asset context, and news, then calls the LLM. Advisory only — the result
// never influences trades. The payload deliberately carries full context (signal
// + full OI chain + scalper LSTM + overnight next-day bias) so the LLM sees the
// complete market picture.
func FetchIntradayRead(signal *models.TradeSignal, oi *models.OIChainData) (map[string]any, error) {
	payload := map[string]any{"signal": signal}
	if oi != nil {
		payload["oi_chain"] = oi // full chain: strikes, OI, OI-change, PCR, totals
	}
	if scalper, err := FetchScalperPrediction(); err == nil {
		payload["scalper_lstm"] = scalper // 3-min horizon scalp signal
	}
	if ovn, err := FetchOvernightPrediction(); err == nil && ovn != nil && ovn.Error == "" {
		payload["overnight_bias"] = ovn // next-day direction/magnitude context
	}

	body, err := json.Marshal(payload)
	if err != nil {
		return nil, err
	}
	post := func(url string) (*http.Response, error) {
		return llmClient.Post(url, "application/json", bytes.NewReader(body))
	}
	resp, err := post("http://ml-sidecar:8240/intraday_read")
	if err != nil {
		resp, err = post("http://localhost:8240/intraday_read")
		if err != nil {
			return nil, err
		}
	}
	defer resp.Body.Close()

	var out map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, err
	}

	latestIntradayReadMu.Lock()
	latestIntradayRead = out
	latestIntradayReadMu.Unlock()
	return out, nil
}

// GetLatestIntradayRead returns the cached most-recent read (for the frontend).
func GetLatestIntradayRead() map[string]any {
	latestIntradayReadMu.RLock()
	defer latestIntradayReadMu.RUnlock()
	return latestIntradayRead
}

// LatestLLMBrief returns the most recent LLM two-liner (empty until the first
// read of the session). Written into every per-minute signal-log row so the
// advisory read travels with the actively-accumulated logs.
func LatestLLMBrief() string {
	latestIntradayReadMu.RLock()
	read := latestIntradayRead
	latestIntradayReadMu.RUnlock()
	if read == nil {
		return ""
	}
	llm, _ := read["llm"].(map[string]any)
	r, _ := llm["read"].(map[string]any)
	if r == nil {
		return ""
	}
	if v, ok := r["two_liner"].(string); ok && v != "" {
		return v
	}
	if v, ok := r["summary"].(string); ok { // fallback if two_liner absent
		return v
	}
	return ""
}

// logIntradayRead appends a flattened row to intraday_reads.csv for history.
func logIntradayRead(now time.Time, read map[string]any) {
	gauge, _ := read["gauge"].(map[string]any)
	llm, _ := read["llm"].(map[string]any)
	r, _ := llm["read"].(map[string]any)

	get := func(m map[string]any, k string) string {
		if m == nil {
			return ""
		}
		if v, ok := m[k]; ok && v != nil {
			b, _ := json.Marshal(v)
			s := string(b)
			if len(s) >= 2 && s[0] == '"' {
				s = s[1 : len(s)-1] // unquote simple strings
			}
			return s
		}
		return ""
	}

	// Compact CSV row for quick history/scanning.
	path := intradayReadCSVPath()
	_, statErr := os.Stat(path)
	f, err := os.OpenFile(path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
	if err == nil {
		defer f.Close()
		w := csv.NewWriter(f)
		defer w.Flush()
		if os.IsNotExist(statErr) {
			w.Write([]string{"Date", "Time", "Regime", "ATR_Pct", "VIX", "TimeBucket",
				"EffectiveWindow", "Recommendation", "ExpectedVol", "DirectionalLean",
				"LeanConfidence", "Summary"})
		}
		w.Write([]string{
			now.Format("2006-01-02"), now.Format("15:04:05"),
			get(gauge, "regime"), get(gauge, "atr_pct"), get(gauge, "vix"), get(gauge, "time_bucket"),
			get(r, "effective_window"), get(r, "recommendation"), get(r, "expected_volatility"),
			get(r, "directional_lean"), get(r, "lean_confidence"), get(r, "summary"),
		})
	}

	// Full elaborate read appended as JSONL so nothing is lost (dashboard/history).
	if jf, err := os.OpenFile(DataPath("intraday_reads_full.jsonl"),
		os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644); err == nil {
		defer jf.Close()
		if b, err := json.Marshal(map[string]any{
			"ts": now.Format(time.RFC3339), "read": read,
		}); err == nil {
			jf.Write(append(b, '\n'))
		}
	}
}
