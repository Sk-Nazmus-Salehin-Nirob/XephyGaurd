// Streamer benchmark (screen Step 20, part a): the real AgentStateMachine loop, tile diff, encoder and flow
// control on synthetic 1080p workloads. The capture is synthetic and behaves like the current X11 capture
// (full copy per call, full_dirty = true), so its memcpy cost is included, as a real capture's would be.
// An immediate ACK stands in for the viewer. Gateway and headless-viewer latency are part b (M3-3b).
// Reports per phase: fps, bytes/s, ms from capture return to sent (tile diff + encode) p50/p95, keyframes,
// CPU seconds per second and per frame, thread wake-ups per second. Pin it with `taskset -c 0`.
#include "../agent/agent_state.h"
#include "../capture/capture.h"

#include <sys/resource.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <iostream>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

namespace {
using Clock = std::chrono::steady_clock;
constexpr int kW = 1920, kH = 1080;

struct Rng {
  uint64_t s = 88172645463325252ull;
  uint32_t next() { s ^= s << 13; s ^= s >> 7; s ^= s << 17; return static_cast<uint32_t>(s >> 16); }
};

double ms_since(Clock::time_point t) { return std::chrono::duration<double, std::milli>(Clock::now() - t).count(); }

// Mutates a 1080p BGRA buffer according to the workload, by wall-clock time.
class SyntheticCapture : public xg::ScreenCapture {
public:
  explicit SyntheticCapture(std::string workload) : workload_(std::move(workload)), buf_(size_t(kW) * kH * 4, 0xFF) {
    Rng r;  // text-like page: dark dashes on white, so the encoder sees realistic detail
    for (int y = 40; y < kH - 40; y += 20)
      for (int x = 40; x < kW - 40; x += 12)
        if (r.next() % 5) fill(x, y, 6 + int(r.next() % 4), 10, 0x30);
    t0_ = next_ = Clock::now();
  }
  bool initialize() override { return true; }
  bool start() override { t0_ = next_ = Clock::now(); return true; }
  void stop() override {}
  xg::CaptureStatus capture(xg::Frame& out) override {
    {
      std::lock_guard<std::mutex> lk(m_);
      captured_at_ = Clock::now();
    }
    captures.fetch_add(1);
    advance();
    out.width = kW; out.height = kH; out.stride = kW * 4;
    out.bgra.assign(buf_.begin(), buf_.end());
    out.dirty.clear();
    out.full_dirty = true;
    out.secure_desktop = false;
    return xg::CaptureStatus::Ok;
  }
  std::atomic<uint64_t> captures{0};
  Clock::time_point captured_at() { std::lock_guard<std::mutex> lk(m_); return captured_at_; }

private:
  void fill(int x, int y, int w, int h, uint8_t v) {
    for (int j = y; j < y + h && j < kH; ++j) std::memset(&buf_[(size_t(j) * kW + x) * 4], v, size_t(std::min(w, kW - x)) * 4);
  }
  void advance() {
    const auto now = Clock::now();
    auto due = [&](int period_ms) { if (now < next_) return false; next_ = now + std::chrono::milliseconds(period_ms); return true; };
    ++tick_;
    if (workload_ == "typing") {          // one 16x24 glyph every 120 ms
      if (due(120)) fill(100 + (tick_ * 16) % 1200, 200, 16, 24, uint8_t(tick_ * 37));
    } else if (workload_ == "scrolling") {  // a 1920x900 text area shifts 24 px every 33 ms
      if (due(33)) {
        std::memmove(&buf_[size_t(100) * kW * 4], &buf_[size_t(124) * kW * 4], size_t(876) * kW * 4);
        for (int i = 0; i < 24; ++i) fill(40, 976 + i, 1800, 1, (tick_ + i) % 3 ? 0xFF : 0x30);
      }
    } else if (workload_ == "drag") {     // an 800x500 window moves 12 px every 16 ms
      if (due(16)) {
        const int x = 200 + (tick_ * 12) % 800;
        for (int j = 0; j < 500; ++j) std::memset(&buf_[(size_t(300 + j) * kW + x) * 4], uint8_t(0x80 + j % 64), size_t(800) * 4);
      }
    } else if (workload_ == "video") {    // a 1280x720 region changes every 33 ms (30 fps)
      if (due(33)) {
        Rng r; r.s += tick_;
        for (int j = 0; j < 720; ++j) {
          uint8_t* row = &buf_[(size_t(180 + j) * kW + 320) * 4];
          for (int i = 0; i < 1280; ++i) { uint32_t v = r.next(); row[i * 4] = uint8_t(v); row[i * 4 + 1] = uint8_t(j + tick_); row[i * 4 + 2] = uint8_t(i >> 2); }
        }
      }
    }  // "static" and "idle": nothing changes
  }
  std::string workload_;
  std::vector<uint8_t> buf_;
  Clock::time_point t0_, next_, captured_at_;
  int tick_ = 0;
  std::mutex m_;
};

double pct(std::vector<double>& v, double p) {
  if (v.empty()) return 0;
  std::sort(v.begin(), v.end());
  return v[std::min(v.size() - 1, size_t(v.size() * p))];
}

struct Usage { double cpu_s; long wakeups; };
Usage usage() {
  rusage ru{};
  getrusage(RUSAGE_SELF, &ru);
  return {ru.ru_utime.tv_sec + ru.ru_utime.tv_usec / 1e6 + ru.ru_stime.tv_sec + ru.ru_stime.tv_usec / 1e6, ru.ru_nvcsw};
}

void run_phase(const std::string& workload, int seconds, bool json) {
  auto cap = std::make_shared<SyntheticCapture>(workload);
  std::vector<double> lat;
  uint64_t frames = 0, bytes = 0, keys = 0;
  std::mutex m;
  xg::AgentStateMachine* sm_ptr = nullptr;
  xg::AgentStateMachine sm(cap, xg::EncoderConfig{}, [&](const std::vector<uint8_t>& wire) {
    const double ms = ms_since(cap->captured_at());
    std::lock_guard<std::mutex> lk(m);
    ++frames; bytes += wire.size();
    if (wire.size() >= 28 && wire[3] == 1) {
      lat.push_back(ms);
      if (wire[4] & 1) ++keys;
      if (sm_ptr) {  // the viewer's ACK, with no network delay
        xg::Message ack{}; ack.type = xg::MsgType::Ack; ack.stream_id = 1;
        ack.seq = uint32_t(wire[12]) | uint32_t(wire[13]) << 8 | uint32_t(wire[14]) << 16 | uint32_t(wire[15]) << 24;
        auto a = xg::encode(ack);
        sm_ptr->on_incoming_message(a.data(), a.size());
      }
    }
  });
  sm_ptr = &sm;
  if (workload != "idle" && !sm.on_view_start(1, "live")) { std::cerr << "streamer did not start\n"; return; }

  const uint64_t c0 = cap->captures.load();
  const Usage u0 = usage();
  const auto t0 = Clock::now();
  std::this_thread::sleep_for(std::chrono::seconds(seconds));
  const double secs = ms_since(t0) / 1000.0;
  const Usage u1 = usage();
  const double caps = double(cap->captures.load() - c0);
  sm.on_view_stop();

  std::lock_guard<std::mutex> lk(m);
  const double cpu = u1.cpu_s - u0.cpu_s;
  const double fps = frames / secs, wake = double(u1.wakeups - u0.wakeups) / secs;
  const double p50 = pct(lat, 0.5), p95 = pct(lat, 0.95);
  if (json) {
    std::printf("{\"workload\":\"%s\",\"seconds\":%.1f,\"fps\":%.2f,\"bytes_per_s\":%.0f,\"build_ms_p50\":%.2f,\"build_ms_p95\":%.2f,"
                "\"keyframes\":%llu,\"cpu_s_per_s\":%.4f,\"cpu_ms_per_frame\":%.2f,\"captures_per_s\":%.1f,\"cpu_ms_per_capture\":%.2f,\"wakeups_per_s\":%.1f}\n",
                workload.c_str(), secs, fps, bytes / secs, p50, p95, (unsigned long long)keys, cpu / secs,
                frames ? cpu * 1000 / frames : 0.0, caps / secs, caps ? cpu * 1000 / caps : 0.0, wake);
  } else {
    std::printf("%-10s fps %6.2f  %9.0f B/s  build p50/p95 %6.2f/%6.2f ms  key %3llu  cpu %5.1f%% of a core  %7.2f ms/frame  %5.1f cap/s %6.2f ms/cap  wake-ups %6.1f/s\n",
                workload.c_str(), fps, bytes / secs, p50, p95, (unsigned long long)keys, 100 * cpu / secs,
                frames ? cpu * 1000 / frames : 0.0, caps / secs, caps ? cpu * 1000 / caps : 0.0, wake);
  }
  std::fflush(stdout);
}
}  // namespace

int main(int argc, char** argv) {
  int seconds = 10;
  bool json = false;
  std::vector<std::string> phases;
  for (int i = 1; i < argc; ++i) {
    const std::string a = argv[i];
    if (a == "--seconds" && i + 1 < argc) seconds = std::max(1, std::atoi(argv[++i]));
    else if (a == "--workload" && i + 1 < argc) phases.push_back(argv[++i]);
    else if (a == "--json") json = true;
    else { std::cerr << "usage: xgstreambench [--seconds N] [--workload idle|static|typing|scrolling|drag|video]... [--json]\n"; return 2; }
  }
  if (phases.empty()) phases = {"idle", "static", "typing", "scrolling", "drag", "video"};
  for (const auto& p : phases) run_phase(p, seconds, json);
  return 0;
}
