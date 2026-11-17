// Helper-side streamer after screen Step 61: no network, frames to a callback (the IPC channel),
// capture driven only by gateway messages relayed by the service.
#include <catch2/catch_test_macros.hpp>

#include <atomic>
#include <chrono>
#include <mutex>
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
