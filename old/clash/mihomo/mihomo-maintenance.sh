#!/bin/bash
# Mihomo 每日重启前维护脚本
# 在 03:20 重启前执行：同步远程配置 → 更新 providers → 重启服务

MIHOMO_DIR="/etc/mihomo"
API="http://127.0.0.1:9090"
SECRET="rain8240"
AUTH_HEADER="Authorization: Bearer ${SECRET}"
LOG="${MIHOMO_DIR}/logs/maintenance.log"
REMOTE_CONFIG="https://list.magichub.top/d/clash/mihomo/config.yaml"
LOCAL_CONFIG="${MIHOMO_DIR}/config.yaml"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') $1" >> "${LOG}"
}

log "=== Daily maintenance start ==="

# 同步远程配置文件
HTTP_CODE=$(curl -s -o /tmp/mihomo_remote_config.yaml -w '%{http_code}' \
    -H "Cache-Control: no-cache" \
    --connect-timeout 10 --max-time 30 \
    "${REMOTE_CONFIG}" 2>/dev/null)

if [ "${HTTP_CODE}" = "200" ]; then
    REMOTE_MD5=$(md5sum /tmp/mihomo_remote_config.yaml | cut -d' ' -f1)
    LOCAL_MD5=$(md5sum "${LOCAL_CONFIG}" | cut -d' ' -f1)
    if [ "${REMOTE_MD5}" != "${LOCAL_MD5}" ]; then
        cp "${LOCAL_CONFIG}" "${LOCAL_CONFIG}.bak.$(date +%Y%m%d%H%M%S)"
        cp /tmp/mihomo_remote_config.yaml "${LOCAL_CONFIG}"
        log "OK: config updated from remote"
    else
        log "OK: config already up-to-date"
    fi
else
    log "WARN: remote config fetch failed (HTTP ${HTTP_CODE}), using local"
fi

# 重启服务（使用新配置）
systemctl restart mihomo
sleep 5

# 验证服务启动
if systemctl is-active --quiet mihomo; then
    log "OK: mihomo restarted successfully"
else
    log "FATAL: mihomo failed to start after restart"
    exit 1
fi

# 更新 proxy-providers（重启后节点列表可能已变化）
for provider in Airport_01 Airport_02 Airport_03; do
    curl -s -X PUT -H "${AUTH_HEADER}" "${API}/providers/proxies/${provider}" >/dev/null 2>&1
    log "OK: proxy-provider ${provider} updated"
done

# 清理旧备份文件（保留最近3份）
ls -t "${MIHOMO_DIR}"/config.yaml.bak.* 2>/dev/null | tail -n +4 | xargs -r rm -f

log "=== Daily maintenance done ==="
