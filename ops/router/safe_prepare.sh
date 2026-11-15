#!/bin/sh
# 固定本机适配器；不接收命令、URL或目标目录，不启动任何服务。
set -eu
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH
umask 077

fail() { printf '%s\n' "${1:-SAFE_ADAPTER_FAILED}" >&2; exit 1; }
sha() { sha256sum "$1" | awk '{print $1}'; }
valid_sha() { [ "${#1}" -eq 64 ] && ! printf '%s' "$1" | LC_ALL=C grep -q '[^0-9a-f]'; }
private_dir() {
    [ ! -L "$1" ] || fail PRIVATE_PATH_SYMLINK
    if [ ! -d "$1" ]; then mkdir -m 700 "$1"; fi
    [ "$(stat -c %u "$1")" = 0 ] || fail PRIVATE_OWNER_REQUIRED
    [ "$(stat -c %a "$1")" = 700 ] || fail PRIVATE_MODE_REQUIRED
}
check_device() {
    [ "$(id -u)" = 0 ] || fail ROUTER_ROOT_REQUIRED
    [ -f /etc/openwrt_release ] && [ -f /etc/board.json ] || fail OPENWRT_REQUIRED
    for tool in uci nft ip conntrack crontab sha256sum tar netstat; do
        command -v "$tool" >/dev/null 2>&1 || fail REQUIRED_COLLECTOR_MISSING
    done
}
state_dir() {
    valid_sha "$1" || fail INVALID_PLAN_SHA
    [ ! -L /root ] || fail PRIVATE_PATH_SYMLINK
    private_dir /root/.magicpanel-safe-preparation
    state=/root/.magicpanel-safe-preparation/$1
    private_dir "$state"
    private_dir "$state/inert"
}
clean_uci() { [ -z "$(uci changes)" ] || fail PENDING_UCI_CHANGES; }
update_keys() {
    uci -X show openclash | awk -F= '
        $1 ~ /^openclash\.config\.(auto_update|geo_auto_update|geoip_auto_update|geosite_auto_update|chnr_auto_update)$/ {print $1}
        $2 == "config_subscribe" || $2 == "\047config_subscribe\047" {
            if ($1 ~ /^openclash\.[a-zA-Z_][a-zA-Z_0-9]*$/ || $1 ~ /^openclash\.@config_subscribe\[[0-9]+\]$/)
                sections[$1]=1
        }
        {keys[$1]=1}
        END {for (section in sections) if ((section ".auto_update") in keys) print section ".auto_update"}
    ' | LC_ALL=C sort -u
}
freeze_cron() {
    LC_ALL=C awk '
    function tokenize(text,out, i,c,q,word,active,escape,n) {
        for(i in out) delete out[i]
        q="";word="";active=0;escape=0;n=0
        for(i=1;i<=length(text);i++) {
            c=substr(text,i,1)
            if(escape) {word=word c;escape=0}
            else if(c=="\\" && q!="\047") {escape=1;active=1}
            else if(q!="") {if(c==q) q="";else word=word c}
            else if(c=="\047" || c=="\042") {q=c;active=1}
            else if(c=="#" && !active) break
            else if(c ~ /[[:space:]]/) {if(active) out[++n]=word;word="";active=0}
            else {word=word c;active=1}
        }
        if(q!="" || escape) return -1
        if(active) out[++n]=word
        return n
    }
    function valid_args(words,start,n, script,count,name,remainder) {
        if(n>=2 && words[n-1]==">/dev/null" && words[n]=="2>&1") n-=2
        else if(n>=3 && words[n-2]==">" && words[n-1]=="/dev/null" && words[n]=="2>&1") n-=3
        script=words[start];count=n-start
        if(script=="/usr/share/openclash/openclash_chnroute.sh") return count==0
        if(script=="/usr/share/openclash/openclash_geo.sh")
            return count==0 || (count==1 && words[start+1] ~ /^(ipdb|geosite|geoip)$/)
        if(count==0) return 1
        name=words[start+1];remainder=name
        gsub(/[A-Za-z0-9_. +\-]/,"",remainder)
        if(length(name)<1 || length(name)>128 || remainder !~ /^[\200-\377]*$/) return 0
        return count==1 || (count==3 && words[start+2]=="loop" && words[start+3] ~ /^[1-9][0-9]*$/ && length(words[start+3])<=9)
    }
    /^[[:space:]]*(#|$)/ {print; next}
    {
        line=$0; command=$0
        if (command ~ /^[[:space:]]*@/) sub(/^[[:space:]]*[^[:space:]]+[[:space:]]+/, "", command)
        else {for (i=0;i<5;i++) sub(/^[[:space:]]*[^[:space:]]+[[:space:]]+/, "", command)}
        n=tokenize(command,words);if(n<0) exit 42
        start=1;if(words[start]=="exec") start++
        if(words[start] ~ /^(\/bin\/)?(ash|sh|bash)$/) start++
        if (words[start] ~ /^\/usr\/share\/openclash\/openclash(_geo|_chnroute)?\.sh$/) {
            if(!valid_args(words,start,n)) exit 42
            print "# magicpanel-safe-preparation " line
        } else {
            if (command ~ /\/usr\/share\/openclash\/openclash(_geo|_chnroute)?\.sh/ && words[1] !~ /^(\/bin\/)?echo$/) exit 42
            print line
        }
    }' "$1"
}
capture() {
    temp=$(mktemp -d /tmp/magicpanel-safe-capture.XXXXXX)
    trap 'rm -rf "$temp"' EXIT HUP INT TERM
    mkdir -m 700 "$temp/files" "$temp/observed"
    # tar 仅作为私密备份传给本机调用者，不展开或执行其中任何文件。
    for path in /etc/config/network /etc/config/dhcp /etc/config/firewall /etc/config/openclash /etc/crontabs/root /etc/board.json; do
        [ -f "$path" ] && [ ! -L "$path" ] || fail BACKUP_COMPONENT_MISSING
    done
    [ -d /etc/openclash ] && [ -f /etc/adguardhome/adguardhome.yaml ] || fail BACKUP_COMPONENT_MISSING
    tar -cf "$temp/files/config.tar" /etc/config /etc/openclash /etc/adguardhome/adguardhome.yaml /etc/crontabs/root /etc/board.json 2>/dev/null
    uci -X show openclash > "$temp/observed/uci.txt"
    uci changes > "$temp/observed/pending.txt"
    uci export network > "$temp/observed/network.txt"
    uci export dhcp > "$temp/observed/dhcp.txt"
    uci export firewall > "$temp/observed/firewall_config.txt"
    cp /etc/config/openclash "$temp/observed/openclash.txt"
    cp /etc/crontabs/root "$temp/observed/crontab.txt"
    cp /etc/board.json "$temp/observed/board.json"
    cp /etc/adguardhome/adguardhome.yaml "$temp/observed/agh.txt"
    nft -j list ruleset > "$temp/observed/nft.json"
    ip -j route show table all > "$temp/observed/routes4.json"
    ip -j -6 route show table all > "$temp/observed/routes6.json"
    ip -j rule show > "$temp/observed/rules4.json"
    ip -j -6 rule show > "$temp/observed/rules6.json"
    sysctl net.ipv4.ip_forward net.ipv6.conf.all.forwarding > "$temp/observed/forwarding.txt"
    netstat -ln > "$temp/observed/listeners.txt"
    conntrack -L -o extended > "$temp/observed/connections.txt" 2>/dev/null
    ps w > "$temp/observed/processes.txt"
    : > "$temp/observed/core.txt"
    for pid in $(pidof clash mihomo 2>/dev/null || true); do
        case "$pid" in ''|*[!0-9]*) fail INVALID_CORE_PID;; esac
        [ -r "/proc/$pid/stat" ] || fail CORE_CHANGED_DURING_CAPTURE
        # stat中的comm可能含空格；去掉最后的右括号前缀后，第20项为starttime。
        start=$(sed 's/.*) //' "/proc/$pid/stat" | awk '{print $20}')
        printf '%s %s\n' "$pid" "$start" >> "$temp/observed/core.txt"
    done
    [ -s "$temp/observed/core.txt" ] || fail CORE_BASELINE_REQUIRED
    # raw、provider缓存和Geo全部备份，Python以文件正文生成稳定摘要。
    tar -cf "$temp/files/openclash.tar" /etc/openclash 2>/dev/null
    tar -C "$temp" -cf - files observed
}
restore_schedule() {
    [ -f "$state/before.config" ] || return 0
    if [ "$(sha /etc/config/openclash)" != "$(sha "$state/before.config")" ]; then
        [ -f "$state/after.config.sha" ] || fail OWNED_ROLLBACK_HASH_REQUIRED
        [ "$(sha /etc/config/openclash)" = "$(cat "$state/after.config.sha")" ] || fail LATER_CHANGE_PRESERVED
        cp "$state/before.config" /etc/config/.magicpanel-openclash.restore
        mv /etc/config/.magicpanel-openclash.restore /etc/config/openclash
    fi
    if [ "$(sha /etc/crontabs/root)" != "$(sha "$state/before.cron")" ]; then
        [ -f "$state/after.cron.sha" ] || fail OWNED_ROLLBACK_HASH_REQUIRED
        [ "$(sha /etc/crontabs/root)" = "$(cat "$state/after.cron.sha")" ] || fail LATER_CHANGE_PRESERVED
        crontab "$state/before.cron"
    fi
    [ "$(sha /etc/config/openclash)" = "$(sha "$state/before.config")" ] || fail OWNED_ROLLBACK_FAILED
    [ "$(sha /etc/crontabs/root)" = "$(sha "$state/before.cron")" ] || fail OWNED_ROLLBACK_FAILED
    clean_uci
}
freeze_updates() {
    clean_uci
    [ ! -e "$state/before.config" ] || fail PREPARATION_ALREADY_ATTEMPTED
    valid_sha "$1" && valid_sha "$2" || fail INVALID_BASELINE_SHA
    [ "$(sha /etc/config/openclash)" = "$1" ] && [ "$(sha /etc/crontabs/root)" = "$2" ] || fail BASELINE_CHANGED
    cp /etc/config/openclash "$state/before.config"
    cp /etc/crontabs/root "$state/before.cron"
    freeze_cron "$state/before.cron" > "$state/candidate.cron" || fail MIXED_UPDATE_CRON
    update_keys > "$state/keys"
    uci -X show openclash > "$state/before.map"
    # 清理只revert本事务的pending，不触碰原本或外部同时新增的字段。
    trap 'while IFS= read -r key; do
        pending=$(uci changes openclash)
        if printf "%s\n" "$pending" | grep -Fqx "$key='"'"'0'"'"'" || printf "%s\n" "$pending" | grep -Fqx "$key=0"; then uci revert "$key"; fi
    done < "$state/keys"
    restore_schedule' EXIT HUP INT TERM
    while IFS= read -r key; do
        value=$(uci get "$key")
        case "$value" in 0) :;; 1) uci set "$key=0";; *) fail INVALID_UPDATE_FIELD;; esac
    done < "$state/keys"
    uci changes openclash > "$state/pending"
    while IFS= read -r line; do
        [ -n "$line" ] || continue
        key=${line%%=*}; grep -Fxq "$key" "$state/keys" || fail UNOWNED_PENDING_UCI_CHANGE
        case "$line" in "$key=0"|"$key='0'") :;; *) fail UNOWNED_PENDING_UCI_CHANGE;; esac
    done < "$state/pending"
    [ "$(sha /etc/config/openclash)" = "$1" ] || fail BASELINE_CHANGED
    uci commit openclash
    sha /etc/config/openclash > "$state/after.config.sha"
    uci -X show openclash > "$state/after.map"
    awk -F= 'NR==FNR {keys[$0]=1;next} !($1 in keys)' "$state/keys" "$state/before.map" > "$state/before.unowned"
    awk -F= 'NR==FNR {keys[$0]=1;next} !($1 in keys)' "$state/keys" "$state/after.map" > "$state/after.unowned"
    cmp -s "$state/before.unowned" "$state/after.unowned" || fail UNOWNED_UCI_CHANGE
    while IFS= read -r key; do [ "$(uci get "$key")" = 0 ] || fail SCHEDULE_NOT_FROZEN; done < "$state/keys"
    [ "$(sha /etc/crontabs/root)" = "$2" ] || fail BASELINE_CHANGED
    sha "$state/candidate.cron" > "$state/after.cron.sha"
    crontab "$state/candidate.cron"
    [ "$(sha /etc/crontabs/root)" = "$(cat "$state/after.cron.sha")" ] || fail SCHEDULE_NOT_FROZEN
    clean_uci
    trap - EXIT HUP INT TERM
}

