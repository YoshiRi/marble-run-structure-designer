from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from math import cos, hypot, radians, sin
from typing import Mapping, Sequence

from .catalog import PartCatalog
from .model import (
    Layout, PortRef, flow_sequences, flow_sign, rail_end_is_exit, rail_hole_world,
    rail_pose,
)
from .routing_geometry import port_pose, validate_route_link_geometry


@dataclass(frozen=True)
class ConnectivityResult:
    valid: bool
    reachable: bool
    source: str
    sinks: tuple[str, ...]
    reached_sinks: tuple[str, ...]
    reachable_nodes: tuple[str, ...]
    dead_ends: tuple[str, ...]
    reasons: tuple[str, ...] = ()
    # Shortest directed route to each reached sink (node keys in traversal order).
    paths: Mapping[str, tuple[str, ...]] = field(default_factory=dict)


@dataclass(frozen=True)
class RoutingGraph:
    edges: Mapping[str, tuple[str, ...]]
    nodes: tuple[str, ...]
    reasons: tuple[str, ...] = ()


def _add_edge(graph: dict[str, set[str]], source: str, target: str) -> None:
    graph.setdefault(source, set()).add(target)
    graph.setdefault(target, set())


def _rail_node(rail_id: str, port: str) -> str:
    return f"{rail_id}:{port}"


def _add_hole_falls(graph: dict[str, set[str]], layout: Layout, catalog: PartCatalog) -> None:
    held = {(s.upper_rail_id, s.upper_hole_index) for s in layout.supports if s.stack_part_ids}
    stood = {(s.lower_rail_id, s.lower_hole_index) for s in layout.supports if s.stack_part_ids}
    holes = []
    for rail in layout.rails:
        spec = catalog.rails.get(rail.rail_type)
        if spec is None:
            continue
        for k in range(len(spec.holes_cm)):
            x, y, _ = rail_hole_world(rail, catalog, k)
            level = rail.z_units + spec.hole_level(k)
            holes.append((rail, k, x, y, level, level + spec.height_units))
    for rail, j, x, y, level, _top in holes:
        if rail.hole_states.get(j, "open") != "open" or (rail.id, j) in held or (rail.id, j) in stood:
            continue
        if catalog.rails[rail.rail_type].shape == "plate":
            continue
        below = [h for h in holes if h[0].id != rail.id and hypot(h[2] - x, h[3] - y) <= 0.35
                 and h[5] <= level + 1e-9]
        if not below:
            continue
        lower, k = max(below, key=lambda h: h[5])[:2]
        # A covered hole stops it; so does a block standing on the hole.
        if lower.hole_states.get(k, "open") == "covered" or (lower.id, k) in stood:
            continue
        _add_edge(graph, _rail_node(rail.id, f"hole:{j}"), _rail_node(lower.id, f"hole:{k}"))


