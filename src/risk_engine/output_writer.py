"""
src/risk_engine/output_writer.py

Two output formats per pipeline run:

  1. CSV outputs  (data/curate/csv/)
     - risk_report_summary.csv      one row per event processed
     - affected_suppliers.csv       one row per supplier-event pair
     - open_pos_at_risk.csv         one row per open PO under affected supplier
     - outstanding_invoices.csv     one row per outstanding invoice

  2. Email payload  (data/curate/email/)
     - email_<event_id>.txt         plain-text email body, ready to send
     Actual SMTP sending: placeholder function at bottom — wire in when ready.

All files are appended if they exist (idempotent runs), not overwritten.
A run_id column ties all four CSVs together for any given pipeline run.
"""

import csv
import os
from pathlib import Path
from datetime import datetime


OUTPUT_DIR = Path("data/curate")
CSV_DIR = OUTPUT_DIR / "csv"
EMAIL_DIR = OUTPUT_DIR / "email"


# ---------------------------------------------------------------------------
# CSV schemas
# ---------------------------------------------------------------------------

SUMMARY_COLS = [
    "run_id", "generated_at", "event_id", "event_source", "event_title",
    "category_label", "event_severity", "event_date", "lat", "lon",
    "affected_supplier_count", "total_open_po_value_usd",
    "total_invoice_exposure_usd", "top_priority",
]

SUPPLIER_COLS = [
    "run_id", "event_id", "event_source", "event_title", "category_label",
    "supplier_id", "supplier_name", "city", "country", "risk_tier", "category",
    "contact_name", "contact_email", "annual_spend_usd",
    "priority", "impact_score", "supplier_risk",
    "match_method", "distance_km",
    "open_po_count", "open_po_value_usd",
    "invoice_count", "invoice_value_usd",
]

PO_COLS = [
    "run_id", "event_id", "supplier_id", "supplier_name",
    "po_id", "po_value_usd", "status", "expected_delivery",
    "criticality", "category",
]

INVOICE_COLS = [
    "run_id", "event_id", "supplier_id", "supplier_name",
    "invoice_id", "amount_usd", "status", "due_date", "payment_terms",
]


def _ensure_csv(path: Path, cols: list[str]):
    """Create CSV with header if it doesn't exist."""
    if not path.exists():
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=cols)
            writer.writeheader()


