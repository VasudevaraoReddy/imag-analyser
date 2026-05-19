"""User-journey extractor.

Given a fully normalized AnalysisResult, walks the connection graph from
every entry actor to every meaningful sink, scores the resulting paths,
and returns them as a ranked list of Journey objects.

This is pure post-processing — it has no AI in it and runs in microseconds.
The compliance evaluator's findings are referenced (not recomputed) so each
journey carries the controls that touched it.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from ..schemas import (
    AnalysisResult,
    Component,
    Connection,
    Journey,
    JourneyHop,
    JourneyKind,
    TrustZone,
)

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

# Cap path length so cyclic graphs don't explode. 8 hops is plenty for a
# real bank architecture (user → CDN → WAF → APIM → app → cache → db → audit).
_MAX_PATH_LEN = 8

# At most this many shortest paths per (entry, sink) pair. Diagrams that
# show multiple routes between the same endpoints stay readable; we don't
# enumerate every permutation.
_MAX_PATHS_PER_PAIR = 3

# Minimum score for a journey to be returned. Scores below this are
# usually trivial intra-zone hops not worth a card in the UI.
_MIN_SCORE = 10

# Service types that mark a meaningful TERMINAL sink for a journey.
_SINK_SERVICE_TYPES = {
    # data tier — most common destination
    "database_relational", "database_nosql", "database_cache", "database_warehouse",
    "storage_object", "storage_file", "storage_block",
    # security plane
    "identity", "secrets_vault", "key_management",
    # integrations / messaging
    "messaging_queue", "messaging_pubsub", "messaging_event_stream",
    "third_party_saas",
    # mainframe / on-prem
    "mainframe", "on_prem_app",
    # observability is a valid telemetry sink
    "monitoring", "logging", "siem",
}

# Service types that mark journey ENTRY points.
_ENTRY_SERVICE_TYPES = {"user_actor"}


_ZONE_LEVEL = {
    "external": 0,
    "perimeter": 1,
    "dmz": 2,
    "internal": 3,
    "restricted": 4,
    "management": 3,
}


# ---------------------------------------------------------------------------
# Graph building
# ---------------------------------------------------------------------------

def _component_by_id(result: AnalysisResult) -> dict[str, Component]:
    return {c.id: c for c in result.components}


def _zone_kind_by_id(result: AnalysisResult) -> dict[str, str]:
    return {z.id: z.kind for z in result.trust_zones}


def _zone_kind_for_component(
    comp: Component,
    zones: dict[str, str],
) -> str:
    return zones.get(comp.trust_zone, "")


def _direction_for_edge(
    edge: Connection,
    components: dict[str, Component],
) -> list[tuple[str, str, Connection, bool]]:
    """Decide which way an edge points.

    Returns a list of (from_id, to_id, edge, direction_inferred) tuples —
    one entry for a directed edge, two for a bidirectional/undirected one.

    Heuristics when the LLM marked the edge bidirectional/undirected:
      - actor (user_actor) is always a source
      - data-tier (database_*, storage_*) is almost always a sink
      - identity is bidirectional (auth flows both ways)
      - otherwise emit both directions and let the path enumerator pick
    """
    f = components.get(edge.from_)
    t = components.get(edge.to)
    if f is None or t is None:
        return []  # dangling edge — skip

    if not edge.bidirectional:
        return [(edge.from_, edge.to, edge, False)]

    # Bidirectional case — try to infer the natural direction.
    if f.service_type == "user_actor" and t.service_type != "user_actor":
        return [(edge.from_, edge.to, edge, True)]
    if t.service_type == "user_actor" and f.service_type != "user_actor":
        return [(edge.to, edge.from_, edge, True)]

    is_sink = lambda st: st in _SINK_SERVICE_TYPES  # noqa: E731
    if is_sink(t.service_type) and not is_sink(f.service_type):
        return [(edge.from_, edge.to, edge, True)]
    if is_sink(f.service_type) and not is_sink(t.service_type):
        return [(edge.to, edge.from_, edge, True)]

    # Identity is naturally bidirectional — emit both.
    if "identity" in (f.service_type, t.service_type):
        return [
            (edge.from_, edge.to, edge, True),
            (edge.to, edge.from_, edge, True),
        ]

    # Last resort: emit both directions and let scoring filter the
    # irrelevant one out.
    return [
        (edge.from_, edge.to, edge, True),
        (edge.to, edge.from_, edge, True),
    ]


def _build_graph(
    result: AnalysisResult,
) -> tuple[dict[str, list[tuple[str, Connection, bool]]], dict[str, Component]]:
    """Return (adjacency_list, components_by_id).

    adjacency_list[node_id] = [(neighbor_id, edge, direction_inferred), ...]
    Only data-flow edges are included; management/dependency lines are dropped.
    """
    components = _component_by_id(result)
    adj: dict[str, list[tuple[str, Connection, bool]]] = defaultdict(list)
    for edge in result.connections:
        if not edge.is_data_flow:
            continue
        for f, t, e, inferred in _direction_for_edge(edge, components):
            adj[f].append((t, e, inferred))
    return adj, components


# ---------------------------------------------------------------------------
# Entry / sink discovery
# ---------------------------------------------------------------------------

def _entry_points(result: AnalysisResult, zones: dict[str, str]) -> list[Component]:
    entries: list[Component] = []
    seen: set[str] = set()
    for c in result.components:
        if c.id in seen:
            continue
        if (
            c.service_type in _ENTRY_SERVICE_TYPES
            or zones.get(c.trust_zone) == "external"
        ):
            entries.append(c)
            seen.add(c.id)
    return entries


def _sinks(result: AnalysisResult) -> list[Component]:
    return [c for c in result.components if c.service_type in _SINK_SERVICE_TYPES]


# ---------------------------------------------------------------------------
# Path enumeration
# ---------------------------------------------------------------------------

def _all_simple_paths(
    adj: dict[str, list[tuple[str, Connection, bool]]],
    src: str,
    dst: str,
    max_len: int = _MAX_PATH_LEN,
) -> Iterable[list[tuple[str, Connection | None, bool]]]:
    """Yield each simple path from src to dst as a list of (node_id, incoming_edge, dir_inferred).

    Iterative DFS. Bounded by ``max_len`` nodes (so ``max_len - 1`` hops).
    """
    stack: list[tuple[str, list[tuple[str, Connection | None, bool]], set[str]]] = [
        (src, [(src, None, False)], {src})
    ]
    while stack:
        node, path, visited = stack.pop()
        if node == dst and len(path) > 1:
            yield path
            continue
        if len(path) >= max_len:
            continue
        for nbr, edge, inferred in adj.get(node, []):
            if nbr in visited:
                continue
            stack.append((nbr, [*path, (nbr, edge, inferred)], visited | {nbr}))


# ---------------------------------------------------------------------------
# Scoring + annotation
# ---------------------------------------------------------------------------

_ENCRYPTED_PROTOCOLS = {"HTTPS", "TLS", "MTLS", "SSH", "SFTP", "GRPCS", "AMQPS", "WSS"}
_INSECURE_PROTOCOLS = {"HTTP", "FTP", "TELNET", "AMQP", "MQTT", "WS"}


def _hop_encrypted(edge: Connection | None) -> bool | None:
    if edge is None:
        return None
    if edge.encrypted is True:
        return True
    if edge.encrypted is False:
        return False
    proto = (edge.protocol or "").upper()
    if proto in _ENCRYPTED_PROTOCOLS:
        return True
    if proto in _INSECURE_PROTOCOLS:
        return False
    return None


def _journey_kind(sink: Component) -> JourneyKind:  # type: ignore[valid-type]
    st = sink.service_type
    if st == "identity":
        return "auth"  # type: ignore[return-value]
    if st in {"monitoring", "logging", "siem"}:
        return "admin"  # type: ignore[return-value]
    if st in {"messaging_queue", "messaging_pubsub", "messaging_event_stream",
              "third_party_saas"}:
        return "integration"  # type: ignore[return-value]
    if st.startswith("storage_"):
        return "write"  # type: ignore[return-value]
    if st.startswith("database_"):
        # Heuristic — cache is mostly read, others both. Default to write
        # because that's the security-interesting case.
        return "read" if st == "database_cache" else "write"  # type: ignore[return-value]
    return "generic"  # type: ignore[return-value]


def _annotate_journey(
    path: list[tuple[str, Connection | None, bool]],
    components: dict[str, Component],
    zones: dict[str, str],
    findings_by_component: dict[str, list[str]],
    findings_by_connection: dict[str, list[str]],
    journey_id: str,
) -> Journey | None:
    if len(path) < 2:
        return None

    nodes = [components[node_id] for node_id, _, _ in path if node_id in components]
    if len(nodes) < 2:
        return None

    src = nodes[0]
    dst = nodes[-1]

    hops: list[JourneyHop] = []
    protocols: list[str] = []
    hop_encryption: list[bool | None] = []
    component_ids: list[str] = [c.id for c in nodes]
    connection_ids: list[str] = []

    for idx, (node_id, edge, inferred) in enumerate(path):
        if idx == 0:
            continue
        prev_node_id = path[idx - 1][0]
        prev = components.get(prev_node_id)
        cur = components.get(node_id)
        if prev is None or cur is None:
            continue
        enc = _hop_encrypted(edge)
        hop_encryption.append(enc)
        if edge and edge.protocol and edge.protocol not in protocols:
            protocols.append(edge.protocol)
        if edge:
            connection_ids.append(edge.id)
        hops.append(
            JourneyHop(
                **{"from": prev.id, "to": cur.id},  # type: ignore[arg-type]
                from_name=prev.name,
                to_name=cur.name,
                label=edge.label if edge else None,
                protocol=edge.protocol if edge else None,
                port=edge.port if edge else None,
                encrypted=enc,
                from_zone_kind=zones.get(prev.trust_zone, ""),
                to_zone_kind=zones.get(cur.trust_zone, ""),
                connection_id=edge.id if edge else None,
                direction_inferred=inferred,
            )
        )

    if not hops:
        return None

    zones_in_order: list[str] = []
    for c in nodes:
        zk = zones.get(c.trust_zone, "")
        if zk and (not zones_in_order or zones_in_order[-1] != zk):
            zones_in_order.append(zk)

    has_unenc = any(e is False for e in hop_encryption)
    all_enc = all(e is True for e in hop_encryption) if hop_encryption else None
    starts_external = zones.get(src.trust_zone) == "external" or src.service_type == "user_actor"
    enters_restricted = any(z == "restricted" for z in zones_in_order)

    # Relevant compliance findings — anything that touched a component or
    # connection on this path.
    related: set[str] = set()
    for cid in component_ids:
        related.update(findings_by_component.get(cid, []))
    for eid in connection_ids:
        related.update(findings_by_connection.get(eid, []))

    # Scoring
    score = 0
    score += len({z for z in zones_in_order}) * 10  # diverse zones
    if starts_external:
        score += 20
    if enters_restricted:
        score += 20
    if has_unenc:
        score += 15  # risky paths bubble up
    score += min(len(hops), 6) * 2  # longer paths slightly preferred
    if related:
        score += 5

    title = f"{src.name} → {dst.name}"
    kind = _journey_kind(dst)

    return Journey(
        id=journey_id,
        title=title,
        kind=kind,
        hops=hops,
        component_ids=component_ids,
        connection_ids=connection_ids,
        zones_crossed=zones_in_order,
        protocols=protocols,
        is_fully_encrypted=all_enc,
        has_unencrypted_hop=has_unenc,
        enters_restricted=enters_restricted,
        starts_external=starts_external,
        related_findings=sorted(related),
        score=score,
        narrative=_narrate(hops, zones_in_order, has_unenc, kind),
        warnings=(
            ["One or more hop directions were inferred from service-type heuristics."]
            if any(h.direction_inferred for h in hops) else []
        ),
    )


def _narrate(
    hops: list[JourneyHop],
    zones_in_order: list[str],
    has_unenc: bool,
    kind: JourneyKind,  # type: ignore[valid-type]
) -> str:
    """Short prose describing the journey for a non-technical reader."""
    if not hops:
        return ""

    first = hops[0]
    last = hops[-1]

    intro_by_kind: dict[str, str] = {
        "auth": (
            f"{first.from_name} authenticates against {last.to_name}"
        ),
        "read": (
            f"{first.from_name} reads from {last.to_name}"
        ),
        "write": (
            f"{first.from_name} writes to {last.to_name}"
        ),
        "admin": (
            f"{first.from_name} reaches the management plane at {last.to_name}"
        ),
        "integration": (
            f"{first.from_name} integrates with {last.to_name}"
        ),
        "generic": (
            f"{first.from_name} reaches {last.to_name}"
        ),
    }
    intro = intro_by_kind.get(str(kind), f"{first.from_name} reaches {last.to_name}")

    zone_summary = " → ".join(zones_in_order) if zones_in_order else ""
    enc_summary = (
        "with TLS at every hop"
        if not has_unenc and all(h.encrypted is True for h in hops)
        else (
            "with at least one unencrypted hop"
            if has_unenc else "with mixed or unverified encryption"
        )
    )

    pieces = [intro]
    if zone_summary:
        pieces.append(f"crossing {zone_summary}")
    pieces.append(enc_summary)
    return " ".join(pieces) + "."


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def extract_journeys(result: AnalysisResult) -> list[Journey]:
    """Return ranked Journey objects derived from the analysis graph."""
    if not result.components or not result.connections:
        return []

    adj, components = _build_graph(result)
    zones = _zone_kind_by_id(result)

    entries = _entry_points(result, zones)
    sinks = _sinks(result)

    # If there are no obvious entries, fall back to anything in `perimeter`
    # (edge components are nearly always reached from external traffic).
    if not entries:
        entries = [c for c in result.components if zones.get(c.trust_zone) == "perimeter"]

    if not entries or not sinks:
        return []

    findings_by_component: dict[str, list[str]] = defaultdict(list)
    findings_by_connection: dict[str, list[str]] = defaultdict(list)
    for f in result.compliance_findings:
        if f.status == "pass" or f.status == "not_applicable":
            # Only attach hits that surfaced an issue. Passes still apply
            # globally; tagging them per-journey would be noise.
            continue
        for cid in f.affected_component_ids:
            findings_by_component[cid].append(f.rule)
        for eid in f.affected_connection_ids:
            findings_by_connection[eid].append(f.rule)

    journeys: list[Journey] = []
    seen_signatures: set[tuple[str, ...]] = set()
    counter = 1

    for src in entries:
        for dst in sinks:
            if src.id == dst.id:
                continue
            paths_for_pair: list[list[tuple[str, Connection | None, bool]]] = []
            for path in _all_simple_paths(adj, src.id, dst.id):
                paths_for_pair.append(path)
                if len(paths_for_pair) >= _MAX_PATHS_PER_PAIR:
                    break
            for path in paths_for_pair:
                sig = tuple(n for n, _, _ in path)
                if sig in seen_signatures:
                    continue
                seen_signatures.add(sig)
                j = _annotate_journey(
                    path,
                    components,
                    zones,
                    findings_by_component,
                    findings_by_connection,
                    journey_id=f"j-{counter}",
                )
                if j is None:
                    continue
                if j.score < _MIN_SCORE:
                    continue
                journeys.append(j)
                counter += 1

    # Rank: highest score first, tie-break by length ASC so the cleanest
    # path of a given importance wins the top slot.
    journeys.sort(key=lambda j: (-j.score, len(j.hops)))

    # Drop journeys whose component sequence is a strict prefix of another
    # higher-scoring journey — keeps the list short.
    deduped: list[Journey] = []
    for j in journeys:
        sig = tuple(j.component_ids)
        is_prefix = False
        for other in deduped:
            other_sig = tuple(other.component_ids)
            if len(other_sig) > len(sig) and other_sig[: len(sig)] == sig:
                is_prefix = True
                break
        if not is_prefix:
            deduped.append(j)

    # Cap final output so UI stays readable.
    return deduped[:25]
