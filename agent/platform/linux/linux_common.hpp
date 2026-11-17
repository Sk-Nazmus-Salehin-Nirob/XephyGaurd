#pragma once
#include <functional>
#include <map>
#include <string>
#include <unordered_map>
#include <vector>

#include "xg/interfaces.hpp"

namespace xg::lnx {

struct TcpSocketStat {
    uint64_t inode = 0;
    uint16_t local_port = 0;
    std::string remote_ip;
    uint16_t remote_port = 0;
    int64_t pid = 0;
    std::string process;
    uint64_t bytes_sent = 0;
    uint64_t bytes_recv = 0;
};

struct PidNetStats {
    double net_kbps = 0.0;
    uint32_t net_conns = 0;
};

struct SocketDeltaTracker {
    struct Counters {
        uint64_t out = 0;
        uint64_t in = 0;
        bool initialized = false;
    };
    std::map<uint64_t, Counters> conn_bytes;       // socket inode -> last byte counters
    std::map<std::string, std::string> tuple_sni;  // "local_port->remote_ip:remote_port" -> observed TLS SNI

    std::vector<OutboundAiFlow> evaluate(
        std::vector<TcpSocketStat>& sockets,
        const std::vector<std::string>& ai_domains,
        const std::function<void(std::vector<TcpSocketStat*>&)>& resolve_owners = {});
};

std::string tuple_key(uint16_t local_port, const std::string& remote_ip, uint16_t remote_port);
std::vector<TcpSocketStat> query_sock_diag_tcp();
std::unordered_map<int64_t, PidNetStats> sample_pid_net_stats();

std::string read_small(const std::string& path);           // whole small file, "" if missing
std::string read_link(const std::string& path);
std::vector<std::string> list_dir(const std::string& path);
std::string user_name(uint32_t uid);
std::string user_home(const std::string& user);
uint32_t file_uid(const std::string& path);

/// Writes or clears Chrome, Chromium, Edge and Firefox JSON enterprise policies under `root_prefix`.
bool apply_linux_browser_policies(const std::string& root_prefix, bool ai_suppressed, const std::string& search_url,
                                  const std::string& pac_url);
/// Writes or clears `/etc/systemd/resolved.conf.d/xephyguard.conf` under `root_prefix`.
bool apply_linux_resolved_dns(const std::string& root_prefix, const std::string& dns_ip, bool reload_service = true);

std::unique_ptr<IProcessMonitor> make_process_monitor();
std::unique_ptr<INetworkMonitor> make_network_monitor();
std::unique_ptr<INetworkIsolator> make_network_isolator();
std::unique_ptr<IDeviceMonitor> make_device_monitor();
std::unique_ptr<IExtensionScanner> make_extension_scanner(ISystemInfo* sys);
std::unique_ptr<IFileWatcher> make_file_watcher();
std::unique_ptr<IInputTimingMonitor> make_evdev_input();
std::unique_ptr<ISystemInfo> make_system_info();
std::unique_ptr<IGpuMonitor> make_gpu_monitor(std::string drm_root = "/sys/class/drm");
std::unique_ptr<IServiceHost> make_service_host();
std::unique_ptr<IHelperLauncher> make_helper_launcher();
std::unique_ptr<IIpcServer> make_ipc_server(std::string allowed_exe);
std::unique_ptr<IIpcClient> make_ipc_client();

std::unique_ptr<IWindowMonitor> make_window_monitor();
std::unique_ptr<IClipboardMonitor> make_clipboard_monitor();
std::unique_ptr<IStudentUi> make_student_ui();
std::unique_ptr<IHelperSystem> make_helper_system();
/// Helper-only: measure the current CLIPBOARD content (features only). Used for paste probes.
bool probe_clipboard(PasteInfo& out);

struct IndicatorWorkArea {
    int x = 0;
    int y = 0;
    int width = 1920;
    int height = 1080;
};

struct IndicatorRect {
    int x = 0;
    int y = 0;
    int width = 200;
    int height = 24;
};

/// Sanitizes UTF-8 separator glyphs (middle dot / dashes) for core X11 Latin-1 fonts.
std::string sanitize_indicator_label(const std::string& text);
/// Places the indicator badge cleanly in the bottom-right corner of the desktop workarea.
IndicatorRect compute_indicator_rect(const IndicatorWorkArea& work_area, int text_width_px, int margin_px = 14);

}  // namespace xg::lnx
