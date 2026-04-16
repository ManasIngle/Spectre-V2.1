package services

import (
	"encoding/json"
	"fmt"
	"net/http"
	"time"
)

// MLPrediction is the response from the Python ML sidecar.
type ModelOutput struct {
	Prediction int        `json:"prediction"`
	Probs      [3]float64 `json:"probs"`
	Label      string     `json:"label"`
	Accuracy   float64    `json:"accuracy"`
}

type ModelsBreakdown struct {
	Rolling      ModelOutput  `json:"rolling"`
	Direction    ModelOutput  `json:"direction"`
	CrossAsset   ModelOutput  `json:"cross_asset"`
	OldDirection *ModelOutput `json:"old_direction,omitempty"`
}

type MLPrediction struct {
	Prediction           int             `json:"prediction"`
	Probs                [3]float64      `json:"probs"`
	XGBProbs             [3]float64      `json:"xgb_probs"`
	LSTMProbs            [3]float64      `json:"lstm_probs"`
	CrossAssetPrediction int             `json:"cross_asset_prediction"`
	CrossAssetProbs      [3]float64      `json:"cross_asset_probs"`
	EnsembleMode         bool            `json:"ensemble_mode"`
	ModelAccuracy        float64         `json:"model_accuracy"`
	Models               ModelsBreakdown `json:"models"`
	Error                string          `json:"error,omitempty"`
}

var mlClient = &http.Client{Timeout: 8 * time.Second}

// ScalperPrediction is the response from the 3-minute scalper LSTM endpoint.
type ScalperPrediction struct {
	Signal         string             `json:"signal"`
	Prediction     string             `json:"prediction"`
	Confidence     float64            `json:"confidence"`
	Probs          ScalperProbs       `json:"probs"`
	HorizonMinutes int                `json:"horizon_minutes"`
	SeqLenUsed     int                `json:"seq_len_used"`
	ModelAccuracy  float64            `json:"model_accuracy"`
	BarsAvailable  int                `json:"bars_available"`
	Error          string             `json:"error,omitempty"`
}

type ScalperProbs struct {
	Sideways float64 `json:"sideways"`
	Up       float64 `json:"up"`
	Down     float64 `json:"down"`
}

var scalperCache = NewTTLCache()

// FetchScalperPrediction calls /predict-scalper on the Python sidecar.
func FetchScalperPrediction() (*ScalperPrediction, error) {
	if v, ok := scalperCache.Get("scalper"); ok {
		return v.(*ScalperPrediction), nil
	}
	resp, err := mlClient.Get("http://ml-sidecar:8240/predict-scalper")
	if err != nil {
		// try localhost fallback
		resp, err = mlClient.Get("http://localhost:8240/predict-scalper")
		if err != nil {
			return nil, fmt.Errorf("scalper sidecar unreachable: %v", err)
		}
	}
	if resp.StatusCode != http.StatusOK {
		resp.Body.Close()
		return nil, fmt.Errorf("scalper sidecar returned HTTP %d", resp.StatusCode)
	}
	body, err := readBody(resp, 1<<20)
	if err != nil {
		return nil, fmt.Errorf("scalper sidecar read error: %w", err)
	}
	var pred ScalperPrediction
	if err := json.Unmarshal(body, &pred); err != nil {
		return nil, fmt.Errorf("scalper sidecar parse error: %v", err)
	}
	if pred.Error != "" {
		return nil, fmt.Errorf("scalper sidecar error: %s", pred.Error)
	}
	scalperCache.Set("scalper", &pred, 55*time.Second) // cache for ~1 bar
	return &pred, nil
}

func CheckSidecarHealth() (bool, error) {
	resp, err := mlClient.Get("http://ml-sidecar:8240/health")
	if err != nil {
		return false, err
	}
	defer resp.Body.Close()
	return resp.StatusCode == http.StatusOK, nil
}

// FetchMLPrediction calls the Python sidecar at :8240/predict.
// The sidecar just loads the pkl models and returns probabilities.
// This is fast (<50ms) because the models stay in memory.
func FetchMLPrediction() (*MLPrediction, error) {
	resp, err := mlClient.Get("http://ml-sidecar:8240/predict")
	if err != nil {
		return nil, fmt.Errorf("ML sidecar unreachable: %v", err)
	}
	if resp.StatusCode != http.StatusOK {
		resp.Body.Close()
		return nil, fmt.Errorf("ML sidecar returned HTTP %d", resp.StatusCode)
	}
	body, err := readBody(resp, 1<<20)
	if err != nil {
		return nil, fmt.Errorf("ML sidecar read error: %w", err)
	}
	var pred MLPrediction
	if err := json.Unmarshal(body, &pred); err != nil {
		return nil, fmt.Errorf("ML sidecar parse error: %v", err)
	}
	if pred.Error != "" {
		return nil, fmt.Errorf("ML sidecar error: %s", pred.Error)
	}
	return &pred, nil
}
