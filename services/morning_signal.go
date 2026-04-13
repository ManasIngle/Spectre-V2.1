package services

import (
	"encoding/json"
	"fmt"
	"net/http"
	"time"

	"spectre/models"
)

var morningCache = NewTTLCache()

func FetchMorningPrediction() (*models.MorningSignal, error) {
	resp, err := mlClient.Get("http://ml-sidecar:8240/morning-predict")
	if err != nil {
		return nil, fmt.Errorf("morning predict unreachable: %v", err)
	}
	if resp.StatusCode != http.StatusOK {
		resp.Body.Close()
		return nil, fmt.Errorf("morning predict returned HTTP %d", resp.StatusCode)
	}
	body, err := readBody(resp, 1<<20)
	if err != nil {
		return nil, fmt.Errorf("morning predict read error: %w", err)
	}

	var raw struct {
		Prediction      string  `json:"prediction"`
		Confidence      float64 `json:"confidence"`
		FilteredConf    float64 `json:"filtered_confidence"`
		ProbGap         float64 `json:"prob_gap"`
		RawSignal       string  `json:"raw_signal"`
		OptionType      string  `json:"option_type"`
		NiftySpot       float64 `json:"nifty_spot"`
		PrevDayClose    float64 `json:"prev_day_close"`
		TodayOpen       float64 `json:"today_open"`
		GapPct          float64 `json:"gap_pct"`
		GapType         string  `json:"gap_type"`
		GapSeverity     string  `json:"gap_severity"`
		GapFilter       string  `json:"gap_filter"`
		PrevDayTrend    string  `json:"prev_day_trend"`
		ModelAccuracy   float64 `json:"model_accuracy"`
		GeneratedAt     string  `json:"generated_at"`
		ValidForMinutes int     `json:"valid_for_minutes"`
		Error           string  `json:"error,omitempty"`
		Skip            bool    `json:"skip,omitempty"`
	}

	if err := json.Unmarshal(body, &raw); err != nil {
		return nil, fmt.Errorf("morning predict parse error: %w", err)
	}
	if raw.Error != "" && !raw.Skip {
		return nil, fmt.Errorf("morning predict error: %s", raw.Error)
	}

	sig := &models.MorningSignal{
		Prediction:      raw.Prediction,
		Confidence:      raw.Confidence,
		FilteredConf:    raw.FilteredConf,
		ProbGap:         raw.ProbGap,
		RawSignal:       raw.RawSignal,
		OptionType:      raw.OptionType,
		NiftySpot:       raw.NiftySpot,
		PrevDayClose:    raw.PrevDayClose,
		TodayOpen:       raw.TodayOpen,
		GapPct:          raw.GapPct,
		GapType:         raw.GapType,
		GapSeverity:     raw.GapSeverity,
		GapFilter:       raw.GapFilter,
		PrevDayTrend:    raw.PrevDayTrend,
		ModelAccuracy:   raw.ModelAccuracy,
		GeneratedAt:     raw.GeneratedAt,
		ValidForMinutes: raw.ValidForMinutes,
	}

	if raw.Skip {
		sig.RawSignal = "NOT YET"
		sig.Error = raw.Error
	}

	return sig, nil
}

func GetMorningSignal() (*models.MorningSignal, error) {
	if v, ok := morningCache.Get("morning"); ok {
		return v.(*models.MorningSignal), nil
	}

	sig, err := FetchMorningPrediction()
	if err != nil {
		return &models.MorningSignal{Error: err.Error(), RawSignal: "PENDING"}, nil
	}

	morningCache.Set("morning", sig, 2*time.Minute)
	return sig, nil
}

func RefreshMorningSignal() {
	morningCache.Delete("morning")
	sig, err := FetchMorningPrediction()
	if err != nil {
		return
	}
	loc, _ := time.LoadLocation("Asia/Kolkata")
	now := time.Now().In(loc)
	fmt.Printf("[Morning Signal %s] %s | Conf: %.1f%% | Gap: %s (%.2f%%) | Filter: %s\n",
		now.Format("15:04:05"), sig.RawSignal, sig.Confidence, sig.GapType, sig.GapPct, sig.GapFilter)
	morningCache.Set("morning", sig, 5*time.Minute)
}
