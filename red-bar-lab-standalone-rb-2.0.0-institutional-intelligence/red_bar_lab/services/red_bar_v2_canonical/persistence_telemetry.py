from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter_ns
from typing import Callable, TypeVar

_T = TypeVar("_T")


@dataclass(frozen=True, slots=True)
class PersistenceBenchmark:
    iterations: int
    average_ms: float
    minimum_ms: float
    maximum_ms: float


def benchmark_persistence_call(
    iterations: int,
    operation: Callable[[], _T],
) -> PersistenceBenchmark:
    if not isinstance(iterations, int) or iterations <= 0:
        raise ValueError("iterations must be a positive integer")
    samples: list[float] = []
    for _ in range(iterations):
        started = perf_counter_ns()
        operation()
        samples.append((perf_counter_ns() - started) / 1_000_000.0)
    return PersistenceBenchmark(
        iterations=iterations,
        average_ms=sum(samples) / len(samples),
        minimum_ms=min(samples),
        maximum_ms=max(samples),
    )
