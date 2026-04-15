package services

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"

	"spectre/models"
)

var marketCache = NewTTLCache()
var yahooClient = &http.Client{Timeout: 12 * time.Second}

// sidecarOHLCVURL — Python sidecar proxies Yahoo Finance to avoid TLS fingerprint block
const sidecarOHLCVURL = "http://localhost:8240/ohlcv"

func readBody(resp *http.Response, maxBytes int64) ([]byte, error) {
	defer resp.Body.Close()
	return io.ReadAll(io.LimitReader(resp.Body, maxBytes))
}

func FetchOHLCV(ticker, interval, rangeVal string, ttl time.Duration) ([]models.OHLCV, error) {
	cacheKey := fmt.Sprintf("%s|%s|%s", ticker, interval, rangeVal)
	if v, ok := marketCache.Get(cacheKey); ok {
		return v.([]models.OHLCV), nil
	}

	// Try sidecar proxy first — Python aiohttp passes TLS check that Go net/http fails
	if bars, err := fetchOHLCVViaSidecar(ticker, interval, rangeVal); err == nil && len(bars) > 0 {
		marketCache.Set(cacheKey, bars, ttl)
		return bars, nil
	}

	// Fallback: direct Go fetch
	bars, err := fetchOHLCVDirect(ticker, interval, rangeVal)
	if err != nil {
		return nil, err
	}
	marketCache.Set(cacheKey, bars, ttl)
	return bars, nil
}

func fetchOHLCVViaSidecar(ticker, interval, rangeVal string) ([]models.OHLCV, error) {
	url := fmt.Sprintf("%s?ticker=%s&interval=%s&range=%s", sidecarOHLCVURL, ticker, interval, rangeVal)
	resp, err := yahooClient.Get(url)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	body, err := readBody(resp, 1<<20)
	if err != nil {
		return nil, err
	}
	var result struct {
		Error string `json:"error"`
		Bars  []struct {
			T int64   `json:"t"`
			O float64 `json:"o"`
			H float64 `json:"h"`
			L float64 `json:"l"`
			C float64 `json:"c"`
			V float64 `json:"v"`
		} `json:"bars"`
	}
	if err := json.Unmarshal(body, &result); err != nil {
		return nil, err
	}
	if result.Error != "" {
		return nil, fmt.Errorf("sidecar: %s", result.Error)
	}
	bars := make([]models.OHLCV, 0, len(result.Bars))
	for _, b := range result.Bars {
		if b.C == 0 {
			continue
		}
		bars = append(bars, models.OHLCV{Time: b.T, Open: b.O, High: b.H, Low: b.L, Close: b.C, Volume: b.V})
	}
	return bars, nil
}

func fetchOHLCVDirect(ticker, interval, rangeVal string) ([]models.OHLCV, error) {
	url := fmt.Sprintf(
		"https://query2.finance.yahoo.com/v8/finance/chart/%s?interval=%s&range=%s",
		ticker, interval, rangeVal,
	)
	req, err := http.NewRequest("GET", url, nil)
	if err != nil {
		return nil, fmt.Errorf("build request for %s: %w", ticker, err)
	}
	req.Header.Set("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
	req.Header.Set("Accept", "*/*")
	req.Header.Set("Accept-Language", "en-US,en;q=0.9")
	req.Header.Set("Referer", "https://finance.yahoo.com/")
	req.Header.Set("Origin", "https://finance.yahoo.com")

	resp, err := yahooClient.Do(req)
	if err != nil {
		return nil, err
	}
	if resp.StatusCode != http.StatusOK {
		resp.Body.Close()
		return nil, fmt.Errorf("Yahoo returned %d for %s", resp.StatusCode, ticker)
	}
	body, err := readBody(resp, 1<<20)
	if err != nil {
		return nil, fmt.Errorf("read body for %s: %w", ticker, err)
	}
	type quoteBlock struct {
		Open   []float64 `json:"open"`
		High   []float64 `json:"high"`
		Low    []float64 `json:"low"`
		Close  []float64 `json:"close"`
		Volume []float64 `json:"volume"`
	}
	type resultBlock struct {
		Timestamp  []int64 `json:"timestamp"`
		Indicators struct {
			Quote []quoteBlock `json:"quote"`
		} `json:"indicators"`
	}
	var raw struct {
		Chart struct {
			Result []resultBlock `json:"result"`
		} `json:"chart"`
	}
	if err := json.Unmarshal(body, &raw); err != nil {
		return nil, fmt.Errorf("parse %s: %v", ticker, err)
	}
	if len(raw.Chart.Result) == 0 {
		return nil, fmt.Errorf("no data for %s", ticker)
	}
	res := raw.Chart.Result[0]
	if len(res.Indicators.Quote) == 0 {
		return nil, fmt.Errorf("empty quote for %s", ticker)
	}
	q := res.Indicators.Quote[0]
	var bars []models.OHLCV
	for i, ts := range res.Timestamp {
		if i >= len(q.Close) || q.Close[i] == 0 {
			continue
		}
		vol := 0.0
		if i < len(q.Volume) {
			vol = q.Volume[i]
		}
		bars = append(bars, models.OHLCV{
			Time: ts, Open: q.Open[i], High: q.High[i],
			Low: q.Low[i], Close: q.Close[i], Volume: vol,
		})
	}
	return bars, nil
}

// LTP returns the latest close price.
func LTP(ticker, interval, rangeVal string) (float64, error) {
	bars, err := FetchOHLCV(ticker, interval, rangeVal, 25*time.Second)
	if err != nil || len(bars) == 0 {
		return 0, err
	}
	return bars[len(bars)-1].Close, nil
}

// DisplayName converts Yahoo ticker to short name.
func DisplayName(ticker string) string {
	switch ticker {
	case "^NSEI":
		return "NIFTY"
	case "^NSEBANK":
		return "BANKNIFTY"
	case "^DJI":
		return "DOW"
	}
	for i := len(ticker) - 1; i >= 0; i-- {
		if ticker[i] == '.' {
			return ticker[:i]
		}
	}
	return ticker
}
