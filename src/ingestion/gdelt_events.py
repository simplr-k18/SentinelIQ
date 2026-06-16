"""
src/ingestion/gdelt_events.py

Fetches supply chain disruption signals from two free sources:
  1. GDELT 2.0 Doc API  — global news, 15-min updates, no API key
  2. RSS feeds          — BBC Business, Reuters, FT fallbacks

Each article is classified into a disruption category and assigned
a severity score. Returns the same dict shape as nasa_events.py
so the rest of the pipeline needs zero changes.

Run on your machine: python src/ingestion/gdelt_events.py
"""

import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus
import hashlib
import re


# ---------------------------------------------------------------------------
# Disruption signal taxonomy
# Maps keyword patterns → (category_label, severity_score 0-100)
# Ordered by severity — first match wins
# ---------------------------------------------------------------------------
DISRUPTION_SIGNALS = [
    # Financial distress
    (["bankruptcy", "chapter 11", "chapter 7", "insolvency", "insolvent",
      "liquidat", "receivership", "creditor protection"],
     "Supplier Bankruptcy", 92),

    (["financial distress", "cash flow crisis", "debt default", "bond default",
      "credit downgrade", "payment default", "restructur"],
     "Financial Distress", 78),

    # Operational shutdown
    (["factory fire", "plant fire", "facility fire", "warehouse fire"],
     "Facility Fire", 90),

    (["factory shutdown", "plant shutdown", "facility closed", "production halt",
      "production suspended", "manufacturing halt", "plant closure"],
     "Production Shutdown", 85),

    (["product recall", "safety recall", "mandatory recall", "fda recall",
      "quality recall"],
     "Product Recall", 70),

    # Labour
    (["labour strike", "labor strike", "workers strike", "union strike",
      "walkout", "work stoppage", "industrial action"],
     "Labour Strike", 75),

    # Logistics & trade
    (["port congestion", "port closure", "port strike", "shipping delay",
      "container shortage", "freight disruption"],
     "Logistics Disruption", 68),

    (["trade sanction", "export ban", "import ban", "tariff", "trade restriction",
      "customs hold", "embargo"],
     "Trade Restriction", 72),

    # Geopolitical
    (["supply chain disruption", "supply shortage", "component shortage",
      "raw material shortage", "procurement crisis"],
     "Supply Shortage", 65),

    (["acquisition", "merger", "takeover", "acquired by", "bought by"],
     "M&A Activity", 45),

    (["executive resign", "ceo resign", "cfo resign", "leadership change",
      "management change"],
     "Leadership Change", 35),
]

# GDELT search queries — each targets a disruption cluster
GDELT_QUERIES = [
    "supplier bankruptcy insolvency",
    "factory shutdown production halt",
    "supply chain disruption shortage",
    "labour strike manufacturing",
    "trade sanction export ban supplier",
    "factory fire plant closure",
]

# Fallback RSS feeds (no API key needed)
RSS_FEEDS = [
    "https://feeds.bbci.co.uk/news/business/rss.xml",
    "https://rss.reuters.com/reuters/businessNews",
    "https://feeds.ft.com/rss/home/uk",
]

GDELT_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

# Known city coordinates for geocoding company HQ mentions
# Extended list — used when no lat/lon in article
CITY_COORDS = {
    "new york": (40.7128, -74.0060), "los angeles": (34.0522, -118.2437),
    "chicago": (41.8781, -87.6298), "houston": (29.7604, -95.3698),
    "san francisco": (37.7749, -122.4194), "seattle": (47.6062, -122.3321),
    "boston": (42.3601, -71.0589), "detroit": (42.3314, -83.0458),
    "miami": (25.7617, -80.1918), "dallas": (32.7767, -96.7970),
    "london": (51.5074, -0.1278), "paris": (48.8566, 2.3522),
    "berlin": (52.5200, 13.4050), "amsterdam": (52.3676, 4.9041),
    "frankfurt": (50.1109, 8.6821), "milan": (45.4654, 9.1859),
    "madrid": (40.4168, -3.7038), "stockholm": (59.3293, 18.0686),
    "tokyo": (35.6762, 139.6503), "osaka": (34.6937, 135.5023),
    "beijing": (39.9042, 116.4074), "shanghai": (31.2304, 121.4737),
    "shenzhen": (22.5431, 114.0579), "guangzhou": (23.1291, 113.2644),
    "seoul": (37.5665, 126.9780), "taipei": (25.0330, 121.5654),
    "singapore": (1.3521, 103.8198), "hong kong": (22.3193, 114.1694),
    "sydney": (-33.8688, 151.2093), "melbourne": (-37.8136, 144.9631),
    "mumbai": (19.0760, 72.8777), "delhi": (28.7041, 77.1025),
    "bangalore": (12.9716, 77.5946), "chennai": (13.0827, 80.2707),
    "jakarta": (-6.2088, 106.8456), "manila": (14.5995, 120.9842),
    "bangkok": (13.7563, 100.5018), "kuala lumpur": (3.1390, 101.6869),
    "dubai": (25.2048, 55.2708), "riyadh": (24.7136, 46.6753),
    "cairo": (30.0444, 31.2357), "johannesburg": (-26.2041, 28.0473),
    "sao paulo": (-23.5505, -46.6333), "mexico city": (19.4326, -99.1332),
    "toronto": (43.6532, -79.3832), "vancouver": (49.2827, -123.1207),
}


