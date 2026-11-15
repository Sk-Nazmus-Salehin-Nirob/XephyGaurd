// GPU usage: NVIDIA via NVML (dlopen, optional), AMD via amdgpu sysfs, or Intel i915/Xe via RC6 residency + GT freq.
#include <dlfcn.h>

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <map>
#include <optional>
#include <string>
#include <vector>

#include "linux_common.hpp"
#include "xg/util.hpp"

namespace xg::lnx {
namespace {

struct NvmlUtil { unsigned int gpu, memory; };
struct NvmlMem { unsigned long long total, free, used; };
using nvmlInit_t = int (*)();
using nvmlGetHandle_t = int (*)(unsigned int, void**);
using nvmlGetUtil_t = int (*)(void*, NvmlUtil*);
using nvmlGetMem_t = int (*)(void*, NvmlMem*);
using nvmlGetName_t = int (*)(void*, char*, unsigned int);

std::optional<double> parse_double(const std::string& raw) {
    const std::string t = trim(raw);
    if (t.empty()) return std::nullopt;
    try {
        size_t idx = 0;
        double val = std::stod(t, &idx);
        if (idx == 0) return std::nullopt;
        return val;
    } catch (...) {
        return std::nullopt;
    }
}

std::optional<uint64_t> parse_u64(const std::string& raw) {
    const std::string t = trim(raw);
    if (t.empty()) return std::nullopt;
    try {
        size_t idx = 0;
        uint64_t val = std::stoull(t, &idx);
        if (idx == 0) return std::nullopt;
        return val;
    } catch (...) {
        return std::nullopt;
    }
}

std::optional<double> read_first_double(const std::string& base, const std::vector<std::string>& rels) {
    for (const auto& r : rels) {
        if (auto v = parse_double(read_small(base + "/" + r))) return v;
    }
    return std::nullopt;
}

std::optional<uint64_t> read_first_u64(const std::string& base, const std::vector<std::string>& rels) {
    for (const auto& r : rels) {
        if (auto v = parse_u64(read_small(base + "/" + r))) return v;
    }
    return std::nullopt;
}

std::string uevent_field(const std::string& uevent, const std::string& key) {
    const std::string prefix = key + "=";
    size_t pos = 0;
    while (pos < uevent.size()) {
        size_t end = uevent.find('\n', pos);
        if (end == std::string::npos) end = uevent.size();
        const std::string line = uevent.substr(pos, end - pos);
        if (line.starts_with(prefix)) return trim(line.substr(prefix.size()));
        pos = end + 1;
    }
    return {};
}

class GpuMonitor final : public IGpuMonitor {
public:
    explicit GpuMonitor(std::string drm_root) : drm_root_(std::move(drm_root)) {
        if (drm_root_ == "/sys/class/drm") {
            lib_ = dlopen("libnvidia-ml.so.1", RTLD_LAZY | RTLD_LOCAL);
            if (lib_) {
                auto init = reinterpret_cast<nvmlInit_t>(dlsym(lib_, "nvmlInit_v2"));
                get_handle_ = reinterpret_cast<nvmlGetHandle_t>(dlsym(lib_, "nvmlDeviceGetHandleByIndex_v2"));
                get_util_ = reinterpret_cast<nvmlGetUtil_t>(dlsym(lib_, "nvmlDeviceGetUtilizationRates"));
                get_mem_ = reinterpret_cast<nvmlGetMem_t>(dlsym(lib_, "nvmlDeviceGetMemoryInfo"));
                get_name_ = reinterpret_cast<nvmlGetName_t>(dlsym(lib_, "nvmlDeviceGetName"));
                if (!init || init() != 0 || !get_handle_ || get_handle_(0, &dev_) != 0) dev_ = nullptr;
            }
        }
    }
    ~GpuMonitor() override { if (lib_) dlclose(lib_); }

    bool available() const override {
        if (dev_ && get_util_ && get_mem_) return true;
        for (const auto& card : drm_cards()) {
            const std::string cpath = drm_root_ + "/" + card;
            if (has_amd_telemetry(cpath) || has_intel_telemetry(cpath)) return true;
        }
        return false;
    }

    std::optional<Sample> sample() override {
        if (dev_ && get_util_ && get_mem_) {
            NvmlUtil u{};
            NvmlMem m{};
            if (get_util_(dev_, &u) == 0 && get_mem_(dev_, &m) == 0) {
                Sample s;
                s.util_pct = u.gpu;
                s.mem_used_mb = double(m.used) / 1048576.0;
                s.mem_total_mb = double(m.total) / 1048576.0;
                char name[96] = {0};
                if (get_name_) get_name_(dev_, name, sizeof name);
                s.name = name;
                return s;
            }
        }
        for (const auto& card : drm_cards()) {
            const std::string cpath = drm_root_ + "/" + card;
            if (auto amd = sample_amd(card, cpath)) return amd;
            if (auto intel = sample_intel(card, cpath)) return intel;
        }
        return std::nullopt;
    }

private:
    struct PrevRc6 {
        uint64_t residency_ms = 0;
        std::chrono::steady_clock::time_point ts{};
        bool valid = false;
    };

    std::vector<std::string> drm_cards() const {
        std::vector<std::string> cards = list_dir(drm_root_);
        std::sort(cards.begin(), cards.end());
        std::vector<std::string> out;
        for (const auto& card : cards) {
            if (!card.starts_with("card") || card.find('-') != std::string::npos) continue;
            out.push_back(card);
        }
        return out;
    }

    static bool has_amd_telemetry(const std::string& cpath) {
        return parse_double(read_small(cpath + "/device/gpu_busy_percent")).has_value();
    }

