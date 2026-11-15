#pragma once
#include <atomic>
#include <cstdint>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <utility>
#include <vector>

#include "xg/tls.hpp"

namespace xg::net {

enum class WsOpcode : uint8_t { cont = 0x0, text = 0x1, binary = 0x2, close = 0x8, ping = 0x9, pong = 0xA };

struct WsFrame {
    bool fin = true;
    WsOpcode opcode = WsOpcode::text;
    std::string payload;
};

/// RFC 6455 frame codec (exposed for tests).
std::string ws_encode_frame(WsOpcode op, const std::string& payload, bool mask, const uint8_t mask_key[4]);
/// Decodes one frame from the front of `buf`. Returns nullopt if more bytes are needed.
std::optional<WsFrame> ws_decode_frame(const std::string& buf, size_t* consumed, bool* protocol_error);
std::string ws_accept_key(const std::string& client_key_b64);

/// Blocking/thread-safe duplex WebSocket client over TLS or plain TCP.
class WebSocketClient {
public:
    ~WebSocketClient();
    bool connect(const std::string& host, uint16_t port, const std::string& path, const TlsOptions& opts,
                 std::string* err,
                 const std::vector<std::pair<std::string, std::string>>& extra_headers = {},
                 bool use_tls = true);
    bool send_text(const std::string& text);
    bool send_binary(const void* data, size_t len);
    bool send_binary(const std::string& data);
    /// Waits up to `timeout_ms` for a complete message. Returns nullopt on timeout (check open()).
    std::optional<std::string> receive(int timeout_ms);
    void close();
    bool open() const { return open_.load(); }

private:
    bool send_frame(WsOpcode op, const std::string& payload);
    bool raw_write_all(const void* data, size_t len);
    long raw_read_some(void* buf, size_t len);
    bool raw_wait_readable(int timeout_ms);
    void raw_close_locked();

    TlsConnection conn_;
    long long plain_sock_ = -1;
    bool use_tls_ = true;
    mutable std::mutex io_mu_;
    std::string buf_, partial_;
    std::atomic<bool> open_{false};
};

}  // namespace xg::net