action=${1:-}
case "$action" in
    capture) [ "$#" -eq 1 ] || fail INVALID_ARGUMENTS;;
    freeze) [ "$#" -eq 4 ] || fail INVALID_ARGUMENTS;;
    restore) [ "$#" -eq 2 ] || fail INVALID_ARGUMENTS;;
    stage|unstage) [ "$#" -eq 4 ] || fail INVALID_ARGUMENTS;;
    *) fail UNKNOWN_SAFE_ACTION;;
esac
check_device
case "$action" in
    capture) capture;;
    freeze) state_dir "$2"; freeze_updates "$3" "$4";;
    restore) state_dir "$2"; restore_schedule;;
    stage|unstage)
        state_dir "$2"
        case "$3" in ''|.*|*[!A-Za-z0-9_.-]*) fail INVALID_INERT_NAME;; esac
        [ "${#3}" -le 128 ] && valid_sha "$4" || fail INVALID_ARGUMENTS
        target=$state/inert/$3
        [ ! -L "$target" ] || fail PRIVATE_PATH_SYMLINK
        if [ "$action" = stage ]; then
            [ ! -e "$target" ] || fail INERT_FILE_EXISTS
            (set -C; head -c 1048577 > "$target")
            [ "$(wc -c < "$target")" -le 1048576 ] && [ "$(sha "$target")" = "$4" ] || fail INERT_DIGEST_MISMATCH
            chmod 600 "$target"
        elif [ -e "$target" ]; then
            [ "$(sha "$target")" = "$4" ] || fail LATER_CHANGE_PRESERVED
            rm "$target"
        fi;;
esac
