package handlers

import (
	"fmt"
	"net/http"
	"sync"

	"github.com/gin-gonic/gin"

	"spectre/config"
	"spectre/models"
	"spectre/services"
)

// GetDashboard returns indicator signals for the trader watchlist.
func GetDashboard(c *gin.Context) {
interval := c.DefaultQuery("interval", "3m")
	rangeVal := "5d"
	switch interval {
	case "15m", "30m", "60m":
		rangeVal = "1mo"
	}

	type result struct {
		ticker string
		row    models.TickerRow
		err    error
	}

	tickers := config.TraderTickers
	ch := make(chan result, len(tickers))
	var wg sync.WaitGroup

	for _, t := range tickers {
		wg.Add(1)
		go func(ticker string) {
			defer wg.Done()
			bars, err := services.FetchOHLCV(ticker, interval, rangeVal, config.CacheTTLFast)
			if err != nil {
				ch <- result{ticker: ticker, err: err}
				return
			}
			if len(bars) < 50 {
				ch <- result{ticker: ticker, err: fmt.Errorf("insufficient bars: %d", len(bars))}
				return
			}
			row, err := services.ComputeSignals(bars)
			row.Script = services.DisplayName(ticker)
			ch <- result{ticker: ticker, row: row, err: err}
		}(t)
	}
	wg.Wait()
	close(ch)

	var rows []models.TickerRow
	for r := range ch {
		if r.err == nil {
			rows = append(rows, r.row)
		}
	}

	c.JSON(http.StatusOK, gin.H{"data": rows, "interval": interval})
}
