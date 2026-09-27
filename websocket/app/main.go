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
	roleBrowser         = "browser"
	rolePython          = "python"
	roleUnity           = "unity"
	maxJPEGSize         = 200 * 1024
	pairingTTL          = 15 * time.Minute
	maxSessionAge       = 4 * time.Hour
	disconnectTTL       = 5 * time.Minute
	writeWait           = 5 * time.Second
	pongWait            = 70 * time.Second
	pingPeriod          = 25 * time.Second
	minFrameInterval    = 100 * time.Millisecond
	maxPairingPerMinute = 10
)

type GestureData struct {
	Type      string    `json:"type"`
	Angles    []float64 `json:"angles"`
	Timestamp float64   `json:"timestamp"`
	Sequence  uint64    `json:"sequence"`
}

type sourceMessage struct {
	Type   string `json:"type"`
	Source string `json:"source"`
}

type outboundMessage struct {
	messageType int
	payload     []byte
}

type client struct {
	conn *websocket.Conn
	send chan outboundMessage
}

type session struct {
	ID             string
	Code           string
	CreatedAt      time.Time
	PairingExpires time.Time
	LastAction     time.Time
	Tokens         map[string]string
	Paired         map[string]bool
	Clients        map[string]*client
	Source         string
	LastSequence   uint64
}

type SessionManager struct {
	mu       sync.RWMutex
	sessions map[string]*session
	tokens   map[string]*session
	codes    map[string]*session
}

func newSessionManager() *SessionManager {
	return &SessionManager{
		sessions: make(map[string]*session),
		tokens:   make(map[string]*session),
		codes:    make(map[string]*session),
	}
}

func (sm *SessionManager) createSession(now time.Time) (*session, string, error) {
	sm.mu.Lock()
	defer sm.mu.Unlock()

	if len(sm.sessions) >= 100 {
		return nil, "", errors.New("maximum number of sessions reached")
	}

	code, err := sm.uniqueCodeLocked()
	if err != nil {
		return nil, "", err
	}

	id, err := randomToken(18)
	if err != nil {
		return nil, "", err
	}

	browserToken, err := randomToken(32)
	if err != nil {
		return nil, "", err
	}

	session := &session{
		ID:             id,
		Code:           code,
		CreatedAt:      now,
		PairingExpires: now.Add(pairingTTL),
		LastAction:     now,
		Tokens: map[string]string{
			roleBrowser: browserToken,
		},
		Paired: map[string]bool{
			roleBrowser: true,
		},
		Clients: make(map[string]*client),
	}
	sm.sessions[id] = session
	sm.codes[code] = session
	sm.tokens[browserToken] = session
	return session, browserToken, nil
}

func (sm *SessionManager) pairSession(code, role string, now time.Time) (*session, string, error) {
	sm.mu.Lock()
	defer sm.mu.Unlock()

	if role != rolePython && role != roleUnity {
		return nil, "", errors.New("Invalid role")
	}

	session := sm.codes[normalizeCode(code)]
	if session == nil || now.After(session.PairingExpires) {
		return nil, "", errors.New("Invalid or expired code")
	}

	if session.Paired[role] {
		return nil, "", errors.New("Role already paired")
	}

	token, err := randomToken(32)
	if err != nil {
		return nil, "", err
	}

	session.Paired[role] = true
	session.Tokens[role] = token
	session.LastAction = now
	sm.tokens[token] = session
	return session, token, nil
}

func (sm *SessionManager) sessionForToken(token, role string) *session {
	sm.mu.RLock()
	defer sm.mu.RUnlock()

	session := sm.tokens[token]
	if session == nil || session.Tokens[role] != token {
		return nil
	}
	return session
}

func (sm *SessionManager) registerClient(session *session, role string, client *client) *client {
	sm.mu.Lock()
	defer sm.mu.Unlock()

	previousClient := session.Clients[role]
	session.Clients[role] = client
	session.LastAction = time.Now()
	return previousClient
}

