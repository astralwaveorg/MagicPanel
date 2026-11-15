"""操作定义只由源码登记，读取时返回副本。"""
from collections.abc import Mapping
from copy import deepcopy

PHASES = ("OFFLINE", "PRE_NETWORK", "ROUTER_FINAL")
_PRODUCTION = (
    "nas.production.reader_install", "freeze.production.prepare", "freeze.production.arm",
    "nas.production.db_migrate", "nas.production.image_upgrade",
)
_STAGING = (
    "nas.staging.reader_install", "freeze.staging.prepare", "freeze.staging.arm",
    "nas.staging.db_migrate", "nas.staging.image_upgrade",
)
_ROUTER = (
    "router.probe_bypass", "router.dns", "router.subscription", "router.core",
    "router.firewall", "router.service", "router.apply_canary", "router.wireguard",
    "router.sqm_calibrate",
)
_DEFINITIONS = {
    name: {"id": name, "target_role": "router" if name in _ROUTER or name == "read.router"
           else "nas", "effects": [name]}
    for name in (*_PRODUCTION, *_STAGING, *_ROUTER, "read.router", "read.nas")
}
_DEFINITIONS["router.safe_preparation"] = {
    "id": "router.safe_preparation", "target_role": "router",
    "handler": "scripts.ops.safe_preparation.apply_safe_preparation",
    "effects": ["router.private_backup", "router.stage_inert_rescue", "router.freeze_update_schedule"],
}
for _role in ("hk", "kr"):
    _name = f"dns_control.{_role}.deploy"
    _DEFINITIONS[_name] = {
        "id": _name, "target_role": "dns_control",
        "handler": "scripts.ops.dns_control.apply_registered_role", "effects": [_name],
    }


class _Registry(Mapping):
    def __getitem__(self, key):
        return deepcopy(_DEFINITIONS[key])

    def __iter__(self):
        return iter(_DEFINITIONS)

    def __len__(self):
        return len(_DEFINITIONS)


OPERATION_REGISTRY = _Registry()
