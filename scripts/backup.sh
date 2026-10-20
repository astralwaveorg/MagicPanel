#!/usr/bin/env bash
# 数据备份：一致性快照 + 主密钥归档 + 轮转保留。
#
# 为什么必须有：面板里存着机场订阅地址、设备令牌、节点凭据的密文，
# 全部依赖 data/secret.key 才能解密。NAS 磁盘故障或误删密钥时，
# 没有备份就等于全量丢失。
#
# 用法（在容器内或 NAS 上执行）：
#   bash scripts/backup.sh [备份目录]
set -euo pipefail

DATA_DIR="${MAGICPANEL_DATA_DIR:-/app/data}"
BACKUP_DIR="${1:-/app/data/backup}"
KEEP="${BACKUP_KEEP:-14}"
STAMP="$(date +%Y%m%d-%H%M%S)"

mkdir -p "$BACKUP_DIR"

# 1) 数据库一致性快照：VACUUM INTO 不会锁住正在使用的库
DB_FILE="$DATA_DIR/magicpanel.db"
if [ ! -f "$DB_FILE" ]; then
  echo "找不到数据库：$DB_FILE" >&2
  exit 1
fi
sqlite3 "$DB_FILE" "VACUUM INTO '$BACKUP_DIR/magicpanel-$STAMP.db'" 2>/dev/null \
  || python3 - "$DB_FILE" "$BACKUP_DIR/magicpanel-$STAMP.db" <<'PY'
import sqlite3, sys
src, dst = sys.argv[1], sys.argv[2]
conn = sqlite3.connect(src)
with conn:
    conn.execute("VACUUM INTO ?", (dst,))
conn.close()
PY

# 2) 主密钥：没有它，备份里的密文全都解不开
if [ -f "$DATA_DIR/secret.key" ]; then
  cp "$DATA_DIR/secret.key" "$BACKUP_DIR/secret-$STAMP.key"
  chmod 600 "$BACKUP_DIR/secret-$STAMP.key"
fi

# 3) 校验快照可读
python3 - "$BACKUP_DIR/magicpanel-$STAMP.db" <<'PY'
import sqlite3, sys
conn = sqlite3.connect(sys.argv[1])
result = conn.execute("PRAGMA integrity_check").fetchone()[0]
conn.close()
if result != "ok":
    raise SystemExit(f"备份校验失败：{result}")
print("备份校验通过")
PY

# 4) 轮转：只保留最近 N 份
ls -1t "$BACKUP_DIR"/magicpanel-*.db 2>/dev/null | tail -n +$((KEEP + 1)) | while read -r old; do
  rm -f "$old"
done
ls -1t "$BACKUP_DIR"/secret-*.key 2>/dev/null | tail -n +$((KEEP + 1)) | while read -r old; do
  rm -f "$old"
done

echo "备份完成：$BACKUP_DIR/magicpanel-$STAMP.db"
