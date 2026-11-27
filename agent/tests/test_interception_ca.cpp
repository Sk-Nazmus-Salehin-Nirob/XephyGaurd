// The proxy's interception CA from the policy response (agent Step 41, server S-75).
#include <catch2/catch_test_macros.hpp>
#include <cctype>
#include <filesystem>
#include <vector>
#include <openssl/evp.h>
#include <openssl/pem.h>
#include <openssl/x509.h>
#include <openssl/x509v3.h>

#include "fakes.hpp"
#include "xg/agent.hpp"
#include "xg/crypto.hpp"
#include "xg/interception_ca.hpp"
#include "xg/util.hpp"

using namespace xg;
namespace fs = std::filesystem;

namespace {
/// Self-signed P-256 certificate; `ca` adds basicConstraints CA:TRUE.
std::string make_cert(const char* cn, bool ca) {
    EVP_PKEY* key = EVP_EC_gen("P-256");
    X509* cert = X509_new();
    X509_set_version(cert, 2);
    ASN1_INTEGER_set(X509_get_serialNumber(cert), 1);
    X509_gmtime_adj(X509_getm_notBefore(cert), 0);
    X509_gmtime_adj(X509_getm_notAfter(cert), 3600);
    X509_set_pubkey(cert, key);
    X509_NAME_add_entry_by_txt(X509_get_subject_name(cert), "CN", MBSTRING_ASC,
                               reinterpret_cast<const unsigned char*>(cn), -1, -1, 0);
    X509_set_issuer_name(cert, X509_get_subject_name(cert));
    if (ca) {
        X509_EXTENSION* ext = X509V3_EXT_conf_nid(nullptr, nullptr, NID_basic_constraints, "critical,CA:TRUE");
        X509_add_ext(cert, ext, -1);
        X509_EXTENSION_free(ext);
    }
    X509_sign(cert, key, EVP_sha256());
    BIO* b = BIO_new(BIO_s_mem());
    PEM_write_bio_X509(b, cert);
    char* d = nullptr;
    const long n = BIO_get_mem_data(b, &d);
    std::string pem(d, size_t(n));
    BIO_free(b);
    X509_free(cert);
    EVP_PKEY_free(key);
    return pem;
}

std::string upper(std::string s) {
    for (auto& c : s) c = char(std::toupper(static_cast<unsigned char>(c)));
    return s;
}

struct FakeTrust final : ITrustStore {
    std::vector<std::string> installed, removed;
    bool fail_install = false;
    bool install(const std::string& /*pem*/, const std::string& sha) override {
        if (fail_install) return false;
        installed.push_back(sha);
        return true;
    }
    bool remove(const std::string& sha) override {
        removed.push_back(sha);
        return true;
    }
};
}  // namespace

TEST_CASE("interception CA decision") {
    const std::string a = make_cert("Interception A", true), b = make_cert("Interception B", true);
    const std::string leaf = make_cert("not a CA", false);
    const std::string sa = *crypto::cert_fingerprint(a), sb = *crypto::cert_fingerprint(b);
    using ica::Action;

    CHECK(ica::decide("", "", "").action == Action::keep);
    CHECK(ica::decide(sa, "", "").action == Action::remove);   // absent field: the CCC has none
    CHECK(ica::decide(sa, upper(sa), "").action == Action::keep);
    CHECK(ica::decide("", sa, a).action == Action::install);
    CHECK(ica::decide(sa, sb, b).action == Action::install);   // replace
    CHECK(ica::decide("", sa, "").action == Action::reject);   // hash without PEM
    CHECK(ica::decide("", sa, b).action == Action::reject);    // PEM does not match the hash
    CHECK(ica::decide("", sa, "garbage").action == Action::reject);
    const std::string sl = *crypto::cert_fingerprint(leaf);
    CHECK(ica::decide("", sl, leaf).action == Action::reject);  // CA:false
    CHECK(crypto::cert_is_ca(a));
    CHECK_FALSE(crypto::cert_is_ca(leaf));
    CHECK(ica::path_for((fs::path("d") / "ca.crt").string()) == (fs::path("d") / "interception-ca.crt").string());
}

TEST_CASE("agent installs, replaces and removes the interception CA") {
    const fs::path dir = fs::temp_directory_path() / ("xgi-" + random_hex(4));
    fs::create_directories(dir);
    const std::string lab = make_cert("Lab CA", true);
    REQUIRE(write_file_atomic((dir / "ca.crt").string(), lab));
    ServicePlatform plat;
    plat.system = std::make_unique<test::FakeSystem>();
    auto trust = std::make_unique<FakeTrust>();
    FakeTrust* t = trust.get();
    plat.trust = std::move(trust);
    Config cfg = Config::defaults();
    cfg.data_dir = dir.string();
    cfg.ca_file = (dir / "ca.crt").string();
    const std::string file = ica::path_for(cfg.ca_file);
    const std::string a = make_cert("Interception A", true), b = make_cert("Interception B", true);
    const std::string sa = *crypto::cert_fingerprint(a), sb = *crypto::cert_fingerprint(b);
    {
        Agent agent(cfg, (dir / "agent.toml").string(), plat);

        t->fail_install = true;   // a failed OS install leaves no file, so the next policy retries
        agent.apply_interception_ca(sa, a);
        CHECK_FALSE(fs::exists(file));
        t->fail_install = false;
        agent.apply_interception_ca(sa, a);
        REQUIRE(t->installed == std::vector<std::string>{sa});
        CHECK(read_file(file) == a);

        agent.apply_interception_ca(sa, a);   // unchanged: nothing happens
        CHECK(t->installed.size() == 1);

        agent.apply_interception_ca(sb, a);   // PEM does not match: rejected, A stays
        CHECK(read_file(file) == a);

        agent.apply_interception_ca(sb, b);   // replace: B in, then A out
        CHECK(t->installed == std::vector<std::string>{sa, sb});
        CHECK(t->removed == std::vector<std::string>{sa});
        CHECK(read_file(file) == b);

        agent.apply_interception_ca("", "");   // the CCC has none any more
        CHECK(t->removed == std::vector<std::string>{sa, sb});
        CHECK_FALSE(fs::exists(file));
        CHECK(read_file(cfg.ca_file) == lab);   // the lab CA is never touched
    }
    fs::remove_all(dir);
}
