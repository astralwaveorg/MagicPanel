#!/bin/sh
set -eu
. "$(dirname -- "$0")/guard_common.sh"
load_bundle "${1:?}"
if [ ! -f "$state_dir/routes-owned" ]; then
    for family in -4 -6; do
        if [ -n "$(ip "$family" route show table 177 2>/dev/null)" ] || ip "$family" rule show | grep -q '^17777:'; then
            echo ROUTE_OWNER_CONFLICT >&2; exit 65
        fi
    done
fi
for family in -4 -6; do
    occupied=$(ip "$family" rule show | grep '^17777:' || true)
    if [ -n "$occupied" ] && ! printf '%s\n' "$occupied" | grep -q 'fwmark 0x4d50.*lookup 177'; then
        echo ROUTE_OWNER_CONFLICT >&2; exit 65
    fi
    [ -n "$occupied" ] || ip "$family" rule add priority 17777 fwmark 0x4d50 lookup 177
done
touch "$state_dir/routes-owned"
ip -4 route replace local 0.0.0.0/0 dev lo table 177
ip -6 route replace local ::/0 dev lo table 177
rules="$state_dir/gateway.nft.$$"
{
    if "$nft" list table inet "$owner" >/dev/null 2>&1; then printf 'delete table inet %s\n' "$owner"; fi
    cat <<EOF
table inet $owner {
 chain redirect4 {
  type nat hook prerouting priority -100; policy accept;
  iifname "lan0" meta nfproto ipv4 tcp dport != 53 redirect to :7892
 }
 chain transparent {
  type filter hook prerouting priority -150; policy accept;
  iifname "lan0" meta nfproto ipv4 udp dport != 53 meta mark set 0x4d50 tproxy ip to :7895 accept
  iifname "lan0" meta nfproto ipv6 meta l4proto { tcp, udp } th dport != 53 meta mark set 0x4d50 tproxy ip6 to :7895 accept
 }
}
EOF
} > "$rules"
if "$nft" -c -f "$rules" && "$nft" -f "$rules"; then
    printf '%s\n' "$(now_ms) apply" >> "$state_dir/gateway.events"
    rm -f "$rules"
else
    rm -f "$rules"; remove_owner; exit 65
fi
