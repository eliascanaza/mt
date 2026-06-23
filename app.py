"""
exploreMore — Flask application
Serves the HTML frontend and exposes a REST API backed by SQLite.

Endpoints:
  GET  /                           → serve the HTML app
  GET  /api/top10                  → top10 places (?type=worldwide or ?type=country&country=Chile)
  GET  /api/top10/countries        → country directory (flag + destination count)
  GET  /api/getsavedplan            → plans for a user (?user_id=1111), most recent first
  POST /api/saveplan                → save a plan from a live search (from/to + stops found)
  GET  /api/autocomplete           → place suggestions for the search bar
  GET  /api/placeinformation        → place details (rating, weather, AI tip) by name
  GET  /api/suggestion              → real tourist places near a point (Google Places), for explore mode
  GET  /api/climate                 → live temperature range / best season / altitude for a point (Open-Meteo)
"""

import datetime
import json
import math
import os
import ssl
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
import certifi
from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory, render_template

import database as db

# Python.org's macOS builds don't always ship a usable CA trust store for
# urllib; pin it to certifi's bundle so outbound HTTPS calls (Places lookup)
# don't fail with CERTIFICATE_VERIFY_FAILED.
_SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())

load_dotenv()

app = Flask(__name__, template_folder="templates", static_folder="assets", static_url_path="/assets")
app.config["JSON_SORT_KEYS"] = False
app.config["GOOGLE_MAPS_API_KEY"] = os.environ.get("GOOGLE_MAPS_API_KEY", "")


# ── HTML frontend ────────────────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory("templates", "index.html")


@app.route("/profile")
def profile():
    return send_from_directory("templates", "profile.html")


@app.route("/home")
def home():
    return render_template("home.html", google_maps_api_key=app.config["GOOGLE_MAPS_API_KEY"])


@app.route("/info")
def info():
    return send_from_directory("templates", "info.html")


# ── Top 10 places (worldwide / by country / by category) ──────────────────
@app.route("/api/top10", methods=["GET"])
def api_top10_places():
    list_type = request.args.get("type", "worldwide").strip().lower()
    if list_type not in {"worldwide", "country", "category"}:
        return jsonify({"error": "type must be 'worldwide', 'country' or 'category'"}), 400

    country = request.args.get("country", "").strip()
    if list_type == "country" and not country:
        return jsonify({
            "error": "country is required when type=country",
            "available_countries": db.get_top10_countries(),
        }), 400

    items = db.get_top10_places(list_type, country or None)
    return jsonify({
        "list_type": list_type,
        "country": country or None,
        "items": items,
        "count": len(items),
    })


# ── Top 10 country directory (flag + destination count, for "Search by country") ─
@app.route("/api/top10/countries", methods=["GET"])
def api_top10_country_directory():
    return jsonify({"countries": db.get_top10_country_directory()})

# ── Autocomplete ─────────────────────────────────────────────────────────
@app.route("/api/autocomplete", methods=["GET"])
def api_autocomplete():
    """Place suggestions for the from/to search bar, queried from the DB."""
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"query": query, "results": []})
    results = db.search_places(query)
    return jsonify({"query": query, "results": results, "count": len(results)})


# ── Place details (mt_places) ───────────────────────────────────────────
@app.route("/api/placeinformation", methods=["GET"])
def api_mt_place():
    """Stands in for an external place-data provider: fetches rating, weather,
    season and AI-recommendation info for a place selected in the search bar."""
    name = request.args.get("name", "").strip()
    if not name:
        return jsonify({"error": "Missing required query param: name"}), 400
    place = db.get_mt_place(name)
    if not place:
        return jsonify({"error": f"No place data found for '{name}'"}), 404
    return jsonify({"place": place})


# ── Live climate (temperature range / best season / altitude) ────────────
# Single trusted public source for all three: Open-Meteo (open-meteo.com),
# a free, keyless weather API — no curated/mocked values involved.
_MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _fetch_json(url, timeout=8):
    with urllib.request.urlopen(url, timeout=timeout, context=_SSL_CONTEXT) as resp:
        return json.loads(resp.read())


def _fetch_elevation_m(lat, lng):
    params = urllib.parse.urlencode({"latitude": lat, "longitude": lng})
    data = _fetch_json(f"https://api.open-meteo.com/v1/elevation?{params}")
    elevations = data.get("elevation") or []
    return round(elevations[0]) if elevations else None


