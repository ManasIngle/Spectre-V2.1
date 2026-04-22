package services

import (
	"context"
	"crypto/md5"
	"encoding/hex"
	"encoding/xml"
	"fmt"
	"net/http"
	"regexp"
	"sort"
	"strings"
	"sync"
	"time"
)

type newsFeed struct {
	Name string
	URL  string
	Icon string
}

var rssFeeds = []newsFeed{
	{"MoneyControl", "https://www.moneycontrol.com/rss/marketreports.xml", "MC"},
	{"ET Markets", "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms", "ET"},
	{"LiveMint", "https://www.livemint.com/rss/markets", "LM"},
	{"NDTV Profit", "https://feeds.feedburner.com/ndtvprofit-latest", "NP"},
}

var marketMoveKeywords = []string{
	"rbi", "rate cut", "rate hike", "monetary policy", "repo rate",
	"gdp", "inflation", "cpi", "iip", "fiscal deficit",
	"nifty", "sensex", "market crash", "rally", "correction", "bull", "bear",
	"fii", "dii", "fpi", "foreign", "institutional",
	"sebi", "ban", "circuit", "halt", "suspension",
	"results", "earnings", "quarterly", "profit", "revenue", "guidance",
	"ipo", "listing", "buyback", "dividend", "bonus", "split",
	"crude", "oil", "gold", "dollar", "rupee", "forex",
	"fed", "powell", "ecb", "boj", "global",
	"war", "sanctions", "tariff", "trade war", "geopolitical",
	"election", "budget", "tax", "gst", "policy",
	"default", "crisis", "recession", "layoff",
}

var bullishKeywords = []string{
	"rally", "surge", "soar", "gain", "jump", "rise", "bull", "boom",
	"record high", "all-time high", "breakout", "upgrade", "positive",
	"beat", "above estimate", "strong", "growth", "recovery", "rebound",
	"rate cut", "stimulus", "reform", "buy", "accumulate",
}
var bearishKeywords = []string{
	"crash", "plunge", "fall", "drop", "decline", "bear", "slump",
	"sell-off", "selloff", "correction", "downgrade", "negative",
	"miss", "below estimate", "weak", "slowdown", "recession",
	"rate hike", "tightening", "default", "crisis", "ban",
	"circuit breaker", "halt", "warning", "concern", "risk",
}

type Headline struct {
	Title        string `json:"title"`
	Description  string `json:"description"`
	Link         string `json:"link"`
	Source       string `json:"source"`
	SourceIcon   string `json:"source_icon"`
	Published    string `json:"published"`
	TimeAgo      string `json:"time_ago"`
	Sentiment    string `json:"sentiment"`
	MarketMoving bool   `json:"market_moving"`

	// Internal — not serialized
	publishedAt time.Time `json:"-"`
}

type NewsResult struct {
	Headlines        []Headline     `json:"headlines"`
	Total            int            `json:"total"`
	SourcesActive    int            `json:"sources_active"`
	SourcesTotal     int            `json:"sources_total"`
	SentimentSummary map[string]int `json:"sentiment_summary"`
}

var (
	newsCache   = NewTTLCache()
	newsClient  = &http.Client{Timeout: 12 * time.Second}
	htmlTagRE   = regexp.MustCompile(`<[^>]+>`)
	punctRE     = regexp.MustCompile(`[^\w\s]`)
	spaceRE     = regexp.MustCompile(`\s+`)
	newsCacheTTL = 120 * time.Second
)

// rssEnvelope captures both RSS 2.0 (<item>) and Atom (<entry>) shapes in one struct.
// Go's xml decoder populates whichever path matches the feed; the other stays empty.
type rssEnvelope struct {
	XMLName xml.Name     `xml:"-"`
	Items   []rssItem    `xml:"channel>item"`
	Entries []atomEntry  `xml:"entry"`
}

type rssItem struct {
	Title       string `xml:"title"`
	Description string `xml:"description"`
	Link        string `xml:"link"`
	PubDate     string `xml:"pubDate"`
}

type atomEntry struct {
	Title     string `xml:"title"`
	Summary   string `xml:"summary"`
	Published string `xml:"published"`
	Updated   string `xml:"updated"`
	Links     []struct {
		Href string `xml:"href,attr"`
	} `xml:"link"`
}

func computeSentiment(title, description string) string {
	text := strings.ToLower(title + " " + description)
	bull, bear := 0, 0
	for _, kw := range bullishKeywords {
		if strings.Contains(text, kw) {
			bull++
		}
	}
	for _, kw := range bearishKeywords {
		if strings.Contains(text, kw) {
			bear++
		}
	}
	switch {
	case bull > bear+1:
		return "bullish"
	case bear > bull+1:
		return "bearish"
	case bull > bear:
		return "mildly_bullish"
	case bear > bull:
		return "mildly_bearish"
	}
	return "neutral"
}

func isMarketRelevant(title, description string) bool {
	text := strings.ToLower(title + " " + description)
	for _, kw := range marketMoveKeywords {
		if strings.Contains(text, kw) {
			return true
		}
	}
	return false
}

var rssDateFormats = []string{
	time.RFC1123Z,
	time.RFC1123,
	"Mon, 02 Jan 2006 15:04:05 GMT",
	"Mon, 2 Jan 2006 15:04:05 -0700",
	time.RFC3339,
	"2006-01-02T15:04:05Z",
	"2006-01-02 15:04:05",
}