func (sm *SessionManager) unregisterClient(session *session, role string, client *client) {
	sm.mu.Lock()
	defer sm.mu.Unlock()

	if session.Clients[role] == client {
		delete(session.Clients, role)
		session.LastAction = time.Now()
	}
}

func (sm *SessionManager) route(session *session, role string, message outboundMessage, latest bool) bool {
	sm.mu.RLock()
	defer sm.mu.RUnlock()

	target := session.Clients[role]

	if target == nil {
		return false
	}
	if latest {
		select {
		case target.send <- message:
			return true
		default:
		}
		select {
		case <-target.send:
		default:
		}
	}
	select {
	case target.send <- message:
		return true
	default:
		return false
	}
}

func (sm *SessionManager) status(session *session) []byte {
	sm.mu.RLock()
	defer sm.mu.RUnlock()

	payload, _ := json.Marshal(map[string]any{
		"type":   "status",
		"python": session.Clients[rolePython] != nil,
		"unity":  session.Clients[roleUnity] != nil,
		"source": session.Source,
	})
	return payload
}

func (sm *SessionManager) setSource(session *session, source string) {
	sm.mu.Lock()
	defer sm.mu.Unlock()

	session.Source = source
	session.LastAction = time.Now()
}

func (sm *SessionManager) acceptSequence(session *session, sequence uint64) bool {
	sm.mu.Lock()
	defer sm.mu.Unlock()

	if sequence <= session.LastSequence {
		return false
	}

	session.LastSequence = sequence
	session.LastAction = time.Now()
	return true
}

func (sm *SessionManager) cleanup(now time.Time) {
	sm.mu.Lock()
	defer sm.mu.Unlock()

	for id, session := range sm.sessions {
		noClients := len(session.Clients) == 0

		if now.Sub(session.CreatedAt) < maxSessionAge && (!noClients || now.Sub(session.LastAction) < disconnectTTL) {
			continue
		}

		for _, token := range session.Tokens {
			delete(sm.tokens, token)
		}

		delete(sm.codes, session.Code)
		delete(sm.sessions, id)
	}
}

func (sm *SessionManager) uniqueCodeLocked() (string, error) {
	const alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ0123456789"

	for attempt := 0; attempt < 10; attempt++ {
		bytes := make([]byte, 8)

		if _, err := rand.Read(bytes); err != nil {
			return "", err
		}

		for index := range bytes {
			bytes[index] = alphabet[int(bytes[index])%len(alphabet)]
		}

		code := string(bytes[:4]) + "-" + string(bytes[4:])

		if sm.codes[code] == nil {
			return code, nil
		}
	}
	return "", errors.New("failed to generate unique code")
}

func normalizeCode(code string) string {
	clean := strings.ToUpper(strings.ReplaceAll(strings.TrimSpace(code), "-", ""))

	if len(clean) == 8 {
		return clean[:4] + "-" + clean[4:]
	}

	return strings.ToUpper(strings.TrimSpace(code))
}

func randomToken(size int) (string, error) {
	buffer := make([]byte, size)

	if _, err := rand.Read(buffer); err != nil {
		return "", err
	}

	return base64.RawURLEncoding.EncodeToString(buffer), nil
}

type rateEntry struct {
	window time.Time
	count  int
}

type Server struct {
	manager  *SessionManager
	upgrader websocket.Upgrader
	rateMu   sync.Mutex
	pairRate map[string]rateEntry
}

func newServer() *Server {
	allowedOrigin := os.Getenv("ALLOWED_ORIGINS")

	return &Server{
		manager: newSessionManager(),
		upgrader: websocket.Upgrader{
			CheckOrigin: func(r *http.Request) bool {
				origin := r.Header.Get("Origin")
				return allowedOrigin == "" || origin == "" || origin == allowedOrigin
			},
		},
		pairRate: make(map[string]rateEntry),
	}
}

