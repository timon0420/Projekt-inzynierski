package main

import (
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"net"
	"net/http"
	"os"
	"strings"
	"sync"
	"time"
	"github.com/gorilla/websocket"
)

const (
	roleBrowser = "browser"
	rolePython  = "python"
	roleUnity   = "unity"
	maxJPEGSize = 200 * 1024
	pairingTTL = 15 * time.Minute
	maxSessionAge = 4 * time.Hour
	disconnectTTL = 5 * time.Minute
	writeWait = 5 * time.Second
	pongWait = 70 * time.Second
	pingPeriod = 25 * time.Second
	minFrameInterval = 100 * time.Millisecond
	maxPairingPerMinute = 10
)

type GestureData struct {
	Type string `json:"type"`
	Angles []float64 `json:"angles"`
	Timestamp float64 `json:"timestamp"`
	Sequence uint64 `json:"sequence"`
}

type sourceMessage struct {
	Type string `json:"type"`
	Source string `json:"source"`
}

type outboundMessage struct {
	messageType int
	payload []byte
}

type client struct {
	conn *websocket.Conn
	send chan outboundMessage
}

type session struct {
	ID string
	Code string
	CreatedAt time.Time
	PairingExpires time.Time
	LastAction time.Time
	Tokens map[string]string
	Paired map[string]bool
	Clients map[string]*client
	Source string
	LastSequence uint64
}

type SessionManager struct {
	mu sync.RWMutex
	sessions map[string]*session
	tokens map[string]*session
	codes map[string]*session
}