def _append_rows(path: Path, cols: list[str], rows: list[dict]):
    with open(path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        writer.writerows(rows)


# ---------------------------------------------------------------------------
# Main writer
# ---------------------------------------------------------------------------

def write_outputs(results: list[dict], run_id: str = None) -> dict[str, Path]:
    """
    Write all CSV outputs and email payloads for a pipeline run.
    Returns dict of output file paths.
    """
    if not results:
        return {}

    CSV_DIR.mkdir(parents=True, exist_ok=True)
    EMAIL_DIR.mkdir(parents=True, exist_ok=True)

    if run_id is None:
        run_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    summary_path    = CSV_DIR / "risk_report_summary.csv"
    suppliers_path  = CSV_DIR / "affected_suppliers.csv"
    pos_path        = CSV_DIR / "open_pos_at_risk.csv"
    invoices_path   = CSV_DIR / "outstanding_invoices.csv"

    for path, cols in [
        (summary_path, SUMMARY_COLS),
        (suppliers_path, SUPPLIER_COLS),
        (pos_path, PO_COLS),
        (invoices_path, INVOICE_COLS),
    ]:
        _ensure_csv(path, cols)

    summary_rows    = []
    supplier_rows   = []
    po_rows         = []
    invoice_rows    = []

    for result in results:
        event   = result["event"]
        event_id = event["event_id"]
        event_source = event.get("event_source", "")
        event_title  = event.get("title", "")
        category     = event.get("category_label", "")

        # Aggregate financials across all affected suppliers
        all_po_value  = 0
        all_inv_value = 0
        top_priority  = "Low"
        priority_rank = {"Critical": 4, "High": 3, "Medium": 2, "Low": 1}

        # We need enriched data — stored in result if pipeline passed it through
        enriched = result.get("enriched_data", {})

        for sup_dict in result.get("affected_suppliers", []):
            sid = sup_dict["supplier_id"]
            sup_enriched = enriched.get(sid, {})

            open_po_value  = sum(p.get("po_value_usd", 0) for p in sup_enriched.get("open_pos", []))
            inv_value      = sum(i.get("amount_usd", 0) for i in sup_enriched.get("outstanding_invoices", []))
            all_po_value  += open_po_value
            all_inv_value += inv_value

            priority = sup_dict.get("priority", "Low")
            if priority_rank.get(priority, 0) > priority_rank.get(top_priority, 0):
                top_priority = priority

            supplier_rows.append({
                "run_id":               run_id,
                "event_id":             event_id,
                "event_source":         event_source,
                "event_title":          event_title[:80],
                "category_label":       category,
                "supplier_id":          sid,
                "supplier_name":        sup_dict.get("supplier_name", ""),
                "city":                 sup_dict.get("city", ""),
                "country":              sup_dict.get("country", ""),
                "risk_tier":            sup_dict.get("risk_tier", ""),
                "category":             sup_dict.get("category", ""),
                "contact_name":         sup_dict.get("contact_name", ""),
                "contact_email":        sup_dict.get("contact_email", ""),
                "annual_spend_usd":     sup_dict.get("annual_spend_usd", 0),
                "priority":             priority,
                "impact_score":         sup_dict.get("impact_score", ""),
                "supplier_risk":        sup_dict.get("supplier_risk", ""),
                "match_method":         sup_dict.get("match_method", ""),
                "distance_km":          round(sup_dict.get("distance_km", 0), 1),
                "open_po_count":        len(sup_enriched.get("open_pos", [])),
                "open_po_value_usd":    open_po_value,
                "invoice_count":        len(sup_enriched.get("outstanding_invoices", [])),
                "invoice_value_usd":    inv_value,
            })

            for po in sup_enriched.get("open_pos", []):
                po_rows.append({
                    "run_id":           run_id,
                    "event_id":         event_id,
                    "supplier_id":      sid,
                    "supplier_name":    sup_dict.get("supplier_name", ""),
                    "po_id":            po.get("po_id", ""),
                    "po_value_usd":     po.get("po_value_usd", 0),
                    "status":           po.get("status", ""),
                    "expected_delivery":po.get("expected_delivery", ""),
                    "criticality":      po.get("criticality", ""),
                    "category":         po.get("category", ""),
                })

            for inv in sup_enriched.get("outstanding_invoices", []):
                invoice_rows.append({
                    "run_id":           run_id,
                    "event_id":         event_id,
                    "supplier_id":      sid,
                    "supplier_name":    sup_dict.get("supplier_name", ""),
                    "invoice_id":       inv.get("invoice_id", ""),
                    "amount_usd":       inv.get("amount_usd", 0),
                    "status":           inv.get("status", ""),
                    "due_date":         inv.get("due_date", ""),
                    "payment_terms":    inv.get("payment_terms", ""),
                })

        summary_rows.append({
            "run_id":                    run_id,
            "generated_at":              result.get("generated_at", ""),
            "event_id":                  event_id,
            "event_source":              event_source,
            "event_title":               event_title[:80],
            "category_label":            category,
            "event_severity":            event.get("event_severity", ""),
            "event_date":                event.get("date", ""),
            "lat":                       event.get("lat", ""),
            "lon":                       event.get("lon", ""),
            "affected_supplier_count":   result.get("affected_supplier_count", 0),
            "total_open_po_value_usd":   all_po_value,
            "total_invoice_exposure_usd":all_inv_value,
            "top_priority":              top_priority,
        })

        # Write email payload
        _write_email_payload(result, run_id, email_dir=EMAIL_DIR)

    _append_rows(summary_path, SUMMARY_COLS, summary_rows)
    _append_rows(suppliers_path, SUPPLIER_COLS, supplier_rows)
    _append_rows(pos_path, PO_COLS, po_rows)
    _append_rows(invoices_path, INVOICE_COLS, invoice_rows)

    print(f"[Output] CSVs written to {CSV_DIR}/")
    print(f"         {len(summary_rows)} event(s) | {len(supplier_rows)} supplier rows | {len(po_rows)} PO rows")

    return {
        "summary":   summary_path,
        "suppliers": suppliers_path,
        "pos":       pos_path,
        "invoices":  invoices_path,
    }


# ---------------------------------------------------------------------------
# Email payload writer
# ---------------------------------------------------------------------------

def _write_email_payload(result: dict, run_id: str, email_dir: Path):
    """
    Write a plain-text email body for this event to disk.
    Call send_email() below to actually send it when SMTP is configured.
    """
    event = result["event"]
    event_id = event["event_id"]
    report = result.get("risk_report", "")
    suppliers = result.get("affected_suppliers", [])

    lines = []
    lines.append(f"Subject: [SENTINELIQ] {event.get('category_label','')} Alert — {result['affected_supplier_count']} Suppliers Affected")
    lines.append(f"Run ID: {run_id}")
    lines.append("")
    lines.append("=" * 60)
    lines.append(f"EVENT: {event.get('title','')}")
    lines.append(f"Type:  {event.get('category_label','')}  |  Severity: {event.get('event_severity','')}/100")
    lines.append(f"Date:  {event.get('date','')}")
    if event.get("source_url"):
        lines.append(f"Source: {event['source_url']}")
    lines.append("=" * 60)
    lines.append("")
    lines.append("RISK SUMMARY")
    lines.append("-" * 40)
    lines.append(report)
    lines.append("")
    lines.append("AFFECTED SUPPLIERS")
    lines.append("-" * 40)

    for s in suppliers:
        priority = s.get("priority", "")
        lines.append(
            f"  [{priority}] {s['supplier_name']} — {s.get('city','')}, {s.get('country','')}"
            f"  |  {s.get('risk_tier','')}  |  Contact: {s.get('contact_email','')}"
        )

    lines.append("")
    lines.append("Full detail: data/curate/csv/affected_suppliers.csv")
    lines.append("Generated by SENTINELIQ")

    out_path = email_dir / f"email_{event_id}_{run_id}.txt"
    with open(out_path, "w") as f:
        f.write("\n".join(lines))


# ---------------------------------------------------------------------------
# Email sender — PLACEHOLDER
# Wire this in when SMTP or API is available.
# ---------------------------------------------------------------------------

def send_email(email_txt_path: Path, recipients: list[str]):
    """
    PLACEHOLDER — reads the pre-written email payload and sends it.

    To activate:
      1. pip install secure-smtplib   (or use SendGrid / AWS SES SDK)
      2. Replace the body below with your SMTP or API call.

    Example with Gmail App Password:
      import smtplib
      from email.mime.text import MIMEText
      content = open(email_txt_path).read()
      lines = content.split("\\n")
      subject = lines[0].replace("Subject: ", "")
      body = "\\n".join(lines[2:])
      msg = MIMEText(body)
      msg["Subject"] = subject
      msg["From"] = "you@gmail.com"
      msg["To"] = ", ".join(recipients)
      with smtplib.SMTP("smtp.gmail.com", 587) as s:
          s.starttls()
          s.login("you@gmail.com", "your_app_password")
          s.sendmail("you@gmail.com", recipients, msg.as_string())
    """
    print(f"[Email] PLACEHOLDER — would send {email_txt_path.name} to {recipients}")
    print(f"[Email] Wire in SMTP/SES credentials to activate.")


def send_all_emails(results: list[dict], run_id: str, recipients: list[str]):
    """Call after write_outputs() — sends one email per event."""
    for result in results:
        event_id = result["event"]["event_id"]
        payload_path = EMAIL_DIR / f"email_{event_id}_{run_id}.txt"
        if payload_path.exists():
            send_email(payload_path, recipients)