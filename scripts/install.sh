#!/usr/bin/env sh
# Install the `culprit` CLI.
#
#   curl -fsSL https://raw.githubusercontent.com/Josh-Heath123/Culprit/main/scripts/install.sh | sh
#
# Acceptance criterion 5 of docs/DIAGNOSTIC_PLAN.md Phase 28: "one static
# binary, no runtime installed, `curl | sh` documented".
#
# POSIX sh, not bash: this runs on whatever the machine has, including a
# minimal CI image and Alpine's ash. `set -eu` and nothing fancier.
#
# It downloads one static binary and puts it somewhere on PATH. There is
# no runtime to install, nothing to compile, and no package manager
# involved — that is the whole point of Go here (D2), and the reason the
# CLI has no cgo dependency.
#
# **On piping to a shell.** Running an arbitrary script from the internet
# with your privileges is a real risk, and telling you it is fine would
# be dishonest. If you would rather not: read this file first (it is
# short), or skip it entirely and download the binary from the releases
# page yourself — the URLs it constructs are printed below and there is
# nothing else to the installation.
set -eu

REPO="Josh-Heath123/Culprit"
BIN="culprit"
VERSION="${CULPRIT_VERSION:-latest}"
INSTALL_DIR="${CULPRIT_INSTALL_DIR:-}"

say() { printf '%s\n' "$*"; }
die() { printf 'culprit: %s\n' "$*" >&2; exit 1; }

need() {
    command -v "$1" >/dev/null 2>&1 || die "$1 is required and was not found"
}

detect_platform() {
    os=$(uname -s | tr '[:upper:]' '[:lower:]')
    arch=$(uname -m)
    case "$os" in
        linux)   os=linux ;;
        darwin)  os=darwin ;;
        msys*|mingw*|cygwin*) os=windows ;;
        *) die "unsupported operating system: $os. Build from source: cd cli && go build ./cmd/culprit" ;;
    esac
    case "$arch" in
        x86_64|amd64) arch=amd64 ;;
        arm64|aarch64) arch=arm64 ;;
        *) die "unsupported architecture: $arch. Build from source: cd cli && go build ./cmd/culprit" ;;
    esac
    printf '%s %s' "$os" "$arch"
}

# Where to put it. A directory the user already owns is strongly
# preferred to anything needing sudo: an installer that asks for root to
# drop one static binary is asking for more than it needs.
choose_install_dir() {
    if [ -n "$INSTALL_DIR" ]; then
        printf '%s' "$INSTALL_DIR"
        return
    fi
    for candidate in "$HOME/.local/bin" "$HOME/bin"; do
        if [ -d "$candidate" ] && [ -w "$candidate" ]; then
            printf '%s' "$candidate"
            return
        fi
    done
    printf '%s' "$HOME/.local/bin"
}

resolve_version() {
    if [ "$VERSION" != "latest" ]; then
        printf '%s' "$VERSION"
        return
    fi
    # The redirect target of /releases/latest is the tag. No jq, no API
    # token, no rate limit worth worrying about.
    tag=$(curl -fsSLI -o /dev/null -w '%{url_effective}' \
        "https://github.com/${REPO}/releases/latest" 2>/dev/null | sed 's#.*/tag/##') || true
    [ -n "${tag:-}" ] || die "could not determine the latest release. Set CULPRIT_VERSION=vX.Y.Z."
    printf '%s' "$tag"
}

main() {
    need curl
    need uname

    platform=$(detect_platform)
    os=${platform% *}
    arch=${platform#* }

    tag=$(resolve_version)
    bare=${tag#v}
    ext=""
    [ "$os" = "windows" ] && ext=".exe"

    asset="${BIN}_${bare}_${os}_${arch}${ext}"
    url="https://github.com/${REPO}/releases/download/${tag}/${asset}"
    checksums="https://github.com/${REPO}/releases/download/${tag}/checksums.txt"

    dir=$(choose_install_dir)
    mkdir -p "$dir"

    tmp=$(mktemp -d 2>/dev/null || mktemp -d -t culprit)
    trap 'rm -rf "$tmp"' EXIT INT TERM

    say "==> Downloading $asset ($tag)"
    curl -fsSL "$url" -o "$tmp/$BIN$ext" \
        || die "download failed: $url — check that $tag has a build for ${os}/${arch}"

    # Verified when a checksums file is published, and loudly skipped
    # when it is not. A silent absence of verification is worse than no
    # verification, because it looks like verification happened.
    if curl -fsSL "$checksums" -o "$tmp/checksums.txt" 2>/dev/null; then
        if command -v sha256sum >/dev/null 2>&1; then
            (cd "$tmp" && grep " ${asset}\$" checksums.txt | sha256sum -c -) \
                || die "checksum mismatch for $asset — do not use this download"
            say "==> Checksum verified"
        elif command -v shasum >/dev/null 2>&1; then
            (cd "$tmp" && grep " ${asset}\$" checksums.txt | shasum -a 256 -c -) \
                || die "checksum mismatch for $asset — do not use this download"
            say "==> Checksum verified"
        else
            say "==> No sha256sum or shasum available; checksum NOT verified"
        fi
    else
        say "==> No checksums.txt published for $tag; checksum NOT verified"
    fi

    chmod +x "$tmp/$BIN$ext"
    mv "$tmp/$BIN$ext" "$dir/$BIN$ext"

    say "==> Installed $dir/$BIN$ext"
    "$dir/$BIN$ext" --version || true

    case ":$PATH:" in
        *":$dir:"*) ;;
        *)
            say ""
            say "$dir is not on your PATH. Add it:"
            say "    export PATH=\"$dir:\$PATH\""
            ;;
    esac

    say ""
    say "Next: run it in a repository with a culprit.yaml."
    say "    culprit intent"
    say "See docs/EXTRACTOR_PROTOCOL.md for what it reads and what it never reads."
}

main "$@"
