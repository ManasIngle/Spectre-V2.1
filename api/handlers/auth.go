package handlers

import (
	"net/http"

	"github.com/gin-gonic/gin"
	"spectre/services"
)

type loginReq struct {
	Username string `json:"username"`
	Password string `json:"password"`
}

// Login validates credentials and sets the session cookie.
func Login(c *gin.Context) {
	var req loginReq
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid request body"})
		return
	}
	user, err := services.AuthenticateUser(req.Username, req.Password)
	if err != nil {
		c.JSON(http.StatusUnauthorized, gin.H{"error": err.Error()})
		return
	}

	token := services.CreateSessionToken(user)
	c.SetSameSite(http.SameSiteLaxMode)
	c.SetCookie(
		services.CookieName(),
		token,
		services.SessionMaxAge(),
		"/",
		"",     // current host
		false,  // secure (set to true in prod with HTTPS — Dokploy fronts with TLS)
		true,   // HttpOnly
	)
	c.JSON(http.StatusOK, gin.H{
		"authenticated": true,
		"username":      user.Username,
		"role":          user.Role,
	})
}

// Logout clears the session cookie.
func Logout(c *gin.Context) {
	c.SetSameSite(http.SameSiteLaxMode)
	c.SetCookie(services.CookieName(), "", -1, "/", "", false, true)
	c.JSON(http.StatusOK, gin.H{"authenticated": false})
}

// Me returns the current session info (or unauthenticated).
func Me(c *gin.Context) {
	token, err := c.Cookie(services.CookieName())
	if err != nil || token == "" {
		c.JSON(http.StatusOK, gin.H{"authenticated": false})
		return
	}
	sess, err := services.ValidateSessionToken(token)
	if err != nil {
		c.JSON(http.StatusOK, gin.H{"authenticated": false, "error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{
		"authenticated": true,
		"username":      sess.Username,
		"role":          sess.Role,
	})
}

// ListUsers — admin only
func ListUsers(c *gin.Context) {
	users, err := services.ListUsers()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"users": users})
}

type createUserReq struct {
	Username string `json:"username"`
	Password string `json:"password"`
	Role     string `json:"role"`
}

// CreateUser — admin only
func CreateUser(c *gin.Context) {
	var req createUserReq
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid request body"})
		return
	}
	if req.Role == "" {
		req.Role = "user"
	}
	if err := services.AddUser(req.Username, req.Password, req.Role); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusCreated, gin.H{"username": req.Username, "role": req.Role})
}

// DeleteUser — admin only
func DeleteUser(c *gin.Context) {
	username := c.Param("username")
	if err := services.DeleteUser(username); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"deleted": username})
}
