#include "agent_state.h"
#include <chrono>

namespace xg {

static uint64_t get_now_ms() {
  return static_cast<uint64_t>(
      std::chrono::duration_cast<std::chrono::milliseconds>(
          std::chrono::steady_clock::now().time_since_epoch())
          .count());
}

AgentStateMachine::AgentStateMachine(std::shared_ptr<ScreenCapture> capture,
                                     EncoderConfig enc_cfg,
                                     FrameSender sender)
    : capture_(std::move(capture)),
      enc_cfg_(enc_cfg),
      sender_(std::move(sender)) {}

AgentStateMachine::~AgentStateMachine() {
  on_view_stop();
}

void AgentStateMachine::set_frame_sender(FrameSender sender) {
  std::lock_guard<std::recursive_mutex> lock(mutex_);
  sender_ = std::move(sender);
}

void AgentStateMachine::set_privacy_checker(PrivacyChecker checker) {
  std::lock_guard<std::recursive_mutex> lock(mutex_);
  privacy_checker_ = std::move(checker);
}

void AgentStateMachine::set_privacy_filter(std::shared_ptr<PrivacyFilter> filter) {
  std::lock_guard<std::recursive_mutex> lock(mutex_);
  privacy_filter_ = std::move(filter);
}

AgentState AgentStateMachine::state() const {
  std::lock_guard<std::recursive_mutex> lock(mutex_);
  return state_;
}

const std::string& AgentStateMachine::mode() const {
  std::lock_guard<std::recursive_mutex> lock(mutex_);
  return mode_;
}

uint32_t AgentStateMachine::stream_id() const {
  std::lock_guard<std::recursive_mutex> lock(mutex_);
  return stream_id_;
}

uint32_t AgentStateMachine::current_seq() const {
  std::lock_guard<std::recursive_mutex> lock(mutex_);
  return seq_;
}

bool AgentStateMachine::is_thread_running() const {
  return running_.load();
}

void AgentStateMachine::set_wall_interval_ms(int ms) {
  std::lock_guard<std::recursive_mutex> lock(mutex_);
  wall_interval_ms_ = ms > 0 ? ms : 1;
}

void AgentStateMachine::wall_pause() {
  std::unique_lock<std::recursive_mutex> lock(mutex_);
  wake_cv_.wait_for(lock, std::chrono::milliseconds(wall_interval_ms_),
                    [&] { return !running_.load() || wall_wake_; });
  wall_wake_ = false;
}

std::vector<uint8_t> AgentStateMachine::wall_unchanged_locked() const {
  // A frame header without KEY/FULL/DELTA and without tiles: "the thumbnail you have is still current".
  Message same{};
  same.type = MsgType::Frame;
  same.stream_id = stream_id_;
  same.seq = last_sent_seq_;
  same.base_seq = last_sent_seq_;
  return encode(same);
}

bool AgentStateMachine::on_view_start(uint32_t stream_id, const std::string& mode) {
  std::lock_guard<std::recursive_mutex> lock(mutex_);
  if (running_.load()) {
    return false;
  }

  stream_id_ = stream_id;
  mode_ = mode;
  seq_ = 0;
  last_sent_seq_ = 0;
  wall_sent_ = false;
  wall_wake_ = false;
  wall_last_.clear();

  if (!capture_ || !capture_->initialize() || !capture_->start()) {
    return false;
  }

  EncoderConfig cfg = enc_cfg_;
  if (mode == "snapshot") {
    cfg.quality_text = 95;
    cfg.full_frame_threshold = 0.0; // Force full frame
  }

  encoder_ = std::make_unique<FrameEncoder>(cfg);
  flow_ = std::make_unique<FlowControl>(3);
  tracker_.reset();

  state_ = AgentState::Streaming;
  running_.store(true);

  capture_thread_ = std::thread(&AgentStateMachine::capture_loop, this);
  return true;
}

bool AgentStateMachine::on_view_stop() {
  running_.store(false);
  if (capture_) capture_->interrupt_wait();  // the capture thread may be blocked waiting for a screen change
  { std::lock_guard<std::recursive_mutex> lock(mutex_); }  // a wall_pause() between its check and its wait sees it
  wake_cv_.notify_all();

  if (capture_thread_.joinable()) {
    capture_thread_.join();
  }

  std::lock_guard<std::recursive_mutex> lock(mutex_);
  if (capture_) {
    capture_->stop();
  }
  tracker_.reset();
  encoder_.reset();
  flow_.reset();
  state_ = AgentState::Idle;
  return true;
}

void AgentStateMachine::on_network_disconnected() {
  std::lock_guard<std::recursive_mutex> lock(mutex_);
  if (state_ == AgentState::Streaming || state_ == AgentState::PausedMasked ||
      state_ == AgentState::PausedSecure) {
    pre_pause_state_ = state_;
    state_ = AgentState::PausedDisconnected;
  }
}

void AgentStateMachine::on_network_connected() {
  std::lock_guard<std::recursive_mutex> lock(mutex_);
  if (state_ == AgentState::PausedDisconnected) {
    state_ = (pre_pause_state_ != AgentState::Idle) ? pre_pause_state_
                                                    : AgentState::Streaming;
    if (flow_) {
      flow_->reset();
    }
    if (tracker_) {
      tracker_->force_all_pending();
    }
    wall_sent_ = false;
  }
}

void AgentStateMachine::on_privacy_mask_changed(bool masked) {
  std::lock_guard<std::recursive_mutex> lock(mutex_);
  if (masked) {
    if (state_ == AgentState::Streaming) {
      state_ = AgentState::PausedMasked;
      if (sender_) {
        Message placeholder{};
        placeholder.type = MsgType::Frame;
        placeholder.flags = Flags::MASKED;
        placeholder.stream_id = stream_id_;
        sender_(encode(placeholder));
      }
    }
  } else {
    if (state_ == AgentState::PausedMasked) {
      state_ = AgentState::Streaming;
      if (flow_) {
        flow_->reset();
      }
      if (tracker_) {
        tracker_->force_all_pending();
      }
      wall_sent_ = false;
    }
  }
}

void AgentStateMachine::send_cursor(uint16_t x, uint16_t y, const std::vector<uint8_t>& shape_data) {
  std::lock_guard<std::recursive_mutex> lock(mutex_);
  if (!sender_ || state_ == AgentState::Idle) return;

  Message msg{};
  msg.type = MsgType::Cursor;
  msg.flags = Flags::CURSOR_F;
  msg.stream_id = stream_id_;
  msg.seq = ++seq_;
  msg.width = x;
  msg.height = y;

  if (!shape_data.empty()) {
    TileRec rec;
    rec.x = 0;
    rec.y = 0;
    rec.codec = Codec::Raw;
    rec.payload = shape_data;
    msg.tiles.push_back(std::move(rec));
  }

  sender_(encode(msg));
}

void AgentStateMachine::on_incoming_message(const uint8_t* data, size_t len) {
  auto opt = decode(data, len);
  if (!opt.has_value()) return;

  const auto& msg = *opt;
  std::lock_guard<std::recursive_mutex> lock(mutex_);
  if (!flow_) return;

  uint64_t now_ms = get_now_ms();

  if (msg.type == MsgType::Ack) {
    flow_->on_ack(msg.seq, now_ms);
  } else if (msg.type == MsgType::KeyframeReq) {
    flow_->reset();
    if (tracker_) {
      tracker_->force_all_pending();
    }
    wall_sent_ = false;
    wall_wake_ = true;
    wake_cv_.notify_all();
    if (capture_) capture_->interrupt_wait();  // answer a new viewer now, not at the next wait timeout
  }
}

void AgentStateMachine::capture_loop() {
  // Never sleep while holding mutex_: std::recursive_mutex is not fair, so the loop would re-take it at once and
  // starve state(), on_incoming_message() and set_privacy_filter() for seconds while masked or paused.
  bool asked_full = false;  // request_full() sent and no frame has come back yet
  while (running_.load()) {
    uint64_t now_ms = get_now_ms();
    int pause_ms = 0;

    {
      std::lock_guard<std::recursive_mutex> lock(mutex_);
      if (state_ == AgentState::PausedDisconnected) {
        pause_ms = 50;
      } else {
        bool masked = false;
        if (privacy_filter_) {
          masked = privacy_filter_->check_masked(now_ms);
        } else if (privacy_checker_) {
          try {
            masked = privacy_checker_();
          } catch (...) {
            masked = true;
          }
        }

        if (masked) {
          if (state_ != AgentState::PausedMasked) {
            state_ = AgentState::PausedMasked;
            if (sender_) {
              Message placeholder{};
              placeholder.type = MsgType::Frame;
              placeholder.flags = Flags::MASKED;
              placeholder.stream_id = stream_id_;
              sender_(encode(placeholder));
            }
          }
          pause_ms = 50;
        } else {
          if (state_ == AgentState::PausedMasked) {
            state_ = AgentState::Streaming;
            if (flow_) flow_->reset();
            if (tracker_) tracker_->force_all_pending();
            wall_sent_ = false;
          }
          if (mode_ != "wall" && flow_ && !flow_->can_send(now_ms)) pause_ms = 10;
        }
      }
    }
    if (pause_ms > 0) {
      std::this_thread::sleep_for(std::chrono::milliseconds(pause_ms));
      continue;
    }

    Frame frame;
    CaptureStatus status = capture_->capture(frame);

    if (status == CaptureStatus::Lost) {
      {
        std::lock_guard<std::recursive_mutex> lock(mutex_);
        capture_->stop();
        capture_->initialize();
        capture_->start();
        if (flow_) flow_->reset();
        if (tracker_) tracker_->force_all_pending();
        wall_sent_ = false;
      }
      std::this_thread::sleep_for(std::chrono::milliseconds(50));
      continue;
    }

    if (status == CaptureStatus::SecureDesktop) {
      {
        std::lock_guard<std::recursive_mutex> lock(mutex_);
        state_ = AgentState::PausedSecure;
        wall_sent_ = false;
        if (sender_) {
          Message placeholder{};
          placeholder.type = MsgType::Frame;
          placeholder.flags = Flags::SECURE;
          placeholder.stream_id = stream_id_;
          sender_(encode(placeholder));
        }
      }
      std::this_thread::sleep_for(std::chrono::milliseconds(100));
      continue;
    }

    if (status == CaptureStatus::NoChange) {
      // Nothing on screen changed. A viewer that still needs a picture (keyframe request, lifted mask, reconnect)
      // gets one by asking the capture for the whole screen; otherwise block until the screen changes. The wait
      // is bounded so the privacy check at the top of the loop keeps running a few times per second.
      bool need_picture = false;
      std::vector<uint8_t> unchanged;
      {
        std::lock_guard<std::recursive_mutex> lock(mutex_);
        if (mode_ == "wall") {
          need_picture = !wall_sent_;
          if (wall_sent_) unchanged = wall_unchanged_locked();
        } else {
          need_picture = !tracker_ || (flow_ && flow_->needs_keyframe()) || !tracker_->pending().empty();
        }
      }
      if (!unchanged.empty()) {  // wall: nothing changed since the last thumbnail, send 28 bytes and wait
        if (sender_) sender_(unchanged);
        wall_pause();
        continue;
      }
      if (need_picture && !asked_full) {
        asked_full = true;
        capture_->request_full();
        continue;
      }
      capture_->wait_for_change(250);
      continue;
    }
    asked_full = false;

    if (status == CaptureStatus::Ok) {
      std::vector<uint8_t> wire_data;
      bool is_snapshot = false;
      bool is_wall = false;

      {
        std::lock_guard<std::recursive_mutex> lock(mutex_);
        if (state_ == AgentState::PausedSecure) {
          state_ = AgentState::Streaming;
        }

        if (mode_ == "wall") {
          is_wall = true;
          int out_h = 0;
          auto downscaled = downscale_box(frame, 320, &out_h);

          if (wall_sent_ && downscaled == wall_last_) {
            wire_data = wall_unchanged_locked();  // the screen changed but not the thumbnail: no encode
          } else {
            Frame wall_frame;
            wall_frame.width = 320;
            wall_frame.height = out_h;
            wall_frame.stride = 320 * 4;
            wall_frame.bgra = std::move(downscaled);
            wall_frame.full_dirty = true;

            TileTracker wall_tracker(wall_frame.width, wall_frame.height);
            wall_tracker.update(wall_frame);

            ++seq_;
            // Wall mode: always full keyframes, never deltas
            auto msg = encoder_->build(wall_frame, wall_tracker.pending(), stream_id_, seq_, 0, true);
            wire_data = encode(msg);
            last_sent_seq_ = seq_;
            wall_last_ = std::move(wall_frame.bgra);
            wall_sent_ = true;
          }
        } else {
          if (!tracker_) {
            tracker_ = std::make_unique<TileTracker>(frame.width, frame.height);
          }

          tracker_->update(frame);
          const auto& pending = tracker_->pending();

          if (pending.empty() && !flow_->needs_keyframe()) {
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
            continue;
          }

          bool keyframe = flow_->needs_keyframe();
          ++seq_;
          uint32_t base = keyframe ? 0 : last_sent_seq_;

          encoder_->set_quality_scale(flow_->quality_scale());
          auto msg = encoder_->build(frame, pending, stream_id_, seq_, base, keyframe);
          wire_data = encode(msg);

          tracker_->mark_sent();
          flow_->on_sent(seq_, now_ms);
          if (keyframe) {
            flow_->note_keyframe_sent();
          }
          last_sent_seq_ = seq_;

          if (mode_ == "snapshot") {
            is_snapshot = true;
          }
        }
      }

      if (sender_ && !wire_data.empty()) {
        sender_(wire_data);
      }

      if (is_snapshot) {
        std::lock_guard<std::recursive_mutex> lock(mutex_);
        running_.store(false);
        state_ = AgentState::Armed;
        break;
      }

      if (is_wall) {
        wall_pause();  // one wait per thumbnail period (was 50 wake-ups of 100 ms)
        continue;
      }
    }

    std::this_thread::sleep_for(std::chrono::milliseconds(30));
  }
}

}  // namespace xg
