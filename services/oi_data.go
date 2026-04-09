package services

import (
"encoding/json"
"fmt"
"io"
"net/http"
neturl "net/url"
"time"

"spectre/models"
)

var oiCache = NewTTLCache()

const oiCacheTTL = 30 * time.Second

// cookieJar is a minimal http.CookieJar to hold NSE session cookies.
type cookieJar struct {
	cookies map[string][]*http.Cookie
}

func (j *cookieJar) SetCookies(u *neturl.URL, cookies []*http.Cookie) { j.cookies[u.Host] = cookies }
func (j *cookieJar) Cookies(u *neturl.URL) []*http.Cookie              { return j.cookies[u.Host] }

func newClient() *http.Client {
	jar := &cookieJar{cookies: make(map[string][]*http.Cookie)}
	return &http.Client{Timeout: 12 * time.Second, Jar: jar}
}

func FetchOIChain() (*models.OIChainData, error) {
	if v, ok := oiCache.Get("oi"); ok {
		return v.(*models.OIChainData), nil
	}

	client := newClient()

	// Prime cookies
	homeReq, _ := http.NewRequest("GET", "https://www.nseindia.com", nil)
	homeReq.Header.Set("User-Agent", "Mozilla/5.0")
	client.Do(homeReq) //nolint

	url := "https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY"
	req, _ := http.NewRequest("GET", url, nil)
	req.Header.Set("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
	req.Header.Set("Accept", "*/*")
	req.Header.Set("Referer", "https://www.nseindia.com")

	resp, err := client.Do(req)
	if err != nil {
		return &models.OIChainData{Error: err.Error()}, nil
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(resp.Body)

	var raw struct {
		Records struct {
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
		} `json:"records"`
	}

	if err := json.Unmarshal(body, &raw); err != nil {
		return &models.OIChainData{Error: fmt.Sprintf("parse: %v", err)}, nil
	}

	result := &models.OIChainData{}
	for _, d := range raw.Records.Data {
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

	oiCache.Set("oi", result, oiCacheTTL)
	return result, nil
}
