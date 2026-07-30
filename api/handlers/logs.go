package handlers

import (
	"bufio"
	"encoding/csv"
	"encoding/json"
	"net/http"
	"os"
	"sort"
	"strconv"
	"strings"

	"github.com/gin-gonic/gin"
	"spectre/services"
)

// logSpec describes one downloadable historical log.
//
// SECURITY: this is a strict WHITELIST. Handlers resolve files only through
// this registry — never from a caller-supplied path — so path traversal is
// impossible and sensitive files that share the data directory (notably
// users.json, which holds credentials) can never be served.
type logSpec struct {
	Key       string `json:"key"`
	File      string `json:"file"`
	Kind      string `json:"kind"` // "csv" | "jsonl"
	DateField string `json:"date_field,omitempty"`
	Desc      string `json:"description"`
}

var logRegistry = []logSpec{
	{"signals", "system_signals.csv", "csv", "Date",
		"Per-minute ML signal log: 6 models + ensemble, confidence, spot, strike, PCR, and the LLM_Brief two-liner."},
	{"trades", "executed_trades.csv", "csv", "Date",
		"Simulator positions: entries/exits, premiums, exit reason, P&L."},
	{"grades", "signal_grades.csv", "csv", "Date",
		"Daily per-signal grading output."},
	{"scorecard", "model_scorecard.csv", "csv", "Date",
		"Per-model rolling scorecard."},
	{"option_array", "option_price_array.csv", "csv", "Date",
		"Per-minute option price snapshots for tracked strikes."},
	{"intraday_reads", "intraday_reads.csv", "csv", "Date",
		"Advisory LLM market reads (compact: regime, recommendation, summary)."},
	{"intraday_reads_full", "intraday_reads_full.jsonl", "jsonl", "ts",
		"Advisory LLM market reads (full structured JSON per read)."},
	{"overnight_predictions", "overnight_predictions.csv", "csv", "Date",
		"Overnight next-day predictions logged by the sidecar (if present)."},
}

func findLogSpec(key string) (logSpec, bool) {
	for _, s := range logRegistry {
		if s.Key == key {
			return s, true
		}
	}
	return logSpec{}, false
}

// ── CSV / JSONL readers ───────────────────────────────────────────────────

func readCSVAsMaps(path string) ([]string, []map[string]string, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, nil, err
	}
	defer f.Close()

	r := csv.NewReader(f)
	r.FieldsPerRecord = -1 // tolerate ragged rows from older schema versions
	recs, err := r.ReadAll()
	if err != nil {
		return nil, nil, err
	}
	if len(recs) == 0 {
		return []string{}, []map[string]string{}, nil
	}
	header := recs[0]
	rows := make([]map[string]string, 0, len(recs)-1)
	for _, rec := range recs[1:] {
		m := make(map[string]string, len(header))
		for i, h := range header {
			if i < len(rec) {
				m[h] = rec[i]
			} else {
				m[h] = ""
			}
		}
		rows = append(rows, m)
	}
	return header, rows, nil
}

func readJSONL(path string) ([]any, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()

	out := []any{}
	sc := bufio.NewScanner(f)
	sc.Buffer(make([]byte, 0, 1024*1024), 16*1024*1024)
	for sc.Scan() {
		line := strings.TrimSpace(sc.Text())
		if line == "" {
			continue
		}
		var obj any
		if err := json.Unmarshal([]byte(line), &obj); err == nil {
			out = append(out, obj)
		}
	}
	return out, sc.Err()
}

// dateOf pulls the filter field out of a row (CSV map or JSONL object).
func dateOf(row any, field string) string {
	switch v := row.(type) {
	case map[string]string:
		return v[field]
	case map[string]any:
		if s, ok := v[field].(string); ok {
			return s
		}
	}
	return ""
}

// applyFilters trims by date range then applies offset/limit.
// from/to are inclusive YYYY-MM-DD; comparison is lexicographic, which is
// correct for both YYYY-MM-DD and RFC3339 timestamps.
func applyFilters[T any](rows []T, dateField, from, to string, offset, limit int, get func(T) string) []T {
	out := rows
	if dateField != "" && (from != "" || to != "") {
		filtered := make([]T, 0, len(out))
		for _, r := range out {
			d := get(r)
			if d == "" {
				continue
			}
			if from != "" && d < from {
				continue
			}
			// `to` is inclusive: a full-day timestamp still matches its date.
			if to != "" && d > to+"￿" {
				continue
			}
			filtered = append(filtered, r)
		}
		out = filtered
	}
	if offset > 0 {
		if offset >= len(out) {
			return out[:0]
		}
		out = out[offset:]
	}
	if limit > 0 && limit < len(out) {
		out = out[:limit]
	}
	return out
}

func intQuery(c *gin.Context, name string, def int) int {
	if v := c.Query(name); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			return n
		}
	}
	return def
}

// ── Handlers ──────────────────────────────────────────────────────────────

