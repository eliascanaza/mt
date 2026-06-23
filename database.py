"""
exploreMore — MongoDB database layer
Handles all DB setup, seed data, and reads/writes for:
  - places / mt_places       : search-bar autocomplete and place details
  - top10_places             : curated top-10 rankings (worldwide/country/category)
  - saved_plans              : plans saved from a live search
  - stops / routes / reviews : legacy schema, kept for the get_all_stops()/
                                get_reviews() demo in __main__ below

Connects to MongoDB (Atlas or any other "online"/remote cluster) via the
MONGODB_URI env var — set it in .env, e.g.:
  MONGODB_URI=mongodb+srv://user:pass@cluster0.xxxxx.mongodb.net
Falls back to a local mongod (mongodb://localhost:27017) for development
when MONGODB_URI isn't set.
"""

import os
import json
import re
from datetime import datetime, timezone

import certifi
from dotenv import load_dotenv
from pymongo import MongoClient, ASCENDING

# database.py is sometimes imported before app.py's own load_dotenv() call
# (and run standalone via `python3 database.py`), so it loads .env itself.
load_dotenv()

MONGODB_URI = os.environ.get("MONGODB_URI", "mongodb://localhost:27017")
MONGODB_DB_NAME = os.environ.get("MONGODB_DB_NAME", "maketrip")

_client = None


def get_client() -> MongoClient:
    global _client
    if _client is None:
        # Same fix app.py uses for urllib: macOS Python builds don't always
        # ship a usable CA trust store, which breaks TLS to Atlas
        # (mongodb+srv://) with CERTIFICATE_VERIFY_FAILED. Harmless no-op
        # for a non-TLS local mongodb:// connection.
        _client = MongoClient(MONGODB_URI, tlsCAFile=certifi.where())
    return _client


def get_db():
    """The active database handle — collections are created lazily by Mongo
    on first write, so there's no upfront CREATE TABLE step."""
    return get_client()[MONGODB_DB_NAME]


# ── Schema (indexes only — Mongo collections/fields are schemaless) ──────
def init_db():
    db = get_db()
    db.top10.create_index([("list_type", ASCENDING), ("rank", ASCENDING)], unique=True)
    db.top10_places.create_index([("list_type", ASCENDING), ("rank", ASCENDING)])
    db.stops.create_index("id", unique=True)
    db.reviews.create_index("stop_id")
    db.places.create_index("name")
    db.mt_places.create_index("city")
    db.saved_plans.create_index("user_id")
    db.users.create_index("id", unique=True)
    db.users.create_index("google_sub", unique=True)
    db.users.create_index("email", unique=True)
    print("✅  Schema ready")


