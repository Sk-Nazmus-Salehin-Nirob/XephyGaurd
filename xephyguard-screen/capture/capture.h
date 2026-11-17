#pragma once
#include <algorithm>
#include <chrono>
#include <cstdint>
#include <thread>
#include <vector>

namespace xg {
struct Frame {
  int width = 0, height = 0, stride = 0;     // stride in bytes
  std::vector<uint8_t> bgra;                  // size = stride * height
  struct Rect { int x, y, w, h; };
  std::vector<Rect> dirty;                    // empty + full_dirty=false => unchanged
  bool full_dirty = false;                    // true => treat everything as changed
  bool secure_desktop = false;
};

enum class CaptureStatus { Ok, NoChange, SecureDesktop, Lost, Error };

class ScreenCapture {
public:
  virtual ~ScreenCapture() = default;
  virtual bool initialize() = 0;
  virtual bool start() = 0;
  virtual CaptureStatus capture(Frame& out) = 0;  // fills out when Ok
  virtual void stop() = 0;
  /// Blocks until the screen may have changed or `timeout_ms` passed; false = timed out (nothing changed). Captures
  /// without a change source poll: this default sleeps a short slice and says "maybe", like the old fixed sleeps.
  virtual bool wait_for_change(int timeout_ms) {
    std::this_thread::sleep_for(std::chrono::milliseconds(std::min(timeout_ms, 20)));
    return true;
  }
  /// Thread-safe: ends a wait_for_change() blocked on another thread at once.
  virtual void interrupt_wait() {}
  /// Capture thread only: the next capture() must return Ok with the whole screen (a new viewer or a lifted privacy
  /// mask needs a picture even though nothing changed). Captures that return Ok on every call ignore it.
  virtual void request_full() {}
};
}
