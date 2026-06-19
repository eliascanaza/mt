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

        CREATE TABLE IF NOT EXISTS places (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            emoji       TEXT    NOT NULL,
            name        TEXT    NOT NULL,
            subtitle    TEXT    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS mt_places (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            city               TEXT    NOT NULL,
            country            TEXT    NOT NULL,
            region             TEXT,
            rating             REAL    NOT NULL DEFAULT 0,
            total_reviews      INTEGER NOT NULL DEFAULT 0,
            short_description  TEXT,
            latitude           REAL    NOT NULL,
            longitude          REAL    NOT NULL,
            temperature        TEXT,
            best_season        TEXT,
            altitude           TEXT,
            ai_recommendation  TEXT
        );

        CREATE TABLE IF NOT EXISTS top10_places (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            list_type          TEXT    NOT NULL,   -- worldwide / country
            country            TEXT,               -- NULL for worldwide entries
            city               TEXT    NOT NULL,
            category           TEXT    NOT NULL,
            rating             REAL    NOT NULL,
            place_information  TEXT    NOT NULL,
            latitude           REAL,
            longitude          REAL,
            rank               INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS saved_plans (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user_name       TEXT    DEFAULT 'Alex Traveller',
            user_id         INTEGER DEFAULT 1111,
            user_email      TEXT    DEFAULT 'test@gmail.com',
            route_id        INTEGER REFERENCES routes(id),
            title           TEXT,
            notes           TEXT,
            from_name       TEXT,
            from_lat        REAL,
            from_lng        REAL,
            to_name         TEXT,
            to_lat          REAL,
            to_lng          REAL,
            distance_km     INTEGER,
            duration_text   TEXT,
            transport_mode  TEXT,
            stops_snapshot  TEXT    DEFAULT '[]',
            created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        """)
        _migrate_saved_plans_columns(conn)
    print("✅  Schema ready")


# saved_plans predates the /api/saveplan feature; this backfills the new
# columns onto an already-existing maketrip.db without touching its data.
def _migrate_saved_plans_columns(conn):
    existing = {row[1] for row in conn.execute("PRAGMA table_info(saved_plans)")}
    for name, decl in [
        ("user_id", "INTEGER DEFAULT 1111"),
        ("user_email", "TEXT DEFAULT 'test@gmail.com'"),
        ("from_name", "TEXT"),
        ("from_lat", "REAL"),
        ("from_lng", "REAL"),
        ("to_name", "TEXT"),
        ("to_lat", "REAL"),
        ("to_lng", "REAL"),
        ("distance_km", "INTEGER"),
        ("duration_text", "TEXT"),
        ("transport_mode", "TEXT"),
        ("stops_snapshot", "TEXT DEFAULT '[]'"),
    ]:
        if name not in existing:
            conn.execute(f"ALTER TABLE saved_plans ADD COLUMN {name} {decl}")


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

PLACES_SEED = [
    {"emoji": "🏙️", "name": "Santiago, Chile", "subtitle": "Capital · South America"},
    {"emoji": "🎭", "name": "Buenos Aires, Argentina", "subtitle": "Capital · South America"},
    {"emoji": "🏛️", "name": "Lima, Peru", "subtitle": "Capital · South America"},
    {"emoji": "☁️", "name": "Bogotá, Colombia", "subtitle": "Capital · South America"},
    {"emoji": "🌊", "name": "Rio de Janeiro, Brazil", "subtitle": "Coastal city · South America"},
    {"emoji": "🏔️", "name": "Cusco, Peru", "subtitle": "Inca capital · South America"},
    {"emoji": "🧊", "name": "Patagonia, Chile", "subtitle": "Region · Southern Chile"},
    {"emoji": "🏔️", "name": "Puerto Natales, Chile", "subtitle": "Patagonia gateway · Chile"},
    {"emoji": "⛰️", "name": "Torres del Paine, Chile", "subtitle": "National park · Patagonia"},
    {"emoji": "⛵", "name": "Puerto Montt, Chile", "subtitle": "Lake district · Chile"},
    {"emoji": "🏄", "name": "Futaleufú, Chile", "subtitle": "Whitewater · Patagonia"},
    {"emoji": "🌨️", "name": "Ushuaia, Argentina", "subtitle": "End of the world · Argentina"},
    {"emoji": "🍷", "name": "Mendoza, Argentina", "subtitle": "Wine country · Argentina"},
    {"emoji": "🏰", "name": "Cartagena, Colombia", "subtitle": "Walled city · Caribbean"},
    {"emoji": "🌸", "name": "Medellín, Colombia", "subtitle": "City of eternal spring"},
    {"emoji": "🗿", "name": "Machu Picchu, Peru", "subtitle": "Inca ruins · UNESCO site"},
    {"emoji": "🐢", "name": "Galapagos Islands", "subtitle": "Ecuador · Pacific Ocean"},
    {"emoji": "🌵", "name": "Atacama Desert, Chile", "subtitle": "World's driest desert"},
    {"emoji": "🏔️", "name": "Bariloche, Argentina", "subtitle": "Lakes district · Patagonia"},
    {"emoji": "🎶", "name": "Montevideo, Uruguay", "subtitle": "Capital · South America"},
    {"emoji": "🌮", "name": "Mexico City, Mexico", "subtitle": "Capital · North America"},
    {"emoji": "🏖️", "name": "Cancún, Mexico", "subtitle": "Caribbean resort · Quintana Roo"},
    {"emoji": "🌴", "name": "Tulum, Mexico", "subtitle": "Boho beach town · Riviera Maya"},
    {"emoji": "⛱️", "name": "Playa del Carmen, Mexico", "subtitle": "Riviera Maya hub · Quintana Roo"},
    {"emoji": "🤿", "name": "Cozumel, Mexico", "subtitle": "Diving island · Caribbean"},
    {"emoji": "🏛️", "name": "Chichén Itzá, Mexico", "subtitle": "Maya pyramid · UNESCO site"},
    {"emoji": "🌼", "name": "Mérida, Mexico", "subtitle": "Colonial capital · Yucatán"},
    {"emoji": "🌶️", "name": "Oaxaca, Mexico", "subtitle": "Culture & mezcal · Oaxaca"},
    {"emoji": "🎸", "name": "Guadalajara, Mexico", "subtitle": "Home of mariachi & tequila"},
    {"emoji": "🌅", "name": "Puerto Vallarta, Mexico", "subtitle": "Pacific coast resort · Jalisco"},
    {"emoji": "🎨", "name": "San Miguel de Allende, Mexico", "subtitle": "Colonial art town · Guanajuato"},
    {"emoji": "🏘️", "name": "Guanajuato, Mexico", "subtitle": "Colorful colonial city · Mexico"},
    {"emoji": "🐟", "name": "Los Cabos, Mexico", "subtitle": "Desert meets sea · Baja California Sur"},
    {"emoji": "🏝️", "name": "Isla Holbox, Mexico", "subtitle": "Car-free island · Quintana Roo"},
    {"emoji": "💎", "name": "Bacalar, Mexico", "subtitle": "Lagoon of Seven Colors · Quintana Roo"},
]

MT_PLACES_SEED = [
    {"city": "Santiago", "country": "Chile", "region": "Santiago Metropolitan",
     "rating": 4.5, "total_reviews": 18234,
     "short_description": "Vibrant capital framed by the Andes, mixing colonial architecture with a modern skyline.",
     "latitude": -33.4489, "longitude": -70.6693, "temperature": "10°–28°C", "best_season": "Oct – Apr",
     "altitude": "520 m", "ai_recommendation": "Visit in spring for clear Andes views and outdoor wine tours."},
    {"city": "Buenos Aires", "country": "Argentina", "region": "Buenos Aires Province",
     "rating": 4.6, "total_reviews": 24310,
     "short_description": "The Paris of South America, famed for tango, steak houses and grand boulevards.",
     "latitude": -34.6037, "longitude": -58.3816, "temperature": "9°–29°C", "best_season": "Sep – Nov, Mar – May",
     "altitude": "25 m", "ai_recommendation": "Book a tango show in San Telmo and pair it with a parrilla dinner."},
    {"city": "Lima", "country": "Peru", "region": "Lima Province",
     "rating": 4.4, "total_reviews": 15420,
     "short_description": "Coastal capital celebrated for world-class cuisine and pre-Columbian history.",
     "latitude": -12.0464, "longitude": -77.0428, "temperature": "16°–26°C", "best_season": "Dec – Apr",
     "altitude": "161 m", "ai_recommendation": "Reserve a table at a top ceviche restaurant in Miraflores."},
    {"city": "Bogotá", "country": "Colombia", "region": "Bogotá D.C.",
     "rating": 4.3, "total_reviews": 12870,
     "short_description": "High-altitude capital with a thriving arts scene and colonial La Candelaria district.",
     "latitude": 4.7110, "longitude": -74.0721, "temperature": "8°–19°C", "best_season": "Dec – Mar",
     "altitude": "2,640 m", "ai_recommendation": "Acclimatize a day before exploring — the altitude catches first-timers off guard."},
    {"city": "Rio de Janeiro", "country": "Brazil", "region": "Rio de Janeiro State",
     "rating": 4.7, "total_reviews": 31200,
     "short_description": "Iconic beaches, Christ the Redeemer, and a carnival spirit year-round.",
     "latitude": -22.9068, "longitude": -43.1729, "temperature": "20°–31°C", "best_season": "Sep – Mar",
     "altitude": "2 m", "ai_recommendation": "Ride the Sugarloaf cable car at sunset for the best skyline photos."},
    {"city": "Cusco", "country": "Peru", "region": "Cusco Region",
     "rating": 4.8, "total_reviews": 19850,
     "short_description": "Former Inca capital and gateway to Machu Picchu, rich with Andean culture.",
     "latitude": -13.5320, "longitude": -71.9675, "temperature": "4°–20°C", "best_season": "May – Sep",
     "altitude": "3,400 m", "ai_recommendation": "Spend 2 days acclimatizing before any trek toward Machu Picchu."},
    {"city": "Patagonia", "country": "Chile", "region": "Magallanes",
     "rating": 4.97, "total_reviews": 8420,
     "short_description": "End-of-the-world wilderness of glaciers, granite towers and unmatched silence.",
     "latitude": -51.0, "longitude": -73.0, "temperature": "2°–15°C", "best_season": "Nov – Mar",
     "altitude": "100 m", "ai_recommendation": "Pack layers — Patagonian weather can shift from sun to sleet in an hour."},
    {"city": "Puerto Natales", "country": "Chile", "region": "Magallanes",
     "rating": 4.7, "total_reviews": 4210,
     "short_description": "Gateway to Torres del Paine, with a charming waterfront and outfitter scene.",
     "latitude": -51.7319, "longitude": -72.5083, "temperature": "1°–14°C", "best_season": "Oct – Apr",
     "altitude": "30 m", "ai_recommendation": "Stock up on trekking gear here before heading into the park."},
    {"city": "Torres del Paine", "country": "Chile", "region": "Magallanes",
     "rating": 4.95, "total_reviews": 6890,
     "short_description": "National park famed for granite towers, turquoise lakes and Patagonian steppe.",
     "latitude": -50.9423, "longitude": -72.9587, "temperature": "0°–12°C", "best_season": "Oct – Mar",
     "altitude": "300–2,800 m", "ai_recommendation": "Book the W Trek refugios months ahead — they sell out fast in summer."},
    {"city": "Puerto Montt", "country": "Chile", "region": "Los Lagos",
     "rating": 4.6, "total_reviews": 5230,
     "short_description": "Gateway to Chile's lake district with ferries to Chiloé and dramatic fjords.",
     "latitude": -41.4693, "longitude": -72.9395, "temperature": "5°–18°C", "best_season": "Dec – Feb",
     "altitude": "55 m", "ai_recommendation": "Take the ferry to Chiloé for stilt houses and wooden churches."},
    {"city": "Futaleufú", "country": "Chile", "region": "Los Lagos",
     "rating": 4.9, "total_reviews": 1340,
     "short_description": "World-class whitewater rafting on glacial turquoise rivers in Patagonia.",
     "latitude": -43.1863, "longitude": -71.8698, "temperature": "6°–22°C", "best_season": "Dec – Feb",
     "altitude": "320 m", "ai_recommendation": "Hire a certified local guide — the rapids here are serious."},
    {"city": "Ushuaia", "country": "Argentina", "region": "Tierra del Fuego",
     "rating": 4.6, "total_reviews": 7600,
     "short_description": "Southernmost city in the world, gateway to Antarctic expeditions.",
     "latitude": -54.8019, "longitude": -68.3030, "temperature": "-1°–9°C", "best_season": "Nov – Mar",
     "altitude": "27 m", "ai_recommendation": "Book Antarctica cruises 6+ months ahead for the best fares."},
    {"city": "Mendoza", "country": "Argentina", "region": "Mendoza Province",
     "rating": 4.7, "total_reviews": 11200,
     "short_description": "Argentina's wine capital at the foot of the Andes, famed for Malbec.",
     "latitude": -32.8895, "longitude": -68.8458, "temperature": "5°–28°C", "best_season": "Mar – May",
     "altitude": "746 m", "ai_recommendation": "Harvest season in April brings grape-stomping festivals across the valley."},
    {"city": "Cartagena", "country": "Colombia", "region": "Bolívar",
     "rating": 4.8, "total_reviews": 16400,
     "short_description": "Walled Caribbean city with colorful colonial streets and seaside ramparts.",
     "latitude": 10.3910, "longitude": -75.4794, "temperature": "24°–32°C", "best_season": "Dec – Apr",
     "altitude": "2 m", "ai_recommendation": "Walk the old city walls at sunset to avoid the midday humidity."},
    {"city": "Medellín", "country": "Colombia", "region": "Antioquia",
     "rating": 4.6, "total_reviews": 13900,
     "short_description": "City of eternal spring, reborn through innovation, art and cable cars.",
     "latitude": 6.2442, "longitude": -75.5812, "temperature": "15°–28°C", "best_season": "Dec – Mar",
     "altitude": "1,495 m", "ai_recommendation": "Ride the Metrocable to Comuna 13 for street art and panoramic views."},
    {"city": "Machu Picchu", "country": "Peru", "region": "Cusco Region",
     "rating": 4.90, "total_reviews": 28700,
     "short_description": "15th-century Inca citadel perched in the Andes at 2,430 m above sea level.",
     "latitude": -13.1631, "longitude": -72.5450, "temperature": "6°–21°C", "best_season": "May – Sep",
     "altitude": "2,430 m", "ai_recommendation": "Buy entry tickets weeks ahead — daily visitor numbers are capped."},
    {"city": "Galapagos Islands", "country": "Ecuador", "region": "Galápagos Province",
     "rating": 4.89, "total_reviews": 9650,
     "short_description": "Darwin's living laboratory: wildlife found nowhere else on Earth.",
     "latitude": -0.9538, "longitude": -90.9656, "temperature": "21°–28°C", "best_season": "Jun – Dec",
     "altitude": "0–1,700 m", "ai_recommendation": "Choose a small-boat cruise for closer wildlife encounters than day trips."},
    {"city": "Atacama Desert", "country": "Chile", "region": "Antofagasta",
     "rating": 4.85, "total_reviews": 7320,
     "short_description": "The world's driest desert, with otherworldly salt flats and stargazing skies.",
     "latitude": -23.8859, "longitude": -68.1947, "temperature": "0°–25°C", "best_season": "Year-round (cold nights)",
     "altitude": "2,400 m", "ai_recommendation": "Bring warm layers — desert nights drop well below freezing."},
    {"city": "Bariloche", "country": "Argentina", "region": "Río Negro",
     "rating": 4.7, "total_reviews": 10800,
     "short_description": "Alpine-style lake town in Argentina's Patagonia, famed for chocolate and skiing.",
     "latitude": -41.1335, "longitude": -71.3103, "temperature": "1°–20°C", "best_season": "Jun – Aug (ski), Dec – Feb (summer)",
     "altitude": "770 m", "ai_recommendation": "Try the chocolate tour on Mitre Avenue before a Nahuel Huapi lake cruise."},
    {"city": "Montevideo", "country": "Uruguay", "region": "Montevideo Department",
     "rating": 4.5, "total_reviews": 8900,
     "short_description": "Laid-back capital with golden beaches, tango roots and a famous rambla.",
     "latitude": -34.9011, "longitude": -56.1645, "temperature": "10°–28°C", "best_season": "Dec – Feb",
     "altitude": "43 m", "ai_recommendation": "Walk the Rambla at sunset and stop for a choripán from a beach stand."},
    {"city": "Mexico City", "country": "Mexico", "region": "Mexico City (CDMX)",
     "rating": 4.6, "total_reviews": 27450,
     "short_description": "High-altitude capital blending Aztec ruins, world-class museums and an unmatched street-food scene.",
     "latitude": 19.4326, "longitude": -99.1332, "temperature": "8°–24°C", "best_season": "Mar – May",
     "altitude": "2,240 m", "ai_recommendation": "Spend a day in Teotihuacán and climb the Pyramid of the Sun before midday heat sets in."},
    {"city": "Cancún", "country": "Mexico", "region": "Quintana Roo",
     "rating": 4.6, "total_reviews": 33800,
     "short_description": "Caribbean resort strip with turquoise water, all-inclusive hotels and easy access to Maya ruins.",
     "latitude": 21.1619, "longitude": -86.8515, "temperature": "22°–30°C", "best_season": "Dec – Apr",
     "altitude": "10 m", "ai_recommendation": "Visit Chichén Itzá as an early-morning day trip to beat both the heat and the tour buses."},
    {"city": "Tulum", "country": "Mexico", "region": "Quintana Roo",
     "rating": 4.7, "total_reviews": 21600,
     "short_description": "Boho-chic beach town where Maya ruins sit on a cliff above white sand and turquoise sea.",
     "latitude": 20.2114, "longitude": -87.4654, "temperature": "23°–31°C", "best_season": "Nov – Apr",
     "altitude": "15 m", "ai_recommendation": "Rent a bike to reach the cenotes inland — Gran Cenote and Dos Ojos are both an easy ride away."},
    {"city": "Playa del Carmen", "country": "Mexico", "region": "Quintana Roo",
     "rating": 4.5, "total_reviews": 19200,
     "short_description": "Riviera Maya hub built around pedestrian Fifth Avenue, with ferries out to Cozumel's reefs.",
     "latitude": 20.6296, "longitude": -87.0739, "temperature": "23°–30°C", "best_season": "Nov – Apr",
     "altitude": "10 m", "ai_recommendation": "Catch the passenger ferry to Cozumel for a day of snorkeling the Palancar reef."},
    {"city": "Cozumel", "country": "Mexico", "region": "Quintana Roo",
     "rating": 4.7, "total_reviews": 14300,
     "short_description": "Island famed for some of the best scuba diving and snorkeling on the Mesoamerican Reef.",
     "latitude": 20.4230, "longitude": -86.9223, "temperature": "24°–30°C", "best_season": "Nov – Apr",
     "altitude": "3 m", "ai_recommendation": "Book a two-tank dive on the Palancar wall — visibility is best in the morning before the wind picks up."},
    {"city": "Chichén Itzá", "country": "Mexico", "region": "Yucatán",
     "rating": 4.8, "total_reviews": 22900,
     "short_description": "Monumental Maya city crowned by the Kukulcán pyramid, one of the New Seven Wonders of the World.",
     "latitude": 20.6843, "longitude": -88.5678, "temperature": "20°–34°C", "best_season": "Nov – Feb",
     "altitude": "30 m", "ai_recommendation": "Arrive right at opening time — the site has almost no shade and gets crowded and hot by midday."},
    {"city": "Mérida", "country": "Mexico", "region": "Yucatán",
     "rating": 4.6, "total_reviews": 12700,
     "short_description": "Yucatán's colonial capital, prized for grand mansions, lively plazas and some of Mexico's safest streets.",
     "latitude": 20.9674, "longitude": -89.5926, "temperature": "22°–34°C", "best_season": "Nov – Feb",
     "altitude": "10 m", "ai_recommendation": "Catch the free Saturday night Noche Mexicana street party along Paseo de Montejo."},
    {"city": "Oaxaca", "country": "Mexico", "region": "Oaxaca",
     "rating": 4.8, "total_reviews": 15800,
     "short_description": "Culinary and craft capital of Mexico, famed for mezcal, mole and the Monte Albán ruins above the valley.",
     "latitude": 17.0732, "longitude": -96.7266, "temperature": "11°–28°C", "best_season": "Oct – Apr",
     "altitude": "1,555 m", "ai_recommendation": "Book a mezcal tasting tour in nearby Santiago Matatlán, the world's mezcal capital."},
    {"city": "Guadalajara", "country": "Mexico", "region": "Jalisco",
     "rating": 4.5, "total_reviews": 11400,
     "short_description": "The birthplace of mariachi and tequila, anchored by a beautifully restored colonial center.",
     "latitude": 20.6597, "longitude": -103.3496, "temperature": "13°–28°C", "best_season": "Oct – Dec",
     "altitude": "1,566 m", "ai_recommendation": "Day-trip to the town of Tequila to tour an agave distillery at the source."},
    {"city": "Puerto Vallarta", "country": "Mexico", "region": "Jalisco",
     "rating": 4.6, "total_reviews": 17600,
     "short_description": "Pacific beach resort wrapped by the Sierra Madre, known for its Malecón boardwalk and old-town charm.",
     "latitude": 20.6534, "longitude": -105.2253, "temperature": "18°–29°C", "best_season": "Nov – Apr",
     "altitude": "2 m", "ai_recommendation": "Take a water taxi south to Yelapa — there's no road in, only boats."},
    {"city": "San Miguel de Allende", "country": "Mexico", "region": "Guanajuato",
     "rating": 4.8, "total_reviews": 13100,
     "short_description": "Colonial-era hill town built around a pink Gothic parish church, now a thriving art colony.",
     "latitude": 20.9153, "longitude": -100.7444, "temperature": "8°–28°C", "best_season": "Nov – Apr",
     "altitude": "1,920 m", "ai_recommendation": "Bring a warm layer for evenings — the high desert altitude cools fast after sunset."},
    {"city": "Guanajuato", "country": "Mexico", "region": "Guanajuato",
     "rating": 4.7, "total_reviews": 9800,
     "short_description": "A UNESCO-listed silver-mining city of color-soaked alleys, tunnels and underground streets.",
     "latitude": 21.0190, "longitude": -101.2574, "temperature": "8°–28°C", "best_season": "Oct – Dec",
     "altitude": "2,020 m", "ai_recommendation": "Plan around the Cervantino festival in October if you want the city at its liveliest."},
    {"city": "Los Cabos", "country": "Mexico", "region": "Baja California Sur",
     "rating": 4.6, "total_reviews": 16200,
     "short_description": "Where the Sonoran Desert meets the Sea of Cortez, anchored by the dramatic Land's End arch.",
     "latitude": 22.8905, "longitude": -109.9167, "temperature": "18°–29°C", "best_season": "Dec – Mar",
     "altitude": "10 m", "ai_recommendation": "Book a boat out to El Arco at sunrise to see the sea lions before the day-tripper crowds arrive."},
    {"city": "Isla Holbox", "country": "Mexico", "region": "Quintana Roo",
     "rating": 4.7, "total_reviews": 6900,
     "short_description": "Car-free Caribbean island of sand streets, golf carts and bioluminescent night water.",
     "latitude": 21.5218, "longitude": -87.3795, "temperature": "24°–31°C", "best_season": "Nov – Apr",
     "altitude": "2 m", "ai_recommendation": "Visit June–September for a real shot at swimming alongside whale sharks just offshore."},
    {"city": "Bacalar", "country": "Mexico", "region": "Quintana Roo",
     "rating": 4.8, "total_reviews": 8400,
     "short_description": "The 'Lagoon of Seven Colors' — a freshwater lake of shifting blues, cenotes and stand-up paddling.",
     "latitude": 18.6772, "longitude": -88.3972, "temperature": "23°–32°C", "best_season": "Nov – Apr",
     "altitude": "5 m", "ai_recommendation": "Paddle out to the Pirate Channel early morning when the lagoon is calmest and clearest."},
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

# Top10_places: a richer ranking table (city/country/category/rating) used by /api/top10.
# Worldwide entries reflect well-known global bucket-list destinations; country entries
# are grounded in real, widely-cited top picks for each South American country this app covers.
TOP10_PLACES_SEED = [
    # worldwide
    *[{"list_type": "worldwide", "country": None, "rank": i + 1, "city": c, "category": cat, "rating": r,
       "place_information": info, "latitude": lat, "longitude": lng}
      for i, (c, cat, r, info, lat, lng) in enumerate([
        ("London, UK", "Culture", 4.90, "TripAdvisor's top global destination for 2025, blending iconic landmarks with world-class museums and theatre.", 51.5074, -0.1278),
        ("Paris, France", "Culture", 4.90, "The world's most visited romantic capital, home to the Eiffel Tower, the Louvre and timeless boulevards.", 48.8566, 2.3522),
        ("Bali, Indonesia", "Beach", 4.88, "Rice terraces, sacred temples and surf breaks make Bali Asia's most-loved island escape.", -8.4095, 115.1889),
        ("Machu Picchu, Peru", "History", 4.90, "The 15th-century Inca citadel perched above the Sacred Valley, one of the New Seven Wonders.", -13.1631, -72.5450),
        ("Patagonia, Chile", "Nature", 4.95, "Glaciers, granite towers and end-of-the-world wilderness shared by Chile and Argentina.", -51.0, -73.0),
        ("Rome, Italy", "History", 4.87, "Three thousand years of history packed into the Colosseum, the Vatican and the Roman Forum.", 41.9028, 12.4964),
        ("Santorini, Greece", "Scenic", 4.86, "Whitewashed cliffside villages above a deep-blue volcanic caldera.", 36.3932, 25.4615),
        ("Dubai, UAE", "Luxury", 4.85, "A futuristic skyline, desert safaris and luxury shopping in one of the world's fastest-growing destinations.", 25.2048, 55.2708),
        ("Bangkok, Thailand", "Culture", 4.83, "One of the most-visited cities on Earth, famed for ornate temples, street food and floating markets.", 13.7563, 100.5018),
        ("Marrakech, Morocco", "Culture", 4.80, "Labyrinthine souks, rooftop riads and the Koutoubia mosque in Morocco's red city.", 31.6295, -7.9811),
    ])],
    # Chile
    *[{"list_type": "country", "country": "Chile", "rank": i + 1, "city": c, "category": cat, "rating": r,
       "place_information": info, "latitude": lat, "longitude": lng}
      for i, (c, cat, r, info, lat, lng) in enumerate([
        ("Patagonia", "Nature", 4.97, "End-of-the-world wilderness of glaciers, granite towers and unmatched silence.", -51.0, -73.0),
        ("Torres del Paine", "Nature", 4.95, "National park famed for granite towers, turquoise lakes and Patagonian steppe.", -50.9423, -72.9587),
        ("Valparaíso", "Culture", 4.80, "UNESCO-listed port city known for its hillside funiculars and vivid street art.", -33.0472, -71.6127),
        ("Atacama Desert", "Nature", 4.85, "The world's driest desert, with salt flats, geysers and some of the clearest night skies on Earth.", -23.8859, -68.1947),
        ("Futaleufú", "Adventure", 4.90, "World-class whitewater rafting on glacial turquoise rivers in Patagonia.", -43.1863, -71.8698),
        ("Puerto Natales", "Nature", 4.70, "Gateway to Torres del Paine, with a charming waterfront and outfitter scene.", -51.7319, -72.5083),
        ("Santiago", "Culture", 4.50, "The capital, framed by the Andes, mixing colonial architecture with a modern skyline.", -33.4489, -70.6693),
        ("Puerto Varas", "Nature", 4.60, "Lake-district town with volcano views, German colonial heritage and water sports.", -41.3195, -72.9854),
        ("Viña del Mar", "Beach", 4.50, "Pacific coast resort city an hour from Santiago, known as the 'Garden City'.", -33.0153, -71.5500),
        ("La Serena", "History", 4.40, "Chile's second-oldest city, prized for colonial architecture and nearby observatories.", -29.9027, -71.2519),
    ])],
    # Argentina
    *[{"list_type": "country", "country": "Argentina", "rank": i + 1, "city": c, "category": cat, "rating": r,
       "place_information": info, "latitude": lat, "longitude": lng}
      for i, (c, cat, r, info, lat, lng) in enumerate([
        ("Buenos Aires", "Culture", 4.60, "The tango capital, known for European-style architecture and grand boulevards.", -34.6037, -58.3816),
        ("El Calafate", "Nature", 4.90, "Gateway to Los Glaciares National Park and the spectacular Perito Moreno Glacier.", -50.3379, -72.2648),
        ("Bariloche", "Nature", 4.70, "Lake-district town on Nahuel Huapi, Argentina's premier ski and chocolate destination.", -41.1335, -71.3103),
        ("Ushuaia", "Adventure", 4.60, "The southernmost city in the world and the main embarkation point for Antarctic cruises.", -54.8019, -68.3030),
        ("Mendoza", "Wine", 4.70, "Argentina's wine capital at the foot of the Andes, home to most of the country's vineyards.", -32.8895, -68.8458),
        ("Córdoba", "History", 4.40, "Argentina's second-largest city, founded in 1573 and rich in colonial history.", -31.4201, -64.1888),
    ])],
    # Peru
    *[{"list_type": "country", "country": "Peru", "rank": i + 1, "city": c, "category": cat, "rating": r,
       "place_information": info, "latitude": lat, "longitude": lng}
      for i, (c, cat, r, info, lat, lng) in enumerate([
        ("Machu Picchu", "History", 4.90, "The Inca citadel perched in the Andes at 2,430 m above sea level.", -13.1631, -72.5450),
        ("Cusco", "History", 4.80, "The Inca Empire's historic capital and the gateway to Machu Picchu.", -13.5320, -71.9675),
        ("Lima", "Culture", 4.40, "Peru's coastal capital and most-visited city, celebrated for its culinary scene.", -12.0464, -77.0428),
        ("Arequipa", "History", 4.50, "Peru's second city, framed by three volcanoes and striking colonial architecture.", -16.4090, -71.5375),
        ("Puno (Lake Titicaca)", "Culture", 4.60, "Gateway to Lake Titicaca and the floating Uros Islands.", -15.8402, -70.0219),
    ])],
    # Colombia
    *[{"list_type": "country", "country": "Colombia", "rank": i + 1, "city": c, "category": cat, "rating": r,
       "place_information": info, "latitude": lat, "longitude": lng}
      for i, (c, cat, r, info, lat, lng) in enumerate([
        ("Cartagena", "History", 4.80, "A walled Caribbean city with colorful colonial streets and seaside ramparts.", 10.3910, -75.4794),
        ("Medellín", "Culture", 4.60, "The 'city of eternal spring', reborn through innovation, art and cable cars.", 6.2442, -75.5812),
        ("Bogotá", "Culture", 4.30, "The capital, home to the Gold Museum, La Candelaria and Monserrate.", 4.7110, -74.0721),
        ("Santa Marta", "Nature", 4.50, "Caribbean coastal city and gateway to Tayrona National Park.", 11.2408, -74.1990),
    ])],
    # Brazil
    *[{"list_type": "country", "country": "Brazil", "rank": i + 1, "city": c, "category": cat, "rating": r,
       "place_information": info, "latitude": lat, "longitude": lng}
      for i, (c, cat, r, info, lat, lng) in enumerate([
        ("Rio de Janeiro", "Beach", 4.70, "Iconic beaches, Christ the Redeemer, and a carnival spirit year-round.", -22.9068, -43.1729),
        ("Foz do Iguaçu", "Nature", 4.80, "Home to the thundering Iguazu Falls on the border with Argentina.", -25.5478, -54.5882),
        ("Florianópolis", "Beach", 4.60, "An island city famed for its beaches and laid-back surf culture.", -27.5954, -48.5480),
        ("Salvador", "Culture", 4.50, "Brazil's Afro-Brazilian heritage capital, known for its colorful colonial center.", -12.9777, -38.5016),
        ("São Paulo", "Culture", 4.40, "Brazil's largest city, celebrated for museums, nightlife and its culinary scene.", -23.5505, -46.6333),
    ])],
    # Ecuador
    *[{"list_type": "country", "country": "Ecuador", "rank": i + 1, "city": c, "category": cat, "rating": r,
       "place_information": info, "latitude": lat, "longitude": lng}
      for i, (c, cat, r, info, lat, lng) in enumerate([
        ("Galapagos Islands", "Wildlife", 4.89, "Darwin's living laboratory: wildlife found nowhere else on Earth.", -0.9538, -90.9656),
        ("Quito", "History", 4.60, "A UNESCO-listed colonial old town set high in the Andes.", -0.1807, -78.4678),
        ("Baños", "Adventure", 4.50, "An adventure-sports hub known for waterfalls, rafting and hot springs.", -1.3958, -78.4247),
        ("Cotopaxi", "Nature", 4.60, "One of the world's highest active volcanoes, with a near-perfect snow-capped cone.", -0.6798, -78.4368),
    ])],
    # Uruguay
    *[{"list_type": "country", "country": "Uruguay", "rank": i + 1, "city": c, "category": cat, "rating": r,
       "place_information": info, "latitude": lat, "longitude": lng}
      for i, (c, cat, r, info, lat, lng) in enumerate([
        ("Punta del Este", "Beach", 4.60, "Uruguay's glamorous resort city, known for beaches and a lively summer scene.", -34.9608, -54.9511),
        ("Montevideo", "Culture", 4.50, "The capital, with a famous waterfront rambla and laid-back tango roots.", -34.9011, -56.1645),
        ("Colonia del Sacramento", "History", 4.70, "A UNESCO World Heritage colonial town across the bay from Buenos Aires.", -34.4628, -57.8425),
        ("Cabo Polonio", "Nature", 4.40, "A secluded, road-free beach town known for its bohemian, off-grid atmosphere.", -34.0667, -53.7167),
    ])],
    # Japan
    *[{"list_type": "country", "country": "Japan", "rank": i + 1, "city": c, "category": cat, "rating": r,
       "place_information": info, "latitude": lat, "longitude": lng}
      for i, (c, cat, r, info, lat, lng) in enumerate([
        ("Kyoto", "Culture", 4.95, "Ancient temples, bamboo forests, and the world's most refined tea culture.", 35.01, 135.77),
        ("Tokyo", "City", 4.93, "Hyper-efficient, hyper-delicious, utterly unlike anywhere else on earth.", 35.68, 139.69),
        ("Mount Fuji", "Nature", 4.91, "Japan's sacred volcano and iconic silhouette on the world's skyline.", 35.36, 138.73),
        ("Osaka", "Gastronomy", 4.89, "Japan's kitchen: street food, neon and a wonderfully loud personality.", 34.69, 135.50),
        ("Hiroshima", "History", 4.88, "A city reborn; the Peace Memorial is one of humanity's most moving places.", 34.39, 132.45),
        ("Nara", "Culture", 4.86, "Free-roaming deer and thousand-year-old temples in a compact city.", 34.69, 135.84),
        ("Hakone", "Nature", 4.85, "Volcanic hot springs and views of Fuji from steaming open-air baths.", 35.23, 139.07),
        ("Nikko", "Culture", 4.83, "Ornate shrines and waterfalls in cedar forests north of Tokyo.", 36.75, 139.60),
        ("Hokkaido", "Nature", 4.82, "Japan's wild north: lavender fields, powder snow and fresh seafood.", 43.06, 141.34),
        ("Okinawa", "Beach", 4.80, "Tropical islands with turquoise reefs, unique culture and WWII history.", 26.21, 127.68),
    ])],
    # Greece
    *[{"list_type": "country", "country": "Greece", "rank": i + 1, "city": c, "category": cat, "rating": r,
       "place_information": info, "latitude": lat, "longitude": lng}
      for i, (c, cat, r, info, lat, lng) in enumerate([
        ("Santorini", "Scenic", 4.94, "Volcanic island with iconic white-domed architecture above a deep-blue caldera.", 36.40, 25.43),
        ("Athens", "History", 4.90, "Cradle of Western civilization; the Acropolis needs no introduction.", 37.98, 23.73),
        ("Meteora", "Scenic", 4.93, "Byzantine monasteries perched on impossible pinnacles of rock.", 39.72, 21.63),
        ("Mykonos", "Beach", 4.87, "Windmills, whitewash and the Aegean's most vibrant party island.", 37.45, 25.33),
        ("Crete", "Culture", 4.86, "Greece's largest island: Minoan palaces, gorges and incredible food.", 35.34, 25.14),
        ("Rhodes", "History", 4.84, "A medieval walled city within a sun-drenched island gateway to Turkey.", 36.43, 28.23),
        ("Delphi", "History", 4.83, "Oracle of the ancient world set on the slopes of Mount Parnassus.", 38.48, 22.50),
        ("Thessaloniki", "Culture", 4.81, "Byzantine mosaics, vibrant café culture and the best food in Greece.", 40.64, 22.94),
        ("Corfu", "Beach", 4.80, "Lush Ionian island with Venetian architecture and crystal-clear coves.", 39.62, 19.92),
        ("Olympia", "History", 4.78, "Birthplace of the Olympic Games, surrounded by ancient ruins and pine forests.", 37.64, 21.63),
    ])],
    # Italy
    *[{"list_type": "country", "country": "Italy", "rank": i + 1, "city": c, "category": cat, "rating": r,
       "place_information": info, "latitude": lat, "longitude": lng}
      for i, (c, cat, r, info, lat, lng) in enumerate([
        ("Rome", "History", 4.94, "Two millennia of empire, art and the world's best espresso.", 41.89, 12.49),
        ("Florence", "Art", 4.93, "Renaissance masterpieces at every corner: Uffizi, Duomo, Ponte Vecchio.", 43.77, 11.26),
        ("Venice", "Scenic", 4.91, "A city of canals defying logic, gravity and the passage of time.", 45.44, 12.33),
        ("Amalfi Coast", "Scenic", 4.90, "Vertical cliffs, turquoise sea and villages draped in lemon groves.", 40.63, 14.60),
        ("Cinque Terre", "Scenic", 4.88, "Five pastel fishing villages clinging to Ligurian sea cliffs.", 44.12, 9.73),
        ("Sicily", "Culture", 4.86, "Ancient temples, volcanic landscapes and Italy's finest street food.", 38.12, 13.36),
        ("Milan", "Culture", 4.84, "Fashion capital with Leonardo's Last Supper and a world-class Duomo.", 45.46, 9.19),
        ("Naples", "Gastronomy", 4.83, "Chaotic, delicious and home to the world's original pizza.", 40.85, 14.27),
        ("Pompeii", "History", 4.82, "A Roman city frozen in time by the eruption of Vesuvius in AD 79.", 40.75, 14.49),
        ("Tuscany", "Scenic", 4.81, "Cypress avenues, rolling vineyards and hilltop towns like Siena and Pienza.", 43.32, 11.33),
    ])],
    # France
    *[{"list_type": "country", "country": "France", "rank": i + 1, "city": c, "category": cat, "rating": r,
       "place_information": info, "latitude": lat, "longitude": lng}
      for i, (c, cat, r, info, lat, lng) in enumerate([
        ("Paris", "Culture", 4.92, "The City of Light: Eiffel Tower, Louvre, and the world's finest café culture.", 48.86, 2.35),
        ("Mont Saint-Michel", "Scenic", 4.93, "A tidal abbey-island that rises from the sea like a fairy-tale fortress.", 48.64, -1.51),
        ("Provence", "Scenic", 4.89, "Lavender fields, Roman aqueducts and sun-soaked Provençal villages.", 43.95, 4.81),
        ("Loire Valley", "History", 4.87, "The Garden of France: Renaissance châteaux among vineyards and rivers.", 47.39, 0.68),
        ("French Riviera", "Scenic", 4.86, "Azure Coast of glamour, art and brilliant Mediterranean light.", 43.70, 7.27),
        ("Normandy", "History", 4.84, "D-Day beaches, half-timbered villages and the world's creamiest cuisine.", 49.27, -0.70),
        ("Alsace", "Culture", 4.83, "Wine route through half-timbered villages straight out of a storybook.", 48.57, 7.75),
        ("Bordeaux", "Gastronomy", 4.82, "World wine capital with grand 18th-century architecture along the Garonne.", 44.84, -0.58),
        ("Chamonix", "Adventure", 4.81, "Mountain-town at the foot of Mont Blanc with legendary Alpine skiing.", 45.92, 6.87),
        ("Corsica", "Nature", 4.80, "The Island of Beauty: maquis-covered mountains plunging into turquoise sea.", 41.92, 8.74),
    ])],
    # USA
    *[{"list_type": "country", "country": "USA", "rank": i + 1, "city": c, "category": cat, "rating": r,
       "place_information": info, "latitude": lat, "longitude": lng}
      for i, (c, cat, r, info, lat, lng) in enumerate([
        ("Grand Canyon", "Nature", 4.95, "A mile-deep gorge carved over 5 million years by the Colorado River.", 36.06, -112.11),
        ("Yosemite", "Nature", 4.93, "Cathedral-like granite valleys, ancient sequoias and iconic waterfalls.", 37.75, -119.54),
        ("New York City", "City", 4.92, "Culture, food and skyline in every direction. The city that never sleeps.", 40.71, -74.01),
        ("Yellowstone", "Nature", 4.91, "America's first national park: geysers, hot springs and bison herds.", 44.43, -110.59),
        ("Hawaii", "Beach", 4.90, "Volcanic islands with world-class surfing, lush rainforests and coral reefs.", 21.30, -157.82),
        ("San Francisco", "City", 4.89, "Golden Gate, cable cars, Alcatraz and some of America's best food.", 37.77, -122.42),
        ("New Orleans", "Culture", 4.88, "Jazz birthplace with French Quarter architecture and legendary Creole cuisine.", 29.95, -90.08),
        ("Chicago", "City", 4.87, "Lakefront skyline, deep-dish pizza and world-class architecture.", 41.88, -87.63),
        ("Miami", "Beach", 4.85, "Art Deco beaches, vibrant nightlife and the best Cuban food outside Havana.", 25.77, -80.19),
        ("Los Angeles", "City", 4.83, "Hollywood, Pacific Coast Highway and the world's most diverse food scene.", 34.05, -118.24),
    ])],
    # Australia
    *[{"list_type": "country", "country": "Australia", "rank": i + 1, "city": c, "category": cat, "rating": r,
       "place_information": info, "latitude": lat, "longitude": lng}
      for i, (c, cat, r, info, lat, lng) in enumerate([
        ("Great Barrier Reef", "Wildlife", 4.95, "The world's largest coral reef system, visible from space.", -16.92, 145.77),
        ("Sydney", "City", 4.93, "Opera House, Harbour Bridge and some of the world's best beaches.", -33.87, 151.21),
        ("Uluru", "Culture", 4.91, "A sacred monolith rising 348 m from the flat red centre of the continent.", -25.35, 131.04),
        ("Melbourne", "City", 4.90, "Laneways, coffee culture, street art and Australia's best restaurant scene.", -37.81, 144.96),
        ("Tasmania", "Nature", 4.88, "Wild, unspoiled wilderness at the edge of the world with world-class MONA.", -42.88, 147.33),
        ("Whitsundays", "Beach", 4.87, "74 islands of turquoise water and the dazzling white Whitehaven Beach.", -20.27, 148.96),
        ("Blue Mountains", "Nature", 4.85, "Ancient sandstone escarpments with waterfalls and the iconic Three Sisters.", -33.72, 150.31),
        ("Byron Bay", "Beach", 4.83, "Laid-back surf town with the most easterly lighthouse on the continent.", -28.65, 153.61),
        ("Kangaroo Island", "Wildlife", 4.82, "An ark of unspoilt nature: koalas, sea lions and remarkable rock formations.", -35.86, 137.17),
        ("Darwin", "Culture", 4.79, "Tropical gateway to Kakadu, one of the oldest living cultures on earth.", -12.46, 130.84),
    ])],
    # Morocco
    *[{"list_type": "country", "country": "Morocco", "rank": i + 1, "city": c, "category": cat, "rating": r,
       "place_information": info, "latitude": lat, "longitude": lng}
      for i, (c, cat, r, info, lat, lng) in enumerate([
        ("Marrakech", "Culture", 4.90, "Labyrinthine medinas, vibrant souks and rooftop views over the Koutoubia.", 31.63, -7.99),
        ("Fes", "History", 4.89, "The world's oldest living medieval city with a 9,000-alley medina.", 34.03, -4.99),
        ("Sahara Desert", "Nature", 4.93, "Erg Chebbi: towering orange dunes and camel treks under a dome of stars.", 31.10, -3.98),
        ("Chefchaouen", "Scenic", 4.92, "The Blue City: an extraordinary mountain town painted in shades of cobalt.", 35.17, -5.27),
        ("Aït Benhaddou", "History", 4.88, "UNESCO-listed ksar — mud-brick citadel immortalized in countless films.", 31.05, -7.13),
        ("Essaouira", "Scenic", 4.86, "Atlantic-swept coastal ramparts, blue fishing boats and wind-swept beaches.", 31.51, -9.76),
        ("Ouarzazate", "Culture", 4.84, "Gateway to the Sahara and the Draa Valley of kasbahs and palm groves.", 30.93, -6.89),
        ("Casablanca", "Culture", 4.82, "Art Deco grandeur, Hassan II Mosque and Morocco's cosmopolitan heart.", 33.57, -7.59),
        ("Rabat", "History", 4.80, "Morocco's tranquil capital with UNESCO medina and the unfinished Hassan Tower.", 34.02, -6.84),
        ("Tangier", "Culture", 4.79, "Mythic port city at the meeting point of Atlantic and Mediterranean.", 35.77, -5.80),
    ])],
    # Indonesia
    *[{"list_type": "country", "country": "Indonesia", "rank": i + 1, "city": c, "category": cat, "rating": r,
       "place_information": info, "latitude": lat, "longitude": lng}
      for i, (c, cat, r, info, lat, lng) in enumerate([
        ("Raja Ampat", "Wildlife", 4.95, "The most biodiverse marine ecosystem on the planet, utterly pristine.", -0.51, 130.52),
        ("Ubud, Bali", "Culture", 4.92, "Rice terraces, sacred temples, healers and a world-class wellness scene.", -8.51, 115.26),
        ("Komodo Island", "Wildlife", 4.91, "The only place on earth to witness Komodo dragons in the wild.", -8.55, 119.49),
        ("Yogyakarta", "Culture", 4.89, "Cultural heart of Java with Borobudur and Prambanan temples nearby.", -7.80, 110.36),
        ("Lombok", "Nature", 4.86, "Rinjani volcano, empty beaches and a quieter alternative to Bali.", -8.65, 116.10),
        ("Gili Islands", "Beach", 4.85, "Car-free coral-fringed islands with hammock-chic and sea turtles.", -8.35, 116.05),
        ("Labuan Bajo", "Scenic", 4.84, "Dramatic pink-sand beaches and the gateway to Komodo National Park.", -8.52, 119.89),
        ("Mount Bromo", "Nature", 4.83, "An active volcano set in a vast caldera — sunrise here is unforgettable.", -7.94, 112.95),
        ("Lake Toba", "Nature", 4.81, "The world's largest volcanic lake on Sumatra, with the island of Samosir.", 2.68, 98.82),
        ("Jakarta", "City", 4.75, "Mega-city melting pot of colonial history, ultra-modern malls and street food.", -6.21, 106.85),
    ])],
    # New Zealand
    *[{"list_type": "country", "country": "New Zealand", "rank": i + 1, "city": c, "category": cat, "rating": r,
       "place_information": info, "latitude": lat, "longitude": lng}
      for i, (c, cat, r, info, lat, lng) in enumerate([
        ("Milford Sound", "Scenic", 4.96, "Sheer 1,200 m fiord walls and cascading waterfalls in Fiordland.", -44.67, 167.93),
        ("Queenstown", "Adventure", 4.94, "Adventure capital of the world set against fjords and the Remarkables.", -45.03, 168.66),
        ("Tongariro Alpine Crossing", "Adventure", 4.93, "New Zealand's greatest day hike past active craters and emerald lakes.", -39.20, 175.67),
        ("Franz Josef Glacier", "Nature", 4.90, "A rare temperate rainforest glacier that descends almost to sea level.", -43.39, 170.18),
        ("Bay of Islands", "Nature", 4.88, "Subtropical paradise of 144 islands in the birthplace of New Zealand.", -35.26, 174.08),
        ("Rotorua", "Culture", 4.87, "Geothermal wonderland and living Māori culture in the volcanic heartland.", -38.14, 176.25),
        ("Abel Tasman", "Beach", 4.86, "Golden sand beaches and clear-water coves in a coastal national park.", -40.85, 172.99),
        ("Coromandel Peninsula", "Scenic", 4.84, "Cathedral Cove sea cave and the iconic dig-your-own Hot Water Beach.", -37.02, 175.88),
        ("Kaikōura", "Wildlife", 4.83, "Whale watching, sperm whales and a dramatic snowy mountain backdrop.", -42.40, 173.68),
        ("Wellington", "Culture", 4.82, "Compact capital with Te Papa museum, craft beer and epic windy character.", -41.29, 174.78),
    ])],
    # category (one destination per traveller type, for the "Top 10 by Category" view)
    *[{"list_type": "category", "country": None, "rank": i + 1, "city": c, "category": cat, "rating": r,
       "place_information": info, "latitude": lat, "longitude": lng}
      for i, (c, cat, r, info, lat, lng) in enumerate([
        ("Maldives", "Beach", 4.95, "Overwater bungalows above the clearest lagoons on the planet.", 3.2028, 73.2207),
        ("Patagonia, Chile", "Trekking", 4.97, "The world's finest trekking through raw, uncrowded wilderness.", -51.0, -73.0),
        ("Kyoto, Japan", "Culture", 4.94, "The single best destination for immersing in traditional culture.", 35.0116, 135.7681),
        ("Swiss Alps", "Mountains", 4.92, "Skiing, hiking and mountain railways through Europe's dramatic peaks.", 46.58, 7.90),
        ("Galapagos Islands", "Wildlife", 4.91, "Snorkelling with sea lions and penguins in an untouched ocean ecosystem.", -0.9538, -90.9656),
        ("Cartagena, Colombia", "Romantic", 4.87, "Romantic walled city with vibrant street life and perfect Caribbean evenings.", 10.3910, -75.4794),
        ("Queenstown, NZ", "Adventure", 4.85, "Bungee, skydive, ski, raft — the greatest concentration of adventure on Earth.", -45.0312, 168.6626),
        ("Florence, Italy", "Art & Food", 4.84, "Renaissance art, architecture and food that justify every art history class.", 43.7696, 11.2558),
        ("Atacama Desert, Chile", "Stargazing", 4.83, "Stargazing in the world's driest desert, where the Milky Way is unobscured.", -23.8859, -68.1947),
        ("Bali, Indonesia", "Wellness", 4.82, "Yoga retreats, surf schools and wellness culture set among rice terraces.", -8.4095, 115.1889),
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
            DELETE FROM mt_places;
            DELETE FROM top10_places;
            DELETE FROM places;
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

        # Insert places (autocomplete source)
        for p in PLACES_SEED:
            conn.execute("INSERT INTO places (emoji,name,subtitle) VALUES (:emoji,:name,:subtitle)", p)

        # Insert mt_places (left-panel place details, keyed off the autocomplete selection)
        for mp in MT_PLACES_SEED:
            conn.execute("""
                INSERT INTO mt_places (city,country,region,rating,total_reviews,short_description,
                    latitude,longitude,temperature,best_season,altitude,ai_recommendation)
                VALUES (:city,:country,:region,:rating,:total_reviews,:short_description,
                    :latitude,:longitude,:temperature,:best_season,:altitude,:ai_recommendation)
            """, mp)

        # Insert top10
        for item in TOP10_SEED:
            conn.execute("""
                INSERT OR REPLACE INTO top10 (list_type,rank,name,description,rating,tag)
                VALUES (:list_type,:rank,:name,:description,:rating,:tag)
            """, item)

        # Insert top10_places (richer worldwide / by-country rankings for /api/top10)
        for item in TOP10_PLACES_SEED:
            conn.execute("""
                INSERT INTO top10_places (list_type,country,city,category,rating,place_information,latitude,longitude,rank)
                VALUES (:list_type,:country,:city,:category,:rating,:place_information,:latitude,:longitude,:rank)
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


def get_top10_places(list_type: str, country: str = None):
    """Worldwide, by-country, or by-category top10 rankings
    (city/country/category/rating/place_information)."""
    with get_conn() as conn:
        if list_type == "country":
            rows = conn.execute("""
                SELECT * FROM top10_places
                WHERE list_type='country' AND country=? COLLATE NOCASE
                ORDER BY rank
            """, (country,)).fetchall()
        elif list_type == "category":
            rows = conn.execute("""
                SELECT * FROM top10_places WHERE list_type='category' ORDER BY rank
            """).fetchall()
        else:
            rows = conn.execute("""
                SELECT * FROM top10_places WHERE list_type='worldwide' ORDER BY rank
            """).fetchall()
        return [dict(r) for r in rows]


def get_top10_countries():
    """Distinct countries that have a by-country top10 list, for building UI filters."""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT DISTINCT country FROM top10_places WHERE list_type='country' ORDER BY country
        """).fetchall()
        return [r["country"] for r in rows]


# Flag emoji per country backing a top10_places by-country list — used by the
# "Search by country" directory in the UI.
COUNTRY_FLAGS = {
    "Chile": "🇨🇱", "Argentina": "🇦🇷", "Peru": "🇵🇪", "Colombia": "🇨🇴",
    "Brazil": "🇧🇷", "Ecuador": "🇪🇨", "Uruguay": "🇺🇾", "Japan": "🇯🇵",
    "Greece": "🇬🇷", "Italy": "🇮🇹", "France": "🇫🇷", "USA": "🇺🇸",
    "Australia": "🇦🇺", "Morocco": "🇲🇦", "Indonesia": "🇮🇩", "New Zealand": "🇳🇿",
}


def get_top10_country_directory():
    """Every country with a by-country top10 list, with its flag and
    destination count — backs the "Search by country" directory in the UI."""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT country, COUNT(*) AS count FROM top10_places
            WHERE list_type='country' GROUP BY country ORDER BY country
        """).fetchall()
        return [
            {
                "country": r["country"],
                "flag": COUNTRY_FLAGS.get(r["country"], "🌍"),
                "sub": f"{r['count']} destinations",
            }
            for r in rows
        ]


def search_places(query: str, limit: int = 6):
    """Autocomplete lookup: matches on name or subtitle, name-prefix matches first."""
    like = f"%{query}%"
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT *, (name LIKE :prefix) AS is_prefix
            FROM places
            WHERE name LIKE :like OR subtitle LIKE :like
            ORDER BY is_prefix DESC, name
            LIMIT :limit
        """, {"like": like, "prefix": f"{query}%", "limit": limit}).fetchall()
        return [dict(r) for r in rows]


def get_mt_place(name: str):
    """Look up a place's details by the value typed into the search bar, e.g.
    'Santiago, Chile' or 'Galapagos Islands'. Matches on 'city, country' first, then city alone."""
    name = name.strip()
    city_guess = name.split(",")[0].strip()
    with get_conn() as conn:
        row = conn.execute("""
            SELECT * FROM mt_places
            WHERE (city || ', ' || country) = ? COLLATE NOCASE
               OR city = ? COLLATE NOCASE
            LIMIT 1
        """, (name, name)).fetchone()
        if not row:
            row = conn.execute("""
                SELECT * FROM mt_places WHERE city = ? COLLATE NOCASE LIMIT 1
            """, (city_guess,)).fetchone()
        return dict(row) if row else None


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


def save_full_plan(title: str, from_name: str, from_lat: float, from_lng: float,
                    to_name: str, to_lat: float, to_lng: float,
                    user_id: int = 1111, user_email: str = "test@gmail.com",
                    distance_km: int = None, duration_text: str = None,
                    transport_mode: str = None, places: list = None, notes: str = ""):
    """Saves a plan built from a live search: the real from/to points and the
    Google Maps markers (tourist places, as {name, latitude, longitude}) found
    along that route — associated with the given user."""
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO saved_plans (user_id, user_email, title, notes,
                from_name, from_lat, from_lng, to_name, to_lat, to_lng,
                distance_km, duration_text, transport_mode, stops_snapshot)
            VALUES (:user_id,:user_email,:title,:notes,
                :from_name,:from_lat,:from_lng,:to_name,:to_lat,:to_lng,
                :distance_km,:duration_text,:transport_mode,:places)
        """, {
            "user_id": user_id, "user_email": user_email, "title": title, "notes": notes,
            "from_name": from_name, "from_lat": from_lat, "from_lng": from_lng,
            "to_name": to_name, "to_lat": to_lat, "to_lng": to_lng,
            "distance_km": distance_km, "duration_text": duration_text,
            "transport_mode": transport_mode, "places": json.dumps(places or []),
        })
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def get_plans_for_user(user_id: int):
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT * FROM saved_plans WHERE user_id=? ORDER BY created_at DESC
        """, (user_id,)).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["stops_snapshot"] = json.loads(d["stops_snapshot"] or "[]")
            result.append(d)
        return result


if __name__ == "__main__":
    init_db()
    seed_db()
    print("\n📊  Stops in DB:")
    for s in get_all_stops():
        print(f"  [{s['id']}] {s['emoji']} {s['name']}  ⭐ {s['rating']}  ({s['review_count']} reviews)")
    print("\n💬  Reviews sample:")
    for r in get_reviews(1):
        print(f"  {r['initials']} — {r['rating']}★  \"{r['comment'][:60]}...\"")
