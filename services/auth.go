package services

import (
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"os"
	"strconv"
	"strings"
	"sync"
	"time"

	"golang.org/x/crypto/bcrypt"
)

// Auth — multi-user with admin/user roles. Users persisted in JSON in the
// data volume; sessions are stateless HMAC-signed cookie tokens.

const (
	usersFileName  = "users.json"
	sessionTTL     = 30 * 24 * time.Hour
	bcryptCost     = 12
	roleAdmin      = "admin"
	roleUser       = "user"
	cookieName     = "spectre_session"
)

type User struct {
	Username     string `json:"username"`
	PasswordHash string `json:"password_hash"`
	Role         string `json:"role"`
	CreatedAt    string `json:"created_at,omitempty"`
}

type Session struct {
	Username  string
	Role      string
	ExpiresAt time.Time
}

var (
	usersMu     sync.RWMutex
	cachedUsers []User
	loadedOnce  bool
)

func usersFilePath() string { return DataPath(usersFileName) }

// LoadUsers reads users.json (caches in memory). Bootstraps a default admin
// from BOOTSTRAP_ADMIN_USER + BOOTSTRAP_ADMIN_PASSWORD if the file is missing.
func LoadUsers() ([]User, error) {
	usersMu.Lock()
	defer usersMu.Unlock()

	if loadedOnce {
		return cachedUsers, nil
	}

	path := usersFilePath()
	data, err := os.ReadFile(path)
	if errors.Is(err, os.ErrNotExist) {
		log.Printf("[auth] users.json not found at %s — bootstrapping", path)
		bootUser := os.Getenv("BOOTSTRAP_ADMIN_USER")
		if bootUser == "" {
			bootUser = "admin"
		}
		bootPass := os.Getenv("BOOTSTRAP_ADMIN_PASSWORD")
		if bootPass == "" {
			return nil, fmt.Errorf("users.json missing and BOOTSTRAP_ADMIN_PASSWORD not set — cannot bootstrap")
		}
		hash, err := bcrypt.GenerateFromPassword([]byte(bootPass), bcryptCost)
		if err != nil {
			return nil, fmt.Errorf("bcrypt: %w", err)
		}
		cachedUsers = []User{{
			Username:     bootUser,
			PasswordHash: string(hash),
			Role:         roleAdmin,
			CreatedAt:    time.Now().UTC().Format(time.RFC3339),
		}}
		if err := saveUsersLocked(); err != nil {
			return nil, fmt.Errorf("save bootstrap users: %w", err)
		}
		log.Printf("[auth] bootstrapped admin user: %s (delete BOOTSTRAP_ADMIN_PASSWORD env after first login)", bootUser)
		loadedOnce = true
		return cachedUsers, nil
	}
	if err != nil {
		return nil, err
	}

	if err := json.Unmarshal(data, &cachedUsers); err != nil {
		return nil, err
	}
	loadedOnce = true
	return cachedUsers, nil
}

func saveUsersLocked() error {
	tmp := usersFilePath() + ".tmp"
	data, err := json.MarshalIndent(cachedUsers, "", "  ")
	if err != nil {
		return err
	}
	if err := os.WriteFile(tmp, data, 0600); err != nil {
		return err
	}
	return os.Rename(tmp, usersFilePath())
}

// AuthenticateUser checks username+password. Returns the user on success.
func AuthenticateUser(username, password string) (*User, error) {
	users, err := LoadUsers()
	if err != nil {
		return nil, err
	}
	usersMu.RLock()
	defer usersMu.RUnlock()
	for _, u := range users {
		if u.Username == username {
			if err := bcrypt.CompareHashAndPassword([]byte(u.PasswordHash), []byte(password)); err != nil {
				return nil, errors.New("invalid credentials")
			}
			return &u, nil
		}
	}
	return nil, errors.New("invalid credentials")
}

