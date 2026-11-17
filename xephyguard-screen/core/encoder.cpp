#include "encoder.h"
#include <algorithm>
#include <cmath>
#include <cstring>
#include <turbojpeg.h>
#include <webp/encode.h>

namespace xg {

FrameEncoder::FrameEncoder(EncoderConfig cfg) : cfg_(cfg) {}

void FrameEncoder::set_quality_scale(double s) {
  quality_scale_ = std::clamp(s, 0.3, 1.0);
}

std::vector<FrameEncoder::Region> FrameEncoder::merge_tiles(const std::vector<uint32_t>& tile_indices,
                                                            int width, int height) {
  constexpr int kSpan = kMaxRectSide / kTile;  // tiles per rectangle side
  std::vector<Region> out;
  const int cols = (width + kTile - 1) / kTile;
  const int rows = (height + kTile - 1) / kTile;
  if (cols <= 0 || rows <= 0) return out;
  // 0 = clean, 1 = dirty and not yet covered
  std::vector<uint8_t> grid(static_cast<size_t>(cols) * rows, 0);
  for (uint32_t idx : tile_indices) {
    if (idx < grid.size()) grid[idx] = 1;
  }
  for (int ty = 0; ty < rows; ++ty) {
    for (int tx = 0; tx < cols; ++tx) {
      if (!grid[static_cast<size_t>(ty) * cols + tx]) continue;
      int tw = 1;
      while (tw < kSpan && tx + tw < cols && grid[static_cast<size_t>(ty) * cols + tx + tw]) ++tw;
      int th = 1;
      while (th < kSpan && ty + th < rows) {
        bool whole = true;
        for (int i = 0; i < tw; ++i) {
          if (!grid[static_cast<size_t>(ty + th) * cols + tx + i]) { whole = false; break; }
        }
        if (!whole) break;
        ++th;
      }
      for (int j = 0; j < th; ++j)
        for (int i = 0; i < tw; ++i) grid[static_cast<size_t>(ty + j) * cols + tx + i] = 0;
      Region r;
      r.x = tx * kTile;
      r.y = ty * kTile;
      r.w = std::min(tw * kTile, width - r.x);
      r.h = std::min(th * kTile, height - r.y);
      out.push_back(r);
    }
  }
  return out;
}

Message FrameEncoder::build(const Frame& f, const std::vector<uint32_t>& tile_indices,
                            uint32_t stream_id, uint32_t seq, uint32_t base_seq, bool keyframe) {
  Message m;
  m.version = cfg_.rectangles ? kVersion2 : kVersion;
  m.type = MsgType::Frame;
  m.monitor_id = 0;
  m.stream_id = stream_id;
  m.seq = seq;
  m.width = static_cast<uint16_t>(f.width);
  m.height = static_cast<uint16_t>(f.height);

  const int cols = (f.width + kTile - 1) / kTile;
  const int rows = (f.height + kTile - 1) / kTile;
  const uint32_t total_tiles = static_cast<uint32_t>(cols * rows);

  double fraction = total_tiles > 0 ? (static_cast<double>(tile_indices.size()) / total_tiles) : 0.0;
  bool is_full = keyframe || (fraction >= cfg_.full_frame_threshold);

  if (keyframe) {
    m.flags = Flags::KEY | Flags::FULL;
    m.base_seq = 0;
  } else if (is_full) {
    m.flags = Flags::FULL;
    m.base_seq = 0;
  } else {
    m.flags = Flags::DELTA;
    m.base_seq = base_seq;
  }

  if (f.secure_desktop) {
    m.flags |= Flags::SECURE;
  }

  // Determine list of tiles to send
  std::vector<uint32_t> targets;
  if (is_full) {
    targets.reserve(total_tiles);
    for (uint32_t i = 0; i < total_tiles; ++i) {
      targets.push_back(i);
    }
  } else {
    targets = tile_indices;
  }

  int eff_q = static_cast<int>(std::round(cfg_.quality_text * quality_scale_));
  eff_q = std::clamp(eff_q, 10, 100);

  tjhandle tj = nullptr;
  if (cfg_.codec == Codec::Jpeg) {
    tj = tjInitCompress();
  }

  std::vector<uint8_t> tile_bgra;
  tile_bgra.reserve(static_cast<size_t>(kMaxRectSide) * kMaxRectSide * 4);

  // v1: one region per 64 px tile. v2: dirty tiles merged into rectangles.
  std::vector<Region> regions;
  if (cfg_.rectangles) {
    regions = merge_tiles(targets, f.width, f.height);
  } else {
    regions.reserve(targets.size());
    for (uint32_t idx : targets) {
      Region r;
      r.x = static_cast<int>(idx % cols) * kTile;
      r.y = static_cast<int>(idx / cols) * kTile;
      r.w = std::min(kTile, f.width - r.x);
      r.h = std::min(kTile, f.height - r.y);
      regions.push_back(r);
    }
  }

  m.tiles.reserve(regions.size());
  for (const Region& rg : regions) {
    const int start_x = rg.x;
    const int start_y = rg.y;
    const int tile_w = rg.w;
    const int tile_h = rg.h;

    if (tile_w <= 0 || tile_h <= 0) continue;

    tile_bgra.resize(static_cast<size_t>(tile_w * tile_h * 4));
    for (int y = 0; y < tile_h; ++y) {
      const size_t src_off = static_cast<size_t>((start_y + y) * f.stride + start_x * 4);
      uint8_t* dst_row = tile_bgra.data() + static_cast<size_t>(y * tile_w * 4);
      std::memcpy(dst_row, f.bgra.data() + src_off, static_cast<size_t>(tile_w * 4));
      // Desktop captures (X11 TrueColor, Win32 GDI) often emit 0x00 in byte 3; ensure opaque pixels.
      for (int x = 0; x < tile_w; ++x) {
        dst_row[x * 4 + 3] = 0xFF;
      }
    }

    TileRec rec;
    if (cfg_.rectangles) {
      rec.x = static_cast<uint16_t>(start_x);
      rec.y = static_cast<uint16_t>(start_y);
      rec.w = static_cast<uint16_t>(tile_w);
      rec.h = static_cast<uint16_t>(tile_h);
    } else {
      rec.x = static_cast<uint16_t>(start_x / kTile);
      rec.y = static_cast<uint16_t>(start_y / kTile);
    }
    rec.codec = cfg_.codec;

    if (cfg_.codec == Codec::Webp) {
      // Advanced API: same as WebPEncodeBGRA (default preset) but with a configurable method (speed/size trade).
      WebPConfig wc;
      WebPPicture pic;
      if (WebPConfigInit(&wc) && WebPPictureInit(&pic)) {
        wc.quality = static_cast<float>(eff_q);
        wc.method = std::clamp(cfg_.webp_method, 0, 6);
        pic.width = tile_w;
        pic.height = tile_h;
        WebPMemoryWriter wr;
        WebPMemoryWriterInit(&wr);
        pic.writer = WebPMemoryWrite;
        pic.custom_ptr = &wr;
        if (WebPPictureImportBGRA(&pic, tile_bgra.data(), tile_w * 4) && WebPEncode(&wc, &pic) && wr.size > 0) {
          rec.payload.assign(wr.mem, wr.mem + wr.size);
        }
        WebPMemoryWriterClear(&wr);
        WebPPictureFree(&pic);
      }
    } else if (cfg_.codec == Codec::Jpeg && tj != nullptr) {
      unsigned char* jpeg_buf = nullptr;
      unsigned long jpeg_size = 0;
      if (tjCompress2(tj, tile_bgra.data(), tile_w, tile_w * 4, tile_h,
                      TJPF_BGRA, &jpeg_buf, &jpeg_size, TJSAMP_420, eff_q,
                      TJFLAG_FASTDCT) == 0 && jpeg_buf != nullptr) {
        rec.payload.assign(jpeg_buf, jpeg_buf + jpeg_size);
        tjFree(jpeg_buf);
      }
    } else {
      rec.codec = Codec::Raw;
      rec.payload = tile_bgra;
    }

    // A compressed rectangle must fit the wire limit; the raw one always does (w*h*4 <= 256*256*4).
    if (cfg_.rectangles && rec.payload.size() > kMaxRectPayload) {
      rec.codec = Codec::Raw;
      rec.payload = tile_bgra;
    }

    m.tiles.push_back(std::move(rec));
  }

  if (tj != nullptr) {
    tjDestroy(tj);
  }

  return m;
}

}  // namespace xg
