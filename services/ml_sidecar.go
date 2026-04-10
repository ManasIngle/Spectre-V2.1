package services

import (
"encoding/json"
"fmt"
"io"
"net/http"
"time"
)

// MLPrediction is the response from the Python ML sidecar.
type MLPrediction struct {
	Prediction    int        `json:"prediction"`  // 0=DOWN 1=SIDEWAYS 2=UP
	Probs         [3]float64 `json:"probs"`        // [probDown, probSide, probUp]
	XGBProbs      [3]float64 `json:"xgb_probs"`
	LSTMProbs     [3]float64 `json:"lstm_probs"`
	CrossAssetPrediction int `json:"cross_asset_prediction"`
	CrossAssetProbs [3]float64 `json:"cross_asset_probs"`
	EnsembleMode  bool       `json:"ensemble_mode"`
	ModelAccuracy float64    `json:"model_accuracy"`
	Error         string     `json:"error,omitempty"`
}

var mlClient = &http.Client{Timeout: 8 * time.Second}

// FetchMLPrediction calls the Python sidecar at :8240/predict.
// The sidecar just loads the pkl models and returns probabilities.
// This is fast (<50ms) because the models stay in memory.
func FetchMLPrediction() (*MLPrediction, error) {
	resp, err := mlClient.Get("http://ml-sidecar:8240/predict")
	if err != nil {
		return nil, fmt.Errorf("ML sidecar unreachable: %v", err)
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)
	var pred MLPrediction
	if err := json.Unmarshal(body, &pred); err != nil {
		return nil, fmt.Errorf("ML sidecar parse error: %v", err)
	}
	if pred.Error != "" {
		return nil, fmt.Errorf("ML sidecar error: %s", pred.Error)
	}
	return &pred, nil
}