func parsePubDate(s string) (time.Time, bool) {
	s = strings.TrimSpace(s)
	if s == "" {
		return time.Time{}, false
	}
	for _, fmtStr := range rssDateFormats {
		if t, err := time.Parse(fmtStr, s); err == nil {
			return t, true
		}
	}
	return time.Time{}, false
}

func timeAgo(t time.Time) string {
	if t.IsZero() {
		return "Recently"
	}
	minutes := int(time.Since(t).Minutes())
	switch {
	case minutes < 1:
		return "Just now"
	case minutes < 60:
		return fmt.Sprintf("%dm ago", minutes)
	case minutes < 1440:
		return fmt.Sprintf("%dh ago", minutes/60)
	default:
		return fmt.Sprintf("%dd ago", minutes/1440)
	}
}

func dedupKey(title string) string {
	clean := punctRE.ReplaceAllString(strings.ToLower(strings.TrimSpace(title)), "")
	clean = spaceRE.ReplaceAllString(clean, " ")
	if len(clean) > 80 {
		clean = clean[:80]
	}
	sum := md5.Sum([]byte(clean))
	return hex.EncodeToString(sum[:])
}

func fetchRSS(ctx context.Context, feed newsFeed) []Headline {
	req, err := http.NewRequestWithContext(ctx, "GET", feed.URL, nil)
	if err != nil {
		return nil
	}
	req.Header.Set("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
	req.Header.Set("Accept", "application/rss+xml, application/xml, text/xml")

	resp, err := newsClient.Do(req)
	if err != nil {
		return nil
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil
	}
	body, err := readBody(resp, 2<<20)
	if err != nil {
		return nil
	}

	var env rssEnvelope
	if err := xml.Unmarshal(body, &env); err != nil {
		return nil
	}

	var out []Headline
	appendItem := func(title, desc, link, pub string) {
		title = strings.TrimSpace(title)
		if title == "" {
			return
		}
		desc = htmlTagRE.ReplaceAllString(desc, "")
		desc = strings.TrimSpace(desc)
		if len(desc) > 200 {
			desc = desc[:200]
		}
		pubAt, _ := parsePubDate(pub)
		out = append(out, Headline{
			Title:       title,
			Description: desc,
			Link:        link,
			Source:      feed.Name,
			SourceIcon:  feed.Icon,
			Published:   pub,
			TimeAgo:     timeAgo(pubAt),
			publishedAt: pubAt,
		})
	}

	limit := 20
	for i, it := range env.Items {
		if i >= limit {
			break
		}
		appendItem(it.Title, it.Description, it.Link, it.PubDate)
	}
	for i, e := range env.Entries {
		if i >= limit {
			break
		}
		link := ""
		if len(e.Links) > 0 {
			link = e.Links[0].Href
		}
		pub := e.Published
		if pub == "" {
			pub = e.Updated
		}
		appendItem(e.Title, e.Summary, link, pub)
	}
	return out
}

// FetchNews returns aggregated, deduped, sentiment-tagged headlines from all RSS feeds.
// Cached for 2 min to avoid hammering upstreams.
func FetchNews() *NewsResult {
	if v, ok := newsCache.Get("news"); ok {
		return v.(*NewsResult)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 12*time.Second)
	defer cancel()

	type feedResult struct {
		items []Headline
	}
	results := make([]feedResult, len(rssFeeds))
	var wg sync.WaitGroup
	for i, feed := range rssFeeds {
		wg.Add(1)
		go func(idx int, f newsFeed) {
			defer wg.Done()
			results[idx].items = fetchRSS(ctx, f)
		}(i, feed)
	}
	wg.Wait()

	seen := make(map[string]struct{})
	var all []Headline
	sourcesActive := 0
	for _, r := range results {
		if len(r.items) > 0 {
			sourcesActive++
		}
		for _, h := range r.items {
			key := dedupKey(h.Title)
			if _, ok := seen[key]; ok {
				continue
			}
			seen[key] = struct{}{}
			h.Sentiment = computeSentiment(h.Title, h.Description)
			h.MarketMoving = isMarketRelevant(h.Title, h.Description)
			all = append(all, h)
		}
	}

	// Sort: market-moving first, then newest first (zero-time entries sink to bottom).
	sort.SliceStable(all, func(i, j int) bool {
		if all[i].MarketMoving != all[j].MarketMoving {
			return all[i].MarketMoving
		}
		ti, tj := all[i].publishedAt, all[j].publishedAt
		if ti.IsZero() && !tj.IsZero() {
			return false
		}
		if !ti.IsZero() && tj.IsZero() {
			return true
		}
		return ti.After(tj)
	})

	summary := map[string]int{"bullish": 0, "bearish": 0, "neutral": 0}
	for _, h := range all {
		switch {
		case strings.Contains(h.Sentiment, "bullish"):
			summary["bullish"]++
		case strings.Contains(h.Sentiment, "bearish"):
			summary["bearish"]++
		case h.Sentiment == "neutral":
			summary["neutral"]++
		}
	}

	if len(all) > 50 {
		all = all[:50]
	}

	result := &NewsResult{
		Headlines:        all,
		Total:            len(all),
		SourcesActive:    sourcesActive,
		SourcesTotal:     len(rssFeeds),
		SentimentSummary: summary,
	}
	newsCache.Set("news", result, newsCacheTTL)
	return result
}
