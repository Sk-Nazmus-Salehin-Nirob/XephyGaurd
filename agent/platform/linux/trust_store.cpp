// Interception CA in the Linux system store (update-ca-certificates) and the per-user NSS databases of
// Chromium-based browsers (install-browser-ca.sh). Firefox reads the file through its enterprise policy.
#include <unistd.h>

#include "linux_common.hpp"
#include "xg/crypto.hpp"
#include "xg/log.hpp"
#include "xg/util.hpp"

namespace xg::lnx {

namespace {
constexpr const char* kSystemPath = "/usr/local/share/ca-certificates/xephyguard-interception-ca.crt";
constexpr const char* kUpdate = "/usr/sbin/update-ca-certificates";
constexpr const char* kNssScript = "/usr/lib/xephyguard/install-browser-ca.sh";
constexpr const char* kNick = "XephyGuard Interception CA";

class LinuxTrustStore final : public ITrustStore {
public:
    bool install(const std::string& pem, const std::string& /*sha*/) override {
        if (!write_file_atomic(kSystemPath, pem)) return false;
        if (run_program({kUpdate}) != 0) {
            log::error("trust: {} failed", kUpdate);
            return false;
        }
        // Best effort: a PC without libnss3-tools still has the system store.
        if (::access(kNssScript, X_OK) == 0 && run_program({kNssScript, kSystemPath, kNick}) != 0)
            log::warn("trust: {} could not add the interception CA to every NSS database", kNssScript);
        return true;
    }

    bool remove(const std::string& sha) override {
        bool ok = false;
        const std::string cur = read_file(kSystemPath, &ok);
        if (!ok) return true;
        // Only the one named: after a replace, the file already holds the new CA and stays.
        if (crypto::cert_fingerprint(cur).value_or("") != sha) return true;
        if (::unlink(kSystemPath) != 0) return false;
        if (run_program({kUpdate, "--fresh"}) != 0) log::warn("trust: {} --fresh failed", kUpdate);
        if (::access(kNssScript, X_OK) == 0) run_program({kNssScript, "--remove", kNick});
        return true;
    }
};
}  // namespace

std::unique_ptr<ITrustStore> make_trust_store() { return std::make_unique<LinuxTrustStore>(); }

}  // namespace xg::lnx
