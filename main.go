package main

import (
"log"

"spectre/api"
"spectre/config"
"spectre/services"
)

func main() {
log.Printf("Spectre Go starting on %s", config.Port)
services.StartSystemCron()
r := api.NewRouter()
	if err := r.Run(config.Port); err != nil {
		log.Fatalf("server error: %v", err)
	}
}
