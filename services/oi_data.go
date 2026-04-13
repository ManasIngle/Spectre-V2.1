package services

import (
	"compress/gzip"
	"crypto/tls"
	"encoding/json"
	"fmt"
	"io"
	"math"
	"math/rand"
	"net/http"
	"net/http/cookiejar"
	"strings"
	"sync"
	"time"

	"spectre/models"
)

var oiCache = NewTTLCache()

const oiCacheTTL = 150 * time.Second // 2.5 min — NSE updates every 3 min

// Cookie state
var (
	nseCookies    []*http.Cookie
	nseCookieMu   sync.Mutex
	nseCookieTime time.Time
	nseCookieTTL  = 5 * time.Minute
)

// Browser-like headers for initial page visits
var browserHeaders = map[string]string{
	"User-Agent":                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
	"Accept":                    "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
	"Accept-Language":           "en-US,en;q=0.9,hi;q=0.8",
	"Accept-Encoding":           "gzip, deflate, br",
	"Connection":                "keep-alive",
	"Cache-Control":             "max-age=0",
	"Sec-Ch-Ua":                 `"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"`,
	"Sec-Ch-Ua-Mobile":          "?0",
	"Sec-Ch-Ua-Platform":        `"Windows"`,
	"Sec-Fetch-Dest":            "document",
	"Sec-Fetch-Mode":            "navigate",
	"Sec-Fetch-Site":            "none",
	"Sec-Fetch-User":            "?1",
	"Upgrade-Insecure-Requests": "1",
}

// API headers for actual data requests
var apiHeaders = map[string]string{
	"User-Agent":        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
	"Accept":            "application/json, text/javascript, */*; q=0.01",
	"Accept-Language":   "en-US,en;q=0.9,hi;q=0.8",
	"Accept-Encoding":   "gzip, deflate, br",
	"Connection":        "keep-alive",
	"Referer":           "https://www.nseindia.com/option-chain",
	"Sec-Ch-Ua":         `"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"`,
	"Sec-Ch-Ua-Mobile":  "?0",
	"Sec-Ch-Ua-Platform": `"Windows"`,
	"Sec-Fetch-Dest":    "empty",
	"Sec-Fetch-Mode":    "cors",
	"Sec-Fetch-Site":    "same-origin",
	"X-Requested-With":  "XMLHttpRequest",
}

func newNSEClient() *http.Client {
	jar, _ := cookiejar.New(nil)
	return &http.Client{
		Timeout: 15 * time.Second,
		Jar:     jar,
		Transport: &http.Transport{
			TLSClientConfig: &tls.Config{InsecureSkipVerify: true},
		},
	}
}

// refreshNSECookies visits NSE homepage + option chain page to acquire session cookies
func refreshNSECookies() error {
	nseCookieMu.Lock()
	defer nseCookieMu.Unlock()

	if time.Since(nseCookieTime) < nseCookieTTL && len(nseCookies) > 0 {
		return nil // still fresh
	}

	client := newNSEClient()

	// Step 1: Visit homepage
	req, _ := http.NewRequest("GET", "https://www.nseindia.com", nil)
	for k, v := range browserHeaders {
		req.Header.Set(k, v)
	}
	resp, err := client.Do(req)
	if err != nil {
		return fmt.Errorf("NSE homepage: %w", err)
	}
	io.Copy(io.Discard, resp.Body)
	resp.Body.Close()

	// Human-like delay
	time.Sleep(time.Duration(500+rand.Intn(500)) * time.Millisecond)

	// Step 2: Visit option chain page to set additional cookies
	req2, _ := http.NewRequest("GET", "https://www.nseindia.com/option-chain", nil)
	for k, v := range browserHeaders {
		req2.Header.Set(k, v)
	}
	req2.Header.Set("Referer", "https://www.nseindia.com/")
	resp2, err := client.Do(req2)
	if err != nil {
		return fmt.Errorf("NSE option chain page: %w", err)
	}
	io.Copy(io.Discard, resp2.Body)
	resp2.Body.Close()

	// Collect all cookies from the jar
	homeURL := resp.Request.URL
	ocURL := resp2.Request.URL
	allCookies := make(map[string]*http.Cookie)
	for _, c := range client.Jar.Cookies(homeURL) {
		allCookies[c.Name] = c
	}
	for _, c := range client.Jar.Cookies(ocURL) {
		allCookies[c.Name] = c
	}

	nseCookies = make([]*http.Cookie, 0, len(allCookies))
	for _, c := range allCookies {
		nseCookies = append(nseCookies, c)
	}
	nseCookieTime = time.Now()
	return nil
}

