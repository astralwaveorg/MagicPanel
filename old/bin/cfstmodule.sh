#!/bin/bash

# ========== 环境变量配置 ==========

# 1. 基础路径配置
CFST_WORK_DIR="/home/archon/cfst"
REPO_DIR="/home/archon/cfst/MagicHub"
MODULE_FILE="$REPO_DIR/surge/modules/cfst.sgmodule"
CSV_FILE="$CFST_WORK_DIR/result_auto.csv"

# 2. 需要加速的域名列表
# 既支持具体域名，也支持泛域名 (如 *.cloudflare.com)
DOMAINS=("panel.eoysky.com" "vw.eoysky.com" "list.eoysky.com" "*.cloudflare.com")

# 3. CloudflareSpeedTest 测速参数
CMD_ARGS="-tp 443 -tl 250 -dn 5 -dt 10 -n 200 -httping -o $CSV_FILE"

# =========== 脚本逻辑 ============

echo "[$(date '+%Y-%m-%d %H:%M:%S')] 🚀 开始执行 Cloudflare 优选流程..."

# 0. 停止代理 (确保测速环境纯净)
echo "🛑 正在停止 mihomo 代理服务..."
sudo systemctl stop mihomo

# 1. 进入测速目录
cd "$CFST_WORK_DIR" || { echo "❌ 无法进入目录 $CFST_WORK_DIR"; exit 1; }

# 2. 执行测速
echo "👉 正在运行测速..."
chmod +x ./cfst
./cfst $CMD_ARGS > /dev/null 2>&1

# 3. 提取 Top 3 IP 并格式化
# 提取 CSV 第一列 IP，取前3个，合并为 "IP1, IP2, IP3"
BEST_IPS=$(awk -F, 'NR>1 {print $1}' "$CSV_FILE" | head -n 3 | paste -sd ", " -)

if [[ -z "$BEST_IPS" ]]; then
    echo "❌ 错误：未能提取到有效 IP。"
    # 即使失败也要尝试恢复代理，防止断网
    echo "🔄 尝试恢复 mihomo..."
    sudo systemctl start mihomo
    exit 1
fi

echo "✅ 优选 IP (Top 3): $BEST_IPS"

# 4. 准备域名列表字符串 (用于 MITM)
IFS="," 
MITM_DOMAINS="${DOMAINS[*]}"
MITM_DOMAINS=${MITM_DOMAINS//,/, }
unset IFS

# 5. 生成 Surge Module 文件
echo "👉 正在生成 Surge 模块..."

cat > "$MODULE_FILE" <<EOF
#!name=Cloudflare 优选
#!desc=自动优选 IP 更新。更新时间: $(date "+%Y-%m-%d %H:%M:%S")
#!category=Auto Generated

[Rule]
# 智能判断: 泛域名使用 DOMAIN-SUFFIX，普通域名使用 DOMAIN
EOF

# --- 智能 Rule 生成逻辑 (优化点) ---
for domain in "${DOMAINS[@]}"; do
    if [[ "$domain" == \*\.* ]]; then
        # 如果是泛域名 (*.cloudflare.com)，去除 "*." 前缀并使用 DOMAIN-SUFFIX
        clean_domain="${domain#*.}"
        echo "DOMAIN-SUFFIX,$clean_domain,DIRECT" >> "$MODULE_FILE"
    else
        # 如果是普通域名，使用 DOMAIN
        echo "DOMAIN,$domain,DIRECT" >> "$MODULE_FILE"
    fi
done

cat >> "$MODULE_FILE" <<EOF

[Host]
# 为所有域名映射 Top 3 优选 IP
EOF

# --- Host 生成逻辑 ---
for domain in "${DOMAINS[@]}"; do
    echo "$domain = $BEST_IPS" >> "$MODULE_FILE"
done

cat >> "$MODULE_FILE" <<EOF

[MITM]
hostname = %APPEND% $MITM_DOMAINS
EOF

echo "✅ 模块文件已更新"

# 6. Git 推送
echo "👉 正在推送到 GitHub..."
cd "$REPO_DIR" || { echo "❌ 无法进入 Git 目录"; exit 1; }

if [[ -n $(git status -s "$MODULE_FILE") ]]; then
    git add "$MODULE_FILE"
    git commit -m "🚀 Auto update CF IPs [$(date +%F_%T)]"
    git push origin main
    echo "🎉 推送成功！"
else
    echo "⚠️ 无变化，跳过推送。"
fi

# 7. 恢复代理
echo "🟢 正在启动 mihomo 代理服务..."
sudo systemctl start mihomo

echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✅ 全部完成。"
