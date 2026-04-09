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

// FetchOHLCV fetches OHLCV data from Yahoo Finance.
func FetchOHLCV(ticker, interval, rangeVal string, ttl time.Duration) ([]models.OHLCV, error) {
cacheKey := fmt.Sprintf("%s|%s|%s", ticker, interval, rangeVal)
if v, ok := marketCache.Get(cacheKey); ok {
return v.([]models.OHLCV), nil
}

url := fmt.Sprintf(
"https://query1.finance.yahoo.com/v8/finance/chart/%s?interval=%s&range=%s",
ticker, interval, rangeVal,
)
client := &http.Client{Timeout: 12 * time.Second}
req, _ := http.NewRequest("GET", url, nil)
req.Header.Set("User-Agent", "Mozilla/5.0")

resp, err := client.Do(req)
if err != nil {
return nil, err
}
defer resp.Body.Close()
body, _ := io.ReadAll(resp.Body)

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
if i < len(q.Volume) { vol = q.Volume[i] }
bars = append(bars, models.OHLCV{
Time: ts, Open: q.Open[i], High: q.High[i],
Low: q.Low[i], Close: q.Close[i], Volume: vol,
})
}

marketCache.Set(cacheKey, bars, ttl)
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
case "^NSEI":      return "NIFTY"
case "^NSEBANK":   return "BANKNIFTY"
case "^DJI":       return "DOW"
}
for i := len(ticker) - 1; i >= 0; i-- {
if ticker[i] == '.' { return ticker[:i] }
}
return ticker
}
