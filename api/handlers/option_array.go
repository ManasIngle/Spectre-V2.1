package handlers

import (
	"encoding/csv"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"time"

	"github.com/gin-gonic/gin"
	"spectre/services"
)

// GetOptionArrayToday returns today's per-strike price evolution.
// Response shape:
//
//	{
//	  "date": "2026-04-27",
//	  "strikes": [
//	    {
//	      "strike": 24050, "option_type": "PE",
//	      "first_suggested_at": "10:03:48",
//	      "suggestion_confidence": 35.3,
//	      "points": [
//	        {"time":"10:03:48","ltp":78.95,"spot":24094.20,"min_since":0},
//	        {"time":"10:04:48","ltp":80.10,"spot":24091.20,"min_since":1},
//	        ...
//	      ]
//	    },
//	    ...
//	  ]
//	}
func GetOptionArrayToday(c *gin.Context) {
	ist, err := time.LoadLocation("Asia/Kolkata")
	if err != nil {
		ist = time.FixedZone("IST", 5*3600+1800)
	}
	today := time.Now().In(ist).Format("2006-01-02")

	rows, err := readOptionArrayCSV(today)
	if err != nil {
		c.JSON(http.StatusOK, gin.H{"date": today, "strikes": []interface{}{}})
		return
	}

	type pricePoint struct {
		Time     string  `json:"time"`
		LTP      float64 `json:"ltp"`
		Spot     float64 `json:"spot"`
		MinSince int     `json:"min_since"`
	}
	type strikeBlock struct {
		Strike           int          `json:"strike"`
		OptionType       string       `json:"option_type"`
		FirstSuggestedAt string       `json:"first_suggested_at"`
		Confidence       float64      `json:"suggestion_confidence"`
		Points           []pricePoint `json:"points"`
	}

	groups := map[string]*strikeBlock{}
	for _, r := range rows {
		key := r["Strike"] + "|" + r["OptionType"]
		strike, _ := strconv.Atoi(r["Strike"])
		ltp, _ := strconv.ParseFloat(r["LTP"], 64)
		spot, _ := strconv.ParseFloat(r["Spot"], 64)
		minSince, _ := strconv.Atoi(r["MinutesSinceSuggested"])
		conf, _ := strconv.ParseFloat(r["SuggestionConfidence"], 64)

		blk, ok := groups[key]
		if !ok {
			blk = &strikeBlock{
				Strike:           strike,
				OptionType:       r["OptionType"],
				FirstSuggestedAt: r["FirstSuggestedAt"],
				Confidence:       conf,
			}
			groups[key] = blk
		}
		blk.Points = append(blk.Points, pricePoint{
			Time: r["Time"], LTP: ltp, Spot: spot, MinSince: minSince,
		})
	}

	result := make([]*strikeBlock, 0, len(groups))
	for _, b := range groups {
		result = append(result, b)
	}
	// Sort by first suggested time so the UI shows the earliest-suggested first.
	sort.Slice(result, func(i, j int) bool {
		return result[i].FirstSuggestedAt < result[j].FirstSuggestedAt
	})

	c.JSON(http.StatusOK, gin.H{"date": today, "strikes": result})
}

// DownloadOptionArray streams the full historical CSV.
func DownloadOptionArray(c *gin.Context) {
	abs, err := filepath.Abs(services.OptionArrayPath())
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "path error"})
		return
	}
	c.Header("Content-Disposition", "attachment; filename=option_price_array.csv")
	c.Header("Content-Type", "text/csv")
	c.File(abs)
}

func readOptionArrayCSV(datePrefix string) ([]map[string]string, error) {
	f, err := os.Open(services.OptionArrayPath())
	if err != nil {
		return nil, err
	}
	defer f.Close()

	r := csv.NewReader(f)
	headers, err := r.Read()
	if err != nil {
		return nil, err
	}
	idx := make(map[string]int, len(headers))
	for i, h := range headers {
		idx[h] = i
	}

	get := func(row []string, col string) string {
		i, ok := idx[col]
		if !ok || i >= len(row) {
			return ""
		}
		return row[i]
	}

	var out []map[string]string
	for {
		row, err := r.Read()
		if err == io.EOF {
			break
		}
		if err != nil {
			continue
		}
		if get(row, "Date") != datePrefix {
			continue
		}
		out = append(out, map[string]string{
			"Date":                  get(row, "Date"),
			"Time":                  get(row, "Time"),
			"Strike":                get(row, "Strike"),
			"OptionType":            get(row, "OptionType"),
			"Spot":                  get(row, "Spot"),
			"LTP":                   get(row, "LTP"),
			"FirstSuggestedAt":      get(row, "FirstSuggestedAt"),
			"MinutesSinceSuggested": get(row, "MinutesSinceSuggested"),
			"SuggestionConfidence":  get(row, "SuggestionConfidence"),
		})
	}
	return out, nil
}
