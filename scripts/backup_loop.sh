#!/usr/bin/env bash
# 备份守护循环：先备份、再等待，间隔 BACKUP_INTERVAL 秒（默认 6 小时）。
#
# 2026-11-05 修改：原先是「先 sleep 再备份」，容器每次重启都要等满一个
# INTERVAL 才做第一次备份。NAS 2026-11-04 重启后备份实际停了 52 小时
# （最后一次 11-03 16:03，下次要等到 11-06 02:46），期间磁盘若故障，
# 面板里的机场订阅与设备令牌就全丢了。改成先备份再等待：重启即备份，
# 备份间隔也不再被容器生命周期重置。
set -u
INTERVAL="${BACKUP_INTERVAL:-21600}"
while true; do
  if bash /scripts/backup.sh "${MAGICPANEL_DATA_DIR:-/app/data}/backup"; then
    echo "[backup] 完成"
  else
    echo "[backup] 失败（下次重试）"
  fi
  sleep "$INTERVAL" &
  wait $!
done
