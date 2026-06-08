"""
src/processing/context_builder.py
Build a clean, token-efficient context string for the LLM from supplier + transaction data.
Keeps it under ~2000 tokens — phi3:mini has 4k context window.
"""

from datetime import date


def build_llm_context(event: dict, enriched_data: dict, max_suppliers: int = 5) -> str:
    """
    Build a structured prompt context from event + affected supplier data.
    Limits to top N closest suppliers to stay within small model context window.
    """
    today = date.today().isoformat()
    lines = []

    lines.append(f"## DISASTER EVENT")
    lines.append(f"Event: {event['title']}")
    lines.append(f"Type: {event.get('category_label', 'Unknown')}")
    lines.append(f"Location: {event['lat']:.3f}°, {event['lon']:.3f}°")
    lines.append(f"Date: {event.get('date', 'Recent')}")
    lines.append(f"Analysis Date: {today}")
    lines.append("")

    lines.append(f"## AFFECTED SUPPLIERS ({min(len(enriched_data), max_suppliers)} shown)")
    lines.append("")

    for i, (sid, data) in enumerate(list(enriched_data.items())[:max_suppliers]):
        sup = data["supplier_info"]
        open_pos = data["open_pos"]
        invoices = data["outstanding_invoices"]

        lines.append(f"### Supplier {i+1}: {sup['supplier_name']} ({sid})")
        lines.append(f"  Location: {sup['city']}, {sup['country']} — {sup.get('distance_km', '?'):.1f} km from event")
        lines.append(f"  Category: {sup['category']} | Risk Tier: {sup['risk_tier']} | Active: {sup['active']}")
        lines.append(f"  Contact: {sup['contact_name']} <{sup['contact_email']}>")
        lines.append(f"  Annual Spend: ${sup['annual_spend_usd']:,}")

        if open_pos:
            total_po_value = sum(p.get("po_value_usd", 0) for p in open_pos)
            lines.append(f"  Open POs: {len(open_pos)} orders | Total Value: ${total_po_value:,}")
            for po in open_pos[:3]:  # show max 3
                lines.append(f"    - {po['po_id']} | ${po.get('po_value_usd',0):,} | {po['status']} | Delivery: {po.get('expected_delivery','?')} | Criticality: {po.get('criticality','?')}")
        else:
            lines.append(f"  Open POs: None")

        if invoices:
            total_inv = sum(v.get("amount_usd", 0) for v in invoices)
            lines.append(f"  Outstanding Invoices: {len(invoices)} | Total: ${total_inv:,}")
            for inv in invoices[:2]:  # show max 2
                lines.append(f"    - {inv['invoice_id']} | ${inv.get('amount_usd',0):,} | {inv['status']} | Due: {inv.get('due_date','?')}")
        else:
            lines.append(f"  Outstanding Invoices: None")

        lines.append("")

    return "\n".join(lines)


def build_prompt(event: dict, enriched_data: dict) -> str:
    """Full prompt for phi3:mini — context + instruction."""
    context = build_llm_context(event, enriched_data)

    prompt = f"""{context}

## TASK
You are a supply chain risk analyst. Based on the disaster event and supplier data above:

1. Write a SHORT executive risk summary (3-4 sentences) for the sales/procurement team.
2. List each affected supplier with: risk level (High/Medium/Low), reason, and ONE suggested action.
3. Identify the top 1-2 critical POs at risk and why.

Be direct and specific. Use dollar amounts. No filler text.

## RISK REPORT"""

    return prompt