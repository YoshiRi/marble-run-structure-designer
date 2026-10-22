from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_three_level_fixture_exit_rail_needs_no_purple_pedestal():
    """The blue outlet drops one unit onto a rail at its installation level,
    so the exit rail rests on single ground foundations."""
    layout = yaml.safe_load(
        (ROOT / "tests" / "fixtures" / "three-level-physically-connected.yaml").read_text()
    )
    parts = {part["id"]: part for part in layout["parts"]}
    assert not [p for p in parts.values() if p["part_type"] == "purple_drop"]

    exit_rail = next(rail for rail in layout["rails"] if rail["id"] == "exit")
    blue = parts["blue_column"]
    # Rail groove (z + 1u) equals the blue block's installation level.
    assert exit_rail["z_units"] + 1 == blue["z_units"]

    exit_supports = [s for s in layout["supports"] if s["upper_rail_id"] == "exit"]
    assert len(exit_supports) == 2
    for support in exit_supports:
        (stack_id,) = support["stack_part_ids"]
        foundation = parts[stack_id]
        assert foundation["part_type"] == "wooden_foundation"
        assert foundation["z_units"] == 0
