package services

import (
	"encoding/csv"
	"fmt"
	"log"
	"math"
	"os"
	"strconv"
	"sync"
	"time"

	"spectre/models"
)

// Simulator Mode — sandboxed shadow position tracker.
// Every BUY CE/BUY PE signal opens a virtual position; the tracker checks
// target/SL/timeout/flip every cron tick and writes to executed_trades.csv.
//
// Isolated by design: never modifies signal generation, conviction filter,
// or any UI display path. Only reads signals + writes its own CSVs.

const (
	executedTradesCSVName = "executed_trades.csv"
	defaultHoldMinutes    = 25
	niftyLotSize          = 65
)

type SimPosition struct {
	Date          string  `json:"date"`
	EntryTime     string  `json:"entry_time"`
	entryT        time.Time
	Strike        float64 `json:"strike"`
	OptionType    string  `json:"option_type"`
	Signal        string  `json:"signal"` // BUY CE / BUY PE
	Confidence    float64 `json:"confidence"`
	EntrySpot     float64 `json:"entry_spot"`
	EntryPremium  float64 `json:"entry_premium"`
	TargetNifty   float64 `json:"target_nifty"`
	SLNifty       float64 `json:"sl_nifty"`
	EstHoldMin    float64 `json:"est_hold_min"`
	RollingSig    string  `json:"rolling_sig"`
	DirectionSig  string  `json:"direction_sig"`
	CrossAssetSig string  `json:"cross_asset_sig"`

	// Live fields
	CurrentSpot    float64 `json:"current_spot"`
	CurrentPremium float64 `json:"current_premium"`
	UnrealizedPct  float64 `json:"unrealized_pct"`

	// Closed fields
	ExitTime      string  `json:"exit_time,omitempty"`
	ExitSpot      float64 `json:"exit_spot,omitempty"`
	ExitPremium   float64 `json:"exit_premium,omitempty"`
	ExitReason    string  `json:"exit_reason,omitempty"`
	HoldMin       float64 `json:"hold_min,omitempty"`
	PnLSpotPct    float64 `json:"pnl_spot_pct,omitempty"`
	PnLPremiumPct float64 `json:"pnl_premium_pct,omitempty"`
	PnLRupees     float64 `json:"pnl_rupees,omitempty"`
}

var (
	simMu        sync.Mutex
	openPositions = map[string]*SimPosition{} // key: "STRIKE|TYPE"
	closedToday   []*SimPosition
	lastSimDay    string
)

func executedTradesCSVPath() string { return DataPath(executedTradesCSVName) }

func resetSimIfNewDay(now time.Time) {
	day := now.Format("2006-01-02")
	if day != lastSimDay {
		openPositions = map[string]*SimPosition{}
		closedToday = nil
		lastSimDay = day
	}
}

// SimOnSignal is called after each cron-generated signal. Opens a new virtual
// position if the signal is actionable and we don't already hold one of the
// same direction. Closes the old position with reason FLIP if signal flips.
func SimOnSignal(now time.Time, s *models.TradeSignal, oi *models.OIChainData) {
	if s == nil || s.RawSignal == "NO TRADE" || s.OptionType == "-" || s.Strike == 0 {
		return
	}
	simMu.Lock()
	defer simMu.Unlock()
	resetSimIfNewDay(now)

	key := fmt.Sprintf("%.0f|%s", s.Strike, s.OptionType)

	// Already have this exact position open
	if _, exists := openPositions[key]; exists {
		return
	}

	// Flip check: close any open position of the OPPOSITE type before opening new
	for k, p := range openPositions {
		if p.OptionType != s.OptionType {
			closePosition(now, p, p.CurrentSpot, p.CurrentPremium, "FLIP")
			delete(openPositions, k)
		}
	}

	premium := 0.0
	if s.OptionLTP != nil {
		premium = *s.OptionLTP
	}
	if premium == 0 {
		premium = lookupOptionLTP(oi, s.Strike, s.OptionType)
	}

	estHold := defaultHoldMinutes
	if s.ValidUntil != "" {
		// ValidUntil is "03:04 PM" — parse and diff
		if vu, err := time.ParseInLocation("03:04 PM", s.ValidUntil, now.Location()); err == nil {
			today := time.Date(now.Year(), now.Month(), now.Day(), vu.Hour(), vu.Minute(), 0, 0, now.Location())
			if today.After(now) {
				estHold = int(today.Sub(now).Minutes())
			}
		}
	}

	pos := &SimPosition{
		Date:          now.Format("2006-01-02"),
		EntryTime:     now.Format("15:04:05"),
		entryT:        now,
		Strike:        s.Strike,
		OptionType:    s.OptionType,
		Signal:        s.RawSignal,
		Confidence:    s.Confidence,
		EntrySpot:     s.NiftySpot,
		EntryPremium:  premium,
		TargetNifty:   s.TargetNifty,
		SLNifty:       s.SLNifty,
		EstHoldMin:    float64(estHold),
		RollingSig:    s.Models.Rolling.Signal,
		DirectionSig:  s.Models.Direction.Signal,
		CrossAssetSig: s.Models.CrossAsset.Signal,
		CurrentSpot:   s.NiftySpot,
		CurrentPremium: premium,
	}
	openPositions[key] = pos
	appendTradeRow(pos, "OPEN")
}

