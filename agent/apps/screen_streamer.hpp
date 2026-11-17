#pragma once
// Embedded screen streamer in the session helper (F95). Since screen Step 61 (DECISIONS #24) it only captures
// and encodes: frames leave through the service IPC channel, and the gateway's control messages (Ack,
// KeyframeReq, Status) arrive from the service as `screen_rx`. The helper holds no gateway credential and
// opens no network connection.
#include <cstdint>
#include <functional>
#include <memory>
#include <string>
#include <string_view>

namespace xg {

class ScreenCapture;

class ScreenStreamer {
public:
    /// Sends one encoded screen message to the service; false if it could not be sent.
    using FrameOut = std::function<bool(std::string_view)>;
    /// Makes the capture backend; empty = the platform default (DXGI/GDI on Windows, X11 on Linux).
    using CaptureFactory = std::function<std::shared_ptr<ScreenCapture>()>;

    explicit ScreenStreamer(CaptureFactory factory = {});
    ~ScreenStreamer();

    ScreenStreamer(const ScreenStreamer&) = delete;
    ScreenStreamer& operator=(const ScreenStreamer&) = delete;

    /// Arms the streamer for `stream_id`. Capture starts only when the gateway asks for a picture.
    /// A no-op if already armed for the same stream.
    bool start(uint32_t stream_id, FrameOut out, std::function<void(bool)> on_viewing_changed = {});
    /// One gateway message relayed by the service.
    void on_gateway_message(std::string_view msg);
    /// The service connection is gone: stop capturing until the gateway asks again.
    void on_link_lost();
    void stop();
    bool is_running() const;
    bool is_capturing() const;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace xg
