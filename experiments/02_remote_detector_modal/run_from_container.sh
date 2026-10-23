#!/usr/bin/env bash
# Drive the fully-remote loop from INSIDE the container.
#   capture (scrot, in container) -> Modal CPU (YOLO) -> Pillow annotate -> DeepSeek API
#
# Usage: MODAL_URL=https://... ./run_from_container.sh
set -euo pipefail
cd "$(dirname "$0")"

MODAL_URL="${MODAL_URL:?set MODAL_URL to the deployed Modal endpoint}"
CONTAINER="${CONTAINER:-cua-ui}"
N_CALLS="${N_CALLS:-8}"

read_token() {
  ./.venv/bin/python - "$1" <<'PY'
import pathlib, sys, tomllib
cfg = tomllib.loads(pathlib.Path.home().joinpath(".modal.toml").read_text())
prof = next(v for v in cfg.values() if isinstance(v, dict) and "token_id" in v)
print(prof[sys.argv[1]])
PY
}

CUA_SHARED_SECRET="${CUA_SHARED_SECRET:?set CUA_SHARED_SECRET (same value as the Modal secret)}"
DEEPSEEK_API_KEY="${DEEPSEEK_API_KEY:?set DEEPSEEK_API_KEY}"

umask 077
cat > .env.modal <<EOF
MODAL_URL=${MODAL_URL}
CUA_SHARED_SECRET=${CUA_SHARED_SECRET}
DEEPSEEK_API_KEY=${DEEPSEEK_API_KEY}
N_CALLS=${N_CALLS}
EOF

cleanup() { rm -f .env.modal; }
trap cleanup EXIT

echo "[*] container: ${CONTAINER}"
container cp client_incontainer.py "${CONTAINER}:/tmp/client.py" >/dev/null
container exec --env-file .env.modal "${CONTAINER}" python3 /tmp/client.py

mkdir -p results
for f in run_modal.json annotated.png vlm.md detections_first.json frame.png; do
  container cp "${CONTAINER}:/tmp/out/${f}" "results/${f}" >/dev/null 2>&1 || true
done
echo "[*] artifacts copied to results/"
ls -la results
