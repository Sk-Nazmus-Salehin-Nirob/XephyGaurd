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
	streamID, err := s.auth.AuthViewer(r)
	if err != nil {
		http.Error(w, "Unauthorized viewer: "+err.Error(), http.StatusUnauthorized)
		return
	}

	stream := s.findStreamForViewer(streamID)

	stream.mu.Lock()
	hasAgent := stream.agentConn != nil
	log.Printf("[Gateway Viewer Connect] remote=%s target_stream_id=%d has_agent=%v keyframe_cached=%v",
		r.RemoteAddr, streamID, hasAgent, len(stream.lastKeyframe) > 0)
	if len(stream.viewers) >= kMaxViewers {
		stream.mu.Unlock()
		http.Error(w, "Max viewers reached (max 2)", http.StatusTooManyRequests)
		return
	}

	stream.nextViewerID++
	viewerID := stream.nextViewerID
	v := &Viewer{
		id:     viewerID,
		ch:     make(chan []byte, kViewerQueueSize),
		ctrlCh: make(chan []byte, 4),
	}
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
	v.conn = c
	defer c.Close(websocket.StatusInternalError, "viewer closed")

	ctx, cancel := context.WithCancel(r.Context())
	defer cancel()

	// Writer goroutine to viewer
	writerDone := make(chan struct{})
	go func() {
		defer close(writerDone)
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
			}
		}
	}()

	// Reader goroutine from viewer: forwards ACKs and KEYFRAME_REQs to agent
	for {
		msgType, data, err := c.Read(ctx)
		if err != nil {
			break
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
