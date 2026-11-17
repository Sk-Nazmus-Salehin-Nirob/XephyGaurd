// Helper-side streamer after screen Step 61: no network, frames to a callback (the IPC channel),
// capture driven only by gateway messages relayed by the service.
#include <catch2/catch_test_macros.hpp>

#include <atomic>
#include <chrono>
#include <mutex>
#include <optional>
#include <thread>

#include "fake_capture.h"
#include "protocol.h"
#include "screen_streamer.hpp"

using namespace xg;

namespace {
std::string control(MsgType type, uint16_t flags, uint32_t stream_id) {
    Message m{};
    m.type = type;
    m.flags = flags;
    m.stream_id = stream_id;
    const auto v = encode(m);
    return {v.begin(), v.end()};
}

struct Rig {
    ScreenStreamer s{[] { return std::make_shared<FakeCapture>(320, 240); }};
    std::mutex mu;
    std::vector<std::string> frames;
    std::atomic<int> viewing{-1};
    std::mutex wmu;
    std::optional<ScreenWindow> win = ScreenWindow{"editor", "main.cpp"};  // what the "window monitor" reports
    Rig() {
        s.set_window_source([this] {
            std::lock_guard lk(wmu);
            return win;
        });
    }
    void set_window(std::optional<ScreenWindow> w) {
        std::lock_guard lk(wmu);
        win = std::move(w);
    }
    // 1 = a MASKED placeholder was sent, 2 = a real (unmasked) frame was sent, 0 = nothing yet.
    int kinds() {
        std::lock_guard lk(mu);
        int k = 0;
        for (const auto& f : frames)
            if (auto m = decode(reinterpret_cast<const uint8_t*>(f.data()), f.size()); m && m->type == MsgType::Frame)
                k |= (m->flags & Flags::MASKED) ? 1 : 2;
        return k;
    }
    bool start(uint32_t id) {
        return s.start(id, [this](std::string_view f) {
            std::lock_guard lk(mu);
            frames.emplace_back(f);
            return true;
        }, [this](bool v) { viewing = v ? 1 : 0; });
    }
    size_t count() { std::lock_guard lk(mu); return frames.size(); }
    template <class F> static bool eventually(F f) {
        for (int i = 0; i < 300; ++i) {
            if (f()) return true;
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
        }
        return false;
    }
};
}  // namespace

TEST_CASE("helper streamer stays idle until the gateway asks, then sends frames to the IPC callback", "[screen]") {
    Rig r;
    REQUIRE(r.start(42));
    std::this_thread::sleep_for(std::chrono::milliseconds(100));
    CHECK_FALSE(r.s.is_capturing());
    CHECK(r.count() == 0);  // armed, but nobody is viewing: no capture, no frames

    r.s.on_gateway_message(control(MsgType::KeyframeReq, 0, 42));
    REQUIRE(Rig::eventually([&] { return r.count() > 0; }));
    CHECK(r.viewing == 1);
    {
        std::lock_guard lk(r.mu);
        auto m = decode(reinterpret_cast<const uint8_t*>(r.frames[0].data()), r.frames[0].size());
        REQUIRE(m);
        CHECK(m->stream_id == 42);
    }

    r.s.on_gateway_message(control(MsgType::Status, 0, 42));  // last viewer left
    CHECK_FALSE(r.s.is_capturing());
    CHECK(r.viewing == 0);
}

TEST_CASE("helper streamer stops capturing when the service link is lost and ignores garbage", "[screen]") {
    Rig r;
    REQUIRE(r.start(42));
    r.s.on_gateway_message(std::string("\x01\x02\x03", 3));  // malformed: ignored, no capture
    CHECK_FALSE(r.s.is_capturing());
    r.s.on_gateway_message(control(MsgType::Status, 1, 42));
    REQUIRE(Rig::eventually([&] { return r.s.is_capturing(); }));
    r.s.on_link_lost();
    CHECK_FALSE(r.s.is_capturing());
    CHECK(r.viewing == 0);
    r.s.stop();
    CHECK_FALSE(r.s.is_running());
    CHECK_FALSE(r.start(0));  // no stream id, no streamer
}

TEST_CASE("privacy mask: no window source or an unknown window masks the picture (fail-safe)", "[screen][privacy]") {
    Rig r;
    r.set_window(std::nullopt);  // the helper has no window report yet
    REQUIRE(r.start(42));
    r.s.on_gateway_message(control(MsgType::KeyframeReq, 0, 42));
    REQUIRE(Rig::eventually([&] { return r.kinds() != 0; }));
    CHECK(r.kinds() == 1);

    ScreenStreamer bare([] { return std::make_shared<FakeCapture>(320, 240); });  // never given a window source
    std::mutex mu;
    int masked = 0, real = 0;
    REQUIRE(bare.start(7, [&](std::string_view f) {
        auto m = decode(reinterpret_cast<const uint8_t*>(f.data()), f.size());
        std::lock_guard lk(mu);
        if (m && m->type == MsgType::Frame) ((m->flags & Flags::MASKED) ? masked : real)++;
        return true;
    }));
    bare.on_gateway_message(control(MsgType::KeyframeReq, 0, 7));
    REQUIRE(Rig::eventually([&] { std::lock_guard lk(mu); return masked > 0; }));
    std::lock_guard lk(mu);
    CHECK(real == 0);
}

TEST_CASE("privacy mask: a matching window is masked, leaving it lifts the mask", "[screen][privacy]") {
    Rig r;
    r.s.set_mask_rules({{"keepassxc", ""}, {"", "private|incognito"}});
    r.set_window(ScreenWindow{"KeePassXC", "Passwords"});  // app name compares case-insensitively
    REQUIRE(r.start(42));
    r.s.on_gateway_message(control(MsgType::KeyframeReq, 0, 42));
    REQUIRE(Rig::eventually([&] { return r.kinds() != 0; }));
    CHECK(r.kinds() == 1);

    r.set_window(ScreenWindow{"firefox", "Hello - Incognito window"});  // title regex rule
    std::this_thread::sleep_for(std::chrono::milliseconds(150));
    CHECK(r.kinds() == 1);

    r.set_window(ScreenWindow{"editor", "main.cpp"});
    REQUIRE(Rig::eventually([&] { return (r.kinds() & 2) != 0; }));
}

TEST_CASE("privacy mask: an invalid rule regex masks (fail-safe); rules can change on a running stream", "[screen][privacy]") {
    Rig r;
    r.s.set_mask_rules({{"", "([unclosed"}});
    REQUIRE(r.start(42));
    r.s.on_gateway_message(control(MsgType::KeyframeReq, 0, 42));
    REQUIRE(Rig::eventually([&] { return r.kinds() != 0; }));
    CHECK(r.kinds() == 1);
    r.s.set_mask_rules({});  // the bad list is replaced
    REQUIRE(Rig::eventually([&] { return (r.kinds() & 2) != 0; }));
}
