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
	ErrorCode          string             `json:"error_code,omitempty"`
	Message            string             `json:"message,omitempty"`
	FetchInProgress    bool               `json:"fetch_in_progress,omitempty"`
}

// OvernightDataStatus mirrors the sidecar's /overnight_data_status response.
type OvernightDataStatus struct {
	Exists           bool    `json:"exists"`
	LastModified     string  `json:"last_modified,omitempty"`
	AgeHours         float64 `json:"age_hours,omitempty"`
	FetchInProgress  bool    `json:"fetch_in_progress"`
	FetchStartedAt   string  `json:"fetch_started_at,omitempty"`
	LastFetchStatus  string  `json:"last_fetch_status,omitempty"`
	LastFetchAt      string  `json:"last_fetch_at,omitempty"`
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
//
// On structured errors (data_missing / model_not_loaded) we return the
// prediction object with the error fields populated so the UI can render a
// proper backfill button. Only unreachable / parse failures bubble as errors.
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
	// Structured error → return as-is so frontend can render the backfill flow.
	// Don't cache errors (we want the next fetch to re-check after backfill completes).
	if pred.Error != "" {
		return &pred, nil
	}
	overnightCache.Set("pred", &pred, 10*time.Minute)
	return &pred, nil
}

// RefreshOvernightData triggers a background backfill on the sidecar.
// Returns the sidecar's status payload (may say a fetch was already running).
func RefreshOvernightData() (map[string]interface{}, error) {
	resp, err := mlClient.Post("http://ml-sidecar:8240/refresh_overnight_data", "application/json", nil)
	if err != nil {
		resp, err = mlClient.Post("http://localhost:8240/refresh_overnight_data", "application/json", nil)
	}
	if err != nil {
		return nil, fmt.Errorf("refresh overnight unreachable: %v", err)
	}
	defer resp.Body.Close()
	body, err := readBody(resp, 1<<20)
	if err != nil {
		return nil, fmt.Errorf("refresh overnight read: %w", err)
	}
	out := map[string]interface{}{}
	if err := json.Unmarshal(body, &out); err != nil {
		return nil, fmt.Errorf("refresh overnight parse: %v", err)
	}
	// Invalidate cached error/prediction so the next fetch sees fresh state.
	overnightCache.Delete("pred")
	return out, nil
}

// FetchOvernightDataStatus pulls the current parquet/fetch status from the sidecar.
func FetchOvernightDataStatus() (*OvernightDataStatus, error) {
	resp, err := sidecarGet("/overnight_data_status")
	if err != nil {
		return nil, fmt.Errorf("overnight status unreachable: %v", err)
	}
	defer resp.Body.Close()
	body, err := readBody(resp, 1<<20)
	if err != nil {
		return nil, fmt.Errorf("overnight status read: %w", err)
	}
	var st OvernightDataStatus
	if err := json.Unmarshal(body, &st); err != nil {
		return nil, fmt.Errorf("overnight status parse: %v", err)
	}
	return &st, nil
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
