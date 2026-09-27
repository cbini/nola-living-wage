"""ACS successive-difference replicate SEs (80 replicate weights) and 90% MOEs."""
import math
from collections.abc import Callable, Sequence

import polars as pl

N_REPS = 80


def replicate_se(full: float, reps: Sequence[float]) -> float:
    if len(reps) != N_REPS:
        raise ValueError(f"need {N_REPS} replicate estimates, got {len(reps)}")
    return math.sqrt(4 / N_REPS * sum((r - full) ** 2 for r in reps))


def moe90(se: float, z: float) -> float:
    return z * se


def replicate_estimate(df: pl.DataFrame, stat: Callable[[pl.DataFrame, str], float]) -> tuple[float, float]:
    """Evaluate `stat(df, w)` for `w` = PWGTP and each of PWGTP1..80, then the replicate SE."""
    full = stat(df, "PWGTP")
    reps = [stat(df, f"PWGTP{i}") for i in range(1, N_REPS + 1)]
    return full, replicate_se(full, reps)


def weighted_total(df: pl.DataFrame, value_col: str, weight_prefix: str = "PWGTP") -> tuple[float, float]:
    return replicate_estimate(df, lambda d, w: (d[value_col] * d[w.replace("PWGTP", weight_prefix)]).sum())
