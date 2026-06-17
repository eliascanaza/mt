"""
makeTrip — SQLite database layer
Handles all DB setup, seed data, and CRUD for:
  - stops      : recommended places along a route
  - routes     : saved user routes (from -> to)
  - reviews    : user reviews per stop
  - top10      : curated top-10 lists
"""

import sqlite3
import json
from pathlib import Path

DB_PATH = Path(__file__).parent / "maketrip.db"


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row   # dict-like rows
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ── Schema ─────────────────────────────────────────────────────────────
def init_db():
    with get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS stops (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            emoji       TEXT    NOT NULL,
            name        TEXT    NOT NULL,
            category    TEXT    NOT NULL,   -- trek / lake / town / trail
            description TEXT    NOT NULL,
            rating      REAL    NOT NULL DEFAULT 0,
            review_count INTEGER NOT NULL DEFAULT 0,
            location    TEXT    NOT NULL,
            altitude    TEXT,
            temperature TEXT,
            drive_time  TEXT,
            drive_note  TEXT,
            distance_km TEXT,
            dist_from   TEXT,
            bg_gradient TEXT,
            lat         REAL    NOT NULL,
            lng         REAL    NOT NULL,
            tags        TEXT    DEFAULT '[]',   -- JSON array
            commutes    TEXT    DEFAULT '[]'    -- JSON array of objects
        );

        CREATE TABLE IF NOT EXISTS routes (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            from_name   TEXT    NOT NULL,
            from_lat    REAL    NOT NULL,
            from_lng    REAL    NOT NULL,
            to_name     TEXT    NOT NULL,
            to_lat      REAL    NOT NULL,
            to_lng      REAL    NOT NULL,
            distance_km INTEGER,
            drive_hours INTEGER,
            stop_count  INTEGER DEFAULT 0,
            days_min    INTEGER,
            days_max    INTEGER,
            created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS route_stops (
            route_id    INTEGER REFERENCES routes(id) ON DELETE CASCADE,
            stop_id     INTEGER REFERENCES stops(id)  ON DELETE CASCADE,
            position    INTEGER NOT NULL,
            PRIMARY KEY (route_id, stop_id)
        );

        CREATE TABLE IF NOT EXISTS reviews (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            stop_id      INTEGER REFERENCES stops(id) ON DELETE CASCADE,
            reviewer     TEXT    NOT NULL,
            location     TEXT,
            rating       INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
            comment      TEXT    NOT NULL,
            avatar_color TEXT    DEFAULT '#c94b0c',
            initials     TEXT    DEFAULT 'TR',
            visited_at   TEXT,
            created_at   DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS top10 (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            list_type   TEXT    NOT NULL,   -- worldwide / country / city / category
            rank        INTEGER NOT NULL,
            name        TEXT    NOT NULL,
            description TEXT    NOT NULL,
            rating      REAL    NOT NULL,
            tag         TEXT    NOT NULL,
            UNIQUE(list_type, rank)
        );

        CREATE TABLE IF NOT EXISTS saved_plans (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_name   TEXT    DEFAULT 'Alex Traveller',
            route_id    INTEGER REFERENCES routes(id),
            title       TEXT,
            notes       TEXT,
            created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        """)
    print("✅  Schema ready")


# ── Seed data ───────────────────────────────────────────────────────────
STOPS_SEED = [
    {
        "emoji": "🌋", "name": "Chillán — Hot Springs", "category": "trek",
        "description": "Volcanic hot springs and ski resort at 1,800 m. The perfect first overnight stop — soak in thermal pools after the drive south.",
        "rating": 4.6, "review_count": 1240,
        "location": "Biobío Region · 400 km from Santiago",
        "altitude": "1,800 m", "temperature": "5°–16°C",
        "drive_time": "2 h 30 min", "drive_note": "Drive via Ruta 5",
        "distance_km": "400 km", "dist_from": "Santiago",
        "bg_gradient": "linear-gradient(135deg,#c94b0c,#7b2d0a)",
        "lat": -36.9167, "lng": -71.4067,
        "tags": json.dumps(["Hot Springs", "Volcano", "Ski Resort"]),
        "commutes": json.dumps([
            {"icon": "car", "label": "Drive via Ruta 5", "note": "Highway south", "time": "2 h 30 min"},
            {"icon": "bus", "label": "Express bus", "note": "Via Terminal Alameda", "time": "3 h"},
        ]),
    },
    {
        "emoji": "⛵", "name": "Puerto Montt — Lake District", "category": "lake",
        "description": "Gateway to Chile's magnificent lake district. Ferries to Chiloé Island, exceptional seafood, and dramatic fjord views.",
        "rating": 4.7, "review_count": 3812,
        "location": "Los Lagos Region · 1,050 km from Santiago",
        "altitude": "55 m", "temperature": "8°–18°C",
        "drive_time": "4 h", "drive_note": "Drive via Ruta 5",
        "distance_km": "650 km", "dist_from": "Chillán",
        "bg_gradient": "linear-gradient(135deg,#0a4a7b,#0d2b52)",
        "lat": -41.4693, "lng": -72.9395,
        "tags": json.dumps(["Ferries", "Seafood", "Fjords"]),
        "commutes": json.dumps([
            {"icon": "car", "label": "Drive south, Ruta 5", "note": "Pan-American highway", "time": "4 h"},
            {"icon": "plane", "label": "Fly SCL → PMC", "note": "LATAM daily flights", "time": "1 h 20 min"},
        ]),
    },
    {
        "emoji": "🏄", "name": "Futaleufú — Whitewater", "category": "trail",
        "description": "World-class river rafting on turquoise glacial water. A remote and extraordinary adventure via the Carretera Austral.",
        "rating": 4.9, "review_count": 892,
        "location": "Los Lagos Region · 1,380 km from Santiago",
        "altitude": "320 m", "temperature": "6°–22°C",
        "drive_time": "3 h 30 min", "drive_note": "Via Carretera Austral",
        "distance_km": "330 km", "dist_from": "Puerto Montt",
        "bg_gradient": "linear-gradient(135deg,#0a5c4a,#052e25)",
        "lat": -43.1863, "lng": -71.8698,
        "tags": json.dumps(["Rafting", "River", "Adventure"]),
        "commutes": json.dumps([
            {"icon": "car", "label": "Drive via Carretera Austral", "note": "Scenic dirt road sections", "time": "3 h 30 min"},
        ]),
    },
]

REVIEWS_SEED = [
    # stop_id=1 (Chillán)
    {"stop_id": 1, "reviewer": "Sofia Andersson", "location": "Stockholm, Sweden",
     "rating": 5, "comment": "One of the most breathtaking places I've ever set foot in. The hot springs at night under the stars — pure magic.",
     "avatar_color": "#e63946", "initials": "SA", "visited_at": "March 2024"},
    {"stop_id": 1, "reviewer": "Mateo García", "location": "Buenos Aires, Argentina",
     "rating": 4, "comment": "Beautiful setting, though the winds were brutal. The pools are genuinely therapeutic after a long drive south.",
     "avatar_color": "#2a9d8f", "initials": "MG", "visited_at": "January 2024"},
    # stop_id=2 (Puerto Montt)
    {"stop_id": 2, "reviewer": "Yuki Tanaka", "location": "Tokyo, Japan",
     "rating": 5, "comment": "The ferry to Chiloé is unmissable. Strange, beautiful island with wooden churches and misty fjords.",
     "avatar_color": "#457b9d", "initials": "YT", "visited_at": "February 2024"},
    {"stop_id": 2, "reviewer": "Amara Diallo", "location": "Dakar, Senegal",
     "rating": 4, "comment": "Excellent seafood at the Angelmó market. The smoked salmon and giant clams were unlike anything I'd tasted.",
     "avatar_color": "#c17f24", "initials": "AD", "visited_at": "December 2023"},
    # stop_id=3 (Futaleufú)
    {"stop_id": 3, "reviewer": "Lukas Bauer", "location": "Munich, Germany",
     "rating": 5, "comment": "The Futaleufú river is unlike anything else on earth. Turquoise, powerful, and utterly wild.",
     "avatar_color": "#6d4c41", "initials": "LB", "visited_at": "November 2023"},
    {"stop_id": 3, "reviewer": "Priya Menon", "location": "Bangalore, India",
     "rating": 5, "comment": "I've rafted in Nepal and Costa Rica. Futaleufú is on another level. Book a local guide — they know every rapid.",
     "avatar_color": "#7b1fa2", "initials": "PM", "visited_at": "October 2023"},
]

TOP10_SEED = [
    # worldwide
    *[{"list_type": "worldwide", "rank": i+1, "name": n, "description": d, "rating": r, "tag": t}
      for i, (n, d, r, t) in enumerate([
        ("Patagonia, Chile", "End-of-the-world wilderness: glaciers, granite towers, and unmatched silence.", 4.97, "Nature"),
        ("Kyoto, Japan", "Ancient temples, bamboo forests, and the world's most refined tea culture.", 4.94, "Culture"),
        ("Santorini, Greece", "Volcanic island with iconic white-domed architecture above a deep-blue caldera.", 4.91, "Scenic"),
        ("Machu Picchu, Peru", "15th-century Inca citadel perched in the Andes at 2,430 m above sea level.", 4.90, "History"),
        ("Galápagos Islands", "Darwin's living laboratory: wildlife found nowhere else on earth.", 4.89, "Wildlife"),
        ("Amalfi Coast, Italy", "Vertical cliffs, turquoise sea, and villages draped in lemon groves.", 4.88, "Scenic"),
        ("Bali, Indonesia", "Rice terraces, sacred temples, surf breaks, and some of Asia's best sunsets.", 4.86, "Culture"),
        ("Queenstown, New Zealand", "Adventure capital of the world set against fjords and the Remarkables.", 4.85, "Adventure"),
        ("Marrakech, Morocco", "Labyrinthine medinas, vibrant souks, and rooftop views over the Koutoubia.", 4.83, "Culture"),
        ("Norwegian Fjords", "Sheer cliffs, cascading waterfalls, and mirror-calm water into the distance.", 4.82, "Nature"),
    ])],
    # city
    *[{"list_type": "city", "rank": i+1, "name": n, "description": d, "rating": r, "tag": t}
      for i, (n, d, r, t) in enumerate([
        ("Tokyo, Japan", "Hyper-efficient, hyper-delicious, utterly unlike anywhere else on earth.", 4.95, "Asia"),
        ("New York, USA", "Culture, food, and skyline in every direction. The city that never sleeps.", 4.90, "Americas"),
        ("Barcelona, Spain", "Gaudí's impossible architecture, tapas culture, and beaches within the city.", 4.88, "Europe"),
        ("Cape Town, S. Africa", "Table Mountain, the Cape Peninsula, and some of the world's finest wine.", 4.87, "Africa"),
        ("Buenos Aires, Argentina", "The Paris of South America: tango, steak, bookshops, and endless boulevards.", 4.85, "Americas"),
        ("Amsterdam, Netherlands", "Canal rings, world-class museums, and a cycling culture that defines the city.", 4.84, "Europe"),
        ("Medellín, Colombia", "From turbulent past to model of innovation, culture, and eternal spring.", 4.83, "Americas"),
        ("Lisbon, Portugal", "Pastel hills, fado music, and custard tarts above the Tagus river.", 4.82, "Europe"),
        ("Singapore", "A flawlessly run city-state where hawker centres rival Michelin restaurants.", 4.81, "Asia"),
        ("Marrakech, Morocco", "Pink walls, mint tea, and souks that stretch into one another without end.", 4.80, "Africa"),
    ])],
]


def seed_db():
    with get_conn() as conn:
        # Clear existing data in dependency order
        conn.executescript("""
            DELETE FROM saved_plans;
            DELETE FROM route_stops;
            DELETE FROM reviews;
            DELETE FROM top10;
            DELETE FROM routes;
            DELETE FROM stops;
        """)

        # Insert stops and collect their real IDs
        stop_ids = []
        for s in STOPS_SEED:
            conn.execute("""
                INSERT INTO stops (emoji,name,category,description,rating,review_count,
                    location,altitude,temperature,drive_time,drive_note,distance_km,
                    dist_from,bg_gradient,lat,lng,tags,commutes)
                VALUES (:emoji,:name,:category,:description,:rating,:review_count,
                    :location,:altitude,:temperature,:drive_time,:drive_note,:distance_km,
                    :dist_from,:bg_gradient,:lat,:lng,:tags,:commutes)
            """, s)
            stop_ids.append(conn.execute("SELECT last_insert_rowid()").fetchone()[0])

        # Insert a default route
        conn.execute("""
            INSERT INTO routes (from_name,from_lat,from_lng,to_name,to_lat,to_lng,
                distance_km,drive_hours,stop_count,days_min,days_max)
            VALUES ('Santiago, Chile',-33.4489,-70.6693,'Puerto Natales, Chile',-51.7319,-72.5083,
                2460,26,3,8,10)
        """)
        route_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        # Link stops to route using their real IDs
        for pos, sid in enumerate(stop_ids, 1):
            conn.execute("INSERT INTO route_stops VALUES (?,?,?)", (route_id, sid, pos))

        # Insert reviews using real stop IDs
        for r in REVIEWS_SEED:
            # Map seed stop_id (1-based index) to actual DB id
            actual_stop_id = stop_ids[r["stop_id"] - 1]
            conn.execute("""
                INSERT INTO reviews (stop_id,reviewer,location,rating,comment,avatar_color,initials,visited_at)
                VALUES (?,?,?,?,?,?,?,?)
            """, (actual_stop_id, r["reviewer"], r["location"], r["rating"],
                  r["comment"], r["avatar_color"], r["initials"], r["visited_at"]))

        # Insert top10
        for item in TOP10_SEED:
            conn.execute("""
                INSERT OR REPLACE INTO top10 (list_type,rank,name,description,rating,tag)
                VALUES (:list_type,:rank,:name,:description,:rating,:tag)
            """, item)

        # Default saved plan
        conn.execute("""
            INSERT INTO saved_plans (user_name, route_id, title, notes)
            VALUES ('Alex Traveller', ?, 'Patagonia Road Trip 2024',
                    'Dream route from Santiago all the way to Puerto Natales')
        """, (route_id,))

    print("✅  Seed data inserted")


# ── Query helpers ───────────────────────────────────────────────────────
def get_all_stops():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM stops ORDER BY id").fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["tags"] = json.loads(d["tags"])
            d["commutes"] = json.loads(d["commutes"])
            result.append(d)
        return result


def get_stop(stop_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM stops WHERE id=?", (stop_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["tags"] = json.loads(d["tags"])
        d["commutes"] = json.loads(d["commutes"])
        return d


def get_reviews(stop_id: int):
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT * FROM reviews WHERE stop_id=? ORDER BY created_at DESC
        """, (stop_id,)).fetchall()
        return [dict(r) for r in rows]


def get_top10(list_type: str):
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT * FROM top10 WHERE list_type=? ORDER BY rank
        """, (list_type,)).fetchall()
        return [dict(r) for r in rows]


def get_routes():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM routes ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]


def get_saved_plans():
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT sp.*, r.from_name, r.to_name, r.distance_km, r.drive_hours
            FROM saved_plans sp JOIN routes r ON sp.route_id = r.id
            ORDER BY sp.created_at DESC
        """).fetchall()
        return [dict(r) for r in rows]


def add_review(stop_id: int, reviewer: str, location: str,
               rating: int, comment: str, initials: str = "TR",
               avatar_color: str = "#c94b0c", visited_at: str = None):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO reviews (stop_id,reviewer,location,rating,comment,initials,avatar_color,visited_at)
            VALUES (?,?,?,?,?,?,?,?)
        """, (stop_id, reviewer, location, rating, comment, initials, avatar_color, visited_at))
        # Recalculate rating average
        avg = conn.execute(
            "SELECT AVG(rating) FROM reviews WHERE stop_id=?", (stop_id,)
        ).fetchone()[0]
        cnt = conn.execute(
            "SELECT COUNT(*) FROM reviews WHERE stop_id=?", (stop_id,)
        ).fetchone()[0]
        conn.execute("UPDATE stops SET rating=?, review_count=? WHERE id=?",
                     (round(avg, 2), cnt, stop_id))
    return True


def save_plan(user_name: str, route_id: int, title: str, notes: str = ""):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO saved_plans (user_name, route_id, title, notes)
            VALUES (?,?,?,?)
        """, (user_name, route_id, title, notes))
    return True


if __name__ == "__main__":
    init_db()
    seed_db()
    print("\n📊  Stops in DB:")
    for s in get_all_stops():
        print(f"  [{s['id']}] {s['emoji']} {s['name']}  ⭐ {s['rating']}  ({s['review_count']} reviews)")
    print("\n💬  Reviews sample:")
    for r in get_reviews(1):
        print(f"  {r['initials']} — {r['rating']}★  \"{r['comment'][:60]}...\"")
