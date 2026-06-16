# SENTINELIQ

**When something goes wrong in the world, SENTINELIQ tells you exactly which of your operations is at risk - before your inbox does.**

---

## What this is

Most companies find out a supplier is affected by a disaster, bankruptcy, or strike the same way everyone else does: a news alert, a late delivery, or a phone call. By then, the damage is already in motion.

SENTINELIQ is a pipeline that watches the world continuously - natural disasters from NASA, business disruptions from global news - and the moment something happens, it finds every supplier, facility, or partner inside that event's impact zone, calculates the financial exposure sitting in open orders and invoices, and produces a plain-language risk brief ready to act on.

It is built around supply chain. The pattern works for any business that has operations spread across geography: retail store networks, energy infrastructure, insurance portfolios, logistics routes, healthcare facilities.

---

## The signal sources

```
NASA EONET (real-time)          GDELT Global News (real-time)
  Earthquakes                     Supplier bankruptcy
  Wildfires                       Factory fire or shutdown
  Tropical cyclones               Labour strikes
  Floods                          Trade sanctions / export bans
  Volcanoes                       Financial distress signals
  Severe storms                   Product recalls
  Landslides                      Port and logistics disruptions
  Drought
        |                                   |
        +------------- unified -------------+
                            |
                    deduplicated event feed
                   (same incident from both
                    sources merged into one)
```

---

## How it works

A disaster or disruption event is detected. SENTINELIQ extracts its coordinates or the company name mentioned. It then checks every supplier in your data against that event using two strategies in sequence:

For geographic events - an earthquake, a flood, a factory fire with a known location - it calculates the straight-line distance between the event epicenter and every supplier location. Anyone within the defined radius is flagged.

For named-entity events - a bankruptcy filing, a sanction, a strike at a specific company - it fuzzy-matches the company name in the news article against your supplier names. If the name matches with enough confidence, that supplier is flagged. If no name match is found, it falls back to location.

Once suppliers are flagged, every open purchase order and outstanding invoice for those suppliers is pulled in. Each supplier gets a risk score from 0 to 100 based on four factors: how close they are to the event, how much annual spend they represent, the value of open orders at risk, and their supply chain tier. The event's own severity (earthquakes score 95, a leadership change scores 35) is combined with that supplier score to produce a final impact score.

That scored, enriched context is then formatted and sent to a local AI model - running entirely on your own hardware, no data leaving your environment - which writes the executive risk summary and per-supplier action list.

The output is four CSV files and a plain-text email payload per event.

---

## Output files

Every pipeline run produces these files in `data/curate/`:

```
csv/
  risk_report_summary.csv       One row per event - severity, affected count, total exposure
  affected_suppliers.csv        One row per supplier-event pair - scores, contact, financials
  open_pos_at_risk.csv          One row per open purchase order under an affected supplier
  outstanding_invoices.csv      One row per outstanding invoice under an affected supplier

email/
  email_<event_id>_<run_id>.txt   Ready-to-send plain text brief per event
```

The four CSVs are linked by `run_id` and `event_id` columns so they join cleanly in any BI tool or database.

---

## Risk scoring

The scoring is deterministic and fully auditable. No AI involved at this stage - a procurement manager can read the weights, challenge them, and adjust them.

```
Factor                   Max points    What it measures
-------------------------------------------------------------
Event proximity          30            Distance from epicenter in km
Annual spend             25            Strategic value of the relationship
Open PO exposure         20            Financial value of orders currently at risk
Invoice exposure         15            Outstanding payment obligations
Supply chain tier        10            Tier 1 / Tier 2 / Tier 3 classification
-------------------------------------------------------------
Supplier risk score      100

Combined with event severity (weighted 60% supplier / 40% event):
Impact score             100           Final score driving the priority label

Priority labels: Critical (80+)  High (60-79)  Medium (40-59)  Low (<40)
```

The AI model receives these scores as inputs. It explains them in plain language. It does not generate the numbers.

---

## Where else this applies

The event detection and matching logic is not specific to suppliers. Any dataset with a location, a financial value, and a status field works as input.

| Industry | What you put in | What you get out |
|---|---|---|
| Retail | Store locations and inventory levels | Which stores are inside a disaster zone and what stock is at risk |
| Insurance | Policyholder addresses and policy values | Expected claims volume before a single call comes in |
| Energy | Pipeline segments and substation locations | Infrastructure in earthquake or storm corridors |
| Logistics | Active shipment routes and delivery dates | Routes crossing disruption zones, estimated delay value |
| Healthcare | Clinic and hospital locations | Facilities in affected areas, staffing and supply implications |
| Financial services | Branch and ATM locations | Operational continuity risk by geography |
| Real estate | Property portfolio with asset values | Asset exposure by event type and proximity |

