# The `culprit` binary as an image (Phase 30) — for the optional capture
# agent in infra/docker-compose.prod.yml, and for anyone who would rather
# `docker run` it than install it.
#
# One static binary (CGO_ENABLED=0, D2) on distroless/static: no shell, no
# package manager, nothing to exploit but the binary itself, and the CA
# bundle `culprit env capture`'s certificate check verifies against. Runs
# as nonroot. Build context is cli/ (see the build matrix in
# .github/workflows/ci-cd.yml).
#
# There is no `docker` or `kubectl` in here, deliberately. The agent in
# docker-compose.prod.yml uses the `process` adapter — it reads the
# environment it is started with, from the same .env.prod the api reads —
# so it needs neither, and in particular never needs the Docker socket
# mounted, which would hand a capture tool root on the host.

FROM golang:1.27-alpine AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
ARG VERSION=dev
RUN CGO_ENABLED=0 go build -trimpath -ldflags "-s -w -X main.Version=${VERSION}" \
    -o /out/culprit ./cmd/culprit

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /out/culprit /culprit
ENTRYPOINT ["/culprit"]
