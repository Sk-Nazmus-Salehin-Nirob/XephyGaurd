package main

import (
	"context"
	"encoding/binary"
	"log"
	"net/http"
	"strconv"
	"time"

	"github.com/coder/websocket"
)

func (s *RelayServer) HandleAgent(w http.ResponseWriter, r *http.Request) {
	agentID, err := s.auth.AuthAgent(r)
	if err != nil {
		log.Printf("[Gateway Agent Rejected] remote=%s path=%s err=%v", r.RemoteAddr, r.URL.Path, err)
		http.Error(w, "Unauthorized agent: "+err.Error(), http.StatusUnauthorized)
		return
	}

	streamIDVal := uint32(0)
	if sidStr := r.URL.Query().Get("stream_id"); sidStr != "" {
		if parsed, err := strconv.ParseUint(sidStr, 10, 32); err == nil {
			streamIDVal = uint32(parsed)
		}
	}

	c, err := websocket.Accept(w, r, &websocket.AcceptOptions{
		InsecureSkipVerify: true,
	})
	if err != nil {
		return
	}
	c.SetReadLimit(16 * 1024 * 1024)
	defer c.Close(websocket.StatusInternalError, "agent closed")

	log.Printf("[Gateway Agent Connected] remote=%s path=%s stream_id_param=%d", r.RemoteAddr, r.URL.Path, streamIDVal)

	var stream *Stream
	if streamIDVal != 0 {
		stream = s.getOrCreateStream(streamIDVal)
		stream.mu.Lock()
		if stream.agentConn != c {
			stream.lastKeyframe = nil
		}
		stream.agentConn = c
		stream.agentID = agentID
		if len(stream.viewers) > 0 {
			s.broadcastStatusLocked(stream, true)
			select {
			case stream.agentOut <- buildKeyframeReq(stream.streamID, 0):
			default:
			}
		}
		stream.mu.Unlock()
	}

	ctx, cancel := context.WithCancel(r.Context())
	defer cancel()

	// Writer loop to agent for ACKs and Keyframe requests
	agentWriterDone := make(chan struct{})
	go func() {
		defer close(agentWriterDone)
		for {
			var out []byte
			if stream != nil {
				select {
				case <-ctx.Done():
					return
				case out = <-stream.agentOut:
				}
			} else {
				select {
				case <-ctx.Done():
					return
				case <-time.After(50 * time.Millisecond):
					continue
				}
			}

			writeCtx, writeCancel := context.WithTimeout(ctx, 3*time.Second)
			err := c.Write(writeCtx, websocket.MessageBinary, out)
			writeCancel()
			if err != nil {
				return
			}
		}
	}()

	// Reader loop from agent
	for {
		msgType, data, err := c.Read(ctx)
		if err != nil {
			break
		}

		if msgType == websocket.MessageText {
			// Forward control messages or handle control ping/command
			continue
		}

		if msgType == websocket.MessageBinary && len(data) >= kHeaderSize {
			magic := binary.LittleEndian.Uint16(data[0:2])
			if magic != kMagic {
				continue
			}

			frameStreamID := binary.LittleEndian.Uint32(data[8:12])
			flags := binary.LittleEndian.Uint16(data[4:6])
			monitorID := binary.LittleEndian.Uint16(data[6:8])

			if stream == nil || stream.streamID != frameStreamID {
				stream = s.getOrCreateStream(frameStreamID)
			}

			stream.mu.Lock()
			if stream.agentConn != c {
				stream.lastKeyframe = nil
			}
			stream.agentConn = c
			stream.agentID = agentID

			// Cache keyframe for instant display on new viewer connections
			if (flags & 1) != 0 {
				log.Printf("[Gateway Agent Keyframe] from remote=%s stream_id=%d size=%d", r.RemoteAddr, frameStreamID, len(data))
				stream.lastKeyframe = make([]byte, len(data))
				copy(stream.lastKeyframe, data)
			}

			// Fan out to viewers
			for _, v := range stream.viewers {
				select {
				case v.ch <- data:
				default:
					// Queue full: drop oldest frame
					select {
					case <-v.ch:
					default:
					}
					// Queue newest
					select {
					case v.ch <- data:
					default:
					}
					// Send KEYFRAME_REQ to agent
					keyReq := buildKeyframeReq(frameStreamID, monitorID)
					select {
					case stream.agentOut <- keyReq:
					default:
					}
				}
			}
			stream.mu.Unlock()
		}
	}

	cancel()
	<-agentWriterDone

	if stream != nil {
		stream.mu.Lock()
		if stream.agentConn == c {
			stream.agentConn = nil
			stream.lastKeyframe = nil
			s.broadcastStatusLocked(stream, false)
		}
		stream.mu.Unlock()
	}
}
