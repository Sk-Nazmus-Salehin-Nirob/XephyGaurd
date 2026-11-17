#pragma once
// Embedded screen streamer in the session helper (F95). Since screen Step 61 (DECISIONS #24) it only captures
// and encodes: frames leave through the service IPC channel, and the gateway's control messages (Ack,
// KeyframeReq, Status) arrive from the service as `screen_rx`. The helper holds no gateway credential and
// opens no network connection.
#include <cstdint>
#include <functional>
#include <memory>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

namespace xg {

class ScreenCapture;

/// The window the student is working in, as the helper's window monitor last saw it. Used only to decide
/// whether to mask the picture; never sent anywhere (ETHICS.md, screen Step 11).
struct ScreenWindow {
    std::string app;    // executable name
    std::string title;
};
/// nullopt = unknown (no monitor, no event yet): the streamer then masks the screen (fail-safe).
using WindowSource = std::function<std::optional<ScreenWindow>()>;
/// A window to hide: every non-empty field must match (app case-insensitive, title as case-insensitive regex).
struct MaskRule {
    std::string app, title_regex;
};

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

    /// Where the streamer learns the focused window. Without one the picture stays masked.
    void set_window_source(WindowSource src);
    /// Replaces the windows to hide. Takes effect on a running stream. An invalid regex masks the screen.
    void set_mask_rules(std::vector<MaskRule> rules);

    /// Arms the streamer for `stream_id`. Capture starts only when the gateway asks for a picture.
    /// A no-op if already armed for the same stream.
    bool start(uint32_t stream_id, FrameOut out, std::function<void(bool)> on_viewing_changed = {});
    /// The service says the CCC holds a live-view lease for `ttl_s` more seconds (clamped to 1..120). Capture starts
    /// only inside a lease and stops by itself when it lapses (checked by tick()).
    void grant_lease(int ttl_s);
    /// Stops capture if the lease has lapsed. Call regularly from the helper's main loop.
    void tick();
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