def build_routing_graph(
    layout: Layout,
    catalog: PartCatalog,
) -> RoutingGraph:
    graph: dict[str, set[str]] = {}
    reasons: list[str] = []
    rails = layout.rail_map()
    parts = layout.part_map()

    # Intrinsic routing inside blocks.
    part_ports: dict[str, set[str]] = {}
    for part in layout.parts:
        if catalog.part_spec(part.part_type) is None:
            continue
        ports: set[str] = set()
        for source, target in catalog.internal_routes(part.part_type):
            s = f"{part.id}:{source}"
            t = f"{part.id}:{target}"
            _add_edge(graph, s, t)
            ports.update((source, target))
        part_ports[part.id] = ports

    # Directed route along straight rails. An uncovered/open hole interrupts
    # the rail route; a covered hole preserves it. A block-connected hole also
    # interrupts the rail route because the marble drops into the block.
    for rail in layout.rails:
        spec = catalog.rails.get(rail.rail_type)
        if spec is None:
            continue

        if rail.flow_direction == "to_hole" and rail.flow_hole is not None \
                and rail.hole_states.get(rail.flow_hole, "open") == "covered":
            reasons.append(f"collector_hole_covered:{rail.id}:{rail.flow_hole}")

        for node in ["end_a", *(f"hole:{i}" for i in range(len(spec.holes_cm))), "end_b"]:
            graph.setdefault(_rail_node(rail.id, node), set())
        if spec.shape == "plate":
            continue  # a hole plate has no groove: nothing rolls on it

        for sequence in flow_sequences(rail, len(spec.holes_cm)):
            for i in range(len(sequence) - 1):
                current = sequence[i]
                nxt = sequence[i + 1]
                current_key = _rail_node(rail.id, current)

                if current.startswith("hole:"):
                    hole_index = int(current.split(":", 1)[1])
                    state = rail.hole_states.get(hole_index, "open")
                    if state == "covered":
                        _add_edge(
                            graph,
                            current_key,
                            _rail_node(rail.id, nxt),
                        )
                    elif state == "covered_slope":
                        reasons.append(
                            f"unsupported_covered_slope_semantics:{rail.id}:{hole_index}"
                        )
                    # open and block_connected intentionally stop on the hole.
                else:
                    _add_edge(
                        graph,
                        current_key,
                        _rail_node(rail.id, nxt),
                    )

    # Only infer a drop through a real rail hole and a physically aligned
    # block top. Support declarations alone do not establish a route.
    valid_connected_holes: set[tuple[str, int]] = set()
    for support in layout.supports:
        if not support.stack_part_ids:
            continue
        rail = rails.get(support.upper_rail_id)
        if rail is None:
            continue
        state = rail.hole_states.get(support.upper_hole_index, "open")
        if state != "block_connected":
            continue

        top_part_id = support.stack_part_ids[-1]
        part = parts.get(top_part_id)
        if part is None:
            continue
        if "top" not in part_ports.get(part.id, set()):
            reasons.append(
                f"block_connected_without_top_port:"
                f"{rail.id}:{support.upper_hole_index}:{part.id}"
            )
            continue
        spec = catalog.rails.get(rail.rail_type)
        height = catalog.height_units(part.part_type)
        if spec is None or height is None or not 0 <= support.upper_hole_index < len(spec.holes_cm):
            reasons.append(f"block_connected_invalid_geometry:{rail.id}:{support.upper_hole_index}")
            continue
        x, y, _ = rail_hole_world(rail, catalog, support.upper_hole_index)
        if (
            hypot(part.x_cm - x, part.y_cm - y) > 0.35
            or abs(part.z_units + height - rail.z_units - spec.hole_level(support.upper_hole_index)) > 0.1
        ):
            reasons.append(
                f"block_connected_geometry_mismatch:"
                f"{rail.id}:{support.upper_hole_index}:{part.id}"
            )
            continue
        valid_connected_holes.add((rail.id, support.upper_hole_index))

        _add_edge(
            graph,
            _rail_node(rail.id, f"hole:{support.upper_hole_index}"),
            f"{part.id}:top",
        )

    for rail in layout.rails:
        for index, state in rail.hole_states.items():
            if state == "block_connected" and (rail.id, index) not in valid_connected_holes:
                reasons.append(f"block_connected_without_valid_support:{rail.id}:{index}")

    # A marble leaving a block through its bottom drops straight down the
    # support column: into the top of the part beneath it in the same stack,
    # or, from the bottom of a stack standing on a lower rail, through that
    # rail hole into the top of the column under it (physically confirmed).
    columns_by_upper_hole = {
        (support.upper_rail_id, support.upper_hole_index): support
        for support in layout.supports
        if support.stack_part_ids
    }
    for support in layout.supports:
        stack = [part_id for part_id in support.stack_part_ids if part_id in parts]
        if len(stack) != len(support.stack_part_ids):
            continue
        for lower_id, upper_id in zip(stack, stack[1:]):
            if "bottom" in part_ports.get(upper_id, set()) and "top" in part_ports.get(lower_id, set()):
                _add_edge(graph, f"{upper_id}:bottom", f"{lower_id}:top")
        if not stack or support.lower_rail_id is None:
            continue
        below = columns_by_upper_hole.get((support.lower_rail_id, support.lower_hole_index))
        if below is None or below.stack_part_ids[-1] not in parts:
            continue
        below_top = below.stack_part_ids[-1]
        if "bottom" in part_ports.get(stack[0], set()) and "top" in part_ports.get(below_top, set()):
            _add_edge(graph, f"{stack[0]}:bottom", f"{below_top}:top")

    # A marble dropping through a free hole falls through the hole right under
    # it on a lower rail (user, 2026-10-27: hole to hole works; hole onto a
    # rail's groove does not). It then goes on as that hole does: into the
    # block under it, or out. Not through a covered hole.
    _add_hole_falls(graph, layout, catalog)

    # A block standing directly on a rail can land the marble on that rail:
    # a side outlet facing along the rail drops one unit onto its groove just
    # past the block face, and the marble rolls on in the rail's flow
    # direction (physically confirmed). Explicit route links take precedence.
    explicit_sources = {link.source.key for link in layout.route_links}
    for support in layout.supports:
        if not support.stack_part_ids or support.lower_rail_id is None:
            continue
        for source, target in _landing_edges(layout, catalog, support, explicit_sources):
            _add_edge(graph, source, target)

    unit = catalog.raw.get("geometry_cm", {}).get("height_unit", {})
    unit = float(unit.get("value", 1.5)) if isinstance(unit, Mapping) else float(unit or 1.5)
    seesaw_edges, seesaw_reasons = _seesaw_edges(layout, catalog, unit)
    for source, target in seesaw_edges:
        _add_edge(graph, source, target)
    reasons.extend(seesaw_reasons)

    # Explicit connections must mate actual catalogued openings at the same
    # physical position and opposite facing normals. No teleport edges.
    known_components = layout.component_ids()
    for link in layout.route_links:
        if link.source.component_id not in known_components:
            reasons.append(
                f"route_link_unknown_component:{link.source.component_id}"
            )
            continue
        if link.target.component_id not in known_components:
            reasons.append(
                f"route_link_unknown_component:{link.target.component_id}"
            )
            continue

        reason = validate_route_link_geometry(layout, catalog, link)
        if reason is not None:
            reasons.append(reason)
            continue

        source = link.source.key
        target = link.target.key
        graph.setdefault(source, set())
        graph.setdefault(target, set())
        _add_edge(graph, source, target)
        if link.bidirectional:
            _add_edge(graph, target, source)

    edges = {
        node: tuple(sorted(targets))
        for node, targets in sorted(graph.items())
    }
    return RoutingGraph(
        edges=edges,
        nodes=tuple(edges),
        reasons=tuple(dict.fromkeys(reasons)),
    )


