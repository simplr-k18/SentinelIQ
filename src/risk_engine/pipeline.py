"""
src/risk_engine/pipeline.py
Main orchestration: NASA events → supplier matching → risk scoring → LLM report.
"""

import pandas as pd
import json
from pathlib import Path
from datetime import datetime
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.ingestion.nasa_events import fetch_events
from src.domain.supplier_matcher import (
    match_suppliers_to_event,
    enrich_with_transactions,
    add_risk_scores,
)
from src.domain.context_builder import build_prompt
from src.llm.risk_summarizer import generate_risk_report

DATA_DIR = Path(__file__).parent.parent.parent / "data" / "mock"
OUTPUT_DIR = Path(__file__).parent.parent.parent / "data" / "curate"


def load_supplier_data():
    suppliers = pd.read_csv(DATA_DIR / "suppliers.csv")
    pos = pd.read_csv(DATA_DIR / "purchase_orders.csv")
    invoices = pd.read_csv(DATA_DIR / "invoices.csv")
    print(f"[Data] Loaded {len(suppliers)} suppliers, {len(pos)} POs, {len(invoices)} invoices")
    return suppliers, pos, invoices


def run_pipeline(
    radius_km: float = 500.0,
    max_events: int = 3,
    days_back: int = 30,
) -> list[dict]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    suppliers, pos, invoices = load_supplier_data()

    events = fetch_events(days_back=days_back, limit=50)
    if not events:
        print("[Pipeline] No events fetched — check internet or NASA API")
        return []

    actionable_events = []
    for event in events:
        affected = match_suppliers_to_event(event, suppliers, radius_km=radius_km)
        if not affected.empty:
            event["affected_count"] = len(affected)
            actionable_events.append((event, affected))

    print(f"[Pipeline] {len(actionable_events)} events with supplier exposure (within {radius_km}km)")

    if not actionable_events:
        print("[Pipeline] No supplier exposure found. Try increasing radius_km.")
        return []

    # Sort by most affected suppliers, process top N
    actionable_events.sort(key=lambda x: x[0]["affected_count"], reverse=True)
    actionable_events = actionable_events[:max_events]

    results = []
    for event, affected_suppliers in actionable_events:
        print(f"\n[Pipeline] Processing: {event['title']}")
        print(f"           {len(affected_suppliers)} suppliers within {radius_km}km")

        enriched = enrich_with_transactions(affected_suppliers, pos, invoices)
        enriched = add_risk_scores(enriched, event)
        prompt = build_prompt(event, enriched)
        report = generate_risk_report(prompt)

        result = {
            "event": event,
            "affected_supplier_count": len(affected_suppliers),
            "affected_suppliers": affected_suppliers[
                ["supplier_id", "supplier_name", "city", "country", "distance_km",
                 "contact_email", "risk_tier", "category"]
            ].to_dict(orient="records"),
            "risk_report": report,
            "generated_at": datetime.now().isoformat(),
        }
        results.append(result)

        safe_title = event["title"][:40].replace(" ", "_").replace("/", "-")
        out_path = OUTPUT_DIR / f"report_{safe_title}_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
        with open(out_path, "w") as f:
            json.dump(result, f, indent=2, default=str)
        print(f"[Pipeline] Saved: {out_path.name}")

    return results


if __name__ == "__main__":
    results = run_pipeline(radius_km=500, max_events=3, days_back=30)
    for r in results:
        print("\n" + "=" * 70)
        print(f"EVENT: {r['event']['title']}")
        print(f"AFFECTED SUPPLIERS: {r['affected_supplier_count']}")
        print("-" * 70)
        print(r["risk_report"])
        print("=" * 70)