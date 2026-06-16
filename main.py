"""
main.py — SENTINELIQ entrypoint

Usage:
    python main.py                            # all sources, live
    python main.py --source nasa              # natural disasters only
    python main.py --source gdelt             # news events only
    python main.py --mock-event               # offline NASA test
    python main.py --mock-event --mock-gdelt  # fully offline, both sources
    python main.py --email a@b.com c@d.com    # send email after run
    python main.py --radius 300 --days 14 --max-events 5
"""

import argparse
import json
from pathlib import Path
from datetime import datetime


def mock_event_run(radius_km, mock_gdelt, source, email_recipients):
    import pandas as pd
    from src.domain.supplier_matcher import match_suppliers_to_event, enrich_with_transactions, add_risk_scores
    from src.domain.entity_matcher import match_suppliers_to_news_event
    from src.domain.context_builder import build_prompt
    from src.llm.risk_summarizer import generate_risk_report
    from src.ingestion.gdelt_events import fetch_mock_events
    from src.risk_engine.deduplicator import deduplicate_events, deduplicate_supplier_events
    from src.risk_engine.output_writer import write_outputs, send_all_emails

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    DATA_DIR = Path("data/mock")
    suppliers = pd.read_csv(DATA_DIR / "suppliers.csv")
    pos       = pd.read_csv(DATA_DIR / "purchase_orders.csv")
    invoices  = pd.read_csv(DATA_DIR / "invoices.csv")

    raw_events = []

    if source in ("nasa", "all"):
        raw_events.append({
            "event_id": "MOCK-EQ-001",
            "title": "Magnitude 6.2 Earthquake near Los Angeles",
            "category_label": "Earthquakes",
            "event_severity": 95,
            "event_source": "nasa",
            "lat": 34.05, "lon": -118.24,
            "date": datetime.now().date().isoformat(),
            "source_url": "https://earthquake.usgs.gov",
        })

    if source in ("gdelt", "all") and mock_gdelt:
        for e in fetch_mock_events():
            e["event_source"] = "gdelt"
            raw_events.append(e)

    # Dedup
    raw_events = deduplicate_events(raw_events)

    actionable = []
    for event in raw_events:
        if event["event_source"] == "gdelt":
            affected = match_suppliers_to_news_event(event, suppliers)
        else:
            affected = match_suppliers_to_event(event, suppliers, radius_km=radius_km)
        if not affected.empty:
            event["affected_count"] = len(affected)
            actionable.append((event, affected))

    actionable = deduplicate_supplier_events(actionable)
    actionable.sort(key=lambda x: (x[0].get("event_severity", 0), x[0]["affected_count"]), reverse=True)

    results = []
    for event, affected_suppliers in actionable:
        enriched = enrich_with_transactions(affected_suppliers, pos, invoices)
        enriched = add_risk_scores(enriched, event)
        report   = generate_risk_report(build_prompt(event, enriched))

        base_cols  = ["supplier_id", "supplier_name", "city", "country",
                      "contact_email", "contact_name", "annual_spend_usd",
                      "risk_tier", "category"]
        extra_cols = [c for c in ["distance_km", "match_method"] if c in affected_suppliers.columns]

        supplier_records = []
        for _, row in affected_suppliers.iterrows():
            sid = row["supplier_id"]
            rec = row.to_dict()
            info = enriched.get(sid, {}).get("supplier_info", {})
            rec["priority"]      = info.get("priority", "")
            rec["impact_score"]  = info.get("impact_score", "")
            rec["supplier_risk"] = info.get("supplier_risk", "")
            supplier_records.append({k: rec.get(k, "") for k in base_cols + extra_cols + ["priority","impact_score","supplier_risk"]})

        result = {
            "event":                   event,
            "affected_supplier_count": len(affected_suppliers),
            "affected_suppliers":      supplier_records,
            "enriched_data":           enriched,
            "risk_report":             report,
            "generated_at":            datetime.now().isoformat(),
        }
        results.append(result)
        print(f"\n{'='*70}")
        print(f"[{event.get('event_source','').upper()}] {event['title']}")
        print(f"AFFECTED: {len(affected_suppliers)} suppliers")
        print("-"*70)
        print(report)

    write_outputs(results, run_id=run_id)
    if email_recipients:
        send_all_emails(results, run_id=run_id, recipients=email_recipients)
    return results


def main():
    parser = argparse.ArgumentParser(description="SENTINELIQ — Supply Continuity Risk Monitor")
    parser.add_argument("--source", choices=["nasa", "gdelt", "all"], default="all")
    parser.add_argument("--radius", type=float, default=500)
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--max-events", type=int, default=5)
    parser.add_argument("--email", nargs="*", default=None,
                        help="Email recipients e.g. --email a@co.com b@co.com")
    # --- REMOVE IN PRODUCTION ---
    parser.add_argument("--mock-event", action="store_true")
    parser.add_argument("--mock-gdelt", action="store_true")
    # --- END REMOVE ---
    args = parser.parse_args()

    print("""
 ____  _____ _   _ _____ ___ _   _ _____ _     ___ ___
/ ___|| ____| \\ | |_   _|_ _| \\ | | ____| |   |_ _/ _ \\
\\___ \\|  _| |  \\| | | |  | ||  \\| |  _| | |    | | | | |
 ___) | |___| |\\  | | |  | || |\\  | |___| |___ | | |_| |
|____/|_____|_| \\_| |_| |___|_| \\_|_____|_____|___\\__\\_\\
    Supply Continuity Risk Monitor  |  NASA + GDELT
    """)

    if args.mock_event or args.mock_gdelt:
        results = mock_event_run(
            radius_km=args.radius,
            mock_gdelt=args.mock_gdelt,
            source=args.source,
            email_recipients=args.email,
        )
    else:
        from src.risk_engine.pipeline import run_pipeline
        results = run_pipeline(
            radius_km=args.radius,
            max_events=args.max_events,
            days_back=args.days,
            source=args.source,
            mock_gdelt=False,
            email_recipients=args.email,
        )

    if results:
        print(f"\n{len(results)} report(s) → data/curate/csv/ and data/curate/email/")
    else:
        print("\nNo actionable events found.")


if __name__ == "__main__":
    main()