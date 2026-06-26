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
  GET  /api/placeinformation        → place details (rating, weather, AI tip) by name; includes
                                      AI-generated food_info (typical_dishes, food_culture, must_try)
  GET  /api/typical-food           → AI-generated list of up to 5 iconic foods for a destination
                                      (?place=Tokyo) — each entry has name, description, and a
                                      Wikipedia thumbnail image URL; powered by Gemini 2.5 Flash
  GET  /api/traveler-summary       → AI-generated traveler summary for a place popup
                                      (?name=Tokyo&rating=4.8&cat=city) — returns summary,
                                      what_to_do, what_to_avoid, traveler_quotes; Gemini 2.5 Flash
  GET  /api/place-photos           → up to 10 high-quality photos for a destination with
                                      photographer attribution (?name=Tokyo) — Gemini selects
                                      iconic landmarks, images sourced from Wikimedia Commons
  GET  /api/suggestion              → real tourist places near a point (Google Places), for explore mode
  GET  /api/climate                 → live temperature range / best season / altitude for a point (Open-Meteo)
"""

import datetime
import json
import math
import os
import re
import ssl
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import List
import certifi
from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, request, send_from_directory, render_template, session
from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_auth_requests
from pydantic import BaseModel

try:
    import htmlmin as _htmlmin
except ImportError:
    _htmlmin = None

try:
    from google import genai as _genai
except ImportError:
    _genai = None

import database as db

# Python.org's macOS builds don't always ship a usable CA trust store for
# urllib; pin it to certifi's bundle so outbound HTTPS calls (Places lookup)
# don't fail with CERTIFICATE_VERIFY_FAILED.
_SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())

load_dotenv()

# ── Gemini AI ────────────────────────────────────────────────────────────────
class _FoodInfo(BaseModel):
    typical_dishes: List[str]
    food_culture: str
    must_try: str


_gemini_client = None
if _genai:
    _gemini_key = os.environ.get("GEMINI_API_KEY", "")
    if _gemini_key:
        _gemini_client = _genai.Client(api_key=_gemini_key)

_food_cache: dict = {}


class _FoodItem(BaseModel):
    name: str
    description: str
    wikipedia_title: str


class _TypicalFoods(BaseModel):
    foods: List[_FoodItem]


_typical_foods_cache: dict = {}


def _wiki_thumb(title: str) -> str:
    url = (
        "https://en.wikipedia.org/api/rest_v1/page/summary/"
        + urllib.parse.quote(title.replace(" ", "_"))
    )
    req = urllib.request.Request(url, headers={"User-Agent": "exploreMore/1.0 (travel app)"})
    try:
        with urllib.request.urlopen(req, timeout=5, context=_SSL_CONTEXT) as resp:
            data = json.loads(resp.read())
        return data.get("thumbnail", {}).get("source", "")
    except Exception:
        return ""


def _get_typical_foods_detail(place_name: str) -> list:
    if place_name in _typical_foods_cache:
        return _typical_foods_cache[place_name]
    if not _gemini_client:
        return []
    prompt = (
        f'You are a person who lives on this place, what food could you recommend to the traveler to eat in this place. List exactly 5 iconic traditional dishes or foods from "{place_name}". '
        "For each provide: name (the common dish name), "
        "short description (one sentence about the dish and its key flavors), "
        "wikipedia_title (the exact English Wikipedia article title for this dish — prefer dishes "
        "that are well-known enough to have a Wikipedia article with a photo)."
    )
    try:
        response = _gemini_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config={
                "response_mime_type": "application/json",
                "response_schema": _TypicalFoods,
            },
        )
        food_list = json.loads(response.text).get("foods", [])[:5]
    except Exception as exc:
        app.logger.warning("Gemini typical foods failed for %s: %s", place_name, exc)
        return []

    with ThreadPoolExecutor(max_workers=5) as pool:
        images = list(pool.map(
            lambda f: _wiki_thumb(f.get("wikipedia_title") or f.get("name", "")),
            food_list,
        ))

    result = [
        {
            "name": f.get("name", ""),
            "description": f.get("description", ""),
            "image": img,
        }
        for f, img in zip(food_list, images)
    ]
    _typical_foods_cache[place_name] = result
    return result


class _PlaceSearchTerms(BaseModel):
    terms: List[str]


_place_photos_cache: dict = {}


def _gemini_landmark_terms(place_name: str) -> list:
    """Ask Gemini for 6 iconic, well-photographed landmarks for a destination."""
    prompt = (
        f'List exactly 6 specific, famous, and highly-photographed landmarks, viewpoints, or '
        f'attractions that best represent "{place_name}". '
        f'Use precise proper names exactly as they appear on Wikipedia '
        f'(e.g. "Eiffel Tower", "Senso-ji", "Colosseum"). '
        f'These will be used to search Wikimedia Commons for high-quality travel photos.'
    )
    try:
        r = _gemini_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config={"response_mime_type": "application/json", "response_schema": _PlaceSearchTerms},
        )
        terms = json.loads(r.text).get("terms", [])
        return [t for t in terms if t][:6] or [place_name]
    except Exception as exc:
        app.logger.warning("Gemini landmark terms failed for %s: %s", place_name, exc)
        return [place_name]


def _wikimedia_photos_for_term(term: str) -> list:
    """Search Wikimedia Commons for up to 2 photos of a landmark, with attribution."""
    params = urllib.parse.urlencode({
        "action": "query",
        "generator": "search",
        "gsrnamespace": "6",
        "gsrsearch": term,
        "gsrlimit": "6",
        "prop": "imageinfo",
        "iiprop": "url|thumburl|extmetadata|mime|size",
        "iiurlwidth": "800",
        "iiextmetadatafilter": "Artist|LicenseShortName",
        "format": "json",
        "formatversion": "2",
    })
    url = f"https://commons.wikimedia.org/w/api.php?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "exploreMore/1.0 (travel app)"})
    try:
        with urllib.request.urlopen(req, timeout=8, context=_SSL_CONTEXT) as resp:
            data = json.loads(resp.read())
        pages = data.get("query", {}).get("pages", [])
        results = []
        for page in pages:
            info = (page.get("imageinfo") or [{}])[0]
            if not info.get("mime", "").startswith("image/"):
                continue
            img_url = info.get("thumburl") or info.get("url", "")
            if not img_url:
                continue
            meta = info.get("extmetadata", {})
            artist_raw = meta.get("Artist", {}).get("value", "")
            artist = re.sub(r"<[^>]+>", "", artist_raw).strip()[:80] or "Wikimedia Commons"
            license_ = meta.get("LicenseShortName", {}).get("value", "")
            results.append({
                "url": img_url,
                "photographer": artist,
                "license": license_,
                "source": "Wikimedia Commons",
            })
            if len(results) >= 2:
                break
        return results
    except Exception:
        return []


def _get_place_photos(place_name: str) -> list:
    if place_name in _place_photos_cache:
        return _place_photos_cache[place_name]
    terms = _gemini_landmark_terms(place_name) if _gemini_client else [place_name]
    with ThreadPoolExecutor(max_workers=6) as pool:
        batches = list(pool.map(_wikimedia_photos_for_term, terms))
    seen: set = set()
    photos = []
    for batch in batches:
        for p in batch:
            if p["url"] not in seen and len(photos) < 10:
                seen.add(p["url"])
                photos.append(p)

    # Guarantee at least 1 photo: retry with the raw place name
    if not photos:
        for p in _wikimedia_photos_for_term(place_name):
            if p["url"] not in seen:
                photos.append(p)
                seen.add(p["url"])

    # Last resort: Wikipedia article thumbnail
    if not photos:
        thumb = _wiki_thumb(place_name)
        if thumb:
            photos.append({"url": thumb, "photographer": "Wikipedia", "license": "", "source": "Wikipedia"})

    _place_photos_cache[place_name] = photos
    return photos


class _PlaceInfo(BaseModel):
    short_description: str
    rating: float
    total_reviews: int
    temperature: str
    best_season: str
    altitude: str


_place_info_cache: dict = {}


def _get_place_info_from_gemini(name: str) -> dict:
    """Ask Gemini to generate place-info fields for any destination not in the DB."""
    if name in _place_info_cache:
        return _place_info_cache[name]
    if not _gemini_client:
        return {}
    prompt = (
        f'Provide factual travel information for "{name}" as a destination. '
        f'Return a short_description (1 sentence, max 120 chars), '
        f'a typical traveler rating from 3.5 to 5.0, '
        f'estimated total_reviews (integer), '
        f'annual temperature range (e.g. "10°–28°C"), '
        f'best_season to visit (e.g. "Apr – Oct"), '
        f'and altitude above sea level (e.g. "45 m" or "2,430 m").'
    )
    try:
        r = _gemini_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config={"response_mime_type": "application/json", "response_schema": _PlaceInfo},
        )
        data = json.loads(r.text)
        result = {
            "name": name,
            "short_description": data.get("short_description", ""),
            "rating": float(data.get("rating", 4.0)),
            "total_reviews": int(data.get("total_reviews", 0)),
            "temperature": data.get("temperature", ""),
            "best_season": data.get("best_season", ""),
            "altitude": data.get("altitude", ""),
        }
    except Exception as exc:
        app.logger.warning("Gemini place-info failed for %s: %s", name, exc)
        result = {}
    _place_info_cache[name] = result
    return result


class _TravelerSummary(BaseModel):
    summary: str
    what_to_do: List[str]
    what_to_avoid: List[str]
    traveler_quotes: List[str]


_traveler_summary_cache: dict = {}


def _get_traveler_summary(name: str, rating: str, cat: str) -> dict:
    cache_key = f"{name}|{cat}"
    if cache_key in _traveler_summary_cache:
        return _traveler_summary_cache[cache_key]
    if not _gemini_client:
        return {}
    rating_str = rating if rating and rating != "—" else "4.5+"
    prompt = (
        f'You are a knowledgeable travel writer. Write a traveler summary for "{name}", '
        f'a {cat or "travel"} destination rated {rating_str}★ by visitors. '
        f"Be specific to this actual place — avoid generic travel advice. Provide: "
        f"summary (2 engaging sentences about why this place is special and what makes it worth visiting), "
        f"what_to_do (exactly 4 practical, place-specific tips that only apply to {name}), "
        f"what_to_avoid (exactly 3 practical warnings visitors should know about {name}), "
        f"traveler_quotes (exactly 3 short authentic first-person quotes from imagined past visitors — "
        f"under 20 words each, specific to this destination, not generic praise)."
    )
    try:
        response = _gemini_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config={
                "response_mime_type": "application/json",
                "response_schema": _TravelerSummary,
            },
        )
        result = json.loads(response.text)
        _traveler_summary_cache[cache_key] = result
        return result
    except Exception as exc:
        app.logger.warning("Gemini traveler summary failed for %s: %s", name, exc)
        return {}


def _get_food_info(place_name: str) -> dict:
    if place_name in _food_cache:
        return _food_cache[place_name]
    if not _gemini_client:
        return {}
    prompt = (
        f'You are a culinary and travel expert. For the destination "{place_name}", '
        "provide: typical_dishes (list of 4–6 traditional dishes or street foods), "
        "food_culture (one sentence describing the overall food scene), "
        "must_try (the single most iconic dish or drink a visitor should not miss)."
    )
    try:
        response = _gemini_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config={
                "response_mime_type": "application/json",
                "response_schema": _FoodInfo,
            },
        )
        result = json.loads(response.text)
        _food_cache[place_name] = result
        return result
    except Exception as exc:
        app.logger.warning("Gemini food info failed for %s: %s", place_name, exc)
        return {}


app = Flask(__name__, template_folder="templates", static_folder="assets", static_url_path="/assets")
app.config["JSON_SORT_KEYS"] = False
app.config["GOOGLE_MAPS_API_KEY"] = os.environ.get("GOOGLE_MAPS_API_KEY", "")
app.config["GOOGLE_CLIENT_ID"] = os.environ.get("GOOGLE_CLIENT_ID", "")
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-insecure-key-change-me")


@app.after_request
def _minify_response(response):
    if not _htmlmin or app.debug or not response.content_type.startswith("text/html"):
        return response
    html = response.get_data(as_text=True)
    # Try full minification first; if rjsmin can't handle the JS (e.g. nested
    # template literals), fall back to HTML+CSS only so something always ships.
    for js_min in (True, False):
        try:
            response.data = _htmlmin.minify(
                html,
                remove_comments=True,
                remove_empty_space=True,
                minify_js=js_min,
                minify_css=True,
            ).encode("utf-8")
            break
        except Exception:
            continue
    return response


# ── Public config endpoints (keys served at runtime, not baked into HTML) ─
@app.route("/api/mjs")
def maps_js():
    key = app.config["GOOGLE_MAPS_API_KEY"]
    url = f"https://maps.googleapis.com/maps/api/js?key={key}&libraries=marker,places&v=weekly"
    return redirect(url, code=302)


@app.route("/api/config")
def client_config():
    return jsonify({"client_id": app.config["GOOGLE_CLIENT_ID"]})


# ── HTML frontend ────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/profile")
def profile():
    return render_template("profile.html")


@app.route("/home")
def home():
    return render_template("home.html")


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
        place = _get_place_info_from_gemini(name)
    if not place:
        return jsonify({"error": f"No place data found for '{name}'"}), 404
    food_info = _get_food_info(name)
    if food_info:
        place["food_info"] = food_info
    return jsonify({"place": place})


# ── Typical foods for a destination (AI + Wikipedia images) ─────────────────
@app.route("/api/typical-food", methods=["GET"])
def api_typical_food():
    """Returns up to 5 iconic traditional foods for a destination.

    Query params:
      place  — destination name (e.g. "Tokyo", "Rome", "Mexico City")

    Response 200:
      {
        "place": "Tokyo",
        "foods": [
          {
            "name": "Sushi",
            "description": "Vinegared rice topped with fresh fish ...",
            "image": "https://upload.wikimedia.org/wikipedia/commons/..."
          },
          ...          // up to 5 items
        ]
      }

    Notes:
      - Powered by Gemini 2.0 Flash (structured JSON output via Pydantic schema).
      - Images are fetched from the Wikipedia REST Summary API (no key required).
      - Results are cached in-process; first call for a place takes ~2-3 s.
      - If Gemini is unavailable or quota is exceeded, foods array is empty (no 500).
    """
    place_name = request.args.get("place", "").strip()
    if not place_name:
        return jsonify({"error": "Missing required query param: place"}), 400
    foods = _get_typical_foods_detail(place_name)
    return jsonify({"place": place_name, "foods": foods})


# ── AI traveler summary for place popups ─────────────────────────────────────
@app.route("/api/traveler-summary", methods=["GET"])
def api_traveler_summary():
    """Returns an AI-generated traveler summary for a destination.

    Query params:
      name    — place name (required, e.g. "Tokyo")
      rating  — star rating string (optional, e.g. "4.8")
      cat     — place category (optional, e.g. "city", "beach", "trek")

    Response 200:
      {
        "place": "Tokyo",
        "summary": {
          "summary": "Two sentences about why this place is special...",
          "what_to_do": ["tip1", "tip2", "tip3", "tip4"],
          "what_to_avoid": ["warning1", "warning2", "warning3"],
          "traveler_quotes": ["quote1", "quote2", "quote3"]
        }
      }

    Notes:
      - Powered by Gemini 2.5 Flash with structured JSON output.
      - Results cached in-process per (name, category) pair.
      - Returns empty summary object if Gemini is unavailable (no 500).
    """
    name = request.args.get("name", "").strip()
    if not name:
        return jsonify({"error": "Missing required query param: name"}), 400
    rating = request.args.get("rating", "").strip()
    cat = request.args.get("cat", "").strip()
    result = _get_traveler_summary(name, rating, cat)
    return jsonify({"place": name, "summary": result})


# ── Place photos (Gemini landmark selection + Wikimedia Commons) ─────────────
@app.route("/api/place-photos", methods=["GET"])
def api_place_photos():
    """Returns up to 10 high-quality photos for a destination with photographer credit.

    Query params:
      name  — destination name (required, e.g. "Kyoto")

    Response 200:
      {
        "place": "Kyoto",
        "photos": [
          {
            "url": "https://upload.wikimedia.org/...",
            "photographer": "John Smith",
            "license": "CC BY-SA 4.0",
            "source": "Wikimedia Commons"
          },
          ...   // up to 10 items
        ]
      }

    Notes:
      - Gemini 2.5 Flash selects 6 iconic landmarks for the destination.
      - Each landmark is searched in Wikimedia Commons (free, attributed images).
      - Images are resized to 1200 px wide via Wikimedia thumbnail API.
      - Results cached in-process; first call ~3-5 s, subsequent calls instant.
      - Returns empty photos array if Gemini or Wikimedia are unavailable.
    """
    name = request.args.get("name", "").strip()
    if not name:
        return jsonify({"error": "Missing required query param: name"}), 400
    photos = _get_place_photos(name)
    return jsonify({"place": name, "photos": photos})


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
# ── Auth (Google Sign-In) ──────────────────────────────────────────────────
@app.route("/api/auth/google", methods=["POST"])
def api_auth_google():
    data = request.get_json(silent=True) or {}
    credential = data.get("credential")
    if not credential:
        return jsonify({"error": "Missing credential"}), 400
    if not app.config["GOOGLE_CLIENT_ID"]:
        return jsonify({"error": "Google sign-in is not configured"}), 500

    try:
        payload = google_id_token.verify_oauth2_token(
            credential, google_auth_requests.Request(), app.config["GOOGLE_CLIENT_ID"],
        )
    except ValueError:
        return jsonify({"error": "Invalid Google credential"}), 401

    user = db.get_or_create_google_user(
        google_sub=payload["sub"],
        email=payload.get("email", ""),
        name=payload.get("name") or payload.get("email", "Traveller"),
        picture=payload.get("picture", ""),
    )
    session["user_id"] = user["id"]
    return jsonify({"ok": True, "user": user})


@app.route("/api/auth/me", methods=["GET"])
def api_auth_me():
    user_id = session.get("user_id")
    user = db.get_user_by_id(user_id) if user_id else None
    if not user:
        session.clear()
        return jsonify({"authenticated": False}), 401
    return jsonify({"authenticated": True, "user": user})


@app.route("/api/auth/logout", methods=["POST"])
def api_auth_logout():
    session.clear()
    return jsonify({"ok": True})


# ── Profile forms (Personal Info, Travel Preferences, App Settings,
# Notifications, Privacy) — each profile.html "Save" button PUTs its
# section's fields here, scoped to the signed-in session user. ──────────────
@app.route("/api/profile/<section>", methods=["PUT"])
def api_update_profile_section(section):
    if section not in db.PROFILE_SECTIONS:
        return jsonify({"error": f"Unknown profile section: {section}"}), 404
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"error": "Not signed in"}), 401
    fields = request.get_json(silent=True) or {}
    user = db.update_user_section(user_id, section, fields)
    return jsonify({"ok": True, "user": user})


# ── Search history (History tab) — /home logs every search here; the
# Countries visited / Places explored / km travelled stats are aggregated
# from this log rather than tracked separately. ───────────────────────────
@app.route("/api/history/search", methods=["POST"])
def api_record_search():
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"error": "Not signed in"}), 401
    data = request.get_json(silent=True) or {}
    if not data.get("from_name"):
        return jsonify({"error": "Missing from_name"}), 400
    entry_id = db.record_search(user_id, data)
    return jsonify({"ok": True, "id": entry_id}), 201


@app.route("/api/history", methods=["GET"])
def api_get_history():
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"error": "Not signed in"}), 401
    return jsonify({
        "history": db.get_search_history(user_id),
        "stats": db.get_search_history_stats(user_id),
    })


@app.route("/api/getsavedplan", methods=["GET"])
def api_get_saved_plans():
    user_id = request.args.get("user_id", type=int) or session.get("user_id", 1111)
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

    session_user = db.get_user_by_id(session["user_id"]) if session.get("user_id") else None

    plan_id = db.save_full_plan(
        title=data["title"],
        from_name=data["from_name"], from_lat=float(data["from_lat"]), from_lng=float(data["from_lng"]),
        to_name=data["to_name"], to_lat=float(data["to_lat"]), to_lng=float(data["to_lng"]),
        user_id=session_user["id"] if session_user else data.get("user_id", 1111),
        user_email=session_user["email"] if session_user else data.get("user_email", "test@gmail.com"),
        distance_km=data.get("distance_km"),
        duration_text=data.get("duration_text"),
        transport_mode=data.get("transport_mode"),
        places=data.get("places", []),
        notes=data.get("notes", ""),
    )
    return jsonify({"ok": True, "message": "Plan saved", "plan_id": plan_id}), 201


# ── Typical food ────────────────────────────────────────────────────────────

def _wiki_api(params, timeout=8):
    """Call the Wikipedia MediaWiki API and return parsed JSON."""
    base = "https://en.wikipedia.org/w/api.php"
    qs = urllib.parse.urlencode({**params, "format": "json"})
    req = urllib.request.Request(
        f"{base}?{qs}",
        headers={"User-Agent": "exploreMore/1.0 (travel planning app)"},
    )
    with urllib.request.urlopen(req, context=_SSL_CONTEXT, timeout=timeout) as resp:
        return json.loads(resp.read())


def _fetch_typical_food(place: str):
    """Return up to 10 typical dishes for *place* using Wikipedia data.

    Strategy:
      1. Find the canonical "{place} cuisine" Wikipedia article.
      2. Get its section list and identify food/dish sections.
      3. Pull wikilinks from those sections — these are actual dish names.
      4. Batch-fetch thumbnails + one-sentence description for each dish.
    """
    # Section headings that indicate the content lists actual dishes
    dish_section_keywords = {
        "dish", "food", "snack", "dessert", "soup", "bread",
        "beverage", "drink", "meat", "seafood", "sauce", "regional",
        "coastal", "andes", "amazon", "typical", "main", "popular",
        "street", "sweet", "traditional",
    }

    # 1. Find the canonical cuisine article name
    search = _wiki_api({
        "action": "query",
        "list": "search",
        "srsearch": f"{place} cuisine",
        "srlimit": 1,
    })
    sr = search.get("query", {}).get("search", [])
    cuisine_title = sr[0]["title"] if sr else f"{place} cuisine"

    # 2. Get the article's section list
    try:
        sec_data = _wiki_api({
            "action": "parse",
            "page": cuisine_title,
            "prop": "sections",
        })
    except Exception:
        sec_data = {}

    sections = sec_data.get("parse", {}).get("sections", [])
    # Pick sections whose headings are food-related (first 20 sections)
    food_sections = [
        s["index"] for s in sections[:30]
        if any(kw in s.get("line", "").lower() for kw in dish_section_keywords)
    ]

    # 3. Collect wikilinks from each relevant section
    candidates: list[str] = []
    seen: set[str] = set()
    for idx in food_sections[:10]:
        try:
            link_data = _wiki_api({
                "action": "parse",
                "page": cuisine_title,
                "prop": "links",
                "section": idx,
            })
        except Exception:
            continue
        for lk in link_data.get("parse", {}).get("links", []):
            title = lk.get("*", "")
            if lk.get("ns") == 0 and title not in seen and title.lower() != cuisine_title.lower():
                seen.add(title)
                candidates.append(title)

    # Fallback: search if section parsing yielded nothing
    if not candidates:
        fb = _wiki_api({
            "action": "query",
            "list": "search",
            "srsearch": f"{place} typical dish food",
            "srlimit": 20,
        })
        candidates = [r["title"] for r in fb.get("query", {}).get("search", [])]

    if not candidates:
        return []

    # 4. Batch-fetch thumbnails + two-sentence extract for filtering
    page_data = _wiki_api({
        "action": "query",
        "titles": "|".join(candidates[:40]),
        "prop": "pageimages|extracts",
        "piprop": "thumbnail",
        "pithumbsize": 400,
        "exintro": True,
        "explaintext": True,
        "exsentences": 2,
    })

    # Words that appear in food/dish article openings but not in
    # geography, animal, or people articles.
    food_extract_signals = {
        " dish", " drink", " beverage", " soup", " sauce", " stew",
        " bread", " pastry", " dessert", " snack", " cake", " pudding",
        " sandwich", " salad", " rice", " noodle", " dumpling",
        " cheese", " sausage", " ham", " beef", " pork", " chicken",
        " seafood", " shrimp", " fish dish", " wine", " beer", " spirit",
        " porridge", " cereal", " pie", " tart", " biscuit", " cookie",
        " jam", " broth", " stock", " marinade", " filling",
        "is prepared", "is made from", "is cooked", "is served", "is eaten",
        "is a traditional", "is a popular food", "is a type of food",
        "is a fermented", "is a fried", "is a grilled", "is a baked",
        "is a boiled", "is a smoked", "is a cured", "is a roasted",
        "is a seasoning", "is a condiment", "is a spice",
    }

    foods = []
    for p in page_data.get("query", {}).get("pages", {}).values():
        if p.get("pageid", -1) == -1:
            continue
        raw = (p.get("extract", "") or "").strip()
        extract_lower = raw.lower()
        # Keep only articles whose opening text explicitly describes food
        if not any(sig in extract_lower for sig in food_extract_signals):
            continue
        name = p.get("title", "")
        image = p.get("thumbnail", {}).get("source", "")
        desc = raw.split(".")[0].strip() if raw else ""
        foods.append({"name": name, "image": image, "desc": desc})

    foods.sort(key=lambda f: 0 if f["image"] else 1)
    return foods[:10]


@app.route("/api/typical-food", methods=["GET"])
def typical_food():
    place = request.args.get("place", "").strip()
    if not place:
        return jsonify({"error": "place is required"}), 400
    try:
        foods = _fetch_typical_food(place)
        return jsonify({"place": place, "foods": foods})
    except Exception as e:
        return jsonify({"error": str(e), "foods": []}), 500


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
