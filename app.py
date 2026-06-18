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
  GET  /api/plans                  → saved plans
  POST /api/plans                  → save a new plan
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
