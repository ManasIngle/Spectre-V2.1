package services

import (
	"encoding/json"
	"fmt"
	"net/http"
	"time"
)

// OvernightPrediction mirrors the JSON from /predict_nifty_overnight.
type OvernightPrediction struct {
	PredictionDate     string             `json:"prediction_date"`
	AsofSession        string             `json:"asof_session"`
	TargetDate         string             `json:"target_date"`
	PrevClose          float64            `json:"prev_close"`
	PredictedClose     float64            `json:"predicted_close"`
	PredictedChangePct float64            `json:"predicted_change_pct"`
	Direction          string             `json:"direction"`
	DirectionConf      float64            `json:"direction_confidence"`
	DirectionProbs     map[string]float64 `json:"direction_probs"`
	MagnitudeBucket    string             `json:"magnitude_bucket"`
	AbsChangePct       float64            `json:"abs_change_pct"`
	ModelVersion       string             `json:"model_version"`
	FeatureFreshness   string             `json:"feature_freshness"`
	Error              string             `json:"error,omitempty"`
}

// OvernightLogEntry is one row from /predict_nifty_overnight/log.
type OvernightLogEntry struct {
	PredictionDate     string   `json:"prediction_date"`
	AsofSession        string   `json:"asof_session"`
	TargetDate         string   `json:"target_date"`
	PrevClose          float64  `json:"prev_close"`
	PredictedClose     float64  `json:"predicted_close"`
	PredictedChangePct float64  `json:"predicted_change_pct"`
	Direction          string   `json:"direction"`
	DirectionConf      float64  `json:"direction_confidence"`
	PDown              float64  `json:"p_down"`
	PFlat              float64  `json:"p_flat"`
	PUp                float64  `json:"p_up"`
	MagnitudeBucket    string   `json:"magnitude_bucket"`
	AbsChangePct       float64  `json:"abs_change_pct"`
	ModelVersion       string   `json:"model_version"`
	ActualClose        *float64 `json:"actual_close"`
	AbsErrorPct        *float64 `json:"abs_error_pct"`
	DirectionCorrect   *bool    `json:"direction_correct"`
}

var overnightCache = NewTTLCache()

func sidecarGet(url string) (*http.Response, error) {
	resp, err := mlClient.Get("http://ml-sidecar:8240" + url)
	if err != nil {
		resp, err = mlClient.Get("http://localhost:8240" + url)
	}
	return resp, err
}

// FetchOvernightPrediction calls the sidecar and caches the result for 10 min.
// The overnight model only generates one prediction per day so a 10-min TTL
// avoids hammering the sidecar without hiding stale data meaningfully.
func FetchOvernightPrediction() (*OvernightPrediction, error) {
	if v, ok := overnightCache.Get("pred"); ok {
		return v.(*OvernightPrediction), nil
	}
	resp, err := sidecarGet("/predict_nifty_overnight")
	if err != nil {
		return nil, fmt.Errorf("overnight sidecar unreachable: %v", err)
	}
	if resp.StatusCode != http.StatusOK {
		resp.Body.Close()
		return nil, fmt.Errorf("overnight sidecar HTTP %d", resp.StatusCode)
	}
	body, err := readBody(resp, 1<<20)
	if err != nil {
		return nil, fmt.Errorf("overnight sidecar read: %w", err)
	}
	var pred OvernightPrediction
	if err := json.Unmarshal(body, &pred); err != nil {
		return nil, fmt.Errorf("overnight sidecar parse: %v", err)
	}
	if pred.Error != "" {
		return nil, fmt.Errorf("overnight sidecar: %s", pred.Error)
	}
	overnightCache.Set("pred", &pred, 10*time.Minute)
	return &pred, nil
}

// FetchOvernightLog fetches the last `limit` predictions from the log endpoint.
func FetchOvernightLog(limit int) ([]OvernightLogEntry, error) {
	key := fmt.Sprintf("log:%d", limit)
	if v, ok := overnightCache.Get(key); ok {
		return v.([]OvernightLogEntry), nil
	}
	url := fmt.Sprintf("/predict_nifty_overnight/log?limit=%d", limit)
	resp, err := sidecarGet(url)
	if err != nil {
		return nil, fmt.Errorf("overnight log unreachable: %v", err)
	}
	if resp.StatusCode != http.StatusOK {
		resp.Body.Close()
		return nil, fmt.Errorf("overnight log HTTP %d", resp.StatusCode)
	}
	body, err := readBody(resp, 2<<20)
	if err != nil {
		return nil, fmt.Errorf("overnight log read: %w", err)
	}
	var wrapper struct {
		Rows  []OvernightLogEntry `json:"rows"`
		N     int                 `json:"n"`
		Error string              `json:"error,omitempty"`
	}
	if err := json.Unmarshal(body, &wrapper); err != nil {
		return nil, fmt.Errorf("overnight log parse: %v", err)
	}
	if wrapper.Error != "" && len(wrapper.Rows) == 0 {
		// Empty log file is not an error — return empty slice.
		return []OvernightLogEntry{}, nil
	}
	overnightCache.Set(key, wrapper.Rows, 5*time.Minute)
	return wrapper.Rows, nil
}
