#!/bin/sh
set -eu
. "$(dirname -- "$0")/guard_common.sh"
load_bundle "${1:?}"
# namespace inventory只允许精确空前任；生产前任manifest由任务9适配。
[ "$(field "$bundle/owner.env" predecessor)" = empty ] || { echo PREDECESSOR_UNSUPPORTED >&2; exit 65; }
remove_owner
printf '%s\n' "$(now_ms) withdraw" >> "$state_dir/gateway.events"
