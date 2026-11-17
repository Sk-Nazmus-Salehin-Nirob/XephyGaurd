#include "screen_streamer.hpp"

#include <mutex>
#include <stdexcept>
#include <vector>

#include "agent_state.h"

#if defined(_WIN32)
#include "win_dxgi_capture.h"
#include "win_gdi_capture.h"
#else
#include "x11_capture.h"
#ifdef Status
#undef Status
#endif
#endif

namespace xg {
namespace {

std::shared_ptr<ScreenCapture> platform_capture() {
#if defined(_WIN32)
    auto dxgi = std::make_shared<WinDxgiCapture>();
    if (dxgi->initialize()) return dxgi;
    return std::make_shared<WinGdiCapture>();
#else
    return std::make_shared<X11Capture>();
#endif
}

constexpr size_t kMaxTitleBytes = 512;  // bounds the regex work on a title the student controls

std::shared_ptr<PrivacyFilter> make_filter(const WindowSource& src, const std::vector<MaskRule>& rules) {
    auto f = std::make_shared<PrivacyFilter>();
    std::vector<PrivacyRule> pr;
    for (const auto& r : rules) {
        PrivacyRule x;
        if (!r.app.empty()) x.process_name = r.app;
        if (!r.title_regex.empty()) x.title_regex = r.title_regex;
        pr.push_back(std::move(x));
    }
    f->set_rules(std::move(pr));
    f->set_window_provider([src]() -> xg::WindowInfo {
        auto w = src ? src() : std::nullopt;
        if (!w) throw std::runtime_error("foreground window unknown");  // PrivacyFilter turns this into MASKED
        if (w->title.size() > kMaxTitleBytes) w->title.resize(kMaxTitleBytes);
        return {w->app, {}, w->title};
    });
    return f;
}

}  // namespace

struct ScreenStreamer::Impl {
    CaptureFactory factory;
    mutable std::mutex mu;
    std::unique_ptr<AgentStateMachine> sm;
    uint32_t stream_id = 0;
    bool viewing = false;
    std::function<void(bool)> on_viewing_changed;
    WindowSource window_source;
    std::vector<MaskRule> mask_rules;
    // The filter is rebuilt (not mutated) when the rules change; the state machine swaps it under its own lock.
    void install_filter_locked() {
        if (sm) sm->set_privacy_filter(make_filter(window_source, mask_rules));
    }

    void set_viewing(bool v) {
        if (viewing == v) return;
        viewing = v;
        if (on_viewing_changed) on_viewing_changed(v);
    }
    void stop_capture_locked() {
        if (sm && sm->is_thread_running()) sm->on_view_stop();
        set_viewing(false);
    }
};

ScreenStreamer::ScreenStreamer(CaptureFactory factory) : impl_(std::make_unique<Impl>()) {
    impl_->factory = factory ? std::move(factory) : CaptureFactory(platform_capture);
}

ScreenStreamer::~ScreenStreamer() { stop(); }

void ScreenStreamer::set_window_source(WindowSource src) {
    std::lock_guard lk(impl_->mu);
    impl_->window_source = std::move(src);
    impl_->install_filter_locked();
}

void ScreenStreamer::set_mask_rules(std::vector<MaskRule> rules) {
    std::lock_guard lk(impl_->mu);
    impl_->mask_rules = std::move(rules);
    impl_->install_filter_locked();
}

bool ScreenStreamer::start(uint32_t stream_id, FrameOut out, std::function<void(bool)> on_viewing_changed) {
    if (stream_id == 0 || !out) return false;
    std::lock_guard lk(impl_->mu);
    if (impl_->sm && impl_->stream_id == stream_id) return true;
    impl_->stop_capture_locked();
    impl_->sm.reset();
    auto capture = impl_->factory();
    if (!capture) return false;
    EncoderConfig cfg{};
    cfg.quality_text = 85;
    cfg.codec = Codec::Webp;
    // Called on the capture thread; the IPC client serialises writes with the helper's other messages.
    impl_->sm = std::make_unique<AgentStateMachine>(capture, cfg, [out = std::move(out)](const std::vector<uint8_t>& d) {
        out(std::string_view(reinterpret_cast<const char*>(d.data()), d.size()));
    });
    impl_->install_filter_locked();  // always: with no window source the filter masks everything
    impl_->stream_id = stream_id;
    impl_->on_viewing_changed = std::move(on_viewing_changed);
    return true;
}

void ScreenStreamer::on_gateway_message(std::string_view msg) {
    std::lock_guard lk(impl_->mu);
    if (!impl_->sm) return;
    const auto* bytes = reinterpret_cast<const uint8_t*>(msg.data());
    if (auto m = decode(bytes, msg.size())) {
        if (m->type == MsgType::Status && m->flags == 0) {  // no viewer left
            impl_->stop_capture_locked();
            return;
        }
        if (m->type == MsgType::KeyframeReq || (m->type == MsgType::Status && m->flags > 0)) {
            if (!impl_->sm->is_thread_running()) {
                impl_->sm->on_view_stop();
                impl_->sm->on_view_start(impl_->stream_id, "live");
            }
            impl_->set_viewing(true);
        }
    }
    impl_->sm->on_incoming_message(bytes, msg.size());
}

void ScreenStreamer::on_link_lost() {
    std::lock_guard lk(impl_->mu);
    impl_->stop_capture_locked();
}

void ScreenStreamer::stop() {
    if (!impl_) return;
    std::lock_guard lk(impl_->mu);
    impl_->stop_capture_locked();
    impl_->sm.reset();
    impl_->stream_id = 0;
}

bool ScreenStreamer::is_running() const {
    std::lock_guard lk(impl_->mu);
    return impl_->sm != nullptr;
}

bool ScreenStreamer::is_capturing() const {
    std::lock_guard lk(impl_->mu);
    return impl_->sm && impl_->sm->is_thread_running();
}

}  // namespace xg
