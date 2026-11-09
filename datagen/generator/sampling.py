"""Random sampling helpers. All randomness goes through `random.Random` instances
created by `layer_rng`, so each layer is reproducible and independent of the others."""

from __future__ import annotations

import math
import random
from datetime import datetime, timedelta

Z95 = 1.6448536269514722  # standard normal 95th percentile


def layer_rng(seed: int, layer: str) -> random.Random:
    """Independent, reproducible RNG per layer: changing one layer does not shift the others."""
    return random.Random(f"{seed}:{layer}")


def lognormal(rng: random.Random, median: float, p95: float) -> float:
    """Sample a right-skewed positive value described by its median and 95th percentile."""
    mu = math.log(median)
    sigma = (math.log(p95) - mu) / Z95 if p95 > median else 0.0
    return rng.lognormvariate(mu, sigma)


def poisson(rng: random.Random, lam: float) -> int:
    """Poisson sample (Knuth for small means, normal approximation for large ones)."""
    if lam <= 0:
        return 0
    if lam > 50:
        return max(0, round(rng.gauss(lam, math.sqrt(lam))))
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def choice_weighted(rng: random.Random, shares: dict[str, float]) -> str:
    keys = list(shares)
    return rng.choices(keys, weights=[shares[k] for k in keys], k=1)[0]


def uniform_time(rng: random.Random, start: datetime, end: datetime) -> datetime:
    """Uniform instant in [start, end], rounded to the second."""
    if end <= start:
        return start
    seconds = (end - start).total_seconds()
    return start + timedelta(seconds=round(rng.uniform(0, seconds)))


def hours(h: float) -> timedelta:
    return timedelta(hours=h)
