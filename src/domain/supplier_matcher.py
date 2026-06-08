"""
src/domain/supplier_matcher.py
Supplier geomatching + transaction enrichment + risk scoring.
"""

import math
import pandas as pd

from src.domain.risk_scoring import (
    calculate_supplier_risk,
    classify_risk,
    calculate_impact_score,
)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def match_suppliers_to_event(
    event: dict,
    suppliers_df: pd.DataFrame,
    radius_km: float = 500.0,
) -> pd.DataFrame:
    df = suppliers_df.copy()
    df["distance_km"] = df.apply(
        lambda row: haversine_km(event["lat"], event["lon"], row["lat"], row["lon"]),
        axis=1,
    )
    return df[df["distance_km"] <= radius_km].sort_values("distance_km").reset_index(drop=True)


def enrich_with_transactions(
    affected_suppliers: pd.DataFrame,
    pos_df: pd.DataFrame,
    invoices_df: pd.DataFrame,
) -> dict:
    result = {}
    for _, sup in affected_suppliers.iterrows():
        sid = sup["supplier_id"]
        open_pos = pos_df[
            (pos_df["supplier_id"] == sid)
            & (pos_df["status"].isin(["Open", "In Transit", "Partial", "Delayed"]))
        ]
        outstanding_invoices = invoices_df[
            (invoices_df["supplier_id"] == sid)
            & (invoices_df["status"].isin(["Unpaid", "Overdue", "Disputed"]))
        ]
        result[sid] = {
            "supplier_info": sup.to_dict(),
            "open_pos": open_pos.to_dict(orient="records"),
            "outstanding_invoices": outstanding_invoices.to_dict(orient="records"),
        }
    return result


def add_risk_scores(enriched_data: dict, event: dict) -> dict:
    event_severity = event.get("event_severity", 50)
    for sid, data in enriched_data.items():
        supplier = data["supplier_info"]
        open_po_value = sum(p.get("po_value_usd", 0) for p in data["open_pos"])
        invoice_value = sum(i.get("amount_usd", 0) for i in data["outstanding_invoices"])

        supplier_risk = calculate_supplier_risk(
            distance_km=supplier["distance_km"],
            annual_spend=supplier["annual_spend_usd"],
            open_po_value=open_po_value,
            overdue_invoice_value=invoice_value,
            risk_tier=supplier["risk_tier"],
        )
        impact_score = calculate_impact_score(supplier_risk, event_severity)

        supplier["supplier_risk"] = supplier_risk
        supplier["impact_score"] = impact_score
        supplier["priority"] = classify_risk(impact_score)

    return enriched_data