func (s *Server) routes() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("/api/sessions", s.handleSessions)
	mux.HandleFunc("/api/sessions/pair", s.handlePair)
	mux.HandleFunc("/ws/browser", func(w http.ResponseWriter, r *http.Request) { s.handleWebSocket(roleBrowser, w, r) })
	mux.HandleFunc("/ws/python", func(w http.ResponseWriter, r *http.Request) { s.handleWebSocket(rolePython, w, r) })
	mux.HandleFunc("/ws/unity", func(w http.ResponseWriter, r *http.Request) { s.handleWebSocket(roleUnity, w, r) })
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, _ *http.Request) { w.WriteHeader(http.StatusNoContent) })
	return cors(mux)
}

func cors(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		allowedOrigin := os.Getenv("ALLOWED_ORIGINS")
		if allowedOrigin == "" {
			allowedOrigin = "*"
		}
		w.Header().Set("Access-Control-Allow-Origin", allowedOrigin)
		w.Header().Set("Access-Control-Allow-Headers", "Content-Type")
		w.Header().Set("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
		if r.Method == http.MethodOptions {
			w.WriteHeader(http.StatusNoContent)
			return
		}
		next.ServeHTTP(w, r)
	})
}

func (s *Server) handleSessions(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusMethodNotAllowed, "method_not_allowed")
		return
	}

	session, token, err := s.manager.createSession(time.Now())

	if err != nil {
		writeError(w, http.StatusServiceUnavailable, err.Error())
		return
	}

	writeJSON(w, http.StatusCreated, map[string]any{
		"code":         session.Code,
		"browserToken": token,
		"expiresAt":    session.PairingExpires.UTC().Format(time.RFC3339),
	})
}

func (s *Server) handlePair(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusMethodNotAllowed, "method_not_allowed")
		return
	}

	if !s.allowPair(r) {
		writeError(w, http.StatusTooManyRequests, "rate_limit_exceeded")
		return
	}

	var request struct {
		Code string `json:"code"`
		Role string `json:"role"`
	}

	decoder := json.NewDecoder(http.MaxBytesReader(w, r.Body, 4096))

	if err := decoder.Decode(&request); err != nil {
		writeError(w, http.StatusBadRequest, "invalid_json")
		return
	}
	_, token, err := s.manager.pairSession(request.Code, request.Role, time.Now())

	if err != nil {
		status := http.StatusBadRequest

		if err.Error() == "Role already paired" {
			status = http.StatusConflict
		}
		writeError(w, status, err.Error())
		return
	}

	writeJSON(w, http.StatusOK, map[string]string{
		"token":         token,
		"websocketPath": "/ws/" + request.Role,
	})
}

func (s *Server) allowPair(r *http.Request) bool {
	host, _, err := net.SplitHostPort(r.RemoteAddr)

	if err != nil {
		host = r.RemoteAddr
	}

	now := time.Now()

	s.rateMu.Lock()
	defer s.rateMu.Unlock()

	entry := s.pairRate[host]

	if now.Sub(entry.window) >= time.Minute {
		entry = rateEntry{window: now}
	}

	entry.count++
	s.pairRate[host] = entry
	return entry.count <= maxPairingPerMinute
}

