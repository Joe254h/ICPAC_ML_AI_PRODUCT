#!/usr/bin/env bash
# Read CHIRPS from CHC on this machine and publish it on the repository's chirps-relay
# branch, which the forecast service reads over HTTPS (scripts/chirps_relay.py).
#
# Runs in GitHub Actions (.github/workflows/chirps-relay.yml) and on any machine CHC serves,
# such as the ICPAC HPC:
#
#   GITHUB_TOKEN=<token with Contents: write on the repository> \
#     scripts/chirps_relay.sh ~/chirps-relay
#
# Files already on the branch are kept (a day read by another machine is not lost); each
# run adds what it could read and replaces preliminary days with final ones.
set -euo pipefail
store="${1:?usage: chirps_relay.sh STORE_FOLDER [OWNER/REPO]}"
repo="${2:-Joe254h/ICPAC_ML_AI_PRODUCT}"
# Where the branch is read from and pushed to (a local folder in tests).
remote="${CHIRPS_RELAY_REMOTE:-https://github.com/${repo}.git}"
push="${CHIRPS_RELAY_REMOTE:-https://x-access-token:${GITHUB_TOKEN:-}@github.com/${repo}.git}"
here="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$store"
store="$(cd "$store" && pwd)"

# What the branch already holds: keep it, without overwriting newer local files.
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
if git clone -q --depth 1 -b chirps-relay "$remote" "$work/branch" 2>/dev/null; then
  rm -rf "$work/branch/.git"
  cp -rn "$work/branch/." "$store/"
fi

(cd "$here" && python -m scripts.chirps_relay --store "$store" \
  --days "${CHIRPS_RELAY_DAYS:-120}" --dekads "${CHIRPS_RELAY_DEKADS:-18}")

if [ -z "$(ls -A "$store/daily" 2>/dev/null)" ] && [ -z "$(ls -A "$store/dekad" 2>/dev/null)" ]; then
  echo "Nothing relayed yet; nothing to publish."
  exit 0
fi
mkdir "$work/publish"
cp "$store/index.json" "$work/publish/"
[ -d "$store/daily" ] && cp -r "$store/daily" "$work/publish/"
[ -d "$store/dekad" ] && cp -r "$store/dekad" "$work/publish/"
cat > "$work/publish/README.md" <<'TXT'
CHIRPS v2.0 relayed for the ICPAC Week-2 service (scripts/chirps_relay.sh), cut to the
region. Source: Climate Hazards Center, UC Santa Barbara. This branch is rewritten by every
relay run.
TXT
cd "$work/publish"
git init -q -b chirps-relay
git add -A
git -c user.name="CHIRPS relay" -c user.email="chirps-relay@users.noreply.github.com" \
  commit -qm "CHIRPS relay $(date -u +%Y-%m-%dT%H:%MZ) from $(hostname -s 2>/dev/null || echo runner)"
[ -n "${CHIRPS_RELAY_REMOTE:-}${GITHUB_TOKEN:-}" ] || { echo "Set GITHUB_TOKEN to publish." >&2; exit 1; }
git push -qf "$push" chirps-relay
echo "Published on ${repo}, branch chirps-relay."
