#pragma once
// Root-service relay for the screen stream (screen Step 60, DECISIONS #24).
// The session helper captures and encodes; its frames arrive here as opaque IPC records (ipc_framing.hpp).
// The service owns the only gateway connection: wss://<ccc>:<api_port>/screen-gw/agent with the agent's
// mTLS client cert. Frames go up unchanged; gateway messages (Ack, KeyframeReq, Status) go down to the
// helper as a `screen_rx` JSON line. The relay connects only while the core has named a source helper.
#include <atomic>
#include <condition_variable>
#include <cstdint>
#include <deque>
#include <functional>
#include <memory>
#include <mutex>
#include <optional>
#include <string>

#include "xg/agent_messages.hpp"
#include "xg/interfaces.hpp"
#include "xg/mailbox.hpp"

namespace xg {

/// One duplex message link to the gateway (binary messages). Production: mTLS WebSocket.
class IScreenLink {
public:
    virtual ~IScreenLink() = default;
    virtual bool send(const std::string& msg) = 0;
    virtual std::optional<std::string> receive(int timeout_ms) = 0;
    virtual bool open() const = 0;
    virtual void close() = 0;
};
using ScreenLinkFactory = std::function<std::unique_ptr<IScreenLink>(const UplinkView&, std::string* err)>;

/// wss://<ccc_host>:<api_port>/screen-gw/agent?stream_id=<pc_id>, CA-pinned, with the agent client cert.
ScreenLinkFactory mtls_screen_link_factory();

class ScreenRelay {
public:
    static constexpr size_t kMaxQueuedBytes = 8 * 1024 * 1024;  // two maximum-size frames
    static constexpr size_t kMaxDownlink = 1024;                // gateway control messages are 28 bytes

    ScreenRelay(const Snapshot<UplinkView>& view, IIpcServer* ipc, ScreenLinkFactory factory)
        : view_(view), ipc_(ipc), factory_(std::move(factory)) {}

    /// Core thread: the helper connection allowed to stream (0 = none; the gateway link is closed).
    void set_source(uint64_t conn_id);
    uint64_t source() const { return source_.load(); }
    /// IPC thread: queues one frame from `conn_id`. Never blocks; drops frames from other connections,
    /// while no link is open, or when the queue is full.
    void push(uint64_t conn_id, std::string&& frame);
    /// Relay thread body: connect, relay, reconnect with backoff, until `stop`.
    void run(const std::atomic<bool>& stop);
    void wake();
    uint64_t dropped() const { return dropped_.load(); }
    /// 0 -> 1 s, then doubling up to 30 s.
    static int next_backoff_ms(int current_ms);

private:
    void wait_ms(int ms, const std::atomic<bool>& stop);
    void send_loop(IScreenLink& link, const std::atomic<bool>& stop);
    void forward_down(uint64_t src, const std::string& msg);

    const Snapshot<UplinkView>& view_;
    IIpcServer* ipc_;
    ScreenLinkFactory factory_;
    std::atomic<uint64_t> source_{0};
    std::atomic<bool> linked_{false};
    std::atomic<uint64_t> dropped_{0};
    std::mutex mu_;
    std::condition_variable cv_;
    std::deque<std::string> queue_;
    size_t queued_bytes_ = 0;
    bool woken_ = false;
};

}  // namespace xg
