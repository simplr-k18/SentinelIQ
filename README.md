# SENTINELIQ

**Real-world event detection. Automated risk scoring. AI-generated summaries.**

SENTINELIQ is a proof-of-concept pipeline that watches live disaster events from NASA, matches them against any location-tagged operational dataset, scores exposure using rule-based logic, and generates a plain-language risk brief using a local AI model - all running on a laptop with no paid APIs.

It is built around a supplier intelligence use case. The architecture, however, is not supplier-specific. Any dataset that carries a location, a financial value, and a status can be dropped in: store networks, field assets, project sites, distribution hubs, partner offices. The pattern stays the same.

---

## The problem this solves

When a major event happens - earthquake, wildfire, cyclone - the people who need to act immediately rarely have the right information in front of them. They know something happened. They do not know which of their operations is inside the impact zone, what financial exposure is sitting open, and what to say to the people on the ground.

SENTINELIQ closes that gap in three steps: detect, assess, communicate.

---

## How it works

```
NASA EONET API
      |
      |  active disaster events with coordinates
      v
Event Ingestion
      |
      |  parse location, category, severity score
      v
Geo-Matching
      |
      |  haversine distance against every record in your dataset
      |  filter to within N km of the event
      v
Transaction Enrichment
      |
      |  pull open orders, outstanding invoices, active status
      v
Rule-Based Risk Scoring
      |
      |  proximity + financial exposure + tier weight = 0-100 score
      |  classify as Critical / High / Medium / Low
      v
Context Builder
      |
      |  format all the above into a structured prompt
      |  under 800 tokens - fits any small model
      v
Local LLM  (qwen2.5:3b via Ollama, runs on CPU)
      |
      |  executive summary, per-entity action list, top POs at risk
      v
JSON report saved to data/curate/
```

Nothing in this pipeline requires cloud compute, paid APIs, or a GPU.

---

## Where else this pattern applies

The geo-matching and scoring logic is domain-agnostic. Swap the input dataset and the output becomes a different product.

| Sector | Dataset | What SENTINELIQ monitors |
|---|---|---|
| Retail & FMCG | Store network with lat/lon | Which stores are inside a flood or fire zone |
| Energy | Pipeline or substation registry | Infrastructure exposed to earthquake or storm |
| Insurance | Policyholder locations | Claims likely to spike from a given event |
| Logistics | Active shipment routes | Routes crossing through disaster corridors |
| Real Estate | Property portfolio | Asset exposure by event type and proximity |
| Healthcare | Clinic and hospital network | Facilities in affected zones, staff coordination |
| Financial Services | Branch and ATM locations | Operational continuity risk by geography |

The NASA EONET categories tracked - earthquakes, wildfires, cyclones, floods, volcanoes, landslides, severe storms, drought - cover the events that matter across all of these.

---

## Tech stack

| Layer | Tool | Why |
|---|---|---|
| Event data | NASA EONET API | Free, real-time, globally comprehensive |
| Geo-matching | Haversine formula | No dependencies, exact for this scale |
| Data layer | pandas + Faker (mock) | CSV-in, easily swapped for any source |
| Risk scoring | Rule-based Python | Explainable, auditable, no black box |
| LLM inference | qwen2.5:3b via Ollama | Runs locally, zero cost, good instruction following |
| Output | JSON to disk | Easy to pipe into any downstream system |

No vector database. No RAG. No agents. The dataset fits in memory, the context fits in a prompt, and the task is structured enough that a 3B model handles it reliably. Complexity was added only where it earned its place.

---

## Project structure

