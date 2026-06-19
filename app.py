"""
makeTrip — Flask application
Serves the HTML frontend and exposes a REST API backed by SQLite.

Endpoints:
  GET  /                           → serve the HTML app
  GET  /api/stops                  → all stops
  GET  /api/stops/<id>             → single stop + reviews
  GET  /api/stops/<id>/reviews     → reviews for a stop
  POST /api/stops/<id>/reviews     → add a review
  GET  /api/routes                 → saved routes
  GET  /api/top10/<list_type>      → top10 list (worldwide|country|city|category)
  GET  /api/top10                  → top10 places (?type=worldwide or ?type=country&country=Chile)
  GET  /api/top10/countries        → country directory (flag + destination count)
  GET  /api/plans                  → saved plans
  POST /api/plans                  → save a new plan
  GET  /api/getsavedplan            → plans for a user (?user_id=1111), most recent first
  POST /api/saveplan                → save a plan from a live search (from/to + stops found)
  GET  /api/autocomplete           → place suggestions for the search bar
  GET  /api/placeinformation        → place details (rating, weather, AI tip) by name
"""

import os
from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory, abort, render_template

import database as db

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


# ── Stops ────────────────────────────────────────────────────────────────
@app.route("/api/stops", methods=["GET"])
def api_stops():
    """Return all stops, optionally filtered by category."""
    category = request.args.get("category")
    stops = db.get_all_stops()
    if category and category != "all":
        stops = [s for s in stops if s["category"] == category]
    return jsonify({"stops": stops, "count": len(stops)})


@app.route("/api/stops/<int:stop_id>", methods=["GET"])
def api_stop_detail(stop_id):
    """Return a single stop with its reviews."""
    stop = db.get_stop(stop_id)
    if not stop:
        abort(404)
    reviews = db.get_reviews(stop_id)
    return jsonify({"stop": stop, "reviews": reviews})


@app.route("/api/stops/<int:stop_id>/reviews", methods=["GET"])
def api_reviews(stop_id):
    """Return reviews for a stop."""
    reviews = db.get_reviews(stop_id)
    return jsonify({"stop_id": stop_id, "reviews": reviews, "count": len(reviews)})


@app.route("/api/stops/<int:stop_id>/reviews", methods=["POST"])
def api_add_review(stop_id):
    """Add a new review to a stop."""
    stop = db.get_stop(stop_id)
    if not stop:
        abort(404)
    data = request.get_json(silent=True) or {}
    required = ["reviewer", "rating", "comment"]
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400
    rating = int(data["rating"])
    if not (1 <= rating <= 5):
        return jsonify({"error": "Rating must be 1–5"}), 400
    db.add_review(
        stop_id=stop_id,
        reviewer=data["reviewer"],
        location=data.get("location", ""),
        rating=rating,
        comment=data["comment"],
        initials=data.get("initials", data["reviewer"][:2].upper()),
        avatar_color=data.get("avatar_color", "#c94b0c"),
        visited_at=data.get("visited_at"),
    )
    updated = db.get_stop(stop_id)
    return jsonify({
        "ok": True,
        "message": "Review added",
        "new_rating": updated["rating"],
        "review_count": updated["review_count"],
    }), 201


# ── Routes ────────────────────────────────────────────────────────────────
@app.route("/api/routes", methods=["GET"])
def api_routes():
    routes = db.get_routes()
    return jsonify({"routes": routes, "count": len(routes)})


# ── Top 10 ────────────────────────────────────────────────────────────────
VALID_TYPES = {"worldwide", "country", "city", "category"}

@app.route("/api/top10/<list_type>", methods=["GET"])
def api_top10(list_type):
    if list_type not in VALID_TYPES:
        return jsonify({"error": f"list_type must be one of: {', '.join(VALID_TYPES)}"}), 400
    items = db.get_top10(list_type)
    return jsonify({"list_type": list_type, "items": items, "count": len(items)})


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


# ── Saved plans ────────────────────────────────────────────────────────────
@app.route("/api/plans", methods=["GET"])
def api_plans():
    plans = db.get_saved_plans()
    return jsonify({"plans": plans, "count": len(plans)})


@app.route("/api/plans", methods=["POST"])
def api_save_plan():
    data = request.get_json(silent=True) or {}
    required = ["route_id", "title"]
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400
    db.save_plan(
        user_name=data.get("user_name", "Alex Traveller"),
        route_id=int(data["route_id"]),
        title=data["title"],
        notes=data.get("notes", ""),
    )
    return jsonify({"ok": True, "message": "Plan saved"}), 201


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
            "db": str(db.DB_PATH),
            "stops_in_db": len(stops),
        })
    except Exception as e:
        return jsonify({"status": "error", "detail": str(e)}), 500


if __name__ == "__main__":
    # Ensure DB is ready
    db.init_db()
    db.seed_db()
    print("\n🚀  makeTrip server starting at http://127.0.0.1:5004")
    print("   GET  /             → HTML app")
    print("   GET  /api/stops    → all stops (JSON)")
    print("   GET  /api/health   → health check\n")
    app.run(debug=True, host="0.0.0.0", port=5004)