# Picks the 3 contiguous calendar months whose average temperature sits
# closest to a pleasant ~22°C, wrapping across year-end (e.g. Nov–Jan).
def _best_season_range(month_avg, window=3, target=22):
    if len(month_avg) < window:
        return None
    best_start, best_score = None, None
    for start in range(1, 13):
        months = [(start - 1 + i) % 12 + 1 for i in range(window)]
        vals = [month_avg[m] for m in months if m in month_avg]
        if len(vals) < window:
            continue
        score = sum(abs(v - target) for v in vals) / len(vals)
        if best_score is None or score < best_score:
            best_score, best_start = score, start
    if best_start is None:
        return None
    end = (best_start - 1 + window - 1) % 12 + 1
    return f"{_MONTH_ABBR[best_start - 1]} – {_MONTH_ABBR[end - 1]}"


def _fetch_climate(lat, lng):
    """12-month daily temperature history → an annual range (e.g. "8°–28°C")
    and the mildest 3-month window as the best season to visit."""
    end = datetime.date.today() - datetime.timedelta(days=7)  # archive data lags a few days
    start = end - datetime.timedelta(days=365)
    params = urllib.parse.urlencode({
        "latitude": lat, "longitude": lng,
        "start_date": start.isoformat(), "end_date": end.isoformat(),
        "daily": "temperature_2m_max,temperature_2m_min",
        "timezone": "auto",
    })
    data = _fetch_json(f"https://archive-api.open-meteo.com/v1/archive?{params}")
    daily = data.get("daily") or {}
    dates, highs, lows = daily.get("time") or [], daily.get("temperature_2m_max") or [], daily.get("temperature_2m_min") or []
    if not dates:
        return {}

    valid_highs = [h for h in highs if h is not None]
    valid_lows = [l for l in lows if l is not None]
    temperature = f"{round(min(valid_lows))}°–{round(max(valid_highs))}°C" if valid_highs and valid_lows else None

    month_temps = {}
    for d, h, l in zip(dates, highs, lows):
        if h is None or l is None:
            continue
        month = int(d.split("-")[1])
        month_temps.setdefault(month, []).append((h + l) / 2)
    month_avg = {m: sum(v) / len(v) for m, v in month_temps.items() if v}

    return {"temperature": temperature, "best_season": _best_season_range(month_avg)}


# WMO weather codes (used by Open-Meteo's "current"/"daily" fields) bucketed
# into the 4 backgrounds the popup can render.
_RAIN_CODES = {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 71, 73, 75, 77, 80, 81, 82, 85, 86, 95, 96, 99}
_CLOUDY_CODES = {1, 2, 3, 45, 48}


def _weather_condition(weather_code, is_day):
    if weather_code in _RAIN_CODES:
        return "rain"
    if not is_day:
        return "night"
    if weather_code in _CLOUDY_CODES:
        return "cloudy"
    return "sunny"


def _fetch_current_weather(lat, lng):
    """Right-now temperature + condition, and today's min/max — separate from
    _fetch_climate's 12-month history, since the forecast API (not archive)
    is what carries live/today data."""
    params = urllib.parse.urlencode({
        "latitude": lat, "longitude": lng,
        "current": "temperature_2m,weather_code,is_day",
        "daily": "temperature_2m_max,temperature_2m_min",
        "timezone": "auto",
        "forecast_days": 1,
    })
    data = _fetch_json(f"https://api.open-meteo.com/v1/forecast?{params}")
    current = data.get("current") or {}
    daily = data.get("daily") or {}
    now = current.get("temperature_2m")
    today_max = (daily.get("temperature_2m_max") or [None])[0]
    today_min = (daily.get("temperature_2m_min") or [None])[0]
    if now is None:
        return {}
    return {
        "now": round(now),
        "today_min": round(today_min) if today_min is not None else None,
        "today_max": round(today_max) if today_max is not None else None,
        "condition": _weather_condition(current.get("weather_code"), current.get("is_day", 1)),
    }


@app.route("/api/climate", methods=["GET"])
def api_climate():
    """Live temperature range, best-season window and altitude for a point,
    sourced from Open-Meteo — backs the temperature/best season/altitude
    fields in the place detail popup for any place, not just curated ones."""
    try:
        lat = float(request.args.get("lat", ""))
        lng = float(request.args.get("lng", ""))
    except (TypeError, ValueError):
        return jsonify({"error": "lat and lng query params are required"}), 400

    # Three independent Open-Meteo calls (elevation, 12-month archive, live
    # forecast) — run them concurrently so latency is bounded by the slowest
    # one instead of their sum.
    with ThreadPoolExecutor(max_workers=3) as pool:
        alt_future = pool.submit(_fetch_elevation_m, lat, lng)
        climate_future = pool.submit(_fetch_climate, lat, lng)
        current_future = pool.submit(_fetch_current_weather, lat, lng)

        try:
            altitude_m = alt_future.result()
        except Exception:
            altitude_m = None  # altitude is best-effort — leave it out rather than fail the whole request

        try:
            climate = climate_future.result()
        except Exception:
            climate = {}

        try:
            current = current_future.result()
        except Exception:
            current = {}

    return jsonify({
        "lat": lat,
        "lng": lng,
        "altitude": f"{altitude_m:,} m" if altitude_m is not None else None,
        "temperature": climate.get("temperature"),
        "best_season": climate.get("best_season"),
        "now_temp": current.get("now"),
        "today_min": current.get("today_min"),
        "today_max": current.get("today_max"),
        "condition": current.get("condition"),
        "source": "open-meteo.com",
    })