# ---------------------------------------------------------------------------
# Core classification
# ---------------------------------------------------------------------------

def classify_article(title: str, description: str) -> tuple[str, int] | None:
    """
    Match article text against disruption signal taxonomy.
    Returns (category_label, severity) or None if not supply-chain relevant.
    """
    text = (title + " " + description).lower()
    for keywords, label, severity in DISRUPTION_SIGNALS:
        if any(kw in text for kw in keywords):
            return label, severity
    return None


def extract_location(title: str, description: str) -> tuple[float, float] | None:
    """
    Try to extract a lat/lon from article text.
    Strategy: scan for known city names in text.
    Returns (lat, lon) or None.
    """
    text = (title + " " + description).lower()
    for city, coords in CITY_COORDS.items():
        if city in text:
            return coords
    return None


def make_event_id(title: str, date_str: str) -> str:
    """Stable deterministic ID from title + date."""
    raw = f"{title}{date_str}"
    return "GDELT-" + hashlib.md5(raw.encode()).hexdigest()[:10].upper()


# ---------------------------------------------------------------------------
# GDELT fetcher
# ---------------------------------------------------------------------------

def _fetch_gdelt(query: str, timespan: str = "7d", max_records: int = 10) -> list[dict]:
    """Fetch articles from GDELT 2.0 Doc API."""
    params = {
        "query": query,
        "mode": "artlist",
        "maxrecords": max_records,
        "timespan": timespan,
        "format": "json",
        "sourcelang": "english",
    }
    try:
        resp = requests.get(GDELT_URL, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json().get("articles", [])
    except Exception as e:
        print(f"[GDELT] Query '{query[:30]}' failed: {e}")
        return []


def _fetch_rss(feed_url: str, max_items: int = 10) -> list[dict]:
    """Fetch and parse an RSS feed as fallback."""
    try:
        resp = requests.get(feed_url, timeout=10,
                            headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        items = []
        for item in root.findall(".//item")[:max_items]:
            title = item.findtext("title", "")
            desc = item.findtext("description", "")
            link = item.findtext("link", "")
            pub_date = item.findtext("pubDate", "")
            items.append({
                "title": title,
                "description": desc,
                "url": link,
                "seendate": pub_date,
            })
        return items
    except Exception as e:
        print(f"[RSS] {feed_url} failed: {e}")
        return []


# ---------------------------------------------------------------------------
# Public interface — same shape as nasa_events.fetch_events()
# ---------------------------------------------------------------------------

def fetch_events(days_back: int = 7, max_per_query: int = 8) -> list[dict]:
    """
    Fetch supply chain disruption news from GDELT + RSS fallback.
    Returns list of event dicts compatible with the rest of the pipeline.

    Each event dict:
      event_id, title, category_label, event_severity,
      lat, lon, date, source_url, match_type, raw_excerpt
    """
    timespan = f"{days_back}d"
    raw_articles = []

    # 1. GDELT queries
    seen_urls = set()
    for query in GDELT_QUERIES:
        articles = _fetch_gdelt(query, timespan=timespan, max_records=max_per_query)
        for art in articles:
            url = art.get("url", "")
            if url not in seen_urls:
                seen_urls.add(url)
                raw_articles.append(art)

    # 2. RSS fallback if GDELT returned nothing
    if not raw_articles:
        print("[GDELT] Falling back to RSS feeds...")
        for feed in RSS_FEEDS:
            raw_articles.extend(_fetch_rss(feed, max_items=15))

    print(f"[GDELT] Raw articles fetched: {len(raw_articles)}")

    # 3. Classify and extract location
    events = []
    seen_ids = set()

    for art in raw_articles:
        title = art.get("title", "")
        description = art.get("description", "") or art.get("seendescription", "")
        url = art.get("url", "")
        date_str = art.get("seendate", art.get("pubDate", ""))

        if not title:
            continue

        # Classify disruption type
        classification = classify_article(title, description)
        if classification is None:
            continue  # not supply-chain relevant

        category_label, severity = classification

        # Extract location
        coords = extract_location(title, description)
        if coords is None:
            # Use a sentinel — entity matcher will handle by name instead
            lat, lon = 0.0, 0.0
            match_type = "name"
        else:
            lat, lon = coords
            match_type = "geo"

        # Deduplicate by event ID
        event_id = make_event_id(title, date_str)
        if event_id in seen_ids:
            continue
        seen_ids.add(event_id)

        events.append({
            "event_id": event_id,
            "title": title[:120],
            "category_label": category_label,
            "event_severity": severity,
            "lat": lat,
            "lon": lon,
            "date": date_str[:10] if date_str else datetime.now().date().isoformat(),
            "source_url": url,
            "match_type": match_type,          # "geo" or "name"
            "raw_excerpt": description[:300],  # for LLM context
        })

    print(f"[GDELT] Supply chain events classified: {len(events)}")
    return events


# ---------------------------------------------------------------------------
# Mock events for offline testing (same role as --mock-event in main.py)
# ---------------------------------------------------------------------------

def fetch_mock_events() -> list[dict]:
    """
    Hardcoded news events for offline PoC testing.
    DELETE when moving to production.
    """
    return [
        {
            "event_id": "GDELT-MOCK-001",
            "title": "Acme Electronics files for Chapter 11 bankruptcy protection",
            "category_label": "Supplier Bankruptcy",
            "event_severity": 92,
            "lat": 37.7749, "lon": -122.4194,
            "date": datetime.now().date().isoformat(),
            "source_url": "https://example.com/acme-bankruptcy",
            "match_type": "name",
            "raw_excerpt": "Acme Electronics, a major supplier of semiconductor components, "
                           "filed for Chapter 11 bankruptcy protection citing supply chain "
                           "pressures and rising debt costs.",
        },
        {
            "event_id": "GDELT-MOCK-002",
            "title": "Labour strike halts production at three Tokyo auto parts factories",
            "category_label": "Labour Strike",
            "event_severity": 75,
            "lat": 35.6762, "lon": 139.6503,
            "date": datetime.now().date().isoformat(),
            "source_url": "https://example.com/tokyo-strike",
            "match_type": "geo",
            "raw_excerpt": "Workers at three major auto parts manufacturing facilities "
                           "in the Tokyo metropolitan area began an indefinite strike "
                           "demanding wage increases of 15 percent.",
        },
        {
            "event_id": "GDELT-MOCK-003",
            "title": "US imposes export ban on advanced chip components to Chinese manufacturers",
            "category_label": "Trade Restriction",
            "event_severity": 72,
            "lat": 39.9042, "lon": 116.4074,
            "date": datetime.now().date().isoformat(),
            "source_url": "https://example.com/chip-ban",
            "match_type": "geo",
            "raw_excerpt": "The US Department of Commerce announced new export restrictions "
                           "on advanced semiconductor components affecting suppliers in "
                           "Shenzhen and Shanghai.",
        },
        {
            "event_id": "GDELT-MOCK-004",
            "title": "Fire destroys packaging plant in Houston, production suspended indefinitely",
            "category_label": "Facility Fire",
            "event_severity": 90,
            "lat": 29.7604, "lon": -95.3698,
            "date": datetime.now().date().isoformat(),
            "source_url": "https://example.com/houston-fire",
            "match_type": "geo",
            "raw_excerpt": "A fire broke out at a packaging materials manufacturing plant "
                           "in Houston, destroying the main production facility. "
                           "The company has suspended all operations indefinitely.",
        },
    ]


if __name__ == "__main__":
    print("Testing GDELT ingestion (live)...")
    events = fetch_events(days_back=7)
    if not events:
        print("No live events — showing mock events instead:")
        events = fetch_mock_events()
    for e in events[:5]:
        print(f"\n  [{e['category_label']}] {e['title'][:80]}")
        print(f"   Severity: {e['event_severity']} | Match: {e['match_type']} | Coords: {e['lat']:.2f}, {e['lon']:.2f}")