func buildCookieHeader() string {
	nseCookieMu.Lock()
	defer nseCookieMu.Unlock()
	parts := make([]string, 0, len(nseCookies))
	for _, c := range nseCookies {
		parts = append(parts, fmt.Sprintf("%s=%s", c.Name, c.Value))
	}
	return strings.Join(parts, "; ")
}

func readGzipBody(resp *http.Response) ([]byte, error) {
	defer resp.Body.Close()
	var reader io.Reader = resp.Body
	if resp.Header.Get("Content-Encoding") == "gzip" {
		gr, err := gzip.NewReader(resp.Body)
		if err != nil {
			return nil, err
		}
		defer gr.Close()
		reader = gr
	}
	return io.ReadAll(io.LimitReader(reader, 2<<20))
}

func FetchOIChain() (*models.OIChainData, error) {
	if v, ok := oiCache.Get("oi"); ok {
		return v.(*models.OIChainData), nil
	}

	// Ensure cookies are fresh
	if err := refreshNSECookies(); err != nil {
		return &models.OIChainData{Error: fmt.Sprintf("cookie refresh: %v", err)}, nil
	}

	var lastErr error
	for attempt := 0; attempt < 3; attempt++ {
		result, err := fetchOIAttempt()
		if err == nil {
			oiCache.Set("oi", result, oiCacheTTL)
			return result, nil
		}
		lastErr = err

		// On auth error, force cookie refresh
		if strings.Contains(err.Error(), "401") || strings.Contains(err.Error(), "403") {
			nseCookieMu.Lock()
			nseCookieTime = time.Time{} // force refresh
			nseCookieMu.Unlock()
			refreshNSECookies()
			time.Sleep(time.Duration(1+attempt) * time.Second)
			continue
		}

		// On rate limit, wait longer
		if strings.Contains(err.Error(), "429") {
			time.Sleep(time.Duration(3+attempt*2) * time.Second)
			continue
		}

		time.Sleep(time.Second)
	}

	return &models.OIChainData{Error: fmt.Sprintf("after 3 retries: %v", lastErr)}, nil
}

