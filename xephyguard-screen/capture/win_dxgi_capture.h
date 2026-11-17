#pragma once
#if defined(_WIN32)
#include "capture.h"
#include <d3d11.h>
#include <dxgi1_2.h>
#include <vector>

namespace xg {

class WinDxgiCapture : public ScreenCapture {
public:
  WinDxgiCapture();
  ~WinDxgiCapture() override;

  bool initialize() override;
  bool start() override;
  CaptureStatus capture(Frame& out) override;
  void stop() override;
  void request_full() override { full_pending_ = true; }

private:
  void cleanup();
  // Clamps r to the screen; false when nothing is left. Rects come from the driver: never trusted for bounds.
  bool clamp(RECT& r) const;
  void copy_to_shadow(const uint8_t* src, size_t pitch, const RECT& r);

  ID3D11Device* d3d_device_ = nullptr;
  ID3D11DeviceContext* d3d_context_ = nullptr;
  IDXGIOutputDuplication* duplication_ = nullptr;
  ID3D11Texture2D* staging_texture_ = nullptr;

  int width_ = 0;
  int height_ = 0;
  bool running_ = false;
  bool have_shadow_ = false;   // shadow_ and staging_texture_ hold a whole screen
  bool full_pending_ = true;   // next Ok must report the whole screen
  std::vector<uint8_t> shadow_;  // persistent BGRA frame, width_ * 4 stride
  std::vector<RECT> dirty_rects_buf_;
  std::vector<DXGI_OUTDUPL_MOVE_RECT> move_rects_buf_;
  std::vector<RECT> changed_;  // dirty + move destinations of this frame
};

}  // namespace xg
#endif
