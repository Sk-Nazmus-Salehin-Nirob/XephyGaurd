package main

import (
	"context"
	"encoding/binary"
	"encoding/json"
	"net/http"
	"sync"
	"sync/atomic"

	"github.com/coder/websocket"
)

const (
	kMagic           = uint16(0x5847)
	kVersion         = uint8(1)
	kHeaderSize      = 28
	kMaxViewers      = 2
	kViewerQueueSize = 8
	kMsgTypeFrame    = uint8(1)
	kMsgTypeKeyReq   = uint8(4)
	kMsgTypeStatus   = uint8(5)
)

type Viewer struct {
	id                uint64
	mode              string       // lease mode: live, snapshot or wall
	leaseExp          atomic.Int64 // lease end (unix nanoseconds); extended by an in-band renewal
	ch                chan []byte
	ctrlCh            chan []byte
	conn              *websocket.Conn
	closed            atomic.Bool
	sentOfflineNotice atomic.Bool
}

type Stream struct {
	streamID     uint32
	agentConn    *websocket.Conn
	agentID      string
	agentOut     chan []byte
	mu           sync.Mutex
	viewers      map[uint64]*Viewer
	nextViewerID uint64
	lastKeyframe []byte
	ctx          context.Context
	cancel       context.CancelFunc
}

func newStream(streamID uint32) *Stream {
	ctx, cancel := context.WithCancel(context.Background())
	return &Stream{
		streamID: streamID,
		agentOut: make(chan []byte, 32),
		viewers:  make(map[uint64]*Viewer),
		ctx:      ctx,
		cancel:   cancel,
	}
}

type RelayServer struct {
	auth    Authenticator
	mu      sync.RWMutex
	streams map[uint32]*Stream
}

func NewRelayServer(auth Authenticator) *RelayServer {
	return &RelayServer{
		auth:    auth,
		streams: make(map[uint32]*Stream),
	}
}

func (s *RelayServer) getOrCreateStream(streamID uint32) *Stream {
	s.mu.Lock()
	defer s.mu.Unlock()
	st, exists := s.streams[streamID]
	if !exists {
		st = newStream(streamID)
		s.streams[streamID] = st
	}
	return st
}

func (s *RelayServer) findStreamForViewer(preferredID uint32) *Stream {
	s.mu.Lock()
	defer s.mu.Unlock()

	// Get or create the specific stream for this PC/student
	st, exists := s.streams[preferredID]
	if !exists {
		st = newStream(preferredID)
		s.streams[preferredID] = st
	}
	return st
}

func (s *RelayServer) removeStream(streamID uint32) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if st, exists := s.streams[streamID]; exists {
		st.cancel()
		delete(s.streams, streamID)
	}
}

// Build a binary KeyframeReq message according to protocol.h
func buildKeyframeReq(streamID uint32, monitorID uint16) []byte {
	buf := make([]byte, kHeaderSize)
	binary.LittleEndian.PutUint16(buf[0:2], kMagic)
	buf[2] = kVersion
	buf[3] = kMsgTypeKeyReq
	binary.LittleEndian.PutUint16(buf[4:6], 0)
	binary.LittleEndian.PutUint16(buf[6:8], monitorID)
	binary.LittleEndian.PutUint32(buf[8:12], streamID)
	return buf
}

// Build a binary Status message reporting active viewer count to the agent.
func buildViewerStatus(streamID uint32, viewers uint16) []byte {
	buf := make([]byte, kHeaderSize)
	binary.LittleEndian.PutUint16(buf[0:2], kMagic)
	buf[2] = kVersion
	buf[3] = kMsgTypeStatus
	binary.LittleEndian.PutUint16(buf[4:6], viewers)
	binary.LittleEndian.PutUint16(buf[6:8], 0)
	binary.LittleEndian.PutUint32(buf[8:12], streamID)
	binary.LittleEndian.PutUint16(buf[20:22], viewers)
	return buf
}

func (s *RelayServer) broadcastStatusLocked(stream *Stream, connected bool) {
	if len(stream.viewers) == 0 {
		return
	}
	payload, err := json.Marshal(struct {
		Type           string `json:"type"`
		AgentConnected bool   `json:"agent_connected"`
		StreamID       uint32 `json:"stream_id"`
	}{
		Type:           "status",
		AgentConnected: connected,
		StreamID:       stream.streamID,
	})
	if err != nil {
		return
	}
	for _, v := range stream.viewers {
		if connected {
			if !v.sentOfflineNotice.Swap(false) {
				continue
			}
		} else {
			v.sentOfflineNotice.Store(true)
		}
		select {
		case v.ctrlCh <- payload:
		default:
		}
	}
}

func (s *RelayServer) HandleHealth(w http.ResponseWriter, r *http.Request) {
	s.mu.RLock()
	active := 0
	for _, st := range s.streams {
		st.mu.Lock()
		if st.agentConn != nil {
			active++
		}
		st.mu.Unlock()
	}
	s.mu.RUnlock()

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_ = json.NewEncoder(w).Encode(map[string]any{
		"ok":             true,
		"active_streams": active,
	})
}

func (s *RelayServer) Routes() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("/agent", s.HandleAgent)
	mux.HandleFunc("/screen-gw/agent", s.HandleAgent)
	mux.HandleFunc("/view", s.HandleView)
	mux.HandleFunc("/screen-gw/view", s.HandleView)
	mux.HandleFunc("/health", s.HandleHealth)
	mux.HandleFunc("/screen-gw/health", s.HandleHealth)
	return mux
}

// isKeyframe reports whether msg is a frame message with the KEY flag set.
func isKeyframe(msg []byte) bool {
	return len(msg) >= kHeaderSize &&
		binary.LittleEndian.Uint16(msg[0:2]) == kMagic &&
		msg[3] == kMsgTypeFrame &&
		binary.LittleEndian.Uint16(msg[4:6])&1 != 0
}
