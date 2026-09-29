#!/usr/bin/env bash
# Install the pinned Node.js LTS toolchain into <repo>/.tools/node.
#
#   frontend/scripts/install-node.sh
#   export PATH="$(git rev-parse --show-toplevel)/.tools/node/bin:$PATH"   # then: npm ci
#
# * The version is pinned in frontend/.nvmrc (currently the Node 24 "Krypton" LTS line).
# * Idempotent: does nothing when the pinned version is already installed.
# * The tarball is downloaded from nodejs.org and its SHA-256 is verified against the published
#   SHASUMS256.txt of that release before anything is extracted. A mismatch aborts the install.
# * Nothing outside <repo>/.tools is touched (no global install, no sudo).
#
# Environment overrides (rarely needed): NODE_DIST_URL (mirror of https://nodejs.org/dist),
# AEGIS_TOOLS_DIR (default <repo>/.tools).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${FRONTEND_DIR}/.." && pwd)"
TOOLS_DIR="${AEGIS_TOOLS_DIR:-${REPO_ROOT}/.tools}"
NODE_DIR="${TOOLS_DIR}/node"
DIST_URL="${NODE_DIST_URL:-https://nodejs.org/dist}"

log() { printf '[install-node] %s\n' "$*"; }
die() { printf '[install-node] ERROR: %s\n' "$*" >&2; exit 1; }

[[ -r "${FRONTEND_DIR}/.nvmrc" ]] || die "missing ${FRONTEND_DIR}/.nvmrc"
VERSION="$(tr -d '[:space:]' < "${FRONTEND_DIR}/.nvmrc")"
VERSION="${VERSION#v}"
[[ "${VERSION}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die ".nvmrc must contain an exact version such as 24.21.0 (got '${VERSION}')"

[[ "$(uname -s)" == "Linux" ]] || die "only Linux is supported by this script (got $(uname -s))"
case "$(uname -m)" in
  x86_64 | amd64) PLATFORM="linux-x64" ;;
  aarch64 | arm64) PLATFORM="linux-arm64" ;;
  *) die "unsupported CPU architecture: $(uname -m)" ;;
esac

# Idempotence: an installed toolchain with the pinned version is left alone.
if [[ -x "${NODE_DIR}/bin/node" ]] && [[ "$("${NODE_DIR}/bin/node" --version 2>/dev/null || true)" == "v${VERSION}" ]]; then
  log "Node v${VERSION} already installed at ${NODE_DIR}"
  exit 0
fi

command -v curl > /dev/null || die "curl is required"
if command -v sha256sum > /dev/null; then
  sha256() { sha256sum "$1" | awk '{print $1}'; }
elif command -v shasum > /dev/null; then
  sha256() { shasum -a 256 "$1" | awk '{print $1}'; }
else
  die "sha256sum (or shasum) is required to verify the download"
fi

# Prefer the smaller .tar.xz; fall back to .tar.gz when xz is unavailable.
if command -v xz > /dev/null; then EXT="tar.xz"; else EXT="tar.gz"; fi
BASENAME="node-v${VERSION}-${PLATFORM}"
TARBALL="${BASENAME}.${EXT}"

mkdir -p "${TOOLS_DIR}"
WORK="$(mktemp -d "${TOOLS_DIR}/.node-install.XXXXXX")"
trap 'rm -rf "${WORK}"' EXIT

log "downloading ${TARBALL} (Node v${VERSION}, ${PLATFORM}) from ${DIST_URL}"
curl -fsSL --retry 3 --retry-delay 2 -o "${WORK}/SHASUMS256.txt" "${DIST_URL}/v${VERSION}/SHASUMS256.txt" \
  || die "could not download SHASUMS256.txt for v${VERSION}"
curl -fSL --retry 3 --retry-delay 2 --progress-bar -o "${WORK}/${TARBALL}" "${DIST_URL}/v${VERSION}/${TARBALL}" \
  || die "could not download ${TARBALL}"

EXPECTED="$(awk -v f="${TARBALL}" '$2 == f { print $1 }' "${WORK}/SHASUMS256.txt")"
[[ -n "${EXPECTED}" ]] || die "${TARBALL} is not listed in the published SHASUMS256.txt"
ACTUAL="$(sha256 "${WORK}/${TARBALL}")"
if [[ "${ACTUAL}" != "${EXPECTED}" ]]; then
  die "SHA-256 mismatch for ${TARBALL}: expected ${EXPECTED}, got ${ACTUAL}"
fi
log "SHA-256 verified: ${ACTUAL}"

log "extracting"
tar -xf "${WORK}/${TARBALL}" -C "${WORK}"
[[ -x "${WORK}/${BASENAME}/bin/node" ]] || die "archive did not contain ${BASENAME}/bin/node"

rm -rf "${NODE_DIR}"
mv "${WORK}/${BASENAME}" "${NODE_DIR}"

INSTALLED="$("${NODE_DIR}/bin/node" --version)"
[[ "${INSTALLED}" == "v${VERSION}" ]] || die "installed node reports ${INSTALLED}, expected v${VERSION}"
# npm's shebang is `#!/usr/bin/env node`, so the new toolchain must be on PATH to run it.
NPM_VERSION="$(PATH="${NODE_DIR}/bin:${PATH}" npm --version)"
log "installed node ${INSTALLED} and npm ${NPM_VERSION} into ${NODE_DIR}"
log "use it with:  export PATH=\"${NODE_DIR}/bin:\$PATH\""
