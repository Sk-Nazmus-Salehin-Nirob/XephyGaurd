#pragma once
#include <map>
#include <memory>
#include <string>

#include "xg/tls.hpp"

namespace xg::net {

struct HttpResponse {
    int status = 0;
    std::map<std::string, std::string> headers;   // lowercase names
    std::string body;
    std::string error;                            // transport error, status == 0
    bool ok() const { return status >= 200 && status < 300; }
};

/// Minimal HTTP/1.1 client over TLS with keep-alive, Content-Length and chunked bodies.
class HttpsClient {
public:
    HttpsClient(std::string host, uint16_t port, TlsOptions opts);
    ~HttpsClient();
    HttpResponse request(const std::string& method, const std::string& path, const std::string& body = {},
                         const std::map<std::string, std::string>& headers = {});
    void set_bearer(std::string token) { bearer_ = std::move(token); }
    void reset();

private:
    HttpResponse do_request(const std::string& method, const std::string& path, const std::string& body,
                            const std::map<std::string, std::string>& headers);
    std::string host_;
    uint16_t port_;
    TlsOptions opts_;
    std::string bearer_;
    std::unique_ptr<TlsConnection> conn_;
};

inline constexpr size_t kMaxHeaderBytes = 64 * 1024;
inline constexpr size_t kMaxBodyBytes = 32 * 1024 * 1024;

/// Parses a raw HTTP response held in `raw`. Exposed for tests. Returns false if incomplete or malformed;
/// `malformed` (optional) is set when more bytes cannot help (bad status, non-numeric or oversized lengths).
/// Never throws: the input may come from any local process (LLM port probes).
bool parse_http_response(const std::string& raw, HttpResponse& out, size_t* consumed, bool* malformed = nullptr);
/// Plain-HTTP GET (used once, to fetch the CA certificate before it is trusted; result is pinned).
HttpResponse http_get_plain(const std::string& host, uint16_t port, const std::string& path, int timeout_ms = 5000);

}  // namespace xg::net
