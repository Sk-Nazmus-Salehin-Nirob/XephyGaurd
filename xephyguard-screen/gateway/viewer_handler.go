package main

import (
	"context"
	"encoding/json"
	"log"
	"net/http"
	"time"

	"github.com/coder/websocket"
)

func (s *RelayServer) HandleView(w http.ResponseWriter, r *http.Request) {
	grant, err := s.auth.AuthViewer(r)
	if err != nil {
		http.Error(w, "Unauthorized viewer: "+err.Error(), http.StatusUnauthorized)
		return
	}
	if s.revoked.blocks(grant) {
		http.Error(w, "Unauthorized viewer: lease revoked", http.StatusUnauthorized)
		return
	}
	streamID := grant.StreamID

	stream := s.findStreamForViewer(streamID)

	stream.mu.Lock()
	hasAgent := stream.agentConn != nil
	log.Printf("[Gateway Viewer Connect] remote=%s target_stream_id=%d mode=%s has_agent=%v keyframe_cached=%v",
		r.RemoteAddr, streamID, grant.Mode, hasAgent, len(stream.lastKeyframe) > 0)
	if len(stream.viewers) >= kMaxViewers {
		stream.mu.Unlock()
		http.Error(w, "Max viewers reached (max 2)", http.StatusTooManyRequests)
		return
	}

	stream.nextViewerID++
	viewerID := stream.nextViewerID
	v := &Viewer{
		id:     viewerID,
		mode:   grant.Mode,
		grant:  grant,
		ch:     make(chan []byte, kViewerQueueSize),
		ctrlCh: make(chan []byte, 4),
	}
	v.leaseExp.Store(grant.Exp.UnixNano())
	stream.viewers[viewerID] = v

	// Only replay a cached keyframe and ask for a keyframe when a live agent is connected;
	// otherwise keep the 150ms offline status grace timer active.
	if hasAgent {
		if len(stream.lastKeyframe) > 0 {
			select {
			case v.ch <- stream.lastKeyframe:
			default:
			}
		}

		// Always trigger an immediate keyframe request to the live agent
		select {
		case stream.agentOut <- buildKeyframeReq(stream.streamID, 0):
		default:
		}
	}
	stream.mu.Unlock()

	c, err := websocket.Accept(w, r, &websocket.AcceptOptions{
		InsecureSkipVerify: true,
	})
	if err != nil {
		stream.mu.Lock()
		delete(stream.viewers, viewerID)
		if len(stream.viewers) == 0 && stream.agentConn != nil {
			select {
			case stream.agentOut <- buildViewerStatus(stream.streamID, 0):
			default:
			}
		}
		stream.mu.Unlock()
		return
	}
	c.SetReadLimit(16 * 1024 * 1024)
	stream.mu.Lock()
	v.conn = c // read under stream.mu by closeViewers
	stream.mu.Unlock()
	defer c.Close(websocket.StatusInternalError, "viewer closed")

	ctx, cancel := context.WithCancel(r.Context())
	defer cancel()

	// Writer goroutine to viewer
	writerDone := make(chan struct{})
	go func() {
		defer close(writerDone)
		// The socket closes when the lease ends unless the viewer renewed it in band (screen Step 5).
		leaseTimer := time.NewTimer(time.Until(time.Unix(0, v.leaseExp.Load())))
		defer leaseTimer.Stop()
		var offlineTimer <-chan time.Time
		if !hasAgent {
			t := time.NewTimer(150 * time.Millisecond)
			defer t.Stop()
			offlineTimer = t.C
		}
		for {
			select {
			case <-ctx.Done():
				return
			case <-stream.ctx.Done():
				return
			case <-leaseTimer.C:
				if left := time.Until(time.Unix(0, v.leaseExp.Load())); left > 0 {
					leaseTimer.Reset(left)
					continue
				}
				c.Close(kCloseLeaseExpired, "lease expired")
				return
			case <-offlineTimer:
				offlineTimer = nil
				stream.mu.Lock()
				stillOffline := stream.agentConn == nil
				stream.mu.Unlock()
				if stillOffline {
					if statusPayload, merr := json.Marshal(struct {
						Type           string `json:"type"`
						AgentConnected bool   `json:"agent_connected"`
						StreamID       uint32 `json:"stream_id"`
					}{Type: "status", AgentConnected: false, StreamID: stream.streamID}); merr == nil {
						v.sentOfflineNotice.Store(true)
						writeCtx, writeCancel := context.WithTimeout(ctx, 3*time.Second)
						err := c.Write(writeCtx, websocket.MessageText, statusPayload)
						writeCancel()
						if err != nil {
							return
						}
					}
				}
			case ctrlMsg, ok := <-v.ctrlCh:
				if !ok {
					return
				}
				offlineTimer = nil
				writeCtx, writeCancel := context.WithTimeout(ctx, 3*time.Second)
				err := c.Write(writeCtx, websocket.MessageText, ctrlMsg)
				writeCancel()
				if err != nil {
					return
				}
			case msg, ok := <-v.ch:
				if !ok {
					return
				}
				offlineTimer = nil
				writeCtx, writeCancel := context.WithTimeout(ctx, 3*time.Second)
				err := c.Write(writeCtx, websocket.MessageBinary, msg)
				writeCancel()
				if err != nil {
					return
				}
				// A snapshot lease gets one full picture (a keyframe), then the view ends.
				if v.mode == "snapshot" && isKeyframe(msg) {
					c.Close(websocket.StatusNormalClosure, "snapshot delivered")
					return
				}
			}
		}
	}()

	// Reader goroutine from viewer: forwards ACKs and KEYFRAME_REQs to agent
	for {
		msgType, data, err := c.Read(ctx)
		if err != nil {
			break
		}

		if msgType == websocket.MessageText {
			if !s.renewViewerLease(v, grant, data) {
				c.Close(websocket.StatusPolicyViolation, "lease renewal refused")
				break
			}
			continue
		}

		if msgType == websocket.MessageBinary && len(data) >= kHeaderSize {
			select {
			case stream.agentOut <- data:
			case <-ctx.Done():
				break
			case <-stream.ctx.Done():
				break
			default:
				// Avoid blocking viewer reader if agent queue full
			}
		}
	}

	cancel()
	<-writerDone

	stream.mu.Lock()
	delete(stream.viewers, viewerID)
	if len(stream.viewers) == 0 && stream.agentConn != nil {
		select {
		case stream.agentOut <- buildViewerStatus(stream.streamID, 0):
		default:
		}
	}
	v.closed.Store(true)
	stream.mu.Unlock()
}

