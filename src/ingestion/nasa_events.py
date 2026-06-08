import requests

EONET_URL = "https://eonet.gsfc.nasa.gov/api/v3/events"

TRACKED_CATEGORIES = {
    "SE": "Severe Storms",
    "WF": "Wildfires",
    "EQ": "Earthquakes",
    "FL": "Floods",
    "VO": "Volcanoes",
    "LS": "Landslides",
    "TC": "Tropical Cyclones",
    "DR": "Drought",
}

EVENT_SEVERITY = {
    "Earthquakes": 95,
    "Tropical Cyclones": 90,
    "Volcanoes": 85,
    "Floods": 80,
    "Wildfires": 75,
    "Severe Storms": 70,
    "Landslides": 65,
    "Drought": 50,
}


def fetch_events(days_back: int = 30, limit: int = 50) -> list[dict]:

    params = {
        "status": "open",
        "limit": limit,
        "days": days_back,
    }

    try:
        resp = requests.get(
            EONET_URL,
            params=params,
            timeout=15,
        )

        resp.raise_for_status()

        data = resp.json()

    except requests.RequestException as e:
        print(f"[NASA EONET] API error: {e}")
        return []

    events = []

    for evt in data.get("events", []):

        coords = _extract_coords(evt)

        if not coords:
            continue

        category = evt.get("categories", [{}])[0]

        category_label = TRACKED_CATEGORIES.get(
            category.get("id", ""),
            category.get("title", "Unknown"),
        )

        events.append(
            {
                "event_id": evt.get("id"),
                "title": evt.get("title"),
                "category_id": category.get("id", ""),
                "category_label": category_label,
                "event_severity": EVENT_SEVERITY.get(
                    category_label,
                    50,
                ),
                "date": evt.get("geometry", [{}])[-1].get(
                    "date",
                    "",
                ),
                "lat": coords[1],
                "lon": coords[0],
                "source_url": evt.get("sources", [{}])[0].get(
                    "url",
                    "",
                ),
            }
        )

    print(
        f"[NASA EONET] Fetched {len(events)} active events"
    )

    return events


def _extract_coords(evt: dict):

    geometries = evt.get("geometry", [])

    if not geometries:
        return None

    latest = geometries[-1]

    geom_type = latest.get("type", "")
    coords = latest.get("coordinates", [])

    if geom_type == "Point" and len(coords) >= 2:
        return (coords[0], coords[1])

    elif geom_type in (
        "Polygon",
        "MultiPolygon",
    ) and coords:

        ring = (
            coords[0]
            if geom_type == "Polygon"
            else coords[0][0]
        )

        if ring:

            avg_lon = (
                sum(p[0] for p in ring)
                / len(ring)
            )

            avg_lat = (
                sum(p[1] for p in ring)
                / len(ring)
            )

            return (
                avg_lon,
                avg_lat,
            )

    return None


if __name__ == "__main__":

    events = fetch_events()

    for event in events[:5]:
        print(event)