```
SENTINELIQ/
|
+-- main.py                        Entry point
|
+-- data/
|   +-- mock/
|   |   +-- generate_mock_data.py  Faker-based CSV generator
|   |   +-- suppliers.csv          Generated on first run
|   |   +-- purchase_orders.csv
|   |   +-- invoices.csv
|   +-- curate/                    Risk reports land here (JSON)
|   +-- raw/                       Reserved for real source data
|
+-- src/
|   +-- ingestion/
|   |   +-- nasa_events.py         NASA EONET API client
|   |
|   +-- domain/
|   |   +-- supplier_matcher.py    Geo-matching + transaction enrichment
|   |   +-- risk_scoring.py        Scoring and classification logic
|   |   +-- context_builder.py     Prompt construction for LLM
|   |
|   +-- llm/
|   |   +-- risk_summarizer.py     Ollama inference wrapper
|   |
|   +-- risk_engine/
|       +-- pipeline.py            Full orchestration
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

**Requirements:** Python 3.10+, Linux or macOS, 8 GB RAM minimum.

**Step 1 - Install Ollama** (system-level, not inside venv)

```bash
curl -fsSL https://ollama.ai/install.sh | sh
ollama pull qwen2.5:3b
```

**Step 2 - Start the model server** (keep this terminal open)

```bash
ollama serve
```

**Step 3 - Set up Python environment**

```bash
cd SENTINELIQ
python3 -m venv .venv
source .venv/bin/activate
pip install faker pandas requests geopy
```

**Step 4 - Create package markers**

```bash
touch src/__init__.py src/domain/__init__.py src/ingestion/__init__.py src/llm/__init__.py src/risk_engine/__init__.py
```

**Step 5 - Generate mock data**

```bash
python data/mock/generate_mock_data.py
```

---

## Running

**Test the pipeline locally** (no internet needed, uses a hardcoded event)

```bash
python main.py --mock-event --radius 500
```

**Run against live NASA events**

```bash
python main.py --days 30 --radius 500
```

**Options**

```
--radius N        Impact zone radius in km (default: 500)
--days N          How far back to look for events (default: 30)
--max-events N    How many events to process per run (default: 3)
--mock-event      Use hardcoded test event, no NASA call
```

Reports are written to `data/curate/` as JSON files, one per event processed.

---

## Risk scoring logic

The scoring model is deterministic and auditable - no model involved at this stage.

```
Proximity score     0-30   (distance from event epicenter)
Spend score         0-25   (annual value of the relationship)
PO exposure         0-20   (open order value at risk)
Invoice exposure    0-15   (outstanding payment exposure)
Tier weight         0-10   (criticality classification)
                   ------
Total               0-100
```

Impact score combines supplier risk with event severity (weighted 60/40). The result classifies as Critical, High, Medium, or Low before the LLM ever runs. The LLM adds language, not logic.

---

## Design decisions

**Why not RAG?** The dataset is small enough to fit in a single prompt. RAG adds a retrieval layer to handle what cannot fit in context. At 80 entities, direct inclusion is faster, simpler, and more reliable.

**Why not a larger model?** The task is structured summarisation with a defined output format. A 3B model with good instruction tuning handles this reliably. Larger models add latency and memory pressure without improving the output quality for this specific task on consumer hardware.

**Why rule-based scoring instead of ML?** The scoring logic needs to be explainable and act on it. A weighted rule model can be audited, adjusted, and justified. A trained classifier cannot.

**Why local inference?** Zero cost. No data leaves the machine. Deployable in air-gapped environments. For a PoC that demonstrates the pipeline architecture, these matter more than raw model capability.

---

## Extending this

**To use real data instead of mock CSVs:** Replace the `pd.read_csv` calls in `pipeline.py` with your actual data source. The matcher expects columns: `supplier_id`, `lat`, `lon`, `annual_spend_usd`, `risk_tier`. Everything else flows from there.

**To add a new event source:** Implement a function that returns the same dict shape as `fetch_events()` in `nasa_events.py` - `event_id`, `title`, `category_label`, `event_severity`, `lat`, `lon`, `date`. Drop it into `src/ingestion/` and wire it into the pipeline.

**To swap the model:** Change `MODEL_NAME` in `src/llm/risk_summarizer.py`. Any model available in Ollama works. `phi3:mini` and `llama3.2:3b` are tested alternatives.

**To add email alerts:** Implement an SMTP sender in `src/notifications/` and call it from `main.py` after `run_pipeline()` returns results. The result dict contains everything needed: event metadata, affected entity list, and the LLM-generated report.

---

## Status

This is a proof of concept. The pipeline is complete and runs end-to-end. Production hardening - authentication, scheduling, a proper data connector layer, and a delivery mechanism - is out of scope for this version by design.

The goal here is to demonstrate the pattern: live signal detection, deterministic risk scoring, and AI-assisted communication, assembled from simple components that any team can understand, modify, and own.

---