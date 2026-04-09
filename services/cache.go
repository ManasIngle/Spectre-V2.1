package services

import (
"sync"
"time"
)

type cacheEntry struct {
data      interface{}
expiresAt time.Time
}

type TTLCache struct {
mu      sync.RWMutex
entries map[string]cacheEntry
}

func NewTTLCache() *TTLCache {
c := &TTLCache{entries: make(map[string]cacheEntry)}
	go func() {
		for range time.Tick(60 * time.Second) {
			c.mu.Lock()
			now := time.Now()
			for k, v := range c.entries {
				if now.After(v.expiresAt) {
					delete(c.entries, k)
				}
			}
			c.mu.Unlock()
		}
	}()
	return c
}

func (c *TTLCache) Set(key string, val interface{}, ttl time.Duration) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.entries[key] = cacheEntry{data: val, expiresAt: time.Now().Add(ttl)}
}

func (c *TTLCache) Delete(key string) {
	c.mu.Lock()
	defer c.mu.Unlock()
	delete(c.entries, key)
}

func (c *TTLCache) Get(key string) (interface{}, bool) {
	c.mu.RLock()
	defer c.mu.RUnlock()
	e, ok := c.entries[key]
	if !ok || time.Now().After(e.expiresAt) {
		return nil, false
	}
	return e.data, true
}
