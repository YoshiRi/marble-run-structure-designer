"""Improve a generated build by simulated annealing (user idea, 2026-10-26).

The generator grows a build from a stream of random decisions: the
direction of a rail, which hole it stops at, the block of a drop, whether
to switch back or merge... Here that stream is recorded as a *tape*. A
neighbour is the same tape with a change:

- **re-roll from k**: keep the first k decisions, draw the rest afresh. The
  upper part of the build stays; everything grown after decision k is grown
  again (rails re-attached, other drops, another base placement).
- **point change**: one decision gets a new value and the rest are replayed,
  e.g. another block for one drop, another stop hole, a switchback taken.
- **nudge**: one decision moves a little, which often keeps its choice.

Every neighbour is grown by the generator itself and goes through the same
validation and post-passes (support solving, shortening, curves, balance) as
generate(), so every accepted step is a buildable layout. The score is the
same as the generator's (scoring.py); a worse neighbour is accepted with
probability exp(delta / T), T falling geometrically from t_start to t_end.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any, Callable

from .catalog import PartCatalog
from .generator import (
    Budget, Candidate, CascadeGenerator, GeneratorConfig, _base_config, _has_base, candidate_from_state,
)


class TapeRandom(random.Random):
    """random.Random whose draws come from a tape of floats in [0, 1); past
    its end it draws from `fresh` and appends. Every method of Random
    reduces to random() or getrandbits(), so both read the tape."""

    def __init__(self, tape: list[float], fresh: random.Random):
        self.tape = list(tape)
        self.pos = 0
        self.fresh = fresh
        super().__init__(0)

    def _next(self) -> float:
        if self.pos < len(self.tape):
            value = self.tape[self.pos]
        else:
            value = self.fresh.random()
            self.tape.append(value)
        self.pos += 1
        return value

    def random(self) -> float:  # noqa: D401 - random.Random API
        return self._next()

    def getrandbits(self, k: int) -> int:
        return int(self._next() * (1 << k)) if k else 0

    def used(self) -> list[float]:
        return self.tape[:self.pos]


@dataclass
class AnnealResult:
    start: Candidate
    best: Candidate
    best_tape: list[float]
    history: list[dict[str, Any]] = field(default_factory=list)
    evaluated: int = 0
    valid: int = 0


def grow(catalog: PartCatalog, budget: Budget, config: GeneratorConfig, tape: list[float],
         fresh: random.Random, base: str | None = None, name: str = "annealed"
         ) -> tuple[Candidate | None, list[float]]:
    """Grow one build from a tape; returns (candidate or None, tape used)."""
    rng = TapeRandom(tape, fresh)
    generator = CascadeGenerator(catalog, budget, _base_config(config, base) if base else config, rng)
    state = generator.build_once()
    generator.config = config
    if state is None or len(state.rails) < 2 or (base and not _has_base(state, base)):
        return None, rng.used()
    candidate = candidate_from_state(generator, state, config, catalog, budget, rng, name)
    return candidate, rng.used()


def mutate(tape: list[float], rng: random.Random) -> list[float]:
    if not tape:
        return []
    n = len(tape)
    kind = rng.random()
    if kind < 0.45:   # re-roll from k
        return tape[:rng.randrange(n)]
    out = list(tape)
    i = rng.randrange(n)
    if kind < 0.8:    # point change
        out[i] = rng.random()
    else:             # nudge
        out[i] = (out[i] + rng.gauss(0.0, 0.05)) % 1.0
    return out


def anneal(catalog: PartCatalog, budget: Budget, config: GeneratorConfig, *, seed: int = 1,
           iterations: int = 300, base: str | None = None, start_tape: list[float] | None = None,
           t_start: float = 8.0, t_end: float = 0.3, max_starts: int = 400,
           progress: Callable[[int, AnnealResult], Any] | None = None) -> AnnealResult | None:
    """Anneal from `start_tape` (or the first valid random build)."""
    rng = random.Random(seed)
    fresh = random.Random(seed * 7919 + 1)
    evaluated = valid = 0
    current, tape = None, list(start_tape or [])
    for _ in range(max_starts if not start_tape else 1):
        current, tape = grow(catalog, budget, config, tape, fresh, base)
        evaluated += 1
        if current is not None:
            break
        tape = []
    if current is None:
        return None
    valid += 1
    result = AnnealResult(start=current, best=current, best_tape=list(tape))
    for i in range(iterations):
        t = t_start * (t_end / t_start) ** (i / max(1, iterations - 1))
        candidate, new_tape = grow(catalog, budget, config, mutate(tape, rng), fresh, base)
        evaluated += 1
        accepted = False
        if candidate is not None:
            valid += 1
            delta = candidate.score - current.score
            if delta >= 0 or rng.random() < math.exp(delta / t):
                current, tape, accepted = candidate, new_tape, True
                if current.score > result.best.score:
                    result.best, result.best_tape = current, list(tape)
        result.history.append({"i": i, "t": round(t, 3), "valid": candidate is not None,
                               "score": round(candidate.score, 2) if candidate else None,
                               "current": round(current.score, 2), "best": round(result.best.score, 2),
                               "accepted": accepted})
        if progress is not None:
            progress(i, result)
    result.evaluated, result.valid = evaluated, valid
    return result
