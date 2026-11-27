// Interception CA in the Local Machine "Root" store (Chrome, Edge, and Firefox through ImportEnterpriseRoots).
#include "win_common.hpp"   // windows.h first: wincrypt.h needs its types

#include <wincrypt.h>

#include <vector>

#include "xg/crypto.hpp"
#include "xg/log.hpp"

namespace xg::win {

namespace {
HCERTSTORE open_root() {
    return CertOpenStore(CERT_STORE_PROV_SYSTEM_W, 0, 0, CERT_SYSTEM_STORE_LOCAL_MACHINE, L"ROOT");
}

class WinTrustStore final : public ITrustStore {
public:
    bool install(const std::string& pem, const std::string& /*sha*/) override {
        DWORD len = 0;
        if (!CryptStringToBinaryA(pem.c_str(), DWORD(pem.size()), CRYPT_STRING_BASE64HEADER, nullptr, &len, nullptr,
                                  nullptr))
            return false;
        std::vector<BYTE> der(len);
        if (!CryptStringToBinaryA(pem.c_str(), DWORD(pem.size()), CRYPT_STRING_BASE64HEADER, der.data(), &len,
                                  nullptr, nullptr))
            return false;
        HCERTSTORE store = open_root();
        if (!store) {
            log::error("trust: cannot open the Root store: {}", last_error_text());
            return false;
        }
        const BOOL ok = CertAddEncodedCertificateToStore(store, X509_ASN_ENCODING, der.data(), len,
                                                         CERT_STORE_ADD_REPLACE_EXISTING, nullptr);
        if (!ok) log::error("trust: cannot add the interception CA: {}", last_error_text());
        CertCloseStore(store, 0);
        return ok != FALSE;
    }

    bool remove(const std::string& sha) override {
        HCERTSTORE store = open_root();
        if (!store) return false;
        bool ok = true;
        PCCERT_CONTEXT ctx = nullptr;
        while ((ctx = CertEnumCertificatesInStore(store, ctx)) != nullptr) {
            const std::string der(reinterpret_cast<const char*>(ctx->pbCertEncoded), ctx->cbCertEncoded);
            if (crypto::sha256_hex(der) != sha) continue;
            // Delete a duplicate so the enumeration context stays valid.
            if (!CertDeleteCertificateFromStore(CertDuplicateCertificateContext(ctx))) ok = false;
        }
        CertCloseStore(store, 0);
        return ok;
    }
};
}  // namespace

std::unique_ptr<ITrustStore> make_trust_store() { return std::make_unique<WinTrustStore>(); }

}  // namespace xg::win
