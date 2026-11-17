#include "xg/screen_relay.hpp"
#include "xg/util.hpp"

#include <algorithm>
#include <chrono>
#include <thread>

#include "xg/crypto.hpp"
#include "xg/ipc_messages.hpp"
#include "xg/log.hpp"
#include "xg/uplink.hpp"
#include "xg/websocket.hpp"

namespace xg {
namespace {

class WssScreenLink final : public IScreenLink {
public:
    bool connect(const UplinkView& v, std::string* err) {
        ws_.set_max_message(64 * 1024);
        // Always TLS with the client cert: nginx :8443 verifies it and the gateway takes the identity from it.
        return ws_.connect(v.ccc_host, v.api_port, "/screen-gw/agent?stream_id=" + v.pc_id, tls_options_for(v, true),
                           err, {}, true);
    }
    bool send(const std::string& msg) override { return ws_.send_binary(msg); }
    std::optional<std::string> receive(int timeout_ms) override { return ws_.receive(timeout_ms); }
    bool open() const override { return ws_.open(); }
    void close() override { ws_.close(); }

private:
    net::WebSocketClient ws_;
};

bool all_digits(const std::string& s) {
    return !s.empty() && s.size() <= 10 && std::all_of(s.begin(), s.end(), [](char c) { return c >= '0' && c <= '9'; });
}

}  // namespace

ScreenLinkFactory mtls_screen_link_factory() {
    return [](const UplinkView& v, std::string* err) -> std::unique_ptr<IScreenLink> {
        if (!all_digits(v.pc_id) || v.cert_file.empty() || v.key_file.empty()) {
            if (err) *err = "not enrolled with a client certificate";
            return nullptr;
        }
        auto link = std::make_unique<WssScreenLink>();
        if (!link->connect(v, err)) return nullptr;
        return link;
    };
}

int ScreenRelay::next_backoff_ms(int current_ms) { return current_ms <= 0 ? 1000 : std::min(current_ms * 2, 30000); }

void ScreenRelay::set_source(uint64_t conn_id) {
    if (source_.exchange(conn_id) == conn_id) return;
    wake();
    if (conn_id != 0 && lease_active()) send_lease(conn_id, lease_until_ms_.load() - steady_ms());
}

bool ScreenRelay::lease_active() const {
    const int64_t until = lease_until_ms_.load();
    return until != 0 && steady_ms() < until;
}

void ScreenRelay::send_lease(uint64_t conn, int64_t remaining_ms) {
    if (!ipc_ || remaining_ms <= 0) return;
    ipc_->send(conn, ipc::line({{"t", "screen_lease"}, {"ttl_s", std::max<int64_t>(1, (remaining_ms + 999) / 1000)}}));
}

void ScreenRelay::grant_lease(int ttl_s) {
    ttl_s = std::clamp(ttl_s, 1, kMaxLeaseS);
    const bool was_active = lease_active();
    const int64_t now = steady_ms();
    lease_until_ms_ = now + int64_t(ttl_s) * 1000;
    const uint64_t src = source_.load();
    if (src == 0) return;
    send_lease(src, int64_t(ttl_s) * 1000);
    if (was_active) return;
    // The viewer's first request can beat the lease command; replay it once so the picture does not stay blank.
    std::string status, key;
    {
        std::lock_guard lk(hold_mu_);
        if (now - held_at_ms_ <= kHoldMs) { status = std::move(held_status_); key = std::move(held_key_); }
        held_status_.clear();
        held_key_.clear();
    }
    if (!status.empty()) send_down(src, status);
    if (!key.empty()) send_down(src, key);
}

void ScreenRelay::wake() {
    {
        std::lock_guard lk(mu_);
        woken_ = true;
    }
    cv_.notify_all();
}

void ScreenRelay::push(uint64_t conn_id, std::string&& frame) {
    if (conn_id == 0 || conn_id != source_.load() || !linked_.load() || !lease_active()) { ++dropped_; return; }
    {
        std::lock_guard lk(mu_);
        if (queued_bytes_ + frame.size() > kMaxQueuedBytes) { ++dropped_; return; }
        queued_bytes_ += frame.size();
        queue_.push_back(std::move(frame));
    }
    cv_.notify_all();
}

void ScreenRelay::wait_ms(int ms, const std::atomic<bool>& stop) {
    using clock = std::chrono::steady_clock;
    const auto until = clock::now() + std::chrono::milliseconds(ms);
    std::unique_lock lk(mu_);
    // 200 ms slices so a stop request is seen promptly (the stop flag has no condition variable).
    while (!stop && !woken_ && clock::now() < until)
        cv_.wait_until(lk, std::min(until, clock::now() + std::chrono::milliseconds(200)));
    woken_ = false;
}

void ScreenRelay::send_loop(IScreenLink& link, const std::atomic<bool>& stop) {
    while (!stop && linked_.load()) {
        std::string frame;
        {
            std::unique_lock lk(mu_);
            cv_.wait_for(lk, std::chrono::milliseconds(200), [&] { return !queue_.empty() || !linked_.load(); });
            if (queue_.empty()) continue;
            frame = std::move(queue_.front());
            queue_.pop_front();
            queued_bytes_ -= frame.size();
        }
        if (!link.send(frame)) {
            link.close();
            return;
        }
    }
}

void ScreenRelay::forward_down(uint64_t src, const std::string& msg) {
    if (msg.empty() || msg.size() > kMaxDownlink || !ipc_) return;
    if (!lease_active()) {
        // No CCC lease: nothing reaches the helper. Remember a recent start request for grant_lease().
        std::lock_guard lk(hold_mu_);
        const uint8_t type = msg.size() >= 6 ? static_cast<uint8_t>(msg[3]) : 0;
        const bool viewers = msg.size() >= 6 && (msg[4] != 0 || msg[5] != 0);
        if (type == 5 && !viewers) { held_status_.clear(); held_key_.clear(); }
        else if (type == 5) { held_status_ = msg; held_at_ms_ = steady_ms(); }
        else if (type == 4) { held_key_ = msg; held_at_ms_ = steady_ms(); }
        return;
    }
    send_down(src, msg);
}

void ScreenRelay::send_down(uint64_t src, const std::string& msg) {
    ipc_->send(src, ipc::line({{"t", "screen_rx"}, {"data", crypto::base64_encode(msg)}}));
}

void ScreenRelay::run(const std::atomic<bool>& stop) {
    int backoff = 0;
    while (!stop) {
        const auto v = view_.get();
        const uint64_t src = source_.load();
        if (!v->enrolled || src == 0) {
            wait_ms(1000, stop);
            continue;
        }
        {
            std::lock_guard lk(mu_);
            woken_ = false;  // a wake from before this attempt must not skip the next backoff
        }
        std::string err;
        auto link = factory_ ? factory_(*v, &err) : nullptr;
        if (!link || !link->open()) {
            backoff = next_backoff_ms(backoff);
            log::warn("screen: gateway connection failed ({}), retry in {} ms", err, backoff);
            wait_ms(backoff, stop);
            continue;
        }
        const auto connected_at = std::chrono::steady_clock::now();
        log::info("screen: relay connected to the gateway");
        linked_ = true;
        std::thread sender([&] { send_loop(*link, stop); });
        while (!stop && link->open() && source_.load() == src)
            if (auto m = link->receive(250)) forward_down(src, *m);
        linked_ = false;
        link->close();
        cv_.notify_all();
        sender.join();
        {
            std::lock_guard lk(mu_);
            queue_.clear();  // stale frames; the next viewer starts from a keyframe
            queued_bytes_ = 0;
        }
        log::info("screen: relay disconnected from the gateway");
        // A link that held for 10 s was healthy: start the backoff again from 1 s; a flapping one keeps growing.
        if (std::chrono::steady_clock::now() - connected_at >= std::chrono::seconds(10)) backoff = 0;
        backoff = next_backoff_ms(backoff);
        if (!stop && source_.load() == src) wait_ms(backoff, stop);
    }
}

}  // namespace xg
