"""信效度固定调参配置。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReliabilityProfile:
    """固定信效度策略下的集中调参。"""

    distribution_warmup_samples: int
    distribution_gain: float
    distribution_min_factor: float
    distribution_max_factor: float
    distribution_gap_limit: float
    consistency_window_ratio: float
    consistency_window_max: int
    consistency_center_weight: float
    consistency_edge_weight: float
    consistency_outside_decay: float


DEFAULT_RELIABILITY_PROFILE = ReliabilityProfile(
    distribution_warmup_samples=14,
    distribution_gain=1.75,
    distribution_min_factor=0.80,
    distribution_max_factor=1.28,
    distribution_gap_limit=0.28,
    consistency_window_ratio=0.18,
    consistency_window_max=8,
    consistency_center_weight=1.8,
    consistency_edge_weight=0.86,
    consistency_outside_decay=0.02,
)


def get_reliability_profile() -> ReliabilityProfile:
    return DEFAULT_RELIABILITY_PROFILE

