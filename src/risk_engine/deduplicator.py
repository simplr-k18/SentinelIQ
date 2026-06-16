"""
src/risk_engine/deduplicator.py

Two-level deduplication:

  Level 1 — EVENT dedup (before matching)
    Same physical event reported by both NASA and GDELT.
    Detection: geo proximity (< 200km) + same category + same 3-day window.
    Resolution: keep NASA event (authoritative coords), discard GDELT duplicate.

  Level 2 — SUPPLIER-EVENT dedup (after matching)
    Same supplier matched to two different events that are effectively
    the same incident (e.g. "LA wildfire" from NASA and "Los Angeles fire"
    from GDELT news). 
    Detection: same supplier_id appears in two events within 200km + 3 days.
    Resolution: keep the event with higher severity score.
"""

import math
from datetime import datetime, timedelta


GEO_DEDUP_RADIUS_KM = 200
DATE_WINDOW_DAYS = 3

# GDELT category → NASA category equivalents
CATEGORY_OVERLAP = {
    "Facility Fire":       ["Wildfires"],
    "Labour Strike":       [],
    "Supplier Bankruptcy": [],
    "Trade Restriction":   [],
    "Logistics Disruption":["Floods", "Severe Storms"],
    "Production Shutdown": ["Wildfires", "Volcanoes"],
    "Supply Shortage":     ["Earthquakes", "Floods", "Severe Storms", "Tropical Cyclones"],
}


def _haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _parse_date(date_str: str):
    if not date_str:
        return None
    for fmt in ("%Y-%m-%d", "%Y%m%dT%H%M%SZ", "%a, %d %b %Y %H:%M:%S %z"):
        try:
            return datetime.strptime(date_str[:10], "%Y-%m-%d")
        except Exception:
            pass
    return None


def _events_are_same_incident(e1: dict, e2: dict) -> bool:
    """
    Heuristic: two events from different sources describe the same incident
    if they are geographically close, temporally close, and categorically related.
    """
    # Skip if both have no real coordinates (lat=0, lon=0)
    if e1["lat"] == 0 and e1["lon"] == 0:
        return False
    if e2["lat"] == 0 and e2["lon"] == 0:
        return False

    dist = _haversine_km(e1["lat"], e1["lon"], e2["lat"], e2["lon"])
    if dist > GEO_DEDUP_RADIUS_KM:
        return False

    d1 = _parse_date(e1.get("date", ""))
    d2 = _parse_date(e2.get("date", ""))
    if d1 and d2:
        if abs((d1 - d2).days) > DATE_WINDOW_DAYS:
            return False

    # Check category overlap
    cat1 = e1.get("category_label", "")
    cat2 = e2.get("category_label", "")
    overlapping = CATEGORY_OVERLAP.get(cat1, []) + CATEGORY_OVERLAP.get(cat2, [])
    if cat1 == cat2 or cat1 in overlapping or cat2 in overlapping:
        return True

    return False


def deduplicate_events(events: list[dict]) -> list[dict]:
    """
    Level 1: Remove duplicate events across sources.
    When two events are the same incident:
      - Keep the one with higher event_severity
      - If tied, prefer NASA (authoritative geo data)
    Returns deduplicated list.
    """
    if not events:
        return []

    kept = []
    dropped_ids = set()

    for i, e1 in enumerate(events):
        if e1["event_id"] in dropped_ids:
            continue
        is_dup = False
        for j, e2 in enumerate(events):
            if i >= j:
                continue
            if e2["event_id"] in dropped_ids:
                continue
            if _events_are_same_incident(e1, e2):
                # Keep the one with higher severity; ties go to NASA
                sev1 = e1.get("event_severity", 0)
                sev2 = e2.get("event_severity", 0)
                if sev2 > sev1:
                    dropped_ids.add(e1["event_id"])
                    is_dup = True
                    break
                elif sev1 >= sev2:
                    dropped_ids.add(e2["event_id"])
                    print(f"[Dedup] Merged duplicate: '{e2['title'][:50]}' → kept '{e1['title'][:50]}'")

        if not is_dup:
            kept.append(e1)

    removed = len(events) - len(kept)
    if removed:
        print(f"[Dedup] Removed {removed} duplicate event(s) across sources")

    return kept


def deduplicate_supplier_events(actionable: list[tuple]) -> list[tuple]:
    """
    Level 2: If the same supplier appears in multiple events that are
    the same incident, keep only the highest-severity event for that supplier.
    This prevents the same supplier getting two almost-identical reports.
    """
    if not actionable:
        return actionable

    # Build map: supplier_id → list of (event_index, event)
    supplier_event_map: dict[str, list[int]] = {}
    for idx, (event, affected_df) in enumerate(actionable):
        for sid in affected_df["supplier_id"].tolist():
            supplier_event_map.setdefault(sid, []).append(idx)

    # Find supplier_ids appearing in multiple events that are the same incident
    events_to_remove = set()
    for sid, event_indices in supplier_event_map.items():
        if len(event_indices) <= 1:
            continue
        for i in range(len(event_indices)):
            for j in range(i + 1, len(event_indices)):
                ei, ej = event_indices[i], event_indices[j]
                e1 = actionable[ei][0]
                e2 = actionable[ej][0]
                if _events_are_same_incident(e1, e2):
                    # Drop the lower severity one
                    if e1.get("event_severity", 0) >= e2.get("event_severity", 0):
                        events_to_remove.add(ej)
                    else:
                        events_to_remove.add(ei)

    result = [item for idx, item in enumerate(actionable) if idx not in events_to_remove]
    if events_to_remove:
        print(f"[Dedup] Removed {len(events_to_remove)} redundant supplier-event pair(s)")

    return result