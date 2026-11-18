"""探测器注册表：平台矩阵的唯一入口。

对外只暴露三件事：

* ``ALL_DETECTORS`` —— 全部平台探测器（id → 探测器）；
* ``DETECTORS_BY_CATEGORY`` —— 按分类分组后的视图；
* ``detector_by_id()`` / ``platform_ids()`` / ``detectors_for()`` —— 查询辅助。

平台增删只改 ``platforms.py``，本文件自动跟随；id 重复会在导入时直接报错，
避免「后注册的悄悄覆盖前面的」。
"""
from .base import Detector
from .platforms import ALL_PLATFORM_DETECTORS

# 分类 → 界面展示名
CATEGORY_NAMES = {
    "streaming": "流媒体",
    "ai": "国际 AI",
    "social_other": "社交 / 其他",
}


def _build_registry() -> tuple[dict[str, Detector], dict[str, tuple[Detector, ...]]]:
    """按注册顺序建表；id 重复直接报错。"""
    by_id: dict[str, Detector] = {}
    by_category: dict[str, list[Detector]] = {}
    for detector in ALL_PLATFORM_DETECTORS:
        if not detector.platform_id or not detector.category or not detector.display_name:
            raise ValueError(f"探测器信息不完整：{detector!r}")
        if detector.platform_id in by_id:
            raise ValueError(f"探测器 id 重复：{detector.platform_id}")
        by_id[detector.platform_id] = detector
        by_category.setdefault(detector.category, []).append(detector)
    return by_id, {key: tuple(value) for key, value in by_category.items()}


ALL_DETECTORS: dict[str, Detector]
DETECTORS_BY_CATEGORY: dict[str, tuple[Detector, ...]]
ALL_DETECTORS, DETECTORS_BY_CATEGORY = _build_registry()


def detector_by_id(platform_id: str) -> Detector | None:
    """按 id 取探测器；不存在返回 None（不抛异常，方便处理旧缓存里的 id）。"""
    return ALL_DETECTORS.get(platform_id)


def platform_ids(category: str | None = None) -> list[str]:
    """平台 id 列表；给了分类就只返回该分类的（保持注册顺序）。"""
    if category is None:
        return list(ALL_DETECTORS.keys())
    return [d.platform_id for d in DETECTORS_BY_CATEGORY.get(category, ())]


def detectors_for(ids: list[str] | None = None) -> list[Detector]:
    """按 id 列表取探测器；ids 为 None 时返回全部。未知 id 忽略。"""
    if ids is None:
        return list(ALL_DETECTORS.values())
    picked = []
    for platform_id in ids:
        detector = ALL_DETECTORS.get(platform_id)
        if detector is not None:
            picked.append(detector)
    return picked
