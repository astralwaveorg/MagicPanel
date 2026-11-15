"""V2 foundation-v2.0 纯类型合同。"""
from typing import Literal, TypedDict


class MemberRef(TypedDict):
    kind: Literal["node", "group", "builtin"]
    ref: str


class NodeCatalogEntry(TypedDict):
    node_uid: str
    revision: int
    origin_kind: Literal["source", "local"]
    source_id: int | None
    local_node_id: int | None
    raw_name: str
    display_name: str
    emit_name: str
    enabled: bool
    meta: dict


class PrivateBlobRef(TypedDict):
    blob_id: str
    kind: str
    size: int
    ciphertext_sha256: str


class ReconcileReport(TypedDict):
    catalog_revision: int
    created: list[str]
    changed: list[str]
    renamed: list[str]
    retired: list[str]
    issues: list[dict]


class ResolvedConfig(TypedDict):
    engine: str
    platform: str
    device_id: int
    runtime_profile: str
    profile_version: int
    inherited: dict
    overlay: dict
    effective: dict
    provenance: dict
    input_sha256: str
