# Go WebSocket screen-streaming relay for XephyGuard (port 8082).
FROM golang:1.27.4-bookworm@sha256:ce59b41415e2524ae99926fe1f37ce48ba8c194dcbd2a56a65436cdcefa2bd34 AS builder
ENV GOTOOLCHAIN=local
WORKDIR /src
COPY xephyguard-screen/gateway/go.mod xephyguard-screen/gateway/go.sum ./
RUN go mod download
COPY xephyguard-screen/gateway/*.go ./
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/xephyguard-screen-gateway .

FROM debian:bookworm-20261123-slim@sha256:e67eeead736ff7bbe258ef088bff683635c561b1fcfefad0806c1df4ab49ce0e
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=builder /out/xephyguard-screen-gateway /usr/local/bin/xephyguard-screen-gateway
USER nobody
CMD ["/usr/local/bin/xephyguard-screen-gateway"]
