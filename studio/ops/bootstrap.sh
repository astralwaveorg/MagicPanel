#!/usr/bin/env bash
# Run on NAS. The old DB is opened with mode=ro. No files in the old project are replaced.
set -euo pipefail
umask 077
: "${STUDIO_ROOT:=/opt/magicpanel-v2}"
: "${STUDIO_CODE:=$STUDIO_ROOT/bootstrap/code}"
: "${STUDIO_STATE:=$STUDIO_ROOT/bootstrap/data}"
: "${LEGACY_STATE:=/opt/magicpanel/data}"
mkdir -p "$STUDIO_STATE"
snap=$(mktemp -d "$STUDIO_ROOT/.import-XXXXXXXX")
trap 'rm -rf -- "$snap"' EXIT
python3 - "$LEGACY_STATE/magicpanel.db" "$snap/magicpanel.db" <<'PY'
from pathlib import Path
import sqlite3,sys
src=sqlite3.connect(Path(sys.argv[1]).as_uri()+"?mode=ro",uri=True,timeout=10)
dst=sqlite3.connect(sys.argv[2])
src.backup(dst)
dst.execute("PRAGMA journal_mode=DELETE")
dst.close()
src.close()
PY
cp "$LEGACY_STATE/secret.key" "$snap/secret.key"
mkdir "$snap/builds"
docker run --rm --network none --user "$(id -u):$(id -g)" --read-only \
  --tmpfs /tmp:rw,nosuid,nodev,size=192m -v "$snap:/legacy:ro" \
  -v "$LEGACY_STATE/builds:/legacy/builds:ro" -v "$STUDIO_CODE:/code:ro" \
  -v "$STUDIO_STATE:/var/lib/magicpanel-studio" -e PYTHONPATH=/code:/app \
  -e PYTHONDONTWRITEBYTECODE=1 --entrypoint python "$(docker inspect magicpanel --format '{{.Image}}')" \
  -m studio.ops.import_v1
