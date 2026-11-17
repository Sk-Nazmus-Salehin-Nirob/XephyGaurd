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

Message FrameEncoder::build(const Frame& f, const std::vector<uint32_t>& tile_indices,
                            uint32_t stream_id, uint32_t seq, uint32_t base_seq, bool keyframe) {
  Message m;
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
  tile_bgra.reserve(kTile * kTile * 4);

  m.tiles.reserve(targets.size());
  for (uint32_t idx : targets) {
    int tx = static_cast<int>(idx % cols);
    int ty = static_cast<int>(idx / cols);

    int start_x = tx * kTile;
    int start_y = ty * kTile;
    int tile_w = std::min(kTile, f.width - start_x);
    int tile_h = std::min(kTile, f.height - start_y);

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
    rec.x = static_cast<uint16_t>(tx);
    rec.y = static_cast<uint16_t>(ty);
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

    m.tiles.push_back(std::move(rec));
  }

  if (tj != nullptr) {
    tjDestroy(tj);
  }

  return m;
}

}  // namespace xg