# ── Nearby tourist suggestions (explore mode, FROM-only search) ──────────
def _haversine_km(lat1, lng1, lat2, lng2):
    r = 6371
    dlat, dlng = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _estimate_drive_time(km):
    total_min = round((km / 70) * 60)  # rough 70 km/h average
    h, m = divmod(total_min, 60)
    return f"{h} h" + (f" {m} min" if m else "") if h else f"{m} min"


# Buckets a Google Place into the same trek/lake/town/trail filter tabs the
# explore-mode UI already has, from its name and Google "types".
def _categorize_place(name, types):
    name_l = name.lower()
    types = types or []
    if any(k in name_l for k in ("lake", "laguna", "lago", "lagoon")):
        return "lake", "Lake", "🏞️"
    if "park" in types or "hiking_area" in types or any(k in name_l for k in ("trail", "sendero", "trek")):
        return "trek", "Nature", "🏔️"
    if "natural_feature" in types or "mountain" in name_l:
        return "trail", "Adventure", "⛰️"
    return "town", "Culture", "🎭"


# Business types Nearby Search turns up that aren't tourist destinations —
# travel agencies, lodging, offices, and everyday errands around town.
_EXCLUDED_TYPES = {
    "travel_agency", "lodging", "real_estate_agency", "insurance_agency",
    "lawyer", "accounting", "finance", "bank", "atm",
    "general_contractor", "moving_company", "storage", "car_rental",
    "car_dealer", "car_repair", "school", "primary_school", "secondary_school",
    "local_government_office", "courthouse", "police", "post_office",
    "doctor", "dentist", "hospital", "pharmacy", "gym", "hair_care",
    "beauty_salon", "laundry", "convenience_store", "supermarket",
    "gas_station", "parking",
}

# A place needs at least this many ratings to count as "famous" — keeps the
# list to well-known landmarks (in town or out of it) instead of the long
# tail of minor businesses and one-off listings Nearby Search also returns.
_MIN_FAMOUS_RATINGS = 200


def _is_worth_suggesting(place):
    types = set(place.get("types") or [])
    if types & _EXCLUDED_TYPES:
        return False
    if place.get("business_status") == "CLOSED_PERMANENTLY":
        return False
    # "Personal posts" — generic, uncategorized pins (no specific type beyond
    # point_of_interest/establishment) are usually user-submitted, not real
    # attractions.
    if types <= {"point_of_interest", "establishment"}:
        return False
    if (place.get("user_ratings_total") or 0) < _MIN_FAMOUS_RATINGS:
        return False
    return True


def _fetch_places_nearby(lat, lng, radius, api_key, max_pages=3):
    """Calls Google Places Nearby Search, following next_page_token up to
    max_pages times so callers get many known places (~20 per page) instead
    of just the first page."""
    places = []
    page_token = None
    for _ in range(max_pages):
        params = {
            "location": f"{lat},{lng}",
            "radius": radius,
            "type": "tourist_attraction",
            "key": api_key,
        }
        if page_token:
            params = {"pagetoken": page_token, "key": api_key}
            time.sleep(2)  # a fresh page token isn't valid until Google activates it
        url = f"https://maps.googleapis.com/maps/api/place/nearbysearch/json?{urllib.parse.urlencode(params)}"
        with urllib.request.urlopen(url, timeout=8, context=_SSL_CONTEXT) as resp:
            data = json.loads(resp.read())
        if data.get("status") not in ("OK", "ZERO_RESULTS"):
            if not places:
                raise RuntimeError(f"{data.get('status')}: {data.get('error_message', '')}")
            break
        places.extend(data.get("results", []))
        page_token = data.get("next_page_token")
        if not page_token:
            break
    return places


