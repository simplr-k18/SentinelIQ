"""
Generate mock supplier, PO, and invoice CSVs using Faker.
Run once: python data/mock/generate_mock_data.py
"""

import pandas as pd
from faker import Faker
import random

fake = Faker()
random.seed(42)

# Real-world cities prone to natural disasters
DISASTER_PRONE_CITIES = [
    {"city": "Los Angeles", "state": "California", "country": "US", "lat": 34.0522, "lon": -118.2437},
    {"city": "San Francisco", "state": "California", "country": "US", "lat": 37.7749, "lon": -122.4194},
    {"city": "Miami", "state": "Florida", "country": "US", "lat": 25.7617, "lon": -80.1918},
    {"city": "New Orleans", "state": "Louisiana", "country": "US", "lat": 29.9511, "lon": -90.0715},
    {"city": "Houston", "state": "Texas", "country": "US", "lat": 29.7604, "lon": -95.3698},
    {"city": "Seattle", "state": "Washington", "country": "US", "lat": 47.6062, "lon": -122.3321},
    {"city": "Portland", "state": "Oregon", "country": "US", "lat": 45.5051, "lon": -122.6750},
    {"city": "Phoenix", "state": "Arizona", "country": "US", "lat": 33.4484, "lon": -112.0740},
    {"city": "Chicago", "state": "Illinois", "country": "US", "lat": 41.8781, "lon": -87.6298},
    {"city": "New York", "state": "New York", "country": "US", "lat": 40.7128, "lon": -74.0060},
    {"city": "Tokyo", "state": "Tokyo", "country": "JP", "lat": 35.6762, "lon": 139.6503},
    {"city": "Osaka", "state": "Osaka", "country": "JP", "lat": 34.6937, "lon": 135.5023},
    {"city": "Manila", "state": "NCR", "country": "PH", "lat": 14.5995, "lon": 120.9842},
    {"city": "Jakarta", "state": "Jakarta", "country": "ID", "lat": -6.2088, "lon": 106.8456},
    {"city": "Mumbai", "state": "Maharashtra", "country": "IN", "lat": 19.0760, "lon": 72.8777},
    {"city": "Chennai", "state": "Tamil Nadu", "country": "IN", "lat": 13.0827, "lon": 80.2707},
    {"city": "Taipei", "state": "Taipei", "country": "TW", "lat": 25.0330, "lon": 121.5654},
    {"city": "Kathmandu", "state": "Bagmati", "country": "NP", "lat": 27.7172, "lon": 85.3240},
    {"city": "Santiago", "state": "Metropolitan", "country": "CL", "lat": -33.4489, "lon": -70.6693},
    {"city": "Lima", "state": "Lima", "country": "PE", "lat": -12.0464, "lon": -77.0428},
]

CATEGORIES = ["Raw Materials", "Electronics", "Packaging", "Logistics", "Chemicals", "Machinery", "IT Services", "MRO"]
RISK_TIERS = ["Tier 1", "Tier 2", "Tier 3"]
PO_STATUSES = ["Open", "In Transit", "Partial", "Confirmed", "Delayed"]
INV_STATUSES = ["Unpaid", "Paid", "Overdue", "Disputed"]


def generate_suppliers(n=80):
    rows = []
    for i in range(n):
        loc = random.choice(DISASTER_PRONE_CITIES)
        # Add small jitter so some suppliers are ~same city
        lat_jitter = random.uniform(-0.3, 0.3)
        lon_jitter = random.uniform(-0.3, 0.3)
        rows.append({
            "supplier_id": f"SUP-{1000 + i}",
            "supplier_name": fake.company(),
            "contact_name": fake.name(),
            "contact_email": fake.company_email(),
            "contact_phone": fake.phone_number(),
            "city": loc["city"],
            "state": loc["state"],
            "country": loc["country"],
            "lat": round(loc["lat"] + lat_jitter, 4),
            "lon": round(loc["lon"] + lon_jitter, 4),
            "category": random.choice(CATEGORIES),
            "risk_tier": random.choice(RISK_TIERS),
            "annual_spend_usd": random.randint(50_000, 5_000_000),
            "active": random.choice([True, True, True, False]),
        })
    return pd.DataFrame(rows)


def generate_purchase_orders(suppliers_df, n=300):
    rows = []
    for i in range(n):
        sup = suppliers_df.sample(1).iloc[0]
        order_date = fake.date_between(start_date="-180d", end_date="today")
        rows.append({
            "po_id": f"PO-{5000 + i}",
            "supplier_id": sup["supplier_id"],
            "supplier_name": sup["supplier_name"],
            "city": sup["city"],
            "country": sup["country"],
            "po_date": order_date,
            "expected_delivery": fake.date_between(start_date="today", end_date="+90d"),
            "category": sup["category"],
            "po_value_usd": random.randint(10_000, 500_000),
            "quantity": random.randint(10, 1000),
            "status": random.choice(PO_STATUSES),
            "criticality": random.choice(["High", "Medium", "Low"]),
        })
    return pd.DataFrame(rows)


def generate_invoices(suppliers_df, n=250):
    rows = []
    for i in range(n):
        sup = suppliers_df.sample(1).iloc[0]
        rows.append({
            "invoice_id": f"INV-{9000 + i}",
            "supplier_id": sup["supplier_id"],
            "supplier_name": sup["supplier_name"],
            "city": sup["city"],
            "country": sup["country"],
            "invoice_date": fake.date_between(start_date="-90d", end_date="today"),
            "due_date": fake.date_between(start_date="today", end_date="+60d"),
            "amount_usd": random.randint(5_000, 200_000),
            "status": random.choice(INV_STATUSES),
            "payment_terms": random.choice(["Net30", "Net60", "Net90"]),
        })
    return pd.DataFrame(rows)


if __name__ == "__main__":
    import os
    out = os.path.dirname(os.path.abspath(__file__))

    suppliers = generate_suppliers(80)
    pos = generate_purchase_orders(suppliers, 300)
    invoices = generate_invoices(suppliers, 250)

    suppliers.to_csv(f"{out}/suppliers.csv", index=False)
    pos.to_csv(f"{out}/purchase_orders.csv", index=False)
    invoices.to_csv(f"{out}/invoices.csv", index=False)

    print(f"✅ Generated: {len(suppliers)} suppliers, {len(pos)} POs, {len(invoices)} invoices")
    print(f"   Saved to: {out}/")