def _landing_edges(layout, catalog, support, explicit_sources):
    """Edges from the side outlets of a stack's bottom part onto its rail."""
    rail = layout.rail_map().get(support.lower_rail_id)
    part = layout.part_map().get(support.stack_part_ids[0])
    if rail is None or part is None:
        return []
    spec = catalog.rails.get(rail.rail_type)
    # The twist's chute is a plain rail: blocks on it land the marble too.
    if spec is None:
        return []
    unit = catalog.raw.get("geometry_cm", {}).get("height_unit", {})
    unit = float(unit.get("value", 1.5)) if isinstance(unit, Mapping) else float(unit or 1.5)
    hole = support.lower_hole_index
    if hole is None or not 0 <= hole < len(spec.holes_cm):
        return []
    # Direction of the rail where the block stands (tangent on a curve).
    _, _, theta = rail_pose(rail, spec, spec.holes_cm[hole])
    axis = (cos(theta), sin(theta))
    rail_top_cm = (rail.z_units + spec.hole_level(hole) + spec.height_units) * unit
    outputs = {target for _, target in catalog.internal_routes(part.part_type)}
    edges = []
    for port in sorted(outputs & {"front", "rear", "left", "right"}):
        if f"{part.id}:{port}" in explicit_sources:
            continue
        pose = port_pose(layout, catalog, PortRef(part.id, port))
        if pose is None:
            continue
        along = pose.outward[0] * axis[0] + pose.outward[1] * axis[1]
        if abs(along) < 0.95 or abs(pose.position_cm[2] - (rail_top_cm + unit)) > 0.05:
            continue
        # The marble lands just past the block face, half a block from the hole.
        half_block = abs((pose.position_cm[0] - part.x_cm) * axis[0]
                         + (pose.position_cm[1] - part.y_cm) * axis[1])
        landing = spec.holes_cm[hole] + (half_block if along > 0 else -half_block)
        sign = 1 if along > 0 else -1
        if flow_sign(rail, spec.holes_cm, landing) == sign:
            nxt = _station_ahead(spec, landing, sign)
        else:
            nxt = None  # Outlet faces against the rail's flow.
        if nxt is not None:
            edges.append((f"{part.id}:{port}", _rail_node(rail.id, nxt)))
    return edges


def _station_ahead(spec, x_cm: float, sign: int) -> str | None:
    """The first station (end or hole) past x in the direction of travel."""
    stations = [("end_a", 0.0)] + [(f"hole:{i}", h) for i, h in enumerate(spec.holes_cm)] \
        + [("end_b", spec.length_cm)]
    if sign > 0:
        ahead = [name for name, x in stations if x > x_cm + 1e-6]
        return ahead[0] if ahead else None
    ahead = [name for name, x in stations if x < x_cm - 1e-6]
    return ahead[-1] if ahead else None


