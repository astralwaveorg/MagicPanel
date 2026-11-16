#!/bin/sh
set -eu
. "$(dirname -- "$0")/guard_common.sh"
load_bundle "${1:?}"
acquire_lock gateway_watch.sh
start=$(now_ms); tick=0
while :; do
    begin=$(now_ms); control=0; data=0
    if curl --noproxy '*' -fsS --max-time 0.45 http://127.0.0.1:9090/version > "$state_dir/control.tmp" 2>/dev/null; then
        if grep -q 'version' "$state_dir/control.tmp"; then control=1; fi
    fi
    remain=$((1000 - $(now_ms) + begin))
    if [ "$remain" -gt 0 ]; then
        budget=$(awk -v n="$remain" 'BEGIN {printf "%.3f", n/1000}')
        if curl --noproxy '' -fsS --max-time "$budget" -x http://127.0.0.1:7890 \
            http://ready.lab.invalid:8080/ready > "$state_dir/data.tmp" 2>/dev/null; then
            [ "$(cat "$state_dir/data.tmp")" != READY ] || data=1
        fi
    fi
    end=$(now_ms)
    action=$(sh "$here/guard_state.sh" gateway "$state_dir/gateway.state" "$end" "$control" "$data" "$((end - begin))")
    case "$action" in
        withdraw) sh "$here/rollback_bundle.sh" "$bundle";;
        apply) sh "$here/apply_bundle.sh" "$bundle";;
        none)
            if [ "$(field "$state_dir/gateway.state" mode)" = BASIC_WAN ]; then
                if "$nft" list table inet "$owner" >/dev/null 2>&1; then sh "$here/rollback_bundle.sh" "$bundle"; fi
            elif [ "$control" = 1 ] && [ "$data" = 1 ]; then
                if ! "$nft" list table inet "$owner" >/dev/null 2>&1; then sh "$here/apply_bundle.sh" "$bundle"; fi
            fi;;
    esac
    printf '%s\n' "$begin $end $control $data $action" >> "$state_dir/gateway.probes"
    tick=$((tick + 1)); due=$((start + tick * 2000)); current=$(now_ms)
    if [ "$due" -lt "$current" ]; then tick=$(((current - start) / 2000 + 1)); due=$((start + tick * 2000)); fi
    sleep_until "$due"
done