// GetLogsManifest lists every available log with size/row/date-range metadata.
// GET /api/logs
func GetLogsManifest(c *gin.Context) {
	type entry struct {
		logSpec
		Exists   bool   `json:"exists"`
		Bytes    int64  `json:"bytes"`
		Rows     int    `json:"rows"`
		Modified string `json:"modified,omitempty"`
		First    string `json:"first,omitempty"`
		Last     string `json:"last,omitempty"`
	}

	entries := make([]entry, 0, len(logRegistry))
	for _, s := range logRegistry {
		e := entry{logSpec: s}
		path := services.DataPath(s.File)
		st, err := os.Stat(path)
		if err != nil {
			entries = append(entries, e)
			continue
		}
		e.Exists = true
		e.Bytes = st.Size()
		e.Modified = st.ModTime().UTC().Format("2006-01-02T15:04:05Z")

		if s.Kind == "csv" {
			_, rows, err := readCSVAsMaps(path)
			if err == nil {
				e.Rows = len(rows)
				if len(rows) > 0 && s.DateField != "" {
					e.First = rows[0][s.DateField]
					e.Last = rows[len(rows)-1][s.DateField]
				}
			}
		} else {
			rows, err := readJSONL(path)
			if err == nil {
				e.Rows = len(rows)
				if len(rows) > 0 && s.DateField != "" {
					e.First = dateOf(rows[0], s.DateField)
					e.Last = dateOf(rows[len(rows)-1], s.DateField)
				}
			}
		}
		entries = append(entries, e)
	}
	sort.Slice(entries, func(i, j int) bool { return entries[i].Key < entries[j].Key })
	c.JSON(http.StatusOK, gin.H{"logs": entries, "data_dir_configured": services.DataDir() != "."})
}

// GetLogFile serves one whole log.
// GET /api/logs/:key?format=json|csv&from=&to=&limit=&offset=
// Defaults to the FULL log (no limit) — the point of this endpoint.
func GetLogFile(c *gin.Context) {
	spec, ok := findLogSpec(c.Param("key"))
	if !ok {
		c.JSON(http.StatusNotFound, gin.H{"error": "unknown log key", "valid_keys": logKeys()})
		return
	}
	path := services.DataPath(spec.File)
	if _, err := os.Stat(path); err != nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "log not present yet", "key": spec.Key, "file": spec.File})
		return
	}

	from, to := c.Query("from"), c.Query("to")
	offset, limit := intQuery(c, "offset", 0), intQuery(c, "limit", 0)

	// Raw CSV passthrough — most compact for pandas.read_csv(url).
	if c.Query("format") == "csv" && spec.Kind == "csv" && from == "" && to == "" && limit == 0 && offset == 0 {
		c.Header("Content-Disposition", "inline; filename="+spec.File)
		c.File(path)
		return
	}

	if spec.Kind == "jsonl" {
		rows, err := readJSONL(path)
		if err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
			return
		}
		total := len(rows)
		rows = applyFilters(rows, spec.DateField, from, to, offset, limit,
			func(r any) string { return dateOf(r, spec.DateField) })
		c.JSON(http.StatusOK, gin.H{"key": spec.Key, "file": spec.File, "kind": spec.Kind,
			"total": total, "returned": len(rows), "rows": rows})
		return
	}

	header, rows, err := readCSVAsMaps(path)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	total := len(rows)
	rows = applyFilters(rows, spec.DateField, from, to, offset, limit,
		func(r map[string]string) string { return r[spec.DateField] })

	if c.Query("format") == "csv" {
		c.Header("Content-Type", "text/csv; charset=utf-8")
		c.Header("Content-Disposition", "inline; filename="+spec.File)
		w := csv.NewWriter(c.Writer)
		_ = w.Write(header)
		for _, r := range rows {
			rec := make([]string, len(header))
			for i, h := range header {
				rec[i] = r[h]
			}
			_ = w.Write(rec)
		}
		w.Flush()
		return
	}

	c.JSON(http.StatusOK, gin.H{"key": spec.Key, "file": spec.File, "kind": spec.Kind,
		"columns": header, "total": total, "returned": len(rows), "rows": rows})
}

// GetLogsBundle returns EVERY log in a single JSON response — the "give me
// everything for analysis" endpoint. Supports the same from/to filters.
// GET /api/logs/bundle?from=&to=
func GetLogsBundle(c *gin.Context) {
	from, to := c.Query("from"), c.Query("to")
	bundle := gin.H{}
	for _, s := range logRegistry {
		path := services.DataPath(s.File)
		if _, err := os.Stat(path); err != nil {
			bundle[s.Key] = gin.H{"available": false}
			continue
		}
		if s.Kind == "jsonl" {
			rows, err := readJSONL(path)
			if err != nil {
				bundle[s.Key] = gin.H{"available": false, "error": err.Error()}
				continue
			}
			total := len(rows)
			rows = applyFilters(rows, s.DateField, from, to, 0, 0,
				func(r any) string { return dateOf(r, s.DateField) })
			bundle[s.Key] = gin.H{"available": true, "file": s.File, "total": total,
				"returned": len(rows), "rows": rows}
			continue
		}
		header, rows, err := readCSVAsMaps(path)
		if err != nil {
			bundle[s.Key] = gin.H{"available": false, "error": err.Error()}
			continue
		}
		total := len(rows)
		rows = applyFilters(rows, s.DateField, from, to, 0, 0,
			func(r map[string]string) string { return r[s.DateField] })
		bundle[s.Key] = gin.H{"available": true, "file": s.File, "columns": header,
			"total": total, "returned": len(rows), "rows": rows}
	}
	c.JSON(http.StatusOK, gin.H{"bundle": bundle, "filters": gin.H{"from": from, "to": to}})
}

func logKeys() []string {
	ks := make([]string, 0, len(logRegistry))
	for _, s := range logRegistry {
		ks = append(ks, s.Key)
	}
	return ks
}
