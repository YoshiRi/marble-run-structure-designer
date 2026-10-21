import pytest

from quadrilla_solver.statics import (
    GRAVITY_M_S2,
    RailBody,
    SupportConnection,
    analyze_structure,
)


def _ground(x: float, name: str) -> SupportConnection:
    return SupportConnection(x_cm=x, target_id=None, name=name)


def test_centered_rail_has_equal_reactions():
    rail = RailBody(
        id="r",
        length_cm=50,
        mass_g=100,
        supports=(_ground(2, "left"), _ground(48, "right")),
    )

    result = analyze_structure({"r": rail})
    stat = result.rails["r"]

    assert result.valid
    assert stat.effective_com_cm == pytest.approx(25.0)
    assert stat.reactions[0].force_n == pytest.approx(stat.reactions[1].force_n)
    assert stat.normalized_margin == pytest.approx(1.0)
    assert result.total_ground_force_n == pytest.approx(
        0.100 * GRAVITY_M_S2
    )


def test_recursive_upper_rail_load_shifts_lower_effective_com():
    upper = RailBody(
        id="upper",
        length_cm=27,
        mass_g=60,
        supports=(
            SupportConnection(
                x_cm=2,
                target_id="lower",
                target_x_cm=2,
                transfer_mass_g=20,
                name="upper_left_column",
            ),
            SupportConnection(
                x_cm=25,
                target_id="lower",
                target_x_cm=25,
                transfer_mass_g=20,
                name="upper_right_column",
            ),
        ),
    )
    lower = RailBody(
        id="lower",
        length_cm=50,
        mass_g=100,
        supports=(_ground(2, "ground_left"), _ground(48, "ground_right")),
    )

    result = analyze_structure({"upper": upper, "lower": lower})

    assert result.valid
    upper_stat = result.rails["upper"]
    lower_stat = result.rails["lower"]

    # Upper rail is centered between its two support holes.
    assert upper_stat.effective_com_cm == pytest.approx(13.5)
    assert upper_stat.reactions[0].force_n == pytest.approx(
        upper_stat.reactions[1].force_n
    )

    # The upper assembly loads the left half of the lower rail, pulling its
    # effective COM left of the lower rail's own geometric center.
    assert lower_stat.effective_com_cm < 25.0
    assert lower_stat.stable

    # Ground force includes both rails and both 20 g transfer-column masses.
    expected_mass_g = 60 + 100 + 20 + 20
    assert result.total_ground_force_n == pytest.approx(
        expected_mass_g / 1000.0 * GRAVITY_M_S2
    )


def test_heavy_overhang_produces_negative_reaction_and_tipping():
    heavy_upper = RailBody(
        id="upper",
        length_cm=27,
        mass_g=1000,
        supports=(
            SupportConnection(
                x_cm=2,
                target_id="lower",
                target_x_cm=43,
                name="far_right_a",
            ),
            SupportConnection(
                x_cm=25,
                target_id="lower",
                target_x_cm=48,
                name="far_right_b",
            ),
        ),
    )
    lower = RailBody(
        id="lower",
        length_cm=50,
        mass_g=20,
        supports=(_ground(20, "left"), _ground(30, "right")),
    )

    result = analyze_structure({"upper": heavy_upper, "lower": lower})
    lower_stat = result.rails["lower"]

    assert not result.valid
    assert not lower_stat.stable
    assert lower_stat.effective_com_cm > 30
    assert min(r.force_n for r in lower_stat.reactions) < 0
    assert any(reason.startswith("tipping:lower:") for reason in result.reasons)


def test_asymmetric_load_gives_correct_two_support_reactions():
    # 100 g rail mass at x=25, supported at x=0 and x=50, plus 100 g
    # effectively arriving at x=40 from an upper assembly.
    child = RailBody(
        id="child",
        length_cm=10,
        mass_g=100,
        supports=(
            SupportConnection(0, "base", 40, name="a"),
            SupportConnection(10, "base", 40, name="b"),
        ),
    )
    base = RailBody(
        id="base",
        length_cm=50,
        mass_g=100,
        supports=(_ground(0, "left"), _ground(50, "right")),
    )

    result = analyze_structure({"child": child, "base": base})
    stat = result.rails["base"]

    assert stat.effective_com_cm == pytest.approx(32.5)

    total = 0.200 * GRAVITY_M_S2
    expected_right = total * 32.5 / 50.0
    expected_left = total - expected_right
    assert stat.reactions[0].force_n == pytest.approx(expected_left)
    assert stat.reactions[1].force_n == pytest.approx(expected_right)


def test_support_cycle_is_rejected():
    a = RailBody(
        id="a",
        length_cm=10,
        mass_g=10,
        supports=(
            SupportConnection(0, "b", 0, name="a0"),
            SupportConnection(10, "b", 10, name="a1"),
        ),
    )
    b = RailBody(
        id="b",
        length_cm=10,
        mass_g=10,
        supports=(
            SupportConnection(0, "a", 0, name="b0"),
            SupportConnection(10, "a", 10, name="b1"),
        ),
    )

    result = analyze_structure({"a": a, "b": b})
    assert not result.valid
    assert any(reason.startswith("support_cycle:") for reason in result.reasons)


def test_measured_rail_masses_are_loaded_from_catalog():
    from pathlib import Path
    from quadrilla_solver.catalog import load_rail_specs

    root = Path(__file__).resolve().parents[1]
    rails = load_rail_specs(root / "catalog" / "parts.yaml")

    assert rails["straight_long"].mass_g == pytest.approx(135)
    assert rails["straight_short"].mass_g == pytest.approx(74)


def test_routing_block_mass_fallback_and_measured_overrides():
    from pathlib import Path
    from quadrilla_solver.catalog import load_routing_block_masses

    root = Path(__file__).resolve().parents[1]
    masses = load_routing_block_masses(root / "catalog" / "parts.yaml")

    assert masses["blue"] == pytest.approx(53)
    assert masses["orange_vertical"] == pytest.approx(58)
    assert masses["green"] == pytest.approx(55)
    assert masses["cyan"] == pytest.approx(55)
    assert masses["yellow"] == pytest.approx(55)
    assert masses["red_random_split"] == pytest.approx(55)
    assert masses["red_right_angle"] == pytest.approx(55)
    assert masses["natural_drop"] == pytest.approx(55)
    assert masses["purple_drop"] == pytest.approx(12)


def test_foundation_mass_is_recorded_as_12g():
    from pathlib import Path
    import yaml

    root = Path(__file__).resolve().parents[1]
    with (root / "catalog" / "parts.yaml").open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    assert data["structural_parts"]["wooden_foundation"]["mass_g"]["value"] == pytest.approx(12)
