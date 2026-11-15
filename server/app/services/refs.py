"""引用服务兼容入口；领域事务集中在 policy_mutations。"""
from .policy_mutations import (source_refs, local_node_refs, detach_source, detach_local_node,
    rule_provider_refs, detach_rule_provider, group_members, rules_targeting, detach_group,
    target_devices, rename_source, rename_rule_provider, release_resource_refs)
