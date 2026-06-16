"""
src/risk_engine/pipeline.py

Unified pipeline with deduplication and dual outputs (CSV + email payload).

Flow:
  fetch events (NASA + GDELT)
    → deduplicate across sources         [deduplicator.py]
    → match to suppliers                 [supplier_matcher / entity_matcher]
    → deduplicate supplier-event pairs   [deduplicator.py]
    → enrich with POs + invoices
    → score risk
    → build prompt + run LLM
    → write CSV outputs + email payloads [output_writer.py]
"""

import pandas as pd
import json
from pathlib import Path
from datetime import datetime
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.ingestion.nasa_events import fetch_events as fetch_nasa_events
from src.ingestion.gdelt_events import fetch_events as fetch_gdelt_events, fetch_mock_events as fetch_gdelt_mock
from src.domain.supplier_matcher import match_suppliers_to_event, enrich_with_transactions, add_risk_scores
from src.domain.entity_matcher import match_suppliers_to_news_event
from src.domain.context_builder import build_prompt
from src.llm.risk_summarizer import generate_risk_report
from src.risk_engine.deduplicator import deduplicate_events, deduplicate_supplier_events
from src.risk_engine.output_writer import write_outputs, send_all_emails

DATA_DIR  = Path(__file__).parent.parent.parent / "data" / "mock"
OUTPUT_DIR = Path(__file__).parent.parent.parent / "data" / "curate"


def load_supplier_data():
    suppliers = pd.read_csv(DATA_DIR / "suppliers.csv")
    pos       = pd.read_csv(DATA_DIR / "purchase_orders.csv")
    invoices  = pd.read_csv(DATA_DIR / "invoices.csv")
    print(f"[Data] {len(suppliers)} suppliers | {len(pos)} POs | {len(invoices)} invoices")
    return suppliers, pos, invoices


def run_pipeline(
    radius_km: float  = 500.0,
    max_events: int   = 5,
    days_back: int    = 30,
    source: str       = "all",
    mock_gdelt: bool  = False,
    email_recipients: list[str] = None,
) -> list[dict]:

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    suppliers, pos, invoices = load_supplier_data()
    all_events = []

    # ------------------------------------------------------------------
    # 1. Fetch events
    # ------------------------------------------------------------------
    if source in ("nasa", "all"):
        nasa_events = fetch_nasa_events(days_back=days_back, limit=50)
        for e in nasa_events:
            e["event_source"] = "nasa"
        all_events.extend(nasa_events)
        print(f"[Pipeline] NASA: {len(nasa_events)} events")

    if source in ("gdelt", "all"):
        gdelt_events = fetch_gdelt_mock() if mock_gdelt else fetch_gdelt_events(days_back=min(days_back, 7))
        for e in gdelt_events:
            e["event_source"] = "gdelt"
        all_events.extend(gdelt_events)
        print(f"[Pipeline] GDELT: {len(gdelt_events)} events {'(mock)' if mock_gdelt else ''}")

    if not all_events:
        print("[Pipeline] No events fetched.")
        return []

    # ------------------------------------------------------------------
    # 2. Deduplicate events across sources (Level 1)
    # ------------------------------------------------------------------
    all_events = deduplicate_events(all_events)
    print(f"[Pipeline] After dedup: {len(all_events)} unique events")

    # ------------------------------------------------------------------
    # 3. Match events to suppliers
    # ------------------------------------------------------------------
    actionable = []
    for event in all_events:
        if event["event_source"] == "gdelt":
            affected = match_suppliers_to_news_event(event, suppliers)
        else:
            affected = match_suppliers_to_event(event, suppliers, radius_km=radius_km)

        if not affected.empty:
            event["affected_count"] = len(affected)
            actionable.append((event, affected))

    print(f"[Pipeline] {len(actionable)} events with supplier exposure")

    if not actionable:
        print("[Pipeline] No supplier exposure found.")
        return []

    # ------------------------------------------------------------------
    # 4. Deduplicate supplier-event pairs (Level 2)
    # ------------------------------------------------------------------
    actionable = deduplicate_supplier_events(actionable)

    # Sort by severity then affected count, take top N
    actionable.sort(
        key=lambda x: (x[0].get("event_severity", 0), x[0]["affected_count"]),
        reverse=True,
    )
    actionable = actionable[:max_events]

    # ------------------------------------------------------------------
    # 5. Enrich, score, generate reports
    # ------------------------------------------------------------------
    results = []
    for event, affected_suppliers in actionable:
        src_tag = event.get("event_source", "").upper()
        print(f"\n[Pipeline] [{src_tag}] {event['title'][:60]}")
        print(f"           {len(affected_suppliers)} suppliers matched")

        enriched = enrich_with_transactions(affected_suppliers, pos, invoices)
        enriched = add_risk_scores(enriched, event)
        prompt   = build_prompt(event, enriched)
        report   = generate_risk_report(prompt)

        # Add enriched data to result so output_writer can access PO/invoice detail
        base_cols  = ["supplier_id", "supplier_name", "city", "country",
                      "contact_email", "contact_name", "annual_spend_usd",
                      "risk_tier", "category", "priority", "impact_score", "supplier_risk"]
        extra_cols = [c for c in ["distance_km", "match_method", "match_score"]
                      if c in affected_suppliers.columns]

        # Pull priority/impact_score back from enriched into the supplier rows
        supplier_records = []
        for _, row in affected_suppliers.iterrows():
            sid  = row["supplier_id"]
            rec  = row.to_dict()
            info = enriched.get(sid, {}).get("supplier_info", {})
            rec["priority"]      = info.get("priority", "")
            rec["impact_score"]  = info.get("impact_score", "")
            rec["supplier_risk"] = info.get("supplier_risk", "")
            supplier_records.append({k: rec.get(k, "") for k in base_cols + extra_cols})

        result = {
            "event":                    event,
            "affected_supplier_count":  len(affected_suppliers),
            "affected_suppliers":       supplier_records,
            "enriched_data":            enriched,   # for output_writer CSV detail
            "risk_report":              report,
            "generated_at":             datetime.now().isoformat(),
        }
        results.append(result)
        print(f"[Pipeline] Report generated")

    # ------------------------------------------------------------------
    # 6. Write outputs
    # ------------------------------------------------------------------
    write_outputs(results, run_id=run_id)

    if email_recipients:
        send_all_emails(results, run_id=run_id, recipients=email_recipients)

    return results


if __name__ == "__main__":
    results = run_pipeline(source="all", max_events=5, mock_gdelt=True)
    for r in results:
        print("\n" + "=" * 70)
        print(f"[{r['event'].get('event_source','').upper()}] {r['event']['title']}")
        print(f"AFFECTED: {r['affected_supplier_count']} suppliers")
        print("-" * 70)
        print(r["risk_report"])