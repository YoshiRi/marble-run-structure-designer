from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from .catalog import SetInventory

# Levels per standard block (catalog height_units.standard_block; 1 level =
# 1.2 cm, a block 6 cm). Thin (purple) blocks are 1 level.
STANDARD_BLOCK_UNITS = 5


@dataclass(frozen=True)
class GapRecipe:
    standard_blocks: int
    thin_blocks: int
    height_units: int
    left_standard: int
    left_thin: int
    right_standard: int
    right_thin: int


@dataclass(frozen=True)
class HeightSolution:
    set_id: str
    rail_levels: int
    height_units: int
    support_height_units: int
    foundation_height_units: int
    recipes: tuple[GapRecipe, ...]
    assumptions: tuple[str, ...]


def _gap_recipes(max_standard: int, max_thin: int) -> tuple[GapRecipe, ...]:
    """
    Enumerate material usages that can create two equal-height support columns
    for one rail level. Standard block height=STANDARD_BLOCK_UNITS, thin=1.
    """
    best: dict[tuple[int, int], GapRecipe] = {}
    for total_s in range(max_standard + 1):
        for total_t in range(max_thin + 1):
            if total_s + total_t < 2:
                continue
            total_height = STANDARD_BLOCK_UNITS * total_s + total_t
            if total_height % 2:
                continue
            target = total_height // 2
            if target <= 0:
                continue

            found: GapRecipe | None = None
            for left_s in range(total_s + 1):
                right_s = total_s - left_s
                for left_t in range(total_t + 1):
                    right_t = total_t - left_t
                    if left_s + left_t == 0 or right_s + right_t == 0:
                        continue
                    if STANDARD_BLOCK_UNITS * left_s + left_t != target:
                        continue
                    if STANDARD_BLOCK_UNITS * right_s + right_t != target:
                        continue
                    found = GapRecipe(
                        standard_blocks=total_s,
                        thin_blocks=total_t,
                        height_units=target,
                        left_standard=left_s,
                        left_thin=left_t,
                        right_standard=right_s,
                        right_thin=right_t,
                    )
                    break
                if found:
                    break
            if found:
                best[(total_s, total_t)] = found
    return tuple(best.values())


def maximize_straight_tower(
    inventory: SetInventory,
    rail_height_units: int = 1,
    foundation_height_units: int = 1,
) -> HeightSolution | None:
    """
    Maximize height under the initial conservative two-column tower model.

    A rail level:
    - has two equal-height support columns,
    - is supported by the previous stable level (or ground foundations),
    - consumes one modeled straight rail.

    Curves, spirals, seesaws, cantilevers and force-level toppling are excluded.
    """
    if inventory.foundations < 2 or inventory.straight_rails < 1:
        return None

    recipes = _gap_recipes(inventory.standard_blocks, inventory.thin_blocks)

    @lru_cache(maxsize=None)
    def best(
        levels: int,
        remaining_s: int,
        remaining_t: int,
    ) -> tuple[int, tuple[GapRecipe, ...]] | None:
        if levels == 0:
            return (0, ())

        winner: tuple[int, tuple[GapRecipe, ...]] | None = None
        for recipe in recipes:
            if recipe.standard_blocks > remaining_s or recipe.thin_blocks > remaining_t:
                continue
            tail = best(
                levels - 1,
                remaining_s - recipe.standard_blocks,
                remaining_t - recipe.thin_blocks,
            )
            if tail is None:
                continue
            support_height = recipe.height_units + tail[0]
            candidate = (support_height, (recipe,) + tail[1])
            if winner is None or candidate[0] > winner[0]:
                winner = candidate
        return winner

    overall: HeightSolution | None = None
    for levels in range(1, inventory.straight_rails + 1):
        result = best(levels, inventory.standard_blocks, inventory.thin_blocks)
        if result is None:
            continue
        support_height, chosen = result
        height = (
            foundation_height_units
            + support_height
            + levels * rail_height_units
        )
        candidate = HeightSolution(
            set_id=inventory.set_id,
            rail_levels=levels,
            height_units=height,
            support_height_units=support_height,
            foundation_height_units=foundation_height_units,
            recipes=chosen,
            assumptions=(
                "standard block height=4",
                "thin purple block height=1",
                "rail height=1",
                "two foundations support the bottom level",
                "each rail level has two equal-height support columns",
                "only modeled straight rails are used",
                "no force/center-of-mass toppling model yet",
            ),
        )
        if overall is None or candidate.height_units > overall.height_units:
            overall = candidate

    return overall
