#!/bin/sh
# 本候选仅准离线namespace；生产适配器须另做inventory封包与重验。
set -eu
here=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
now_ms() { awk '{printf "%.0f\n", $1 * 1000}' /proc/uptime; }
field() { awk -F= -v key="$2" '$1 == key {print substr($0, length(key)+2); exit}' "$1"; }
acquire_lock() {
    lock="$state_dir/$1.lock"
    if ! mkdir "$lock" 2>/dev/null; then
        prior=$(cat "$lock/pid" 2>/dev/null || true)
        case "$prior" in ''|*[!0-9]*) prior=0;; esac
        if [ "$prior" -gt 0 ] && [ -r "/proc/$prior/cmdline" ] &&
            tr '\000' ' ' < "/proc/$prior/cmdline" | grep -Fq "$here/$1"; then exit 73; fi
        rm -f "$lock/pid"; rmdir "$lock"; mkdir "$lock"
    fi
    printf '%s\n' "$$" > "$lock/pid"
    trap 'rm -f "$lock/pid"; rmdir "$lock" 2>/dev/null || true' EXIT
    trap 'exit 0' HUP INT TERM
}
load_bundle() {
    bundle=${1:?}; [ -d "$bundle" ] && [ ! -L "$bundle" ] || exit 64
    envfile="$bundle/owner.env"
    [ "$(field "$envfile" role)" = packet_namespace ] || { echo ISOLATION_REQUIRED >&2; exit 64; }
    [ "$(field "$envfile" netns)" = "$(readlink /proc/self/ns/net)" ] || exit 64
    [ "$(field "$envfile" parent_netns)" != "$(readlink /proc/self/ns/net)" ] || exit 64
    # ip netns exec会再创建临时mount namespace，不要求其inode跨调用固定。
    [ "$(field "$envfile" parent_mountns)" != "$(readlink /proc/self/ns/mnt)" ] || exit 64
    owner=$(field "$envfile" owner)
    printf '%s\n' "$owner" | LC_ALL=C grep -Eq '^mpv2_[0-9a-f]{8}$' || exit 64
    nft=${MPV2_NFT:-nft}
    state_dir="$bundle/state"; mkdir -p "$state_dir"; chmod 700 "$state_dir"
}
remove_owner() {
    if "$nft" list table inet "$owner" >/dev/null 2>&1; then "$nft" delete table inet "$owner"; fi
    for family in -4 -6; do
        if ip "$family" rule show | grep -q '^17777:.*fwmark 0x4d50.*lookup 177'; then
            ip "$family" rule del priority 17777 fwmark 0x4d50 lookup 177
        fi
    if ip "$family" route show table 177 2>/dev/null | grep -q '^local .*dev lo'; then
            if [ "$family" = -4 ]; then ip -4 route del local 0.0.0.0/0 dev lo table 177
            else ip -6 route del local ::/0 dev lo table 177; fi
        fi
    done
    rm -f "$state_dir/routes-owned"
}
dns_entry() {
    port=$1; case "$port" in 1053|5353) ;; *) exit 64;; esac
    dnsowner="${owner}_dns"; rules="$state_dir/dns.nft.$$"
    { if "$nft" list table inet "$dnsowner" >/dev/null 2>&1; then printf 'delete table inet %s\n' "$dnsowner"; fi
      printf 'table inet %s {\n chain dns {\n type nat hook prerouting priority -110; policy accept;\n iifname "lan0" meta l4proto { tcp, udp } th dport 53 redirect to :%s\n }\n}\n' "$dnsowner" "$port"
    } > "$rules"
    "$nft" -c -f "$rules" && "$nft" -f "$rules"
    rm -f "$rules"
}
sleep_until() {
    left=$(($1 - $(now_ms)))
    if [ "$left" -gt 0 ]; then sleep "$(awk -v n="$left" 'BEGIN {printf "%.3f", n/1000}')"; fi
}
