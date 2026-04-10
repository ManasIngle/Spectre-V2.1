package handlers

import (
	"net/http"

	"github.com/gin-gonic/gin"
	"spectre/services"
)

func GetInstitutionalOutlook(c *gin.Context) {
	c.JSON(http.StatusOK, services.InstitutionalOutlook())
}
