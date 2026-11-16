#!/bin/sh
set -eu
. "$(dirname -- "$0")/guard_common.sh"
load_bundle "${1:?}"
# 02资源的生产热更新适配器尚未封包；此接口只允许离线受控DNS服务。
[ "$(field "$bundle/owner.env" dns_adapter)" = fixture-http-v1 ] || { echo DNS_ADAPTER_REQUIRED >&2; exit 42; }
acquire_lock dns_watch.sh
if [ -f "$state_dir/dns.state" ] && [ "$(field "$state_dir/dns.state" mode)" != TRUSTED ]; then dns_entry 5353
else dns_entry 1053; fi
start=$(now_ms); tick=0
while :; do
    begin=$(now_ms); agh=0; trusted=0
    # 探针是独立服务的受控本地响应；不借Mihomo/AGH API判断自身可用。
    for endpoint in 18053 18054 18055; do
        if curl --noproxy '*' -fsS --max-time 0.75 "http://127.0.0.1:$endpoint/health" > "$state_dir/dns-$endpoint.tmp" 2>/dev/null; then
            if [ "$(cat "$state_dir/dns-$endpoint.tmp")" = DNS_OK ]; then
                if [ "$endpoint" = 18053 ]; then agh=1; else trusted=1; fi
            fi
        fi
    done
    end=$(now_ms)
    action=$(sh "$here/guard_state.sh" dns "$state_dir/dns.state" "$end" "$agh" "$trusted" "$((end - begin))")
    case "$action" in emergency) dns_entry 5353;; trusted) dns_entry 1053;;
        none)
            desired=1053; [ "$(field "$state_dir/dns.state" mode)" = TRUSTED ] || desired=5353
            if ! "$nft" list table inet "${owner}_dns" 2>/dev/null | grep -q "redirect to :$desired"; then dns_entry "$desired"; fi;;
    esac
    printf '%s\n' "$begin $end $agh $trusted $action" >> "$state_dir/dns.probes"
    tick=$((tick + 1)); due=$((start + tick * 500)); current=$(now_ms)
    if [ "$due" -lt "$current" ]; then tick=$(((current - start) / 500 + 1)); due=$((start + tick * 500)); fi
    sleep_until "$due"
done
