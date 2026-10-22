from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from .catalog import PartCatalog
from .model import Layout, PortRef


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

        sequence = ["end_a"] + [
            f"hole:{i}" for i in range(len(spec.holes_cm))
        ] + ["end_b"]
        if rail.flow_direction == "b_to_a":
            sequence.reverse()

        for node in sequence:
            graph.setdefault(_rail_node(rail.id, node), set())

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

    # If a support column ends with a routing block immediately under a
    # block-connected rail hole, infer the vertical drop into that block's TOP.
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

        _add_edge(
            graph,
            _rail_node(rail.id, f"hole:{support.upper_hole_index}"),
            f"{part.id}:top",
        )

    # Explicit connections handle horizontal block exits, special transitions,
    # and any geometry whose exact port offset is not yet in the catalog.
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

    # Unsupported route semantics make the result incomplete even when a sink
    # happens to be reachable through another branch.
    unsupported = any(
        x.startswith("unsupported_") for x in reasons
    )

    return ConnectivityResult(
        valid=reachable and not unknown_sinks and not unsupported,
        reachable=reachable,
        source=source_key,
        sinks=sink_keys,
        reached_sinks=reached,
        reachable_nodes=tuple(sorted(visited)),
        dead_ends=dead_ends,
        reasons=tuple(dict.fromkeys(reasons)),
        paths=paths,
    )