    static bool is_intel_card(const std::string& cpath) {
        const std::string vendor = to_lower(trim(read_small(cpath + "/device/vendor")));
        if (vendor == "0x8086") return true;
        const std::string drv = to_lower(uevent_field(read_small(cpath + "/device/uevent"), "DRIVER"));
        return drv == "i915" || drv == "xe";
    }

    static std::optional<uint64_t> read_intel_rc6_ms(const std::string& cpath) {
        return read_first_u64(cpath, {
                                         "gt/gt0/rc6_residency_ms",
                                         "power/rc6_residency_ms",
                                         "device/tile0/gt0/gtidle/idle_residency_ms",
                                     });
    }

    static std::optional<double> read_intel_act_mhz(const std::string& cpath) {
        return read_first_double(cpath, {
                                            "gt_act_freq_mhz",
                                            "gt/gt0/rps_act_freq_mhz",
                                            "device/tile0/gt0/freq0/act_freq",
                                            "gt_cur_freq_mhz",
                                            "gt/gt0/rps_cur_freq_mhz",
                                            "device/tile0/gt0/freq0/cur_freq",
                                        });
    }

    static std::optional<double> read_intel_max_mhz(const std::string& cpath) {
        return read_first_double(cpath, {
                                            "gt_RP0_freq_mhz",
                                            "gt/gt0/rps_RP0_freq_mhz",
                                            "device/tile0/gt0/freq0/rp0_freq",
                                            "gt_max_freq_mhz",
                                            "gt/gt0/rps_max_freq_mhz",
                                            "device/tile0/gt0/freq0/max_freq",
                                        });
    }

    static bool has_intel_telemetry(const std::string& cpath) {
        if (!is_intel_card(cpath)) return false;
        return read_intel_rc6_ms(cpath).has_value() || read_intel_act_mhz(cpath).has_value();
    }

    static std::optional<Sample> sample_amd(const std::string& card, const std::string& cpath) {
        auto busy = parse_double(read_small(cpath + "/device/gpu_busy_percent"));
        if (!busy) return std::nullopt;
        Sample s;
        s.util_pct = std::clamp(*busy, 0.0, 100.0);
        if (auto used = parse_double(read_small(cpath + "/device/mem_info_vram_used"))) {
            s.mem_used_mb = *used / 1048576.0;
        }
        if (auto total = parse_double(read_small(cpath + "/device/mem_info_vram_total"))) {
            s.mem_total_mb = *total / 1048576.0;
        }
        const std::string uevent = read_small(cpath + "/device/uevent");
        const std::string drv = uevent_field(uevent, "DRIVER");
        s.name = drv.empty() ? card : (drv + ":" + card);
        return s;
    }

    std::optional<Sample> sample_intel(const std::string& card, const std::string& cpath) {
        if (!has_intel_telemetry(cpath)) return std::nullopt;

        const auto rc6 = read_intel_rc6_ms(cpath);
        const auto act_mhz = read_intel_act_mhz(cpath);
        const auto max_mhz = read_intel_max_mhz(cpath);

        double util_pct = 0.0;
        bool computed = false;
        const auto now = std::chrono::steady_clock::now();
        if (rc6) {
            auto& prev = prev_rc6_[card];
            if (prev.valid) {
                const double dt_ms =
                    std::chrono::duration<double, std::milli>(now - prev.ts).count();
                if (dt_ms >= 50.0 && *rc6 >= prev.residency_ms) {
                    const double idle_frac =
                        std::clamp(double(*rc6 - prev.residency_ms) / dt_ms, 0.0, 1.0);
                    util_pct = (1.0 - idle_frac) * 100.0;
                    computed = true;
                }
            }
            prev = PrevRc6{*rc6, now, true};
        }

        if (!computed) {
            if (act_mhz && *act_mhz <= 0.0) {
                util_pct = 0.0;
            } else if (act_mhz && max_mhz && *max_mhz > 0.0) {
                util_pct = std::clamp((*act_mhz / *max_mhz) * 100.0, 0.0, 100.0);
            } else {
                util_pct = 0.0;
            }
        }

        Sample s;
        s.util_pct = util_pct;
        if (auto used = parse_double(read_small(cpath + "/device/mem_info_vram_used"))) {
            s.mem_used_mb = *used / 1048576.0;
        }
        if (auto total = parse_double(read_small(cpath + "/device/mem_info_vram_total"))) {
            s.mem_total_mb = *total / 1048576.0;
        }
        const std::string uevent = read_small(cpath + "/device/uevent");
        std::string drv = uevent_field(uevent, "DRIVER");
        if (drv.empty()) drv = "i915";
        std::string dev_id = trim(read_small(cpath + "/device/device"));
        if (dev_id.empty()) dev_id = uevent_field(uevent, "PCI_ID");
        s.name = dev_id.empty() ? ("intel-" + drv) : ("intel-" + drv + " (" + dev_id + ")");
        return s;
    }

    std::string drm_root_;
    std::map<std::string, PrevRc6> prev_rc6_;
    void* lib_ = nullptr;
    void* dev_ = nullptr;
    nvmlGetHandle_t get_handle_ = nullptr;
    nvmlGetUtil_t get_util_ = nullptr;
    nvmlGetMem_t get_mem_ = nullptr;
    nvmlGetName_t get_name_ = nullptr;
};

}  // namespace

std::unique_ptr<IGpuMonitor> make_gpu_monitor(std::string drm_root) {
    return std::make_unique<GpuMonitor>(std::move(drm_root));
}

}  // namespace xg::lnx
