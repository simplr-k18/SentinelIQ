"""
src/domain/context_builder.py

Builds token-efficient LLM prompt from event + enriched supplier data.
Handles both event types — disaster events and news events get
slightly different framing so the model reasons correctly over each.
"""

from datetime import date


def build_llm_context(event: dict, enriched_data: dict, max_suppliers: int = 5) -> str:
    today = date.today().isoformat()
    event_source = event.get("event_source", "nasa")
    lines = []

    # ------------------------------------------------------------------
    # Event block — different label for disaster vs news
    # ------------------------------------------------------------------
    if event_source == "gdelt":
        lines.append("## SUPPLY CHAIN DISRUPTION SIGNAL")
        lines.append(f"Event: {event['title']}")
        lines.append(f"Type: {event.get('category_label', 'Unknown')}")
        lines.append(f"Severity: {event.get('event_severity', 'N/A')}/100")
        lines.append(f"Date: {event.get('date', 'Recent')}")
        lines.append(f"Analysis Date: {today}")
        if event.get("raw_excerpt"):
            lines.append(f"Source Context: {event['raw_excerpt'][:200]}")
        lines.append(f"Source: {event.get('source_url', '')}")
    else:
        lines.append("## DISASTER EVENT")
        lines.append(f"Event: {event['title']}")
        lines.append(f"Type: {event.get('category_label', 'Unknown')}")
        lines.append(f"Severity Score: {event.get('event_severity', 'N/A')}/100")
        lines.append(f"Location: {event['lat']:.3f}°, {event['lon']:.3f}°")
        lines.append(f"Date: {event.get('date', 'Recent')}")
        lines.append(f"Analysis Date: {today}")

    lines.append("")

    # ------------------------------------------------------------------
    # Supplier block
    # ------------------------------------------------------------------
    lines.append(f"## AFFECTED SUPPLIERS ({min(len(enriched_data), max_suppliers)} shown)")
    lines.append("")

    for i, (sid, data) in enumerate(list(enriched_data.items())[:max_suppliers]):
        sup = data["supplier_info"]
        open_pos = data["open_pos"]
        invoices = data["outstanding_invoices"]

        priority = sup.get("priority", "Unknown")
        impact_score = sup.get("impact_score", "N/A")
        supplier_risk = sup.get("supplier_risk", "N/A")
        match_method = sup.get("match_method", "geo")

        lines.append(f"### Supplier {i+1}: {sup['supplier_name']} ({sid})")
        lines.append(
            f"  Priority: {priority} | Impact Score: {impact_score}/100 "
            f"| Supplier Risk: {supplier_risk}/100 | Match: {match_method}"
        )
        lines.append(f"  Location: {sup['city']}, {sup['country']}")

        if match_method == "geo" and sup.get("distance_km", 0) > 0:
            lines.append(f"  Distance from event: {sup['distance_km']:.1f} km")

        lines.append(f"  Category: {sup['category']} | Risk Tier: {sup['risk_tier']} | Active: {sup['active']}")
        lines.append(f"  Contact: {sup['contact_name']} <{sup['contact_email']}>")
        lines.append(f"  Annual Spend: ${sup['annual_spend_usd']:,}")

        if open_pos:
            total_po_value = sum(p.get("po_value_usd", 0) for p in open_pos)
            lines.append(f"  Open POs: {len(open_pos)} orders | Total Value: ${total_po_value:,}")
            for po in open_pos[:3]:
                lines.append(
                    f"    - {po['po_id']} | ${po.get('po_value_usd', 0):,} | "
                    f"{po['status']} | Delivery: {po.get('expected_delivery', '?')} | "
                    f"Criticality: {po.get('criticality', '?')}"
                )
        else:
            lines.append("  Open POs: None")

        if invoices:
            total_inv = sum(v.get("amount_usd", 0) for v in invoices)
            lines.append(f"  Outstanding Invoices: {len(invoices)} | Total: ${total_inv:,}")
            for inv in invoices[:2]:
                lines.append(
                    f"    - {inv['invoice_id']} | ${inv.get('amount_usd', 0):,} | "
                    f"{inv['status']} | Due: {inv.get('due_date', '?')}"
                )
        else:
            lines.append("  Outstanding Invoices: None")

        lines.append("")

    return "\n".join(lines)


def build_prompt(event: dict, enriched_data: dict) -> str:
    context = build_llm_context(event, enriched_data)
    event_source = event.get("event_source", "nasa")

    if event_source == "gdelt":
        task = """## TASK
You are a supply chain risk analyst reviewing a news-based disruption signal.
Based on the event and supplier data above:

1. Write a SHORT executive risk summary (3-4 sentences). State what happened, which suppliers are exposed, and the total financial exposure.
2. For each supplier: state Priority, the specific risk this event creates for them, and ONE action the procurement team should take today.
3. Flag the top 1-2 open POs most at risk from this event and why.

Be direct and specific. Use dollar amounts. No filler text.

## RISK REPORT"""
    else:
        task = """## TASK
You are a supply chain risk analyst. Based on the disaster event and supplier data above:

1. Write a SHORT executive risk summary (3-4 sentences) for the sales/procurement team.
2. List each affected supplier with: Priority level, reason, and ONE concrete action.
3. Identify the top 1-2 critical POs at risk and why.

Use dollar amounts. Be direct. No filler text.

## RISK REPORT"""

    return f"{context}\n{task}"