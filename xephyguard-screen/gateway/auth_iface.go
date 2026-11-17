// gateway/auth_iface.go  (FIXED)
package main

import "net/http"

type Authenticator interface {
	// Returns the stream_id this viewer may watch. Error => HTTP 401 and close.
	AuthViewer(r *http.Request) (streamID uint32, err error)
	// Returns a stable agent ID (client-cert fingerprint) and the PC the certificate belongs to.
	// The agent may only stream as that PC (stream_id == pcID). Error => reject.
	AuthAgent(r *http.Request) (agentID string, pcID uint32, err error)
}