// AddUser creates a new user. Returns error if username already exists.
func AddUser(username, password, role string) error {
	if username == "" || password == "" {
		return errors.New("username and password required")
	}
	if role != roleAdmin && role != roleUser {
		return errors.New("role must be 'admin' or 'user'")
	}
	if len(password) < 6 {
		return errors.New("password must be at least 6 characters")
	}

	if _, err := LoadUsers(); err != nil {
		return err
	}

	usersMu.Lock()
	defer usersMu.Unlock()
	for _, u := range cachedUsers {
		if u.Username == username {
			return errors.New("user already exists")
		}
	}
	hash, err := bcrypt.GenerateFromPassword([]byte(password), bcryptCost)
	if err != nil {
		return err
	}
	cachedUsers = append(cachedUsers, User{
		Username:     username,
		PasswordHash: string(hash),
		Role:         role,
		CreatedAt:    time.Now().UTC().Format(time.RFC3339),
	})
	return saveUsersLocked()
}

// DeleteUser removes a user by username. Refuses to delete the last admin.
func DeleteUser(username string) error {
	if _, err := LoadUsers(); err != nil {
		return err
	}
	usersMu.Lock()
	defer usersMu.Unlock()

	idx := -1
	adminCount := 0
	for i, u := range cachedUsers {
		if u.Role == roleAdmin {
			adminCount++
		}
		if u.Username == username {
			idx = i
		}
	}
	if idx < 0 {
		return errors.New("user not found")
	}
	if cachedUsers[idx].Role == roleAdmin && adminCount <= 1 {
		return errors.New("cannot delete the last admin")
	}
	cachedUsers = append(cachedUsers[:idx], cachedUsers[idx+1:]...)
	return saveUsersLocked()
}

// ListUsers returns all users WITHOUT password hashes (safe for API).
func ListUsers() ([]User, error) {
	users, err := LoadUsers()
	if err != nil {
		return nil, err
	}
	usersMu.RLock()
	defer usersMu.RUnlock()
	out := make([]User, len(users))
	for i, u := range users {
		out[i] = User{Username: u.Username, Role: u.Role, CreatedAt: u.CreatedAt}
	}
	return out, nil
}

// ─── Session tokens ────────────────────────────────────────────────────────

func sessionSecret() []byte {
	s := os.Getenv("SESSION_SECRET")
	if s == "" {
		// Fallback: dev-mode random secret regenerated each restart (invalidates sessions)
		buf := make([]byte, 32)
		_, _ = rand.Read(buf)
		s = hex.EncodeToString(buf)
		log.Printf("[auth] WARNING: SESSION_SECRET not set — using ephemeral secret (sessions invalidate on restart)")
		// stash so subsequent calls in this process see the same value
		os.Setenv("SESSION_SECRET", s)
	}
	return []byte(s)
}

// CreateSessionToken builds an HMAC-signed cookie value: base64(payload).hex(sig)
// payload format: "username|role|expiresUnix"
func CreateSessionToken(u *User) string {
	expires := time.Now().Add(sessionTTL).Unix()
	payload := fmt.Sprintf("%s|%s|%d", u.Username, u.Role, expires)
	mac := hmac.New(sha256.New, sessionSecret())
	mac.Write([]byte(payload))
	sig := hex.EncodeToString(mac.Sum(nil))
	return base64.URLEncoding.EncodeToString([]byte(payload)) + "." + sig
}

// ValidateSessionToken parses + verifies + checks expiry.
func ValidateSessionToken(token string) (*Session, error) {
	parts := strings.SplitN(token, ".", 2)
	if len(parts) != 2 {
		return nil, errors.New("malformed token")
	}
	payloadBytes, err := base64.URLEncoding.DecodeString(parts[0])
	if err != nil {
		return nil, errors.New("malformed token")
	}
	mac := hmac.New(sha256.New, sessionSecret())
	mac.Write(payloadBytes)
	expectedSig := hex.EncodeToString(mac.Sum(nil))
	if !hmac.Equal([]byte(parts[1]), []byte(expectedSig)) {
		return nil, errors.New("invalid signature")
	}

	pieces := strings.Split(string(payloadBytes), "|")
	if len(pieces) != 3 {
		return nil, errors.New("malformed payload")
	}
	expires, err := strconv.ParseInt(pieces[2], 10, 64)
	if err != nil {
		return nil, errors.New("malformed expiry")
	}
	if time.Now().Unix() > expires {
		return nil, errors.New("session expired")
	}
	return &Session{
		Username:  pieces[0],
		Role:      pieces[1],
		ExpiresAt: time.Unix(expires, 0),
	}, nil
}

func CookieName() string  { return cookieName }
func SessionMaxAge() int  { return int(sessionTTL.Seconds()) }
