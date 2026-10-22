from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_default_viewer_sample_has_ground_level_purple_support_stacks():
    catalog = yaml.safe_load((ROOT / "catalog" / "parts.yaml").read_text())
    layout = yaml.safe_load(
        (ROOT / "examples" / "three-level-physically-connected.yaml").read_text()
    )

    purple_spec = catalog["routing_blocks"]["purple_drop"]
    assert purple_spec["height"] == 1
    assert purple_spec["body_height_cm"]["value"] == 1.5

    parts = layout["parts"]
    purple_parts = [part for part in parts if part["part_type"] == "purple_drop"]
    assert len(purple_parts) == 4

    for y_cm in (9.25, 27.25):
        column = [part for part in parts if part["y_cm"] == y_cm]
        foundations = [
            part for part in column
            if part["part_type"] == "wooden_foundation"
        ]
        purples = sorted(
            (
                part for part in column
                if part["part_type"] == "purple_drop"
            ),
            key=lambda part: part["z_units"],
        )
        assert len(foundations) == 1
        assert foundations[0]["z_units"] == 0
        assert [part["z_units"] for part in purples] == [1, 2]
        assert all(
            abs(part["x_cm"] - foundations[0]["x_cm"]) < 0.01
            for part in purples
        )
