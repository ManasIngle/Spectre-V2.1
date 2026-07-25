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

// FetchIntradayRead POSTs the full trade signal to the sidecar's /intraday_read
// endpoint, which enriches it with the effectiveness gauge, global context, and
// news, then calls the LLM. Advisory only — the result never influences trades.
func FetchIntradayRead(signal *models.TradeSignal) (map[string]any, error) {
	body, err := json.Marshal(signal)
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

	path := intradayReadCSVPath()
	_, statErr := os.Stat(path)
	f, err := os.OpenFile(path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
	if err != nil {
		return
	}
	defer f.Close()
	w := csv.NewWriter(f)
	defer w.Flush()
	if os.IsNotExist(statErr) {
		w.Write([]string{"Date", "Time", "Regime", "ATR_Pct", "VIX", "TimeBucket",
			"EffectiveWindow", "ExpectedVol", "DirectionalLean", "LeanConfidence", "Read"})
	}
	w.Write([]string{
		now.Format("2006-01-02"), now.Format("15:04:05"),
		get(gauge, "regime"), get(gauge, "atr_pct"), get(gauge, "vix"), get(gauge, "time_bucket"),
		get(r, "effective_window"), get(r, "expected_volatility"),
		get(r, "directional_lean"), get(r, "lean_confidence"), get(r, "read"),
	})
}
