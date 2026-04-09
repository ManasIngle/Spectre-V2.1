package main

import (
"log"

"spectre/api"
"spectre/config"
)

func main() {
log.Printf("Spectre Go starting on %s", config.Port)
r := api.NewRouter()
	if err := r.Run(config.Port); err != nil {
		log.Fatalf("server error: %v", err)
	}
}
