#!/usr/bin/env bash
# 备份守护循环：每天执行一次 backup.sh。
set -u
INTERVAL="${BACKUP_INTERVAL:-86400}"
while true; do
  sleep "$INTERVAL" &
  wait $!
  if bash /scripts/backup.sh "${MAGICPANEL_DATA_DIR:-/app/data}/backup"; then
    echo "[backup] 完成"
  else
    echo "[backup] 失败（下次重试）"
  fi
done
