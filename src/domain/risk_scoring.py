"""
src/domain/risk_scoring.py
Rule-based supplier risk scoring — no model needed, pure business logic.
Two outputs:
  supplier_risk  — how exposed THIS supplier is (distance, spend, tier)
  impact_score   — combined score of supplier risk × event severity
"""


def calculate_supplier_risk(
    distance_km: float,
    annual_spend: float,
    open_po_value: float,
    overdue_invoice_value: float,
    risk_tier: str,
) -> int:
    score = 0

    # Proximity to event
    if distance_km <= 50:
        score += 30
    elif distance_km <= 200:
        score += 20
    elif distance_km <= 500:
        score += 10

    # Strategic importance (annual spend)
    if annual_spend >= 3_000_000:
        score += 25
    elif annual_spend >= 1_000_000:
        score += 15

    # Open PO financial exposure
    if open_po_value >= 500_000:
        score += 20
    elif open_po_value >= 100_000:
        score += 10

    # Outstanding invoice exposure
    if overdue_invoice_value >= 100_000:
        score += 15
    elif overdue_invoice_value >= 25_000:
        score += 5

    # Supply chain tier (Tier 1 = most critical)
    tier_scores = {"Tier 1": 10, "Tier 2": 5, "Tier 3": 2}
    score += tier_scores.get(risk_tier, 0)

    return min(score, 100)


def calculate_impact_score(supplier_risk: int, event_severity: int) -> int:
    """
    Combine supplier vulnerability with event severity.
    Both inputs 0-100. Output 0-100.
    Weighted: 60% supplier risk, 40% event severity.
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