---

## Project structure

```
SENTINELIQ/
|
+-- main.py                              Entry point and CLI
|
+-- data/
|   +-- mock/
|   |   +-- generate_mock_data.py        Generates test supplier, PO, invoice CSVs
|   +-- raw/                             Drop real source data here
|   +-- curate/
|       +-- csv/                         Four output CSVs per run
|       +-- email/                       Email payloads per event
|
+-- src/
|   +-- ingestion/
|   |   +-- nasa_events.py               NASA EONET API client - natural disasters
|   |   +-- gdelt_events.py              GDELT + RSS - business disruption news
|   |
|   +-- domain/
|   |   +-- supplier_matcher.py          Haversine geo-matching for disaster events
|   |   +-- entity_matcher.py            Name match -> geo fallback -> sector match
|   |   +-- risk_scoring.py              Deterministic risk scoring for both event types
|   |   +-- context_builder.py           Formats data into LLM prompt
|   |
|   +-- llm/
|   |   +-- risk_summarizer.py           Ollama inference wrapper (qwen2.5:3b)
|   |
|   +-- risk_engine/
|       +-- pipeline.py                  Orchestrates the full run
|       +-- deduplicator.py              Merges duplicate events across sources
|       +-- output_writer.py             Writes CSVs and email payloads
|
+-- notebooks/
|   +-- 01_event_ingestion.ipynb
|   +-- 02_supplier_master.ipynb
|   +-- 06_llm_summary.ipynb
|
+-- requirements.txt
```

---

## Setup

**Requirements:** Python 3.10+, Linux or macOS, 8 GB RAM.

**Step 1 - Install Ollama** (system application, not inside your Python environment)

```bash
curl -fsSL https://ollama.ai/install.sh | sh
ollama pull qwen2.5:3b
```

Ollama installs as a system service. It starts automatically on boot. You do not need to run `ollama serve` manually after installation.

**Step 2 - Set up Python environment**

```bash
cd SENTINELIQ
python3 -m venv .venv
source .venv/bin/activate
pip install faker pandas requests geopy rapidfuzz
```

**Step 3 - Create package markers**

```bash
touch src/__init__.py src/domain/__init__.py src/ingestion/__init__.py \
      src/llm/__init__.py src/risk_engine/__init__.py
```

**Step 4 - Generate test data**

```bash
python data/mock/generate_mock_data.py
```

---

## Running

**Offline test - no internet, no API keys required**

```bash
python main.py --mock-event --mock-gdelt --source all
```

**Live run - natural disasters only**

```bash
python main.py --source nasa --days 30 --radius 500
```

**Live run - news events only**

```bash
python main.py --source gdelt --days 7
```

**Live run - both sources**

```bash
python main.py --source all --days 14 --max-events 5
```

**With email delivery** (configure SMTP in `src/risk_engine/output_writer.py` first)

```bash
python main.py --source all --email procurement@company.com risk-team@company.com
```

**All options**

```
--source          nasa | gdelt | all (default: all)
--radius N        Impact radius in km for geo events (default: 500)
--days N          How far back to look for events (default: 30)
--max-events N    How many events to process per run (default: 5)
--email addr...   Send email payload to these recipients after run
--mock-event      Use hardcoded earthquake - no internet needed
--mock-gdelt      Use hardcoded news events - no internet needed
```

---

## Design principles

**Explainability over accuracy.** The risk score is a weighted sum of auditable factors, not a machine learning prediction. A procurement manager can look at the weights, disagree with one, and change it. That matters more than an extra two points of precision.

**No unnecessary complexity.** There is no vector database, no retrieval layer, no agent framework. The dataset fits in memory. The context fits in a prompt. Simple components that any engineer can read and reason about in a day.

**Data stays local.** The AI model runs on your hardware via Ollama. Supplier names, purchase order values, and invoice details never leave your network. This is the answer to the compliance question before it is asked.

**One input format, any data source.** The pipeline expects three CSVs with defined columns. Whether those come from a mock generator, a PowerBI export, a Snowflake query, or an ERP extract is irrelevant to everything downstream.

---

## Current status

Proof of concept. The pipeline is complete and verified end-to-end. What comes next for production deployment - scheduling, a live data connector, a web interface, and cloud-based inference - is documented separately in the technical handover document.