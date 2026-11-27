#pragma once
// The web proxy's interception CA (ccc-deploy Step 7, server S-75): a separate self-signed root the PC's
// browsers and OS store trust for the inspected hosts. It never becomes a trust anchor of the agent's own
// TLS, which keeps trusting only the lab CA in `ca_file`.
#include <string>

namespace xg::ica {

enum class Action { keep, install, remove, reject };

struct Decision {
    Action action = Action::keep;
    std::string reason;   // why a certificate was rejected (log text)
};

/// `installed_sha`: SHA-256 of the installed interception CA ("" = none). `policy_sha`: the policy's
/// `interception_ca_sha256` ("" = absent: there is none). `pem`: the policy response's `interception_ca`
/// ("" = null). Installs only a CA certificate whose SHA-256 equals the policy value.
Decision decide(const std::string& installed_sha, const std::string& policy_sha, const std::string& pem);

/// `<directory of ca_file>/interception-ca.crt`: the copy the agent keeps (tamper check, replace, remove).
std::string path_for(const std::string& ca_file);

}  // namespace xg::ica
