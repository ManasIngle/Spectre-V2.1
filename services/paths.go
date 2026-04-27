package services

import (
	"os"
	"path/filepath"
)

// DataDir returns the directory where persistent CSVs live.
// Set SPECTRE_DATA_DIR to override (Docker uses /app/data via a bind mount);
// defaults to "." so local `go run` keeps writing next to the binary.
func DataDir() string {
	if d := os.Getenv("SPECTRE_DATA_DIR"); d != "" {
		_ = os.MkdirAll(d, 0755)
		return d
	}
	return "."
}

// DataPath joins DataDir with the given filename.
func DataPath(filename string) string {
	return filepath.Join(DataDir(), filename)
}
