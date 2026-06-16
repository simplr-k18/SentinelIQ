"""
src/domain/entity_matcher.py

Matches news events to suppliers using two strategies:

  Strategy 1 — NAME MATCH (for financial/operational events)
    Fuzzy match event title against supplier names.
    Uses token_set_ratio to handle "Acme Corp" vs "Acme Corporation Ltd".
    Threshold: 72 (tuned to avoid false positives on short names).

  Strategy 2 — LOCATION FALLBACK (for geo-tagged events)
    When name match finds nothing, fall back to haversine distance
    against supplier lat/lon (same logic as supplier_matcher.py).

  Strategy 3 — KEYWORD SECTOR MATCH (last resort)
    If event mentions a sector keyword ("electronics", "packaging", etc.)
    and no specific supplier is matched, flag all suppliers in that category
    as potentially exposed with a reduced severity multiplier (0.6x).

The function always returns a DataFrame with the same schema as
match_suppliers_to_event() so the pipeline treats both identically.
"""

import pandas as pd
import math
from rapidfuzz import fuzz


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

NAME_MATCH_THRESHOLD = 72       # minimum fuzzy score to count as a match
GEO_FALLBACK_RADIUS_KM = 300    # tighter than disaster radius — news events are specific
SECTOR_SEVERITY_MULTIPLIER = 0.6

# Sector keywords → supplier category values in mock data
SECTOR_KEYWORDS = {
    "electronics":   ["Electronics"],
    "semiconductor": ["Electronics"],
    "packaging":     ["Packaging"],
    "chemical":      ["Chemicals"],
    "logistics":     ["Logistics"],
    "machinery":     ["Machinery"],
    "raw material":  ["Raw Materials"],
    "it services":   ["IT Services"],
    "mro":           ["MRO"],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _name_score(event_title: str, supplier_name: str) -> int:
    """
    Fuzzy match score between event title and supplier name.
    token_set_ratio handles word reordering and partial containment:
      "Acme Electronics Corp bankruptcy" vs "Acme Electronics" → high score
      "Toyota strike Japan" vs "Acme Electronics" → low score
    """
    return fuzz.token_set_ratio(event_title.lower(), supplier_name.lower())


def _sector_match(event_text: str, supplier_category: str) -> bool:
    """Check if event text mentions the supplier's sector."""
    text = event_text.lower()
    for keyword, categories in SECTOR_KEYWORDS.items():
        if keyword in text and supplier_category in categories:
            return True
    return False


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def match_suppliers_to_news_event(
    event: dict,
    suppliers_df: pd.DataFrame,
    name_threshold: int = NAME_MATCH_THRESHOLD,
    geo_radius_km: float = GEO_FALLBACK_RADIUS_KM,
) -> pd.DataFrame:
    """
    Match a news event to affected suppliers.

    Returns DataFrame with added columns:
      match_method   — "name" | "geo" | "sector"
      match_score    — fuzzy score (name), distance_km (geo), 0 (sector)
      distance_km    — always present (0.0 for name/sector matches)
      severity_adj   — adjusted severity after sector multiplier

    Empty DataFrame if no match found.
    """
    event_title = event.get("title", "")
    event_text = event_title + " " + event.get("raw_excerpt", "")
    event_lat = event.get("lat", 0.0)
    event_lon = event.get("lon", 0.0)
    match_type_hint = event.get("match_type", "name")  # from ingestion layer

    df = suppliers_df.copy()
    results = []

    # ------------------------------------------------------------------
    # Strategy 1: Name match — always try this first
    # ------------------------------------------------------------------
    for _, sup in df.iterrows():
        score = _name_score(event_title, sup["supplier_name"])
        if score >= name_threshold:
            row = sup.to_dict()
            row["match_method"] = "name"
            row["match_score"] = score
            row["distance_km"] = 0.0
            row["severity_adj"] = event["event_severity"]
            results.append(row)

    if results:
        matched = pd.DataFrame(results).sort_values("match_score", ascending=False)
        return matched.reset_index(drop=True)

    # ------------------------------------------------------------------
    # Strategy 2: Geo fallback — if event has real coordinates
    # ------------------------------------------------------------------
    if event_lat != 0.0 or event_lon != 0.0:
        for _, sup in df.iterrows():
            dist = _haversine_km(event_lat, event_lon, sup["lat"], sup["lon"])
            if dist <= geo_radius_km:
                row = sup.to_dict()
                row["match_method"] = "geo"
                row["match_score"] = round(dist, 1)
                row["distance_km"] = round(dist, 1)
                row["severity_adj"] = event["event_severity"]
                results.append(row)

        if results:
            matched = pd.DataFrame(results).sort_values("distance_km")
            return matched.reset_index(drop=True)

    # ------------------------------------------------------------------
    # Strategy 3: Sector keyword match — last resort, reduced severity
    # ------------------------------------------------------------------
    for _, sup in df.iterrows():
        if _sector_match(event_text, sup["category"]):
            row = sup.to_dict()
            row["match_method"] = "sector"
            row["match_score"] = 0
            row["distance_km"] = 0.0
            row["severity_adj"] = int(event["event_severity"] * SECTOR_SEVERITY_MULTIPLIER)
            results.append(row)

    if results:
        return pd.DataFrame(results).reset_index(drop=True)

    # No match found
    return pd.DataFrame()


if __name__ == "__main__":
    import sys
    sys.path.insert(0, ".")
    import pandas as pd

    suppliers = pd.read_csv("data/mock/suppliers.csv")

    # Test name match
    event_name = {
        "event_id": "TEST-NAME",
        "title": "Goodwin-Todd files for bankruptcy protection",
        "category_label": "Supplier Bankruptcy",
        "event_severity": 92,
        "lat": 0.0, "lon": 0.0,
        "match_type": "name",
        "raw_excerpt": "Goodwin-Todd, a major supplier, has filed for Chapter 11.",
    }

    result = match_suppliers_to_news_event(event_name, suppliers)
    print(f"Name match result: {len(result)} suppliers")
    if not result.empty:
        print(result[["supplier_name", "match_method", "match_score"]].to_string())

    print()

    # Test geo fallback
    event_geo = {
        "event_id": "TEST-GEO",
        "title": "Strike at Tokyo manufacturing plants",
        "category_label": "Labour Strike",
        "event_severity": 75,
        "lat": 35.6762, "lon": 139.6503,
        "match_type": "geo",
        "raw_excerpt": "Workers at factories in Tokyo region begin indefinite strike.",
    }
    result2 = match_suppliers_to_news_event(event_geo, suppliers)
    print(f"Geo match result: {len(result2)} suppliers")
    if not result2.empty:
        print(result2[["supplier_name", "city", "match_method", "distance_km"]].to_string())