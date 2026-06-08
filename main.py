"""
main.py — SENTINELIQ entrypoint

Usage:
    python main.py                  # live NASA events, no email
    python main.py --radius 300     # custom impact radius in km
    python main.py --days 14        # look back N days for events
    python main.py --max-events 5   # process up to N events
    python main.py --mock-event     # test with hardcoded LA earthquake (no internet)

To remove mock-event later: delete the --mock-event block in main() and mock_event_run().
"""

import argparse
import json
from pathlib import Path
from datetime import datetime


def mock_event_run(radius_km: float):
    """
    Offline test using a hardcoded event.
    DELETE THIS FUNCTION when moving to production.
    """
    import pandas as pd
    from src.domain.supplier_matcher import match_suppliers_to_event, enrich_with_transactions, add_risk_scores
    from src.domain.context_builder import build_prompt
    from src.llm.risk_summarizer import generate_risk_report

    DATA_DIR = Path("data/mock")
    suppliers = pd.read_csv(DATA_DIR / "suppliers.csv")
    pos = pd.read_csv(DATA_DIR / "purchase_orders.csv")
    invoices = pd.read_csv(DATA_DIR / "invoices.csv")

    event = {
        "event_id": "MOCK-EQ-001",
        "title": "Magnitude 6.2 Earthquake near Los Angeles",
        "category_label": "Earthquakes",
        "event_severity": 95,
        "lat": 34.05,
        "lon": -118.24,
        "date": datetime.now().date().isoformat(),
        "source_url": "https://earthquake.usgs.gov",
    }

    affected = match_suppliers_to_event(event, suppliers, radius_km=radius_km)
    print(f"\n[Mock] Event: {event['title']}")
    print(f"[Mock] Affected suppliers within {radius_km}km: {len(affected)}")

    if affected.empty:
        print("[Mock] No suppliers in range. Try --radius 800")
        return []

    enriched = enrich_with_transactions(affected, pos, invoices)
    enriched = add_risk_scores(enriched, event)
    prompt = build_prompt(event, enriched)
    report = generate_risk_report(prompt)

    result = {
        "event": event,
        "affected_supplier_count": len(affected),
        "affected_suppliers": affected[
            ["supplier_id", "supplier_name", "city", "country", "distance_km",
             "contact_email", "risk_tier", "category"]
        ].to_dict(orient="records"),
        "risk_report": report,
        "generated_at": datetime.now().isoformat(),
    }

    print("\n" + "=" * 70)
    print(f"EVENT: {event['title']}")
    print(f"AFFECTED: {len(affected)} suppliers")
    print("-" * 70)
    print(report)
    print("=" * 70)

    Path("data/curate").mkdir(parents=True, exist_ok=True)
    out = f"data/curate/report_MOCK_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    with open(out, "w") as f:
        json.dump(result, f, indent=2, default=str)
    print(f"\n[Saved] {out}")
    return [result]


def main():
    parser = argparse.ArgumentParser(description="SENTINELIQ — Disaster Supply Chain Risk Monitor")
    parser.add_argument("--radius", type=float, default=500, help="Impact radius in km (default: 500)")
    parser.add_argument("--days", type=int, default=30, help="Days back to fetch NASA events (default: 30)")
    parser.add_argument("--max-events", type=int, default=3, help="Max events to process (default: 3)")
    parser.add_argument("--mock-event", action="store_true", help="Use mock event — no internet needed (PoC only)")
    args = parser.parse_args()

    print("""
 ____  _____ _   _ _____ ___ _   _ _____ _     ___ ___
/ ___|| ____| \\ | |_   _|_ _| \\ | | ____| |   |_ _/ _ \\
\\___ \\|  _| |  \\| | | |  | ||  \\| |  _| | |    | | | | |
 ___) | |___| |\\  | | |  | || |\\  | |___| |___ | | |_| |
|____/|_____|_| \\_| |_| |___|_| \\_|_____|_____|___\\__\\_\\
    Supply Chain Disaster Risk Monitor
    """)

    if args.mock_event:
        # --- REMOVE THIS BLOCK IN PRODUCTION ---
        results = mock_event_run(radius_km=args.radius)
        # --- END REMOVE ---
    else:
        from src.risk_engine.pipeline import run_pipeline
        results = run_pipeline(
            radius_km=args.radius,
            max_events=args.max_events,
            days_back=args.days,
        )

    if results:
        print(f"\n{len(results)} report(s) generated in data/curate/")
    else:
        print("\nNo actionable events found.")


if __name__ == "__main__":
    main()