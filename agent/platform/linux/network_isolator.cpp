// Linux network isolation via nftables: a dedicated table that drops outbound traffic to public addresses.
// LAN / link-local / multicast stay reachable and the CCC is carved out of the blocked ranges.
// NetworkManager then shows its "no connectivity" (?) icon because its connectivity probe is dropped.
#include <netdb.h>
#include <sys/socket.h>
#include <sys/wait.h>
#include <arpa/inet.h>

#include <unistd.h>

#include <algorithm>
#include <map>
#include <mutex>
#include <set>

#include "linux_common.hpp"
#include "xg/isolation.hpp"
#include "xg/log.hpp"

namespace xg::lnx {
namespace {

constexpr const char* kTable = "xephyguard_isolate";

// nft by absolute path with an argv array: no shell, no PATH lookup (I-AGENT-25).
const std::string& nft_path() {
    static const std::string p = ::access("/usr/sbin/nft", X_OK) == 0 ? "/usr/sbin/nft" : "/sbin/nft";
    return p;
}

int nft(std::vector<std::string> args, const std::string& stdin_text = {}) {
    args.insert(args.begin(), nft_path());
    return run_program(args, stdin_text);
}

}  // namespace

std::string nft_isolation_rules(const std::vector<std::string>& exempt_ips) {
    std::string v4, v6;
    for (const auto& r : isolation::blocked_ipv4_ranges(exempt_ips)) {
        if (!v4.empty()) v4 += ", ";
        v4 += r;
    }
    for (const auto& ip : exempt_ips) {
        in6_addr a{};
        if (ip.find(':') == std::string::npos || ::inet_pton(AF_INET6, ip.c_str(), &a) != 1) continue;  // validated
        if (!v6.empty()) v6 += ", ";
        v6 += ip;
    }
    std::string rules = std::string("table inet ") + kTable +
                        " {\n  chain out {\n    type filter hook output priority 0; policy accept;\n" +
                        "    ip daddr { " + v4 + " } drop\n";
    // A CCC reachable over global IPv6 stays reachable while isolated (I-AGENT-26).
    if (!v6.empty()) rules += "    ip6 daddr { " + v6 + " } accept\n";
    rules += std::string("    ip6 daddr ") + isolation::blocked_ipv6_prefix() + " drop\n  }\n}\n";
    return rules;
}

namespace {

class NetworkIsolator final : public INetworkIsolator {
public:
    bool isolate(const std::vector<std::string>& exempt_hosts) override {
        std::lock_guard lk(mu_);
        for (const auto& h : exempt_hosts) {
            auto ips = resolve(h);
            if (!ips.empty()) known_ips_[h] = std::move(ips);
        }
        std::set<std::string> exempt;
        for (const auto& h : exempt_hosts)
            if (auto it = known_ips_.find(h); it != known_ips_.end()) exempt.insert(it->second.begin(), it->second.end());

        const std::string rules = nft_isolation_rules({exempt.begin(), exempt.end()});
        nft({"delete", "table", "inet", kTable});
        const int rc = nft({"-f", "-"}, rules);
        if (rc != 0) log::error("isolate: nft failed (exit {})", rc);
        else log::info("isolate: outbound Internet blocked (LAN + {} exempt address(es) still reachable)", exempt.size());
        return rc == 0;
    }

    bool restore() override {
        std::lock_guard lk(mu_);
        nft({"delete", "table", "inet", kTable});
        log::info("isolate: outbound Internet restored");
        return true;
    }

    bool active() override {
        std::lock_guard lk(mu_);
        return nft({"list", "table", "inet", kTable}) == 0;
    }

private:
    static std::vector<std::string> resolve(const std::string& host) {
        std::vector<std::string> out;
        if (host.empty()) return out;
        addrinfo hints{};
        hints.ai_family = AF_UNSPEC;
        hints.ai_socktype = SOCK_STREAM;
        addrinfo* res = nullptr;
        if (getaddrinfo(host.c_str(), nullptr, &hints, &res) != 0 || !res) return out;
        for (auto* p = res; p; p = p->ai_next) {
            char buf[INET6_ADDRSTRLEN] = {0};
            if (p->ai_family == AF_INET)
                inet_ntop(AF_INET, &reinterpret_cast<sockaddr_in*>(p->ai_addr)->sin_addr, buf, sizeof buf);
            else if (p->ai_family == AF_INET6)
                inet_ntop(AF_INET6, &reinterpret_cast<sockaddr_in6*>(p->ai_addr)->sin6_addr, buf, sizeof buf);
            else
                continue;
            if (std::find(out.begin(), out.end(), buf) == out.end()) out.emplace_back(buf);
        }
        freeaddrinfo(res);
        return out;
    }

    std::mutex mu_;
    std::map<std::string, std::vector<std::string>> known_ips_;
};

}  // namespace

std::unique_ptr<INetworkIsolator> make_network_isolator() { return std::make_unique<NetworkIsolator>(); }

}  // namespace xg::lnx