def _next_id(db, collection: str) -> int:
    """Small integer ids (matching the old SQLite AUTOINCREMENT ids the
    frontend already expects) — fine at this app's scale; avoids pulling in
    a separate counters collection for a handful of writes per request."""
    last = db[collection].find_one(sort=[("id", -1)], projection={"id": 1})
    return (last["id"] + 1) if last else 1


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
# Worldwide entries are the 10 most iconic individual landmarks on Earth (rather than whole
# cities/regions); country entries are grounded in real, widely-cited top picks for each
# South American country this app covers.
TOP10_PLACES_SEED = [
    # worldwide — iconic landmarks, not whole cities/regions
    *[{"list_type": "worldwide", "country": None, "rank": i + 1, "city": c, "category": cat, "rating": r,
       "place_information": info, "latitude": lat, "longitude": lng}
      for i, (c, cat, r, info, lat, lng) in enumerate([
        ("Eiffel Tower, Paris, France", "Culture", 4.90, "Gustave Eiffel's 330-metre iron landmark on the Seine, the most-visited paid monument on Earth and the symbol of Paris itself.", 48.8584, 2.2945),
        ("Colosseum, Rome, Italy", "History", 4.88, "The largest amphitheatre ever built, where gladiators once fought before 50,000 spectators in the heart of ancient Rome.", 41.8902, 12.4922),
        ("Taj Mahal, Agra, India", "History", 4.92, "A white-marble mausoleum built by Emperor Shah Jahan for his wife Mumtaz Mahal, and one of the most photographed buildings on Earth.", 27.1739, 78.0421),
        ("Statue of Liberty, New York City, USA", "History", 4.80, "France's 1886 gift to the United States, standing watch over New York Harbor as a global symbol of freedom.", 40.6892, -74.0445),
        ("Machu Picchu, Peru", "History", 4.90, "The 15th-century Inca citadel perched above the Sacred Valley, one of the New Seven Wonders.", -13.1631, -72.5450),
        ("Great Wall of China, China", "History", 4.87, "Over 21,000 kilometres of ancient fortifications winding across northern China's mountains, best explored at the restored Badaling section.", 40.3542, 116.0069),
        ("Pyramids of Giza, Cairo, Egypt", "History", 4.85, "The last surviving wonder of the ancient world — the Great Pyramid and its neighbors have stood on the Giza plateau for over 4,500 years.", 29.9792, 31.1342),
        ("Times Square, New York City, USA", "Culture", 4.75, "The neon-lit 'Crossroads of the World,' packed with Broadway theatres, giant billboards and New Year's Eve crowds.", 40.7589, -73.9851),
        ("Kyoto's Temples and Shrines, Kyoto, Japan", "Culture", 4.91, "Thousands of vermilion torii gates at Fushimi Inari and centuries-old wooden temples make Kyoto Japan's spiritual heart.", 34.9672, 135.7728),
        ("Grand Bazaar, Istanbul, Turkey", "Culture", 4.78, "One of the world's oldest and largest covered markets, with thousands of shops trading carpets, spices and gold since the 15th century.", 41.0107, 28.9681),
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
        ("Machu Picchu, Cusco", "History", 4.90, "Machu Picchu is a magnificent 15th-century Inca citadel built high in the Andes mountains. It is widely recognized as one of the most spectacular archaeological sites on the entire planet. This legendary ruins complex served as a royal estate or sacred religious sanctuary for the Inca empire.\n\nIt is universally famous for its incredible dry-stone walls put together without any mortar. The site perfectly integrates massive agricultural terraces with breathtaking, jagged mountain peaks. It lay completely hidden from the Spanish conquistadors and the outside world for centuries.\n\nHiram Bingham famously brought global attention to this hidden cloud forest wonder back in 1911. Today it stands proudly as a designated UNESCO World Heritage site and a global travel icon. Visitors flock here to see the Intihuatana stone, Temple of the Sun, and Room of Three Windows. It remains the ultimate symbol of the power, advanced engineering, and artistry of the Inca Empire.", -13.1631, -72.5450),
        ("Historic Center of Lima, Lima", "History", 4.60, "The Historic Center of Lima, anchored by the Plaza Mayor, is the true birthplace of the capital. It was founded by Spanish conquistador Francisco Pizarro in 1535 as the grand 'City of the Kings.' This area is famous for containing the highest concentration of historic colonial monuments in Lima.\n\nIt serves as the administrative heart of modern Peru, holding the majestic Government Palace. The square is surrounded by spectacular yellow-hued buildings and the grand Cathedral of Lima. It is universally renowned for its iconic, deeply intricate carved wooden balconies from the colonial era.\n\nThe complex contains the San Francisco Convent, famous for its historic library and catacombs. This historic quarter beautifully represents the blending of European baroque architecture and local craft. It showcases the immense wealth, political power, and deep religious history of Spain's viceroyalty. Today it is protected as a UNESCO World Heritage site and serves as a major cultural gateway.", -12.0458, -77.0306),
        ("Santa Catalina Monastery, Arequipa", "History", 4.70, "The Santa Catalina Monastery is an immense, walled religious convent located in downtown Arequipa. Built in 1579, this complex functioned for centuries as a highly secretive, cloistered community. It is world-famous for its striking, intensely vibrant terracotta-orange and cobalt-blue walls.\n\nThe monastery is uniquely structured as a sprawling 'city within a city' covering a massive city block. It features its own narrow cobblestone streets, hidden courtyards, beautiful fountains, and chapels. Wealthy colonial families sent their daughters here, who lived with personal servants and luxuries.\n\nIt offers a fascinating, highly preserved look into the daily life and secrets of colonial nuns. The architecture beautifully blends Spanish mudéjar styles with native volcanic sillar stone carving. It was completely closed off from the outside world for nearly 400 years until opening in 1970. Today it stands as Arequipa's most photogenic architectural masterpiece and a must-visit destination.", -16.3950, -71.5367),
        ("Uros Floating Islands, Puno", "Culture", 4.50, "The Uros Floating Islands are a collection of extraordinary, man-made communities on Lake Titicaca. They are constructed completely out of the buoyant roots and stalks of local native totora reeds. The indigenous Uros people originally built these mobile platforms to escape aggressive mainland tribes.\n\nEvery aspect of daily life on the islands relies heavily on this renewable, versatile reed material. Residents constantly add fresh layers of reeds to the surface to prevent the islands from rotting. The communities feature unique reed houses, distinct hand-woven boats, and even floating school buildings.\n\nIt is a globally unique cultural destination that showcases incredible human adaptation to water. Visitors can experience a way of life that has survived out on the lake for thousands of years. The vibrant traditional clothing and artistic textiles of the residents add immense color to the lake. They represent one of the most famous, highly creative indigenous engineering feats in South America.", -15.8188, -69.9716),
        ("Huacachina Oasis, Ica", "Nature", 4.60, "The Huacachina Oasis is a tiny, incredibly photogenic resort village located in southwestern Peru. It is built directly around a small, calm natural desert lagoon fed by subterranean water currents. The village is completely encircled by some of the tallest, most dramatic sand dunes in the world.\n\nLocal legend states that the lagoon was formed from the tears of a grieving, beautiful princess. It is universally famous as South America's ultimate hub for high-adrenaline desert adventure sports. Thousands of travelers visit every week to experience wild, fast-paced dune buggy mountain rides.\n\nThe massive, smooth sandy slopes surrounding the water provide the perfect conditions for sandboarding. It features a charming, palm-lined boardwalk packed with lively restaurants, cafes, and boutique hotels. The oasis offers some of the most breathtaking, glowing golden sunset views found anywhere in Peru. It stands out as a surreal, dreamlike pocket of lush green and deep blue hidden in an arid desert.", -14.0875, -75.7626),
        ("The Nazca Lines, Nazca", "History", 4.40, "The Nazca Lines are an ancient group of massive geoglyphs etched deeply into the desert floor. They were created by the Nazca culture between 500 BCE and 500 CE by removing dark surface stones. These lines cover an immense, arid plateau stretching across nearly 450 square kilometers of land.\n\nThey are globally famous for depicting enormous, stylized animal figures like monkeys and spiders. The collection also features huge birds, lizards, humanoids, and highly precise geometric lines. Because of the extreme scale, these intricate designs can only be fully appreciated from the air.\n\nTheir exact purpose remains an intriguing archaeological mystery involving calendars and water rituals. Scientists like Maria Reiche dedicated their entire lives to studying and protecting these desert lines. The hyper-arid, windless desert climate has perfectly preserved these fragile markings for millennia. They are designated as a UNESCO World Heritage site and attract curious travelers from around the globe.", -14.9997, -75.0125),
        ("Laguna 69, Huaraz", "Nature", 4.80, "Laguna 69 is an astonishingly beautiful alpine lake tucked deep inside the Cordillera Blanca range. It sits at a dizzying, high-altitude elevation of 4,600 meters inside Huascarán National Park. The lake is universally famous for its incredibly intense, brilliant neon-turquoise colored water.\n\nIt is framed by a magnificent backdrop of towering, jagged granite peaks and massive glaciers. A spectacular, icy waterfall tumbles down directly into the lake from the towering Chacraraju mountain. Reaching this hidden gem requires a challenging, physically demanding 4-to-5 hour uphill day trek.\n\nThe trail winds past scenic rushing streams, unique local flora, and dramatic mountain vistas. It has quickly become one of the most popular, sought-after hiking destinations in South America. Huaraz serves as the essential base camp town where hikers acclimatize before making the journey.\n\nIt stands as a true bucket-list destination for outdoor adventurers, photographers, and mountaineers.", -9.0104, -77.6120),
        ("Pacaya-Samiria National Reserve, Iquitos", "Nature", 4.70, "The Pacaya-Samiria National Reserve is a massive, incredibly pristine protected area in northern Peru. Spanning over 2 million hectares, it is one of the largest wildlife reserves in the entire country. It is widely known as the 'Jungle of Mirrors' due to its perfectly reflective, dark river waters.\n\nThe reserve encompasses a vast, complex ecosystem of flooded tropical rainforests and winding rivers. It is globally famous for its exceptional biodiversity, harboring thousands of unique animal species. Travelers venture here to spot rare pink river dolphins, giant river otters, and colorful macaws.\n\nIt is also a safe haven for jaguars, multiple monkey species, and prehistoric-looking caimans. Iquitos serves as the mandatory river port and gateway town for entering this remote wilderness. Visitors explore the reserve via multi-day luxury river cruises or rustic, eco-friendly jungle lodges. It offers an authentic, deep-jungle expedition experience far away from modern urban development.", -5.2400, -75.6000),
        ("Tambopata National Reserve, Puerto Maldonado", "Nature", 4.70, "The Tambopata National Reserve protects a massive tract of hyper-diverse southern Amazon rainforest. It is situated right alongside the winding Tambopata and Madre de Dios river basins in Peru. The reserve is internationally famous for holding several of the world's largest parrot clay licks.\n\nEvery morning, hundreds of spectacular, colorful macaws gather to consume mineral-rich clay walls. This stunning natural phenomenon creates one of the most famous wildlife spectacles in South America. Tambopata is renowned for breaking world records in species diversity for birds, butterflies, and beetles.\n\nIt features pristine oxbow lakes like Lake Sandoval, home to families of giant endangered river otters. Puerto Maldonado is the bustling jungle city that serves as the primary travel hub for the region. Visitors can stay in world-class eco-lodges that feature canopy walkways high above the forest floor. It offers a highly accessible yet wild jungle experience, located just a short flight from Cusco.", -12.9300, -69.2700),
        ("Chan Chan, Trujillo", "History", 4.50, "Chan Chan is a sprawling, ancient archaeological complex situated right on the northern coast of Peru. It was constructed around 900 CE as the grand capital city of the powerful Chimú Kingdom. This massive site holds the proud title of being the largest adobe clay city in the entire Americas.\n\nBefore its conquest by the Inca Empire, it housed an estimated population of over 60,000 people. It is famous for its nine massive, heavily walled royal citadels built for individual Chimú kings. The thick mud walls are beautifully decorated with elaborate, repetitive geometric and marine carvings.\n\nThese carvings depict stylized fish, pelicans, ocean waves, and celestial astrological symbols. It showcases an incredibly advanced coastal civilization that mastered irrigation and desert living. Today it is protected as a UNESCO World Heritage site and sits right outside the city of Trujillo. It stands as an essential destination for uncovering Peru's rich history long before the Incas.", -8.1100, -79.0700),
        ("Kuelap Fortress, Chachapoyas", "History", 4.60, "Kuelap is a massive, awe-inspiring walled mountain fortress built high in the northern cloud forests. It was constructed by the mysterious pre-Inca Chachapoyas culture, known as the 'Cloud Warriors.' The site sits dramatically perched on a limestone ridge at an altitude of 3,000 meters above sea level.\n\nIt is famous for its colossal perimeter walls, which rise up to a staggering 20 meters in height. This ancient city predates the Incas by centuries, with construction starting around the 6th century CE. Inside the giant walls lie the ruins of over 400 unique, circular stone houses and ceremonial structures.\n\nMany of the stone walls feature beautiful geometric zig-zag patterns and carved humanistic faces. It was built in a highly strategic location to defend the kingdom from aggressive Amazonian tribes. Today a modern, scenic cable car system carries visitors across a deep canyon directly to the ruins. It stands as a grand alternative to Machu Picchu, offering ancient history without the heavy crowds.", -6.4167, -77.9167)
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
    db = get_db()

    # Clear existing data in dependency order
    for name in ["saved_plans", "route_stops", "reviews", "top10", "routes",
                 "stops", "mt_places", "top10_places", "places"]:
        db[name].delete_many({})

    # Insert stops and collect their real IDs
    stop_ids = []
    for i, s in enumerate(STOPS_SEED, 1):
        db.stops.insert_one({**s, "id": i})
        stop_ids.append(i)

    # Insert a default route
    route_id = 1
    db.routes.insert_one({
        "id": route_id,
        "from_name": "Santiago, Chile", "from_lat": -33.4489, "from_lng": -70.6693,
        "to_name": "Puerto Natales, Chile", "to_lat": -51.7319, "to_lng": -72.5083,
        "distance_km": 2460, "drive_hours": 26, "stop_count": 3,
        "days_min": 8, "days_max": 10,
        "created_at": datetime.now(timezone.utc),
    })

    # Link stops to route using their real IDs
    db.route_stops.insert_many([
        {"route_id": route_id, "stop_id": sid, "position": pos}
        for pos, sid in enumerate(stop_ids, 1)
    ])

    # Insert reviews using real stop IDs
    for i, r in enumerate(REVIEWS_SEED, 1):
        # Map seed stop_id (1-based index) to actual DB id
        actual_stop_id = stop_ids[r["stop_id"] - 1]
        db.reviews.insert_one({
            "id": i, "stop_id": actual_stop_id, "reviewer": r["reviewer"],
            "location": r["location"], "rating": r["rating"], "comment": r["comment"],
            "avatar_color": r["avatar_color"], "initials": r["initials"],
            "visited_at": r["visited_at"], "created_at": datetime.now(timezone.utc),
        })

    # Insert places (autocomplete source)
    db.places.insert_many([{**p, "id": i} for i, p in enumerate(PLACES_SEED, 1)])

    # Insert mt_places (left-panel place details, keyed off the autocomplete selection)
    db.mt_places.insert_many([{**mp, "id": i} for i, mp in enumerate(MT_PLACES_SEED, 1)])

    # Insert top10
    for item in TOP10_SEED:
        db.top10.replace_one(
            {"list_type": item["list_type"], "rank": item["rank"]}, item, upsert=True,
        )

    # Insert top10_places (richer worldwide / by-country rankings for /api/top10)
    db.top10_places.insert_many([{**item, "id": i} for i, item in enumerate(TOP10_PLACES_SEED, 1)])

    # Default saved plan
    db.saved_plans.insert_one({
        "id": 1, "user_name": "Alex Traveller", "user_id": 1111, "user_email": "test@gmail.com",
        "route_id": route_id, "title": "Patagonia Road Trip 2024",
        "notes": "Dream route from Santiago all the way to Puerto Natales",
        "from_name": None, "from_lat": None, "from_lng": None,
        "to_name": None, "to_lat": None, "to_lng": None,
        "distance_km": None, "duration_text": None, "transport_mode": None,
        "stops_snapshot": [], "created_at": datetime.now(timezone.utc),
    })

    print("✅  Seed data inserted")


# ── Query helpers ───────────────────────────────────────────────────────
def _strip_id(doc):
    """Drops Mongo's ObjectId _id (not JSON-serializable) from a document
    before it goes into a jsonify() response."""
    if doc is not None:
        doc.pop("_id", None)
    return doc


def _iso(dt):
    """ISO-8601 string for a stored datetime — jsonify() can't serialize
    Python datetime/BSON date objects directly."""
    return dt.isoformat() if dt else dt


def get_all_stops():
    db = get_db()
    result = []
    for d in db.stops.find().sort("id", ASCENDING):
        d = _strip_id(d)
        d["tags"] = json.loads(d["tags"])
        d["commutes"] = json.loads(d["commutes"])
        result.append(d)
    return result


def get_reviews(stop_id: int):
    db = get_db()
    reviews = []
    for d in db.reviews.find({"stop_id": stop_id}).sort("created_at", -1):
        d = _strip_id(d)
        d["created_at"] = _iso(d.get("created_at"))
        reviews.append(d)
    return reviews


def get_top10_places(list_type: str, country: str = None):
    """Worldwide, by-country, or by-category top10 rankings
    (city/country/category/rating/place_information)."""
    db = get_db()
    if list_type == "country":
        query = {"list_type": "country", "country": {"$regex": f"^{re.escape(country or '')}$", "$options": "i"}}
    elif list_type == "category":
        query = {"list_type": "category"}
    else:
        query = {"list_type": "worldwide"}
    return [_strip_id(d) for d in db.top10_places.find(query).sort("rank", ASCENDING)]


def get_top10_countries():
    """Distinct countries that have a by-country top10 list, for building UI filters."""
    db = get_db()
    return sorted(db.top10_places.distinct("country", {"list_type": "country"}))


def _flag_emoji(iso2: str) -> str:
    """Flag emoji from an ISO 3166-1 alpha-2 code (pair of Unicode regional
    indicator symbols) — avoids hand-typing 197 flag glyphs."""
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in iso2.upper())


# All 197 countries (193 UN members + Vatican City + Palestine + Kosovo +
# Taiwan) backing the "Search by country" directory: (name, ISO 3166-1
# alpha-2 code, UNESCO World Heritage Site count, most-visited rank).
# Site counts from UNESCO/World Heritage Centre statistics; the most-visited
# ranking (1-20) is from UNWTO international tourist arrivals — both pulled
# from public sources rather than guessed. Countries outside the top 20 get
# most_visited_rank=None.
WORLD_COUNTRIES = [
    # ── Africa (54) ──
    ("Algeria", "DZ", 7, None), ("Angola", "AO", 1, None), ("Benin", "BJ", 3, None),
    ("Botswana", "BW", 2, None), ("Burkina Faso", "BF", 4, None), ("Burundi", "BI", 0, None),
    ("Cabo Verde", "CV", 1, None), ("Cameroon", "CM", 3, None), ("Central African Republic", "CF", 2, None),
    ("Chad", "TD", 2, None), ("Comoros", "KM", 0, None), ("Democratic Republic of the Congo", "CD", 5, None),
    ("Republic of the Congo", "CG", 2, None), ("Djibouti", "DJ", 0, None), ("Egypt", "EG", 7, None),
    ("Equatorial Guinea", "GQ", 0, None), ("Eritrea", "ER", 1, None), ("Eswatini", "SZ", 0, None),
    ("Ethiopia", "ET", 12, None), ("Gabon", "GA", 2, None), ("Gambia", "GM", 2, None),
    ("Ghana", "GH", 2, None), ("Guinea", "GN", 1, None), ("Guinea-Bissau", "GW", 1, None),
    ("Ivory Coast", "CI", 5, None), ("Kenya", "KE", 8, None), ("Lesotho", "LS", 1, None),
    ("Liberia", "LR", 0, None), ("Libya", "LY", 5, None), ("Madagascar", "MG", 3, None),
    ("Malawi", "MW", 3, None), ("Mali", "ML", 4, None), ("Mauritania", "MR", 2, None),
    ("Mauritius", "MU", 2, None), ("Morocco", "MA", 9, None), ("Mozambique", "MZ", 2, None),
    ("Namibia", "NA", 2, None), ("Niger", "NE", 3, None), ("Nigeria", "NG", 2, None),
    ("Rwanda", "RW", 2, None), ("São Tomé and Príncipe", "ST", 0, None), ("Senegal", "SN", 7, None),
    ("Seychelles", "SC", 2, None), ("Sierra Leone", "SL", 1, None), ("Somalia", "SO", 0, None),
    ("South Africa", "ZA", 12, None), ("South Sudan", "SS", 0, None), ("Sudan", "SD", 3, None),
    ("Tanzania", "TZ", 7, None), ("Togo", "TG", 1, None), ("Tunisia", "TN", 9, None),
    ("Uganda", "UG", 3, None), ("Zambia", "ZM", 1, None), ("Zimbabwe", "ZW", 5, None),

    # ── Americas (35) ──
    ("Antigua and Barbuda", "AG", 1, None), ("Argentina", "AR", 12, None), ("Bahamas", "BS", 0, None),
    ("Barbados", "BB", 1, None), ("Belize", "BZ", 1, None), ("Bolivia", "BO", 7, None),
    ("Brazil", "BR", 25, None), ("Canada", "CA", 22, 20), ("Chile", "CL", 7, None),
    ("Colombia", "CO", 9, None), ("Costa Rica", "CR", 4, None), ("Cuba", "CU", 9, None),
    ("Dominica", "DM", 1, None), ("Dominican Republic", "DO", 1, None), ("Ecuador", "EC", 5, None),
    ("El Salvador", "SV", 1, None), ("Grenada", "GD", 0, None), ("Guatemala", "GT", 4, None),
    ("Guyana", "GY", 0, None), ("Haiti", "HT", 1, None), ("Honduras", "HN", 2, None),
    ("Jamaica", "JM", 2, None), ("Mexico", "MX", 36, 6), ("Nicaragua", "NI", 2, None),
    ("Panama", "PA", 5, None), ("Paraguay", "PY", 1, None), ("Peru", "PE", 13, None),
    ("Saint Kitts and Nevis", "KN", 1, None), ("Saint Lucia", "LC", 1, None),
    ("Saint Vincent and the Grenadines", "VC", 0, None), ("Suriname", "SR", 3, None),
    ("Trinidad and Tobago", "TT", 0, None), ("United States", "US", 26, 3), ("Uruguay", "UY", 3, None),
    ("Venezuela", "VE", 3, None),

    # ── Asia (49, incl. Palestine + Taiwan) ──
    ("Afghanistan", "AF", 2, None), ("Armenia", "AM", 3, None), ("Azerbaijan", "AZ", 5, None),
    ("Bahrain", "BH", 3, None), ("Bangladesh", "BD", 3, None), ("Bhutan", "BT", 0, None),
    ("Brunei", "BN", 0, None), ("Cambodia", "KH", 5, None), ("China", "CN", 60, 19),
    ("Cyprus", "CY", 3, None), ("Georgia", "GE", 4, None), ("India", "IN", 43, 18),
    ("Indonesia", "ID", 10, None), ("Iran", "IR", 29, None), ("Iraq", "IQ", 6, None),
    ("Israel", "IL", 9, None), ("Japan", "JP", 26, 10), ("Jordan", "JO", 7, None),
    ("Kazakhstan", "KZ", 6, None), ("Kuwait", "KW", 0, None), ("Kyrgyzstan", "KG", 3, None),
    ("Laos", "LA", 4, None), ("Lebanon", "LB", 6, None), ("Malaysia", "MY", 6, 16),
    ("Maldives", "MV", 0, None), ("Mongolia", "MN", 6, None), ("Myanmar", "MM", 2, None),
    ("Nepal", "NP", 4, None), ("North Korea", "KP", 3, None), ("Oman", "OM", 5, None),
    ("Pakistan", "PK", 6, None), ("Palestine", "PS", 5, None), ("Philippines", "PH", 6, None),
    ("Qatar", "QA", 1, None), ("Saudi Arabia", "SA", 8, 14), ("Singapore", "SG", 1, None),
    ("South Korea", "KR", 17, None), ("Sri Lanka", "LK", 8, None), ("Syria", "SY", 6, None),
    ("Taiwan", "TW", 0, None), ("Tajikistan", "TJ", 5, None), ("Thailand", "TH", 8, 11),
    ("Timor-Leste", "TL", 0, None), ("Turkey", "TR", 22, 4), ("Turkmenistan", "TM", 5, None),
    ("United Arab Emirates", "AE", 2, 13), ("Uzbekistan", "UZ", 7, None), ("Vietnam", "VN", 9, None),
    ("Yemen", "YE", 5, None),

    # ── Europe (45, incl. Kosovo + Vatican City) ──
    ("Albania", "AL", 4, None), ("Andorra", "AD", 1, None), ("Austria", "AT", 12, 12),
    ("Belarus", "BY", 4, None), ("Belgium", "BE", 16, None), ("Bosnia and Herzegovina", "BA", 5, None),
    ("Bulgaria", "BG", 10, None), ("Croatia", "HR", 10, None), ("Czech Republic", "CZ", 17, None),
    ("Denmark", "DK", 12, None), ("Estonia", "EE", 2, None), ("Finland", "FI", 7, None),
    ("France", "FR", 54, 1), ("Germany", "DE", 54, 8), ("Greece", "GR", 20, 9),
    ("Hungary", "HU", 8, None), ("Iceland", "IS", 3, None), ("Ireland", "IE", 2, None),
    ("Italy", "IT", 61, 5), ("Kosovo", "XK", 0, None), ("Latvia", "LV", 3, None),
    ("Liechtenstein", "LI", 0, None), ("Lithuania", "LT", 5, None), ("Luxembourg", "LU", 1, None),
    ("Malta", "MT", 3, None), ("Moldova", "MD", 1, None), ("Monaco", "MC", 0, None),
    ("Montenegro", "ME", 4, None), ("Netherlands", "NL", 13, 17), ("North Macedonia", "MK", 2, None),
    ("Norway", "NO", 8, None), ("Poland", "PL", 17, None), ("Portugal", "PT", 17, 15),
    ("Romania", "RO", 11, None), ("Russia", "RU", 33, None), ("San Marino", "SM", 1, None),
    ("Serbia", "RS", 5, None), ("Slovakia", "SK", 8, None), ("Slovenia", "SI", 5, None),
    ("Spain", "ES", 50, 2), ("Sweden", "SE", 15, None), ("Switzerland", "CH", 13, None),
    ("Ukraine", "UA", 8, None), ("United Kingdom", "GB", 35, 7), ("Vatican City", "VA", 2, None),

    # ── Oceania (14) ──
    ("Australia", "AU", 21, None), ("Fiji", "FJ", 1, None), ("Kiribati", "KI", 1, None),
    ("Marshall Islands", "MH", 1, None), ("Micronesia", "FM", 1, None), ("Nauru", "NR", 0, None),
    ("New Zealand", "NZ", 3, None), ("Palau", "PW", 1, None), ("Papua New Guinea", "PG", 1, None),
    ("Samoa", "WS", 0, None), ("Solomon Islands", "SB", 1, None), ("Tonga", "TO", 0, None),
    ("Tuvalu", "TV", 0, None), ("Vanuatu", "VU", 1, None),
]


def get_top10_country_directory():
    """All 197 countries with flag, UNESCO World Heritage Site count, and
    most-visited rank — backs the "Search by country" directory in the UI.
    The frontend shows only the most-visited subset by default and searches
    across the full list as the user types."""
    return [
        {
            "country": name,
            "flag": _flag_emoji(iso2),
            "sites": sites,
            "sub": f"{sites} UNESCO World Heritage Site{'s' if sites != 1 else ''}",
            "most_visited_rank": rank,
        }
        for name, iso2, sites, rank in WORLD_COUNTRIES
    ]


def search_places(query: str, limit: int = 6):
    """Autocomplete lookup: matches on name or subtitle, name-prefix matches first."""
    db = get_db()
    pattern = re.escape(query)
    matches = list(db.places.find({
        "$or": [{"name": {"$regex": pattern, "$options": "i"}},
                {"subtitle": {"$regex": pattern, "$options": "i"}}],
    }))
    prefix_re = re.compile(f"^{pattern}", re.IGNORECASE)
    matches.sort(key=lambda d: (not prefix_re.match(d["name"]), d["name"]))
    return [_strip_id(d) for d in matches[:limit]]


def get_mt_place(name: str):
    """Look up a place's details by the value typed into the search bar, e.g.
    'Santiago, Chile' or 'Galapagos Islands'. Matches on 'city, country' first, then city alone."""
    db = get_db()
    name = name.strip()
    city_guess = name.split(",")[0].strip()
    doc = db.mt_places.find_one({
        "$or": [
            {"$expr": {"$eq": [{"$concat": ["$city", ", ", "$country"]}, name]}},
            {"city": {"$regex": f"^{re.escape(name)}$", "$options": "i"}},
        ],
    })
    if not doc:
        doc = db.mt_places.find_one({"city": {"$regex": f"^{re.escape(city_guess)}$", "$options": "i"}})
    return _strip_id(doc) if doc else None


def save_full_plan(title: str, from_name: str, from_lat: float, from_lng: float,
                    to_name: str, to_lat: float, to_lng: float,
                    user_id: int = 1111, user_email: str = "test@gmail.com",
                    distance_km: int = None, duration_text: str = None,
                    transport_mode: str = None, places: list = None, notes: str = ""):
    """Saves a plan built from a live search: the real from/to points and the
    Google Maps markers (tourist places, as {name, latitude, longitude}) found
    along that route — associated with the given user."""
    db = get_db()
    new_id = _next_id(db, "saved_plans")
    db.saved_plans.insert_one({
        "id": new_id, "user_id": user_id, "user_email": user_email, "title": title, "notes": notes,
        "from_name": from_name, "from_lat": from_lat, "from_lng": from_lng,
        "to_name": to_name, "to_lat": to_lat, "to_lng": to_lng,
        "distance_km": distance_km, "duration_text": duration_text,
        "transport_mode": transport_mode, "stops_snapshot": places or [],
        "created_at": datetime.now(timezone.utc),
    })
    return new_id


def get_plans_for_user(user_id: int):
    db = get_db()
    plans = []
    for d in db.saved_plans.find({"user_id": user_id}).sort("created_at", -1):
        d = _strip_id(d)
        d["created_at"] = _iso(d.get("created_at"))
        d["stops_snapshot"] = d.get("stops_snapshot") or []
        plans.append(d)
    return plans


def get_or_create_google_user(google_sub: str, email: str, name: str, picture: str):
    """Looks up a user by their Google account id, creating one on first
    sign-in. Refreshes name/picture on every login since those can change
    on the Google side."""
    db = get_db()
    existing = db.users.find_one({"google_sub": google_sub})
    if existing:
        db.users.update_one(
            {"google_sub": google_sub},
            {"$set": {"name": name, "email": email, "picture": picture}},
        )
        existing["name"], existing["email"], existing["picture"] = name, email, picture
        return _strip_id(existing)

    new_id = _next_id(db, "users")
    doc = {
        "id": new_id, "google_sub": google_sub, "email": email,
        "name": name, "picture": picture,
        "created_at": datetime.now(timezone.utc),
    }
    db.users.insert_one(doc)
    return _strip_id(doc)


def get_user_by_id(user_id: int):
    db = get_db()
    doc = db.users.find_one({"id": user_id})
    if not doc:
        return None
    doc = _strip_id(doc)
    doc["created_at"] = _iso(doc.get("created_at"))
    return doc


if __name__ == "__main__":
    init_db()
    seed_db()
    print("\n📊  Stops in DB:")
    for s in get_all_stops():
        print(f"  [{s['id']}] {s['emoji']} {s['name']}  ⭐ {s['rating']}  ({s['review_count']} reviews)")
    print("\n💬  Reviews sample:")
    for r in get_reviews(1):
        print(f"  {r['initials']} — {r['rating']}★  \"{r['comment'][:60]}...\"")