// SimTick is called every cron tick to update prices and check exit conditions.
func SimTick(now time.Time, oi *models.OIChainData, currentSpot float64) {
	simMu.Lock()
	defer simMu.Unlock()
	resetSimIfNewDay(now)

	if currentSpot == 0 {
		return
	}

	// EOD close at 15:30 IST
	hourMin := fmt.Sprintf("%02d:%02d", now.Hour(), now.Minute())
	isEOD := hourMin >= "15:30"

	for k, p := range openPositions {
		ltp := lookupOptionLTP(oi, p.Strike, p.OptionType)
		if ltp == 0 {
			ltp = p.CurrentPremium
		}
		p.CurrentSpot = currentSpot
		p.CurrentPremium = ltp
		if p.EntryPremium > 0 {
			p.UnrealizedPct = (ltp - p.EntryPremium) / p.EntryPremium * 100
		}

		if isEOD {
			closePosition(now, p, currentSpot, ltp, "EOD")
			delete(openPositions, k)
			continue
		}

		// Target/SL check (Nifty-spot based, matching how TargetNifty/SLNifty are set)
		hitTarget := false
		hitSL := false
		if p.OptionType == "CE" {
			hitTarget = currentSpot >= p.TargetNifty
			hitSL = currentSpot <= p.SLNifty
		} else if p.OptionType == "PE" {
			hitTarget = currentSpot <= p.TargetNifty
			hitSL = currentSpot >= p.SLNifty
		}

		switch {
		case hitTarget:
			closePosition(now, p, currentSpot, ltp, "TARGET")
			delete(openPositions, k)
		case hitSL:
			closePosition(now, p, currentSpot, ltp, "SL")
			delete(openPositions, k)
		case now.Sub(p.entryT).Minutes() >= p.EstHoldMin:
			closePosition(now, p, currentSpot, ltp, "TIMEOUT")
			delete(openPositions, k)
		}
	}
}

func closePosition(now time.Time, p *SimPosition, exitSpot, exitPremium float64, reason string) {
	p.ExitTime = now.Format("15:04:05")
	p.ExitSpot = exitSpot
	p.ExitPremium = exitPremium
	p.ExitReason = reason
	p.HoldMin = math.Round(now.Sub(p.entryT).Minutes()*10) / 10

	if p.OptionType == "CE" {
		p.PnLSpotPct = (exitSpot - p.EntrySpot) / p.EntrySpot * 100
	} else {
		p.PnLSpotPct = (p.EntrySpot - exitSpot) / p.EntrySpot * 100
	}
	if p.EntryPremium > 0 {
		p.PnLPremiumPct = (exitPremium - p.EntryPremium) / p.EntryPremium * 100
		p.PnLRupees = (exitPremium - p.EntryPremium) * niftyLotSize
	}
	closedToday = append(closedToday, p)
	appendTradeRow(p, "EXIT")
}

func lookupOptionLTP(oi *models.OIChainData, strike float64, optType string) float64 {
	if oi == nil {
		return 0
	}
	for _, s := range oi.Strikes {
		if s.Strike != strike {
			continue
		}
		if optType == "CE" {
			return s.CELTP
		}
		return s.PELTP
	}
	return 0
}

func appendTradeRow(p *SimPosition, kind string) {
	path := executedTradesCSVPath()
	file, err := os.OpenFile(path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
	if err != nil {
		log.Printf("[sim] open csv: %v", err)
		return
	}
	defer file.Close()

	w := csv.NewWriter(file)
	defer w.Flush()

	info, _ := file.Stat()
	if info.Size() == 0 {
		w.Write([]string{
			"Kind", "Date", "EntryTime", "Strike", "OptionType", "Signal", "Confidence",
			"EntrySpot", "EntryPremium", "TargetNifty", "SLNifty", "EstHoldMin",
			"ExitTime", "ExitSpot", "ExitPremium", "ExitReason", "HoldMin",
			"PnLSpotPct", "PnLPremiumPct", "PnLRupees",
			"RollingSig", "DirectionSig", "CrossAssetSig",
		})
	}

	w.Write([]string{
		kind, p.Date, p.EntryTime,
		strconv.FormatFloat(p.Strike, 'f', 0, 64),
		p.OptionType, p.Signal,
		fmt.Sprintf("%.1f", p.Confidence),
		fmt.Sprintf("%.2f", p.EntrySpot),
		fmt.Sprintf("%.2f", p.EntryPremium),
		fmt.Sprintf("%.1f", p.TargetNifty),
		fmt.Sprintf("%.1f", p.SLNifty),
		fmt.Sprintf("%.1f", p.EstHoldMin),
		p.ExitTime,
		fmt.Sprintf("%.2f", p.ExitSpot),
		fmt.Sprintf("%.2f", p.ExitPremium),
		p.ExitReason,
		fmt.Sprintf("%.1f", p.HoldMin),
		fmt.Sprintf("%.2f", p.PnLSpotPct),
		fmt.Sprintf("%.2f", p.PnLPremiumPct),
		fmt.Sprintf("%.0f", p.PnLRupees),
		p.RollingSig, p.DirectionSig, p.CrossAssetSig,
	})
}

// GetSimState returns a snapshot of open + closed positions for the current day.
func GetSimState() ([]SimPosition, []SimPosition) {
	simMu.Lock()
	defer simMu.Unlock()
	open := make([]SimPosition, 0, len(openPositions))
	for _, p := range openPositions {
		open = append(open, *p)
	}
	closed := make([]SimPosition, 0, len(closedToday))
	for _, p := range closedToday {
		closed = append(closed, *p)
	}
	return open, closed
}
