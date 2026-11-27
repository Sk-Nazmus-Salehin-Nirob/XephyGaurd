#include "xg/interception_ca.hpp"

#include <algorithm>
#include <cctype>
#include <filesystem>

#include "xg/crypto.hpp"

namespace xg::ica {

namespace {
std::string lower(std::string s) {
    std::transform(s.begin(), s.end(), s.begin(), [](unsigned char c) { return char(std::tolower(c)); });
    return s;
}
}  // namespace

Decision decide(const std::string& installed_sha, const std::string& policy_sha, const std::string& pem) {
    const std::string want = lower(policy_sha);
    const std::string have = lower(installed_sha);
    if (want.empty()) return {have.empty() ? Action::keep : Action::remove, {}};
    if (want == have) return {Action::keep, {}};
    if (pem.empty()) return {Action::reject, "the policy names an interception CA but the response has no PEM"};
    const auto fp = crypto::cert_fingerprint(pem);
    if (!fp) return {Action::reject, "the interception CA is not a valid PEM certificate"};
    if (*fp != want) return {Action::reject, "the interception CA does not match interception_ca_sha256"};
    if (!crypto::cert_is_ca(pem)) return {Action::reject, "the interception CA certificate is not a CA"};
    return {Action::install, {}};
}

std::string path_for(const std::string& ca_file) {
    return (std::filesystem::path(ca_file).parent_path() / "interception-ca.crt").string();
}

}  // namespace xg::ica