func (s *Server) handleWebSocket(role string, w http.ResponseWriter, r *http.Request) {

	token := r.URL.Query().Get("token")
	session := s.manager.sessionForToken(token, role)

	if session == nil {
		writeError(w, http.StatusUnauthorized, "invalid_token")
		return
	}

	conn, err := s.upgrader.Upgrade(w, r, nil)

	if err != nil {
		return
	}
	queueSize := 8

	if role == rolePython {
		queueSize = 1
	}

	c := &client{conn: conn, send: make(chan outboundMessage, queueSize)}
	previous := s.manager.registerClient(session, role, c)

	if previous != nil {
		_ = previous.conn.Close()
	}

	defer func() {
		s.manager.unregisterClient(session, role, c)
		_ = conn.Close()
		s.sendStatus(session)
	}()

	conn.SetReadLimit(maxJPEGSize + 1024)
	_ = conn.SetReadDeadline(time.Now().Add(pongWait))
	conn.SetPongHandler(func(string) error {
		return conn.SetReadDeadline(time.Now().Add(pongWait))
	})
	go s.writePump(c)
	s.sendStatus(session)

	var lastFrame time.Time

	for {
		messageType, payload, err := conn.ReadMessage()

		if err != nil {
			return
		}

		switch role {
		case roleBrowser:

			if messageType != websocket.BinaryMessage || len(payload) > maxJPEGSize || !isJPEG(payload) {
				continue
			}

			now := time.Now()

			if now.Sub(lastFrame) < minFrameInterval {
				continue
			}
			lastFrame = now
			s.manager.route(session, rolePython, outboundMessage{websocket.BinaryMessage, payload}, true)
		case rolePython:

			if messageType != websocket.TextMessage {
				continue
			}
			s.handlePythonMessage(session, payload)
		}
	}
}

func isJPEG(data []byte) bool {
	return len(data) >= 4 && data[0] == 0xff && data[1] == 0xd8 && data[len(data)-2] == 0xff && data[len(data)-1] == 0xd9
}

func (s *Server) handlePythonMessage(session *session, data []byte) {
	var envelope struct {
		Type string `json:"type"`
	}

	if json.Unmarshal(data, &envelope) != nil {
		return
	}

	switch envelope.Type {
	case "source":
		var msg sourceMessage

		if json.Unmarshal(data, &msg) != nil || (msg.Source != "remote_camera" && msg.Source != "local_camera") {
			return
		}

		s.manager.setSource(session, msg.Source)
		s.manager.route(session, roleBrowser, outboundMessage{websocket.TextMessage, s.manager.status(session)}, false)
	case "angles":
		var gesture GestureData

		if json.Unmarshal(data, &gesture) != nil || !validateAngles(gesture.Angles) || !s.manager.acceptSequence(session, gesture.Sequence) {
			return
		}

		clean, _ := json.Marshal(gesture)
		s.manager.route(session, roleUnity, outboundMessage{websocket.TextMessage, clean}, true)
	}
}

func (s *Server) writePump(c *client) {
	ticker := time.NewTicker(pingPeriod)
	defer ticker.Stop()

	for {
		select {
		case message := <-c.send:
			_ = c.conn.SetWriteDeadline(time.Now().Add(writeWait))

			if err := c.conn.WriteMessage(message.messageType, message.payload); err != nil {
				return
			}
		case <-ticker.C:
			_ = c.conn.SetWriteDeadline(time.Now().Add(writeWait))

			if err := c.conn.WriteMessage(websocket.PingMessage, nil); err != nil {
				return
			}
		}
	}
}

func (s *Server) sendStatus(session *session) {
	s.manager.route(session, roleBrowser, outboundMessage{websocket.TextMessage, s.manager.status(session)}, true)
}

func validateAngles(angles []float64) bool {
	if len(angles) != 6 {
		return false
	}

	for _, angle := range angles {
		if angle < 0 || angle > 180 {
			return false
		}
	}

	return true
}

func writeJSON(w http.ResponseWriter, status int, payload any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(payload)
}

func writeError(w http.ResponseWriter, status int, code string) {
	writeJSON(w, status, map[string]string{"error": code})
}

func main() {
	server := newServer()
	go func() {
		ticker := time.NewTicker(time.Minute)
		defer ticker.Stop()

		for now := range ticker.C {
			server.manager.cleanup(now)
		}
	}()

	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}

	address := ":" + port
	fmt.Printf("Server is running on %s\n", address)

	if err := http.ListenAndServe(address, server.routes()); err != nil {
		log.Fatalf("Failed to start server: %v", err)
	}
}