def _seesaw_edges(layout, catalog, unit_cm: float) -> tuple[list[tuple[str, str]], list[str]]:
    """A seesaw (simplified to a random distributor) on the pivot hole of its
    rail: a marble falling onto it from an open hole or a rail end above
    (within the drop limit) goes to either arm, and rolls on along the rail
    from below that arm toward that end. Rolling along the rail into it stops."""
    edges: list[tuple[str, str]] = []
    reasons: list[str] = []
    rails = layout.rail_map()
    for support in layout.supports:
        for part_id in support.stack_part_ids:
            part = layout.part_map().get(part_id)
            spec = catalog.part_spec(part.part_type) if part is not None else None
            if not spec or spec.get("shape") != "seesaw":
                continue
            host = rails.get(support.lower_rail_id) if support.lower_rail_id is not None else None
            host_spec = catalog.rails.get(host.rail_type) if host is not None else None
            if host_spec is None or support.lower_hole_index is None:
                continue  # assembly reports the mount
            pivot = host_spec.holes_cm[support.lower_hole_index]
            reach = float(spec.get("arm_reach_cm", 9.5))
            for port, sign in (("a_side", -1), ("b_side", 1)):
                x = pivot + sign * reach
                if flow_sign(host, host_spec.holes_cm, x) != sign:
                    reasons.append(f"seesaw_against_rail_flow:{part.id}:{host.id}")
                    continue
                ahead = _station_ahead(host_spec, x, sign)
                if ahead is not None:
                    edges.append((f"{part.id}:{port}", _rail_node(host.id, ahead)))
            # Feeds: open holes and exit ends of other rails above it.
            feed = spec.get("feed") or {}
            max_drop = float(feed.get("max_drop_units", 12))
            body = spec.get("body_height_cm", 8.0)
            min_drop = float(body.get("value") if isinstance(body, Mapping) else body) / unit_cm
            fp = spec.get("footprint_cm") or {}
            half_l, half_w = float(fp.get("length", 19.0)) / 2, float(fp.get("width", 3.0)) / 2
            margin = 1.5
            theta = radians(part.rotation_deg)
            for rail in layout.rails:
                rspec = catalog.rails.get(rail.rail_type)
                if rail.id == host.id or rspec is None or rspec.shape == "twist":
                    continue
                points = []
                for i, _ in enumerate(rspec.holes_cm):
                    if rail.hole_states.get(i, "open") == "open":
                        hx, hy, _ = rail_hole_world(rail, catalog, i)
                        points.append((f"hole:{i}", hx, hy, rail.z_units + rspec.hole_level(i)))
                for end, local in (("end_a", 0.0), ("end_b", rspec.length_cm)):
                    if rail_end_is_exit(rail, end):
                        ex, ey, _ = rail_pose(rail, rspec, local)
                        points.append((end, ex, ey, rail.z_units + rspec.end_level(end)))
                for station, px, py, pz in points:
                    drop = pz - part.z_units
                    if not (min_drop - 1e-6 <= drop <= max_drop + 1e-6):
                        continue
                    dx, dy = px - part.x_cm, py - part.y_cm
                    along = dx * cos(theta) + dy * sin(theta)
                    across = -dx * sin(theta) + dy * cos(theta)
                    if abs(along) <= half_l + margin and abs(across) <= half_w + margin:
                        edges.append((_rail_node(rail.id, station), f"{part.id}:top"))
    return edges, reasons


def validate_connectivity(
    layout: Layout,
    catalog: PartCatalog,
    source: PortRef,
    sinks: Sequence[PortRef],
) -> ConnectivityResult:
    routing = build_routing_graph(layout, catalog)
    source_key = source.key
    sink_keys = tuple(x.key for x in sinks)
    reasons = list(routing.reasons)

    if source_key not in routing.edges:
        reasons.append(f"unknown_source:{source_key}")
        return ConnectivityResult(
            valid=False,
            reachable=False,
            source=source_key,
            sinks=sink_keys,
            reached_sinks=(),
            reachable_nodes=(),
            dead_ends=(),
            reasons=tuple(dict.fromkeys(reasons)),
        )

    unknown_sinks = [x for x in sink_keys if x not in routing.edges]
    for sink in unknown_sinks:
        reasons.append(f"unknown_sink:{sink}")

    # BFS records a shortest directed path, not just a reachability boolean.
    visited: set[str] = {source_key}
    previous: dict[str, str] = {}
    queue = deque([source_key])
    while queue:
        node = queue.popleft()
        for target in routing.edges.get(node, ()):
            if target in visited:
                continue
            visited.add(target)
            previous[target] = node
            queue.append(target)

    reached = tuple(sorted(set(sink_keys) & visited))
    paths: dict[str, tuple[str, ...]] = {}
    for sink in reached:
        nodes = [sink]
        while nodes[-1] != source_key:
            nodes.append(previous[nodes[-1]])
        paths[sink] = tuple(reversed(nodes))
    dead_ends = tuple(
        sorted(
            node
            for node in visited
            if not routing.edges.get(node)
            and node not in sink_keys
        )
    )

    reachable = bool(reached)
    if not reachable:
        reasons.append("no_requested_sink_reachable")

    # Invalid geometry makes the graph incomplete, even if another branch
    # happens to reach the requested sink.
    return ConnectivityResult(
        valid=reachable and not reasons,
        reachable=reachable,
        source=source_key,
        sinks=sink_keys,
        reached_sinks=reached,
        reachable_nodes=tuple(sorted(visited)),
        dead_ends=dead_ends,
        reasons=tuple(dict.fromkeys(reasons)),
        paths=paths,
    )
