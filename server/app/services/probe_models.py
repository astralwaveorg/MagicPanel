"""探测、路由计划与资源发布的稳定值对象。"""
from dataclasses import dataclass


@dataclass(frozen=True, order=True)
class NodeKey:
    node_uid: str
    revision: int

    def __post_init__(self):
        if not self.node_uid or type(self.revision) is not int or self.revision < 1:
            raise ValueError('invalid_node_key')


JOB_STATES = frozenset({'queued', 'running', 'paused', 'incomplete',
                        'completed', 'cancelled', 'failed'})
RESULT_STATES = frozenset({'observed-ok', 'blocked', 'auth-required',
                           'challenge', 'rate-limited', 'unknown', 'stale', 'skipped'})
