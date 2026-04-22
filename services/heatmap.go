package services

import (
	"encoding/json"
	"fmt"
	"net/http"
	"time"

	"spectre/models"
)

type HeatmapResponse struct {
	Data      []models.HeatmapItem `json:"data"`
	Total     int                  `json:"total"`
	Requested int                  `json:"requested"`
	Error     string               `json:"error,omitempty"`
}

var (
	heatmapCache  = NewTTLCache()
	heatmapClient = &http.Client{Timeout: 120 * time.Second}
)

var sidecarHeatmapURLs = []string{
	"http://ml-sidecar:8240/heatmap",
	"http://localhost:8240/heatmap",
}

const heatmapCacheTTL = 3 * time.Minute

// FetchHeatmap proxies the sidecar's /heatmap endpoint. The sidecar fetches the NSE
// equity master CSV and fans out to Yahoo with a 50-concurrency semaphore; this can
// take 30–60s on a cold cache.
func FetchHeatmap() (*HeatmapResponse, error) {
	if v, ok := heatmapCache.Get("heatmap"); ok {
		return v.(*HeatmapResponse), nil
	}

	var resp *http.Response
	var err error
	for _, url := range sidecarHeatmapURLs {
		resp, err = heatmapClient.Get(url)
		if err == nil {
			break
		}
	}
	if err != nil {
		return nil, fmt.Errorf("heatmap sidecar unreachable: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("heatmap sidecar returned HTTP %d", resp.StatusCode)
	}
	body, err := readBody(resp, 4<<20)
	if err != nil {
		return nil, fmt.Errorf("heatmap read: %w", err)
	}
	var out HeatmapResponse
	if err := json.Unmarshal(body, &out); err != nil {
		return nil, fmt.Errorf("heatmap parse: %w", err)
	}
	if out.Error != "" {
		return nil, fmt.Errorf("heatmap sidecar error: %s", out.Error)
	}
	heatmapCache.Set("heatmap", &out, heatmapCacheTTL)
	return &out, nil
}
