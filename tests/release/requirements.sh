#!/usr/bin/env bash
# The release's hash-locked comfyctl requirements file (#175): write it, then
# prove it installs. The release job runs this on a `v*` tag, and the
# `release-requirements` job runs it on every PR that touches what the file is
# made from, so a tag runs nothing a PR has not. Only attesting, verifying and
# attaching the file are left to the tag.
#
#   tests/release/requirements.sh <dist dir> <release download URL>
#
#   <dist dir>              holds comfyctl-<version>-py3-none-any.whl, the one
#                           wheel a release ships
#   <release download URL>  where the release serves it, for example
#                           https://github.com/pixeloven/ComfyUI-Docker/releases/download/v1.2.3
#
# Env: COMFYCTL_VERSION (default: the VERSION file).
# Writes <dist dir>/comfyctl-<version>-requirements.txt. Needs uv on PATH.
#
# The wheel names its dependencies by range, so a plain install resolves them
# from PyPI as they are that day. This file pins every one to the version and
# hashes in services/uv.lock, and ends with the wheel itself, by its release URL
# and hash: pip and uv refuse a requirement without a hash in --require-hashes
# mode, the bare wheel included, so this one file is the whole install.
# --no-emit-workspace leaves out the comfyctl line uv would write as a local
# path. comfyrelay is not a comfyctl dependency, so the export never reaches
# it, and the guard below holds that.
set -euo pipefail

if [ "$#" -ne 2 ]; then
  echo "usage: $0 <dist dir> <release download URL>" >&2
  exit 2
fi

root="$(cd "$(dirname "$0")/../.." && pwd)"
dist="$(cd "$1" && pwd)"
url="${2%/}"
version="${COMFYCTL_VERSION:-$(cat "${root}/VERSION")}"
whl="comfyctl-${version}-py3-none-any.whl"
req="${dist}/comfyctl-${version}-requirements.txt"

if [ ! -f "${dist}/${whl}" ]; then
  echo "::error::${dist} has no ${whl}"
  exit 1
fi

(cd "${root}/services" && uv export --package comfyctl --frozen --no-dev --no-emit-workspace) > "${req}"
if grep -q -i '^comfyrelay\|^mcp==' "${req}"; then
  echo "::error::the comfyctl requirements reach comfyrelay"
  exit 1
fi
{
  echo "# comfyctl itself: this release's wheel, by URL and hash."
  echo "comfyctl @ ${url}/${whl} \\"
  echo "    --hash=sha256:$(sha256sum "${dist}/${whl}" | cut -d' ' -f1)"
} >> "${req}"

# The install the comfyctl README gives, into a clean venv. The wheel's release
# URL does not exist until the release does, so this copy points its line at the
# wheel in <dist dir>; the hash it is checked against is the one the file carries.
tmp="$(mktemp -d)"
trap 'rm -rf "${tmp}"' EXIT
sed "s#^comfyctl @ ${url}/${whl} #comfyctl @ file://${dist}/${whl} #" "${req}" > "${tmp}/requirements.txt"
if ! grep -q "^comfyctl @ file://" "${tmp}/requirements.txt"; then
  echo "::error::the requirements file has no comfyctl wheel line"
  exit 1
fi
uv venv -q "${tmp}/venv"
uv pip install -q --python "${tmp}/venv" --require-hashes -r "${tmp}/requirements.txt"
got="$("${tmp}/venv/bin/comfyctl" --version)"
if [ "${got}" != "${version}" ]; then
  echo "::error::the hash-checked install reports ${got}, not ${version}"
  exit 1
fi
echo "requirements ok: ${req##*/} installs with --require-hashes and reports ${version}"
