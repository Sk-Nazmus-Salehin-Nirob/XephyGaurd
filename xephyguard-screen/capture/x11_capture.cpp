#if defined(__linux__)
#include "x11_capture.h"
#include <poll.h>
#include <sys/eventfd.h>
#include <sys/ipc.h>
#include <sys/shm.h>
#include <unistd.h>
#include <algorithm>
#include <chrono>
#include <cstdlib>
#include <cstring>

namespace xg {

namespace {
constexpr size_t kMaxDamageRects = 64;      // more than this in one capture: copy the whole screen instead
constexpr int64_t kSafetyRecheckMs = 1000;  // re-read the screen at least this often even without damage events
int64_t now_ms() {
  return std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now().time_since_epoch()).count();
}
}  // namespace

X11Capture::X11Capture() { wake_fd_ = eventfd(0, EFD_NONBLOCK | EFD_CLOEXEC); }

X11Capture::~X11Capture() {
  cleanup();
  if (wake_fd_ >= 0) ::close(wake_fd_);
}

bool X11Capture::initialize() {
  cleanup();
  const char* display_name = std::getenv("DISPLAY");
  display_ = XOpenDisplay(display_name);
  if (!display_) return false;

  screen_ = DefaultScreen(display_);
  root_ = RootWindow(display_, screen_);

  XWindowAttributes attrs;
  if (!XGetWindowAttributes(display_, root_, &attrs)) {
    cleanup();
    return false;
  }
  width_ = attrs.width;
  height_ = attrs.height;

  // Check Shm extension
  if (!XShmQueryExtension(display_)) {
    cleanup();
    return false;
  }

  shm_image_ = XShmCreateImage(display_, DefaultVisual(display_, screen_),
                               DefaultDepth(display_, screen_), ZPixmap,
                               nullptr, &shminfo_, width_, height_);
  if (!shm_image_) {
    cleanup();
    return false;
  }

  shminfo_.shmid = shmget(IPC_PRIVATE, shm_image_->bytes_per_line * shm_image_->height,
                          IPC_CREAT | 0600);  // owner only: the segment holds screen pixels
  if (shminfo_.shmid < 0) {
    cleanup();
    return false;
  }

  shminfo_.shmaddr = shm_image_->data = static_cast<char*>(shmat(shminfo_.shmid, nullptr, 0));
  if (shminfo_.shmaddr == reinterpret_cast<char*>(-1)) {
    shmctl(shminfo_.shmid, IPC_RMID, nullptr);
    shminfo_.shmid = -1;
    cleanup();
    return false;
  }
  shminfo_.readOnly = False;

  if (!XShmAttach(display_, &shminfo_)) {
    cleanup();
    return false;
  }
  // Once the X server has attached, mark the segment for removal: it disappears when both sides
  // detach, so no other process can attach it later and nothing is left behind after a crash.
  XSync(display_, False);
  shmctl(shminfo_.shmid, IPC_RMID, nullptr);
  shm_removed_ = true;

  // Damage extension
  int damage_event, damage_error;
  if (XDamageQueryExtension(display_, &damage_event, &damage_error)) {
    damage_event_base_ = damage_event;
    damage_ = XDamageCreate(display_, root_, XDamageReportRawRectangles);
  }

  // XRandR events for screen resize
  int r_event, r_error;
  if (XRRQueryExtension(display_, &r_event, &r_error)) {
    XRRSelectInput(display_, root_, RRScreenChangeNotifyMask);
  }

  XSync(display_, False);
  have_shadow_ = false;
  shadow_.assign(static_cast<size_t>(width_) * static_cast<size_t>(height_) * 4, 0);
  pending_.clear();
  damage_all_ = true;  // the first capture reads everything
  lost_ = false;
  return true;
}

bool X11Capture::start() {
  running_ = true;
  return true;
}

void X11Capture::drain_events() {
  bool got_damage = false;
  while (XPending(display_) > 0) {
    XEvent ev;
    XNextEvent(display_, &ev);
    if (ev.type == RRScreenChangeNotify) {
      XRRUpdateConfiguration(&ev);
      lost_ = true;
    } else if (damage_event_base_ >= 0 && ev.type == damage_event_base_ + XDamageNotify) {
      const auto* d = reinterpret_cast<const XDamageNotifyEvent*>(&ev);
      got_damage = true;
      if (damage_all_) continue;
      const int x0 = std::max(0, static_cast<int>(d->area.x)), y0 = std::max(0, static_cast<int>(d->area.y));
      const int x1 = std::min(width_, d->area.x + d->area.width), y1 = std::min(height_, d->area.y + d->area.height);
      if (x1 <= x0 || y1 <= y0) continue;
      if (pending_.size() >= kMaxDamageRects) {
        damage_all_ = true;
        pending_.clear();
      } else {
        pending_.push_back({x0, y0, x1 - x0, y1 - y0});
      }
    }
  }
  if (got_damage && damage_) XDamageSubtract(display_, damage_, None, None);
}