@app.route("/api/suggestion", methods=["GET"])
def api_suggestion():
    """Real tourist attractions near a point, fetched server-side from Google
    Places Nearby Search — backs the map markers shown in explore mode when
    the user searches a FROM place with no destination."""
    try:
        lat = float(request.args.get("lat", ""))
        lng = float(request.args.get("lng", ""))
    except (TypeError, ValueError):
        return jsonify({"error": "lat and lng query params are required"}), 400

    from_name = request.args.get("name", "").strip()
    radius = request.args.get("radius", 10000, type=int)  # 10 km around the place
    api_key = app.config["GOOGLE_MAPS_API_KEY"]
    if not api_key:
        return jsonify({"error": "Server is missing GOOGLE_MAPS_API_KEY"}), 500

    try:
        places = _fetch_places_nearby(lat, lng, radius, api_key)
    except RuntimeError as e:
        return jsonify({"error": f"Places API error: {e}"}), 502
    except Exception as e:
        return jsonify({"error": f"Places lookup failed: {e}"}), 502

    places = [p for p in places if _is_worth_suggesting(p)]

    results = []
    for place in places:
        loc = (place.get("geometry") or {}).get("location") or {}
        p_lat, p_lng = loc.get("lat"), loc.get("lng")
        if p_lat is None or p_lng is None:
            continue
        dist_km = round(_haversine_km(lat, lng, p_lat, p_lng))
        cat, tag, emoji = _categorize_place(place.get("name", ""), place.get("types"))
        rating = place.get("rating")
        results.append({
            "emoji": emoji,
            "name": place.get("name", "Unnamed place"),
            "desc": place.get("vicinity") or (f"Popular spot near {from_name}" if from_name else "Popular nearby spot"),
            "rating": f"{rating:.1f}" if rating else "—",
            "reviews": str(place.get("user_ratings_total", 0)),
            "tag": tag,
            "dist": f"{dist_km} km",
            "time": _estimate_drive_time(dist_km),
            "cat": cat,
            "coord": [p_lng, p_lat],
        })

    results.sort(key=lambda r: -float(r["rating"]) if r["rating"] != "—" else 0)

    return jsonify({
        "from": {"name": from_name, "lat": lat, "lng": lng},
        "results": results,
        "count": len(results),
    })


# ── Fetch saved plans (for the "My Plans" tab, most recently saved first) ──
@app.route("/api/getsavedplan", methods=["GET"])
def api_get_saved_plans():
    user_id = request.args.get("user_id", 1111, type=int)
    plans = db.get_plans_for_user(user_id)
    return jsonify({"plans": plans, "count": len(plans)})


# ── Save plan (from a live search: real from/to + tourist stops found) ────
@app.route("/api/saveplan", methods=["POST"])
def api_save_plan_full():
    data = request.get_json(silent=True) or {}
    required = ["title", "from_name", "from_lat", "from_lng", "to_name", "to_lat", "to_lng"]
    missing = [f for f in required if data.get(f) in (None, "")]
    if missing:
        return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400

    plan_id = db.save_full_plan(
        title=data["title"],
        from_name=data["from_name"], from_lat=float(data["from_lat"]), from_lng=float(data["from_lng"]),
        to_name=data["to_name"], to_lat=float(data["to_lat"]), to_lng=float(data["to_lng"]),
        user_id=data.get("user_id", 1111),
        user_email=data.get("user_email", "test@gmail.com"),
        distance_km=data.get("distance_km"),
        duration_text=data.get("duration_text"),
        transport_mode=data.get("transport_mode"),
        places=data.get("places", []),
        notes=data.get("notes", ""),
    )
    return jsonify({"ok": True, "message": "Plan saved", "plan_id": plan_id}), 201


# ── Health check ────────────────────────────────────────────────────────────
@app.route("/api/health", methods=["GET"])
def health():
    try:
        stops = db.get_all_stops()
        return jsonify({
            "status": "ok",
            "db": db.MONGODB_DB_NAME,
            "stops_in_db": len(stops),
        })
    except Exception as e:
        return jsonify({"status": "error", "detail": str(e)}), 500


# Index creation is idempotent, so it's safe to run on every boot — under
# gunicorn this module is imported rather than run as __main__, so it has
# to happen here rather than in the block below. seed_db() is NOT called
# automatically: it wipes every collection before reseeding, which would
# destroy real user data (saved_plans) on every restart/redeploy. Run it
# manually once (`python3 database.py`) to load the reference/demo data.
db.init_db()

if __name__ == "__main__":
    print("\n🚀  exploreMore server starting at http://127.0.0.1:5004")
    print("   GET  /             → HTML app")
    print("   GET  /api/health   → health check\n")
    app.run(debug=True, host="0.0.0.0", port=5004)
