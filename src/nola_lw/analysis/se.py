"""ACS successive-difference replicate SEs (80 replicate weights) and 90% MOEs."""
import math
from collections.abc import Sequence

import polars as pl

N_REPS = 80


def replicate_se(full: float, reps: Sequence[float]) -> float:
    if len(reps) != N_REPS:
        raise ValueError(f"need {N_REPS} replicate estimates, got {len(reps)}")
    return math.sqrt(4 / N_REPS * sum((r - full) ** 2 for r in reps))


def moe90(se: float, z: float) -> float:
    return z * se


def weighted_total(df: pl.DataFrame, value_col: str, weight_prefix: str = "PWGTP") -> tuple[float, float]:
    cols = [weight_prefix] + [f"{weight_prefix}{i}" for i in range(1, N_REPS + 1)]
    sums = df.select([(pl.col(value_col) * pl.col(c)).sum().alias(c) for c in cols]).row(0)
    return sums[0], replicate_se(sums[0], sums[1:])