func fetchOIAttempt() (*models.OIChainData, error) {
	client := &http.Client{
		Timeout: 15 * time.Second,
		Transport: &http.Transport{
			TLSClientConfig: &tls.Config{InsecureSkipVerify: true},
		},
	}

	// Step 1: Get contract info to find nearest expiry
	contractURL := "https://www.nseindia.com/api/option-chain-contract-info?symbol=NIFTY"
	req1, _ := http.NewRequest("GET", contractURL, nil)
	for k, v := range apiHeaders {
		req1.Header.Set(k, v)
	}
	cookieStr := buildCookieHeader()
	if cookieStr != "" {
		req1.Header.Set("Cookie", cookieStr)
	}

	resp1, err := client.Do(req1)
	if err != nil {
		return nil, fmt.Errorf("contract info: %w", err)
	}
	if resp1.StatusCode != http.StatusOK {
		io.Copy(io.Discard, resp1.Body)
		resp1.Body.Close()
		return nil, fmt.Errorf("contract info HTTP %d", resp1.StatusCode)
	}

	body1, err := readGzipBody(resp1)
	if err != nil {
		return nil, fmt.Errorf("contract body: %w", err)
	}

	var contractData struct {
		ExpiryDates []string `json:"expiryDates"`
	}
	if err := json.Unmarshal(body1, &contractData); err != nil {
		return nil, fmt.Errorf("contract parse: %w", err)
	}
	if len(contractData.ExpiryDates) == 0 {
		return nil, fmt.Errorf("no expiry dates returned")
	}
	nearestExpiry := contractData.ExpiryDates[0]

	// Human-like delay
	time.Sleep(time.Duration(200+rand.Intn(300)) * time.Millisecond)

	// Step 2: Fetch option chain v3
	v3URL := fmt.Sprintf("https://www.nseindia.com/api/option-chain-v3?type=Indices&symbol=NIFTY&expiry=%s", nearestExpiry)
	req2, _ := http.NewRequest("GET", v3URL, nil)
	for k, v := range apiHeaders {
		req2.Header.Set(k, v)
	}
	cookieStr = buildCookieHeader()
	if cookieStr != "" {
		req2.Header.Set("Cookie", cookieStr)
	}

	resp2, err := client.Do(req2)
	if err != nil {
		return nil, fmt.Errorf("v3 chain: %w", err)
	}
	if resp2.StatusCode != http.StatusOK {
		io.Copy(io.Discard, resp2.Body)
		resp2.Body.Close()
		return nil, fmt.Errorf("v3 chain HTTP %d", resp2.StatusCode)
	}

	body2, err := readGzipBody(resp2)
	if err != nil {
		return nil, fmt.Errorf("v3 body: %w", err)
	}

	// Parse the v3 response
	var raw struct {
		Records struct {
			UnderlyingValue float64 `json:"underlyingValue"`
			Data            []struct {
				StrikePrice float64 `json:"strikePrice"`
				CE          *struct {
					OI    int64   `json:"openInterest"`
					OIChg int64   `json:"changeinOpenInterest"`
					LTP   float64 `json:"lastPrice"`
				} `json:"CE"`
				PE *struct {
					OI    int64   `json:"openInterest"`
					OIChg int64   `json:"changeinOpenInterest"`
					LTP   float64 `json:"lastPrice"`
				} `json:"PE"`
			} `json:"data"`
		} `json:"records"`
		// v3 may also nest under "filtered"
		Filtered struct {
			Data []struct {
				StrikePrice float64 `json:"strikePrice"`
				CE          *struct {
					OI    int64   `json:"openInterest"`
					OIChg int64   `json:"changeinOpenInterest"`
					LTP   float64 `json:"lastPrice"`
				} `json:"CE"`
				PE *struct {
					OI    int64   `json:"openInterest"`
					OIChg int64   `json:"changeinOpenInterest"`
					LTP   float64 `json:"lastPrice"`
				} `json:"PE"`
			} `json:"data"`
		} `json:"filtered"`
	}

	if err := json.Unmarshal(body2, &raw); err != nil {
		return nil, fmt.Errorf("v3 parse: %w", err)
	}

	// Use records.data, fall back to filtered.data
	data := raw.Records.Data
	if len(data) == 0 {
		data = raw.Filtered.Data
	}
	if len(data) == 0 {
		return nil, fmt.Errorf("empty option chain data")
	}

	// Determine ATM and filter to ATM ± 1000 points
	underlying := raw.Records.UnderlyingValue
	atm := math.Round(underlying/50) * 50

	result := &models.OIChainData{}
	for _, d := range data {
		// Filter to ±1000 from ATM
		if d.StrikePrice < atm-1000 || d.StrikePrice > atm+1000 {
			continue
		}

		s := models.OptionStrike{Strike: d.StrikePrice}
		if d.CE != nil {
			s.CEOI, s.CEOIChg, s.CELTP = d.CE.OI, d.CE.OIChg, d.CE.LTP
			result.TotalCEOI += s.CEOI
			result.TotalCEOIChg += s.CEOIChg
		}
		if d.PE != nil {
			s.PEOI, s.PEOIChg, s.PELTP = d.PE.OI, d.PE.OIChg, d.PE.LTP
			result.TotalPEOI += s.PEOI
			result.TotalPEOIChg += s.PEOIChg
		}
		result.Strikes = append(result.Strikes, s)
	}

	if result.TotalCEOI > 0 {
		result.PCR = float64(result.TotalPEOI) / float64(result.TotalCEOI)
	}

	return result, nil
}
