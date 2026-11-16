#!/bin/sh
# 纯状态转换；输入为本地探针结果，不接受服务名或命令。
set -eu
kind=${1:?}; state=${2:?}; now=${3:?}; first=${4:?}; second=${5:?}; elapsed=${6:?}
case "$kind" in gateway|dns) ;; *) exit 64;; esac
for value in "$now" "$first" "$second" "$elapsed"; do
    case "$value" in ''|*[!0-9]*) exit 64;; esac
done
[ "$first" -le 1 ] && [ "$second" -le 1 ] || exit 64
mode=MANAGED; [ "$kind" != dns ] || mode=TRUSTED
failures=0; successes=0; epoch=0; changed=0; last_success=-10000; last_good=0; overseas_trusted=1
if [ -f "$state" ]; then
    while IFS='=' read -r key value; do
        case "$key" in
            mode) case "$value" in MANAGED|BASIC_WAN|TRUSTED|DNS_DEGRADED|AGH_BYPASS) mode=$value;; *) exit 65;; esac;;
            failures|successes|epoch|changed|last_success|last_good|overseas_trusted)
                case "$value" in ''|*[!0-9-]*) exit 65;; esac
                case "$key" in
                    failures) failures=$value;; successes) successes=$value;; epoch) epoch=$value;;
                    changed) changed=$value;; last_success) last_success=$value;; last_good) last_good=$value;;
                    overseas_trusted) overseas_trusted=$value;;
                esac;;
            cn_branch) [ "$value" = independent ] || exit 65;;
            *) exit 65;;
        esac
    done < "$state"
fi
# monotonic回退代表重启，保留应急模式并重新开始冷却/恢复确认。
if [ "$now" -lt "$changed" ] || [ "$now" -lt "$last_success" ]; then
    changed=$now; successes=0; last_success=$((now - 10000)); failures=0
fi
action=none
if [ "$kind" = gateway ]; then
    if [ "$first" = 1 ] && [ "$second" = 1 ] && [ "$elapsed" -le 1000 ]; then
        failures=0; successes=$((successes + 1)); last_good=$now
        if [ "$mode" = BASIC_WAN ] && [ "$successes" -ge 5 ] && [ $((now - changed)) -ge 60000 ]; then
            mode=MANAGED; action=apply; changed=$now; epoch=$((epoch + 1))
        fi
    else
        successes=0; failures=$((failures + 1))
        if [ "$failures" -ge 3 ] && [ "$mode" != BASIC_WAN ]; then
            mode=BASIC_WAN; action=withdraw; changed=$now; epoch=$((epoch + 1))
        fi
    fi
else
    if [ "$first" != 1 ] || [ "$second" != 1 ] || [ "$elapsed" -gt 3000 ]; then
        desired=DNS_DEGRADED; [ "$first" = 1 ] || desired=AGH_BYPASS
        successes=0; last_success=$((now - 10000)); overseas_trusted=0
        if [ "$mode" != "$desired" ]; then
            mode=$desired; action=emergency; changed=$now; epoch=$((epoch + 1))
        fi
    elif [ "$mode" = TRUSTED ]; then
        last_good=$now; overseas_trusted=1
    elif [ $((now - last_success)) -ge 10000 ]; then
        successes=$((successes + 1)); last_success=$now
        if [ "$successes" -ge 3 ]; then
            mode=TRUSTED; action=trusted; changed=$now; epoch=$((epoch + 1)); last_good=$now; overseas_trusted=1
        fi
    fi
fi
umask 077
tmp="$state.tmp.$$"
trap 'rm -f "$tmp"' EXIT HUP INT TERM
printf '%s\n' "mode=$mode" "failures=$failures" "successes=$successes" "epoch=$epoch" \
    "changed=$changed" "last_success=$last_success" "last_good=$last_good" \
    "overseas_trusted=$overseas_trusted" 'cn_branch=independent' > "$tmp"
mv -f "$tmp" "$state"
printf '%s\n' "$action"
