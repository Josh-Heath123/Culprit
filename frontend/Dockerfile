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

FROM caddy:2-alpine
# c-ares/curl/libcurl in the published caddy:2-alpine image lag Alpine's
# own patched package index — re-running apk upgrade at build time picks
# up whatever's actually current in the repo instead of what shipped in
# the base image (see .trivyignore for the CVEs this doesn't cover — those
# are compiled into the caddy binary itself, not an apk package).
RUN apk update && apk upgrade --no-cache c-ares curl libcurl
COPY --from=build /app/dist /srv
COPY Caddyfile /etc/caddy/Caddyfile