// kCloseLeaseExpired is the WebSocket close code sent when a viewer lease ends without renewal.
const kCloseLeaseExpired websocket.StatusCode = 4001

// renewViewerLease handles a text message from a viewer. Only {"type":"renew","token":"<jwt>"} is
// accepted; the new token must grant the same stream, PC and mode. It extends the lease and sends
// {"type":"lease","expires_at":<unix>}. Anything else returns false (the caller closes the socket).
func (s *RelayServer) renewViewerLease(v *Viewer, orig ViewerGrant, data []byte) bool {
	var msg struct {
		Type  string `json:"type"`
		Token string `json:"token"`
	}
	if len(data) > 4096 || json.Unmarshal(data, &msg) != nil || msg.Type != "renew" {
		return false
	}
	g, err := s.auth.RenewViewer(msg.Token)
	if err != nil || g.StreamID != orig.StreamID || g.PCID != orig.PCID || g.Mode != orig.Mode ||
		g.UserID != orig.UserID || g.AuditID != orig.AuditID || s.revoked.blocks(g) {
		log.Printf("[Gateway Viewer] lease renewal refused stream_id=%d err=%v", orig.StreamID, err)
		return false
	}
	v.leaseExp.Store(g.Exp.UnixNano())
	if ack, err := json.Marshal(struct {
		Type      string `json:"type"`
		ExpiresAt int64  `json:"expires_at"`
	}{"lease", g.Exp.Unix()}); err == nil {
		select {
		case v.ctrlCh <- ack:
		default:
		}
	}
	return true
}