bool X11Capture::wait_for_change(int timeout_ms) {
  if (!display_) return false;
  const int64_t due = last_full_ms_ + kSafetyRecheckMs - now_ms();
  if (!have_shadow_ || due <= 0 || XPending(display_) > 0) return true;
  pollfd fds[2] = {{ConnectionNumber(display_), POLLIN, 0}, {wake_fd_, POLLIN, 0}};
  const int wait = static_cast<int>(std::min<int64_t>(timeout_ms, due));
  const int n = ::poll(fds, wake_fd_ >= 0 ? 2 : 1, wait);
  if (n > 0 && wake_fd_ >= 0 && (fds[1].revents & POLLIN)) {
    uint64_t v;
    if (::read(wake_fd_, &v, sizeof v) < 0) {}
    return true;
  }
  return n > 0 || wait == due;  // an X event, or the safety re-check came due
}

void X11Capture::interrupt_wait() {
  if (wake_fd_ >= 0) {
    const uint64_t one = 1;
    if (::write(wake_fd_, &one, sizeof one) < 0) {}
  }
}

void X11Capture::copy_rect(int x, int y, int w, int h) {
  const auto* src_base = reinterpret_cast<const uint8_t*>(shm_image_->data);
  const size_t bpl = static_cast<size_t>(shm_image_->bytes_per_line);
  for (int row = y; row < y + h; ++row) {
    const uint8_t* src = src_base + static_cast<size_t>(row) * bpl;
    uint8_t* dst = shadow_.data() + (static_cast<size_t>(row) * static_cast<size_t>(width_) + static_cast<size_t>(x)) * 4;
    if (shm_image_->bits_per_pixel == 32) {
      std::memcpy(dst, src + static_cast<size_t>(x) * 4, static_cast<size_t>(w) * 4);
      // 24-bit TrueColor leaves the padding byte 0: make it opaque (WebP encodes BGRA). One OR per pixel, only
      // over the changed rectangle, and the compiler vectorizes it.
      for (int i = 0; i < w; ++i) {
        uint32_t px;
        std::memcpy(&px, dst + i * 4, 4);
        px |= 0xFF000000u;  // alpha is the high byte on little-endian
        std::memcpy(dst + i * 4, &px, 4);
      }
    } else {
      for (int i = 0; i < w; ++i) {
        const uint8_t* p = src + static_cast<size_t>(x + i) * 3;
        dst[i * 4 + 0] = p[0];
        dst[i * 4 + 1] = p[1];
        dst[i * 4 + 2] = p[2];
        dst[i * 4 + 3] = 0xFF;
      }
    }
  }
}

CaptureStatus X11Capture::capture(Frame& out) {
  if (!running_ || !display_ || !shm_image_) {
    return CaptureStatus::Error;
  }
  if (shm_image_->bits_per_pixel != 32 && shm_image_->bits_per_pixel != 24) {
    return CaptureStatus::Error;
  }

  drain_events();
  if (lost_) {
    return CaptureStatus::Lost;
  }

  // Cost follows change: no damage since the last capture means no screen read at all. Every kSafetyRecheckMs the
  // whole screen is re-read anyway, in case a compositor draws without reporting damage on the root window.
  const int64_t now = now_ms();
  const bool recheck = !have_shadow_ || now - last_full_ms_ >= kSafetyRecheckMs;
  if (!recheck && !damage_all_ && pending_.empty()) {
    return CaptureStatus::NoChange;
  }

  if (!XShmGetImage(display_, root_, shm_image_, 0, 0, AllPlanes)) {
    return CaptureStatus::Error;
  }

  const bool full = recheck || damage_all_;
  out.dirty.clear();
  if (full) {
    copy_rect(0, 0, width_, height_);
    last_full_ms_ = now;
    out.full_dirty = true;
  } else {
    for (const auto& r : pending_) {
      copy_rect(r.x, r.y, r.w, r.h);
      out.dirty.push_back(r);
    }
    out.full_dirty = false;
  }
  pending_.clear();
  damage_all_ = false;
  have_shadow_ = true;

  out.width = width_;
  out.height = height_;
  out.stride = width_ * 4;
  out.bgra.assign(shadow_.begin(), shadow_.end());
  out.secure_desktop = false;

  return CaptureStatus::Ok;
}

void X11Capture::stop() {
  running_ = false;
}

void X11Capture::cleanup() {
  running_ = false;
  if (display_) {
    if (damage_) {
      XDamageDestroy(display_, damage_);
      damage_ = 0;
    }
    if (shminfo_.shmaddr && shminfo_.shmaddr != reinterpret_cast<char*>(-1)) {
      XShmDetach(display_, &shminfo_);
      shmdt(shminfo_.shmaddr);
      // Remove only if not already marked: a removed id may be reused by another segment.
      if (!shm_removed_ && shminfo_.shmid >= 0) shmctl(shminfo_.shmid, IPC_RMID, nullptr);
      shm_removed_ = false;
      shminfo_.shmaddr = nullptr;
    }
    if (shm_image_) {
      XDestroyImage(shm_image_);
      shm_image_ = nullptr;
    }
    XCloseDisplay(display_);
    display_ = nullptr;
  }
}

}  // namespace xg
#endif
