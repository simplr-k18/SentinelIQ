"""
src/domain/risk_scoring.py

Rule-based risk scoring for both event types:
  - Natural disasters (geo proximity drives score)
  - News events (event severity + financial exposure drive score)

Three outputs:
  supplier_risk  — how exposed THIS supplier is
  impact_score   — combined score of supplier risk × event severity
  priority       — Critical / High / Medium / Low
"""


# ---------------------------------------------------------------------------
# Natural disaster scoring (existing — unchanged)
# ---------------------------------------------------------------------------

def calculate_supplier_risk(
    distance_km: float,
    annual_spend: float,
    open_po_value: float,
    overdue_invoice_value: float,
    risk_tier: str,
) -> int:
    score = 0

    if distance_km <= 50:
        score += 30
    elif distance_km <= 200:
        score += 20
    elif distance_km <= 500:
        score += 10

    if annual_spend >= 3_000_000:
        score += 25
    elif annual_spend >= 1_000_000:
        score += 15

    if open_po_value >= 500_000:
        score += 20
    elif open_po_value >= 100_000:
        score += 10

    if overdue_invoice_value >= 100_000:
        score += 15
    elif overdue_invoice_value >= 25_000:
        score += 5

    tier_scores = {"Tier 1": 10, "Tier 2": 5, "Tier 3": 2}
    score += tier_scores.get(risk_tier, 0)

    return min(score, 100)


# ---------------------------------------------------------------------------
# News event scoring (new)
# For non-geographic events: proximity is replaced by event type severity.
# Financial exposure and tier still apply.
# ---------------------------------------------------------------------------

def calculate_news_event_risk(
    event_severity: float,
    annual_spend: float,
    open_po_value: float,
    overdue_invoice_value: float,
    risk_tier: str,
    match_method: str = "name",
) -> int:
    """
    Score supplier exposure from a news event (bankruptcy, strike, etc.)

    event_severity:  0-100 from DISRUPTION_SIGNALS taxonomy
    match_method:    "name" | "geo" | "sector" — affects confidence weight
    """
    score = 0

    # Event severity is the primary driver (replaces proximity)
    # Confidence weight by match method
    confidence = {"name": 1.0, "geo": 0.85, "sector": 0.5}
    weighted_severity = event_severity * confidence.get(match_method, 0.7)

    if weighted_severity >= 85:
        score += 40
    elif weighted_severity >= 70:
        score += 28
    elif weighted_severity >= 50:
        score += 16
    else:
        score += 8

    # Financial exposure — same as disaster scoring
    if annual_spend >= 3_000_000:
        score += 25
    elif annual_spend >= 1_000_000:
        score += 15

    if open_po_value >= 500_000:
        score += 20
    elif open_po_value >= 100_000:
        score += 10

    if overdue_invoice_value >= 100_000:
        score += 15
    elif overdue_invoice_value >= 25_000:
        score += 5

    tier_scores = {"Tier 1": 10, "Tier 2": 5, "Tier 3": 2}
    score += tier_scores.get(risk_tier, 0)

    return min(score, 100)


# ---------------------------------------------------------------------------
# Shared functions
# ---------------------------------------------------------------------------

def calculate_impact_score(supplier_risk: int, event_severity: int) -> int:
    """
    Combined score: 60% supplier vulnerability + 40% event severity.
    """
    return min(int(supplier_risk * 0.6 + event_severity * 0.4), 100)


def classify_risk(score: int) -> str:
    if score >= 80:
        return "Critical"
    elif score >= 60:
        return "High"
    elif score >= 40:
        return "Medium"
    else:
        return "Low"