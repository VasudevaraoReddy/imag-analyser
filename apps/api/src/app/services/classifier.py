"""Deterministic N-S vs E-W flow classifier."""

from __future__ import annotations

from ..schemas import AnalysisResult, Flows, ParsingWarning, TrustZoneKind

ZONE_LEVEL: dict[TrustZoneKind, int] = {
    "external": 0,
    "perimeter": 1,
    "dmz": 2,
    "internal": 3,
    "restricted": 4,
    "management": 3,
}


def classify_flows(result: AnalysisResult) -> AnalysisResult:
    component_to_zone: dict[str, str] = {c.id: c.trust_zone for c in result.components}
    zones_by_id = {z.id: z for z in result.trust_zones}

    ns: list[str] = []
    ew: list[str] = []
    warnings = list(result.parsing_warnings)

    for conn in result.connections:
        if not conn.is_data_flow:
            continue

        from_zone_id = component_to_zone.get(conn.from_)
        to_zone_id = component_to_zone.get(conn.to)
        from_zone = zones_by_id.get(from_zone_id) if from_zone_id else None
        to_zone = zones_by_id.get(to_zone_id) if to_zone_id else None

        if from_zone is None or to_zone is None:
            ns.append(conn.id)
            warnings.append(
                ParsingWarning(
                    kind="ambiguous_edge",
                    message=(
                        f"Connection {conn.id!r}: zone unknown for one endpoint; "
                        "classified conservatively as north-south."
                    ),
                    affected_ids=[conn.id],
                )
            )
            continue

        if from_zone.kind == "external" or to_zone.kind == "external":
            ns.append(conn.id)
        elif ZONE_LEVEL[from_zone.kind] != ZONE_LEVEL[to_zone.kind]:
            ns.append(conn.id)
        else:
            ew.append(conn.id)

    return result.model_copy(
        update={
            "flows": Flows(north_south=ns, east_west=ew),
            "parsing_warnings": warnings,
        }
    )
