# Multi-stage: build the SPA with Node, then serve it from a Caddy image
# that also reverse-proxies to the api container — see Caddyfile's
# comment for why this is one image/container, not build-artifact-plus-
# separate-nginx.

FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .

# Baked in at build time (Vite env vars are compile-time, not runtime).
# "/api" is a same-origin relative path — Caddy's reverse proxy makes it
# resolve correctly regardless of what {$DOMAIN} actually is, so this
# never needs to change per-deployment.
ARG VITE_API_URL=/api
ENV VITE_API_URL=${VITE_API_URL}
RUN npm run build

# Caddy, rebuilt from source. The binary in the published caddy:2-alpine
# image is compiled with whatever Go toolchain and module versions it
# shipped with, and on 2026-09-11 Trivy found 12 CRITICAL/HIGH CVEs in it
# (Go stdlib, golang.org/x/crypto, golang.org/x/net, grpc) with no newer
# upstream image to move to. Building the same Caddy release on a current
# toolchain with those modules pinned forward removes them instead of
# accepting them in .trivyignore. Same Go as cli/Dockerfile. When bumping
# CADDY_VERSION, drop any --replace the new release already satisfies.
FROM golang:1.27-alpine AS caddy
#
# v2.11.7 (2026-11-03) already requires x/crypto v0.57.0 and grpc v1.83.2,
# so those two pins were dropped. It still asks for x/net v0.59.0 and
# go-jose/v4 v4.1.5, both behind their CVE fixes.
ARG CADDY_VERSION=v2.11.7
RUN go install github.com/caddyserver/xcaddy/cmd/xcaddy@v0.4.7
RUN CGO_ENABLED=0 xcaddy build ${CADDY_VERSION} --output /usr/bin/caddy \
      --replace golang.org/x/net=golang.org/x/net@v0.60.0 \
      --replace github.com/go-jose/go-jose/v4=github.com/go-jose/go-jose/v4@v4.1.6

FROM caddy:2-alpine
# c-ares/curl/libcurl in the published caddy:2-alpine image lag Alpine's
# own patched package index — re-running apk upgrade at build time picks
# up whatever's actually current in the repo instead of what shipped in
# the base image. The caddy binary itself is replaced below, from the
# stage above.
RUN apk update && apk upgrade --no-cache
COPY --from=caddy /usr/bin/caddy /usr/bin/caddy
COPY --from=build /app/dist /srv
COPY Caddyfile /etc/caddy/Caddyfile
