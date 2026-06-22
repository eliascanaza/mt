# exploreMore 🗺️

A travel route explorer web app with a Python/SQLite backend and a single-page HTML/JS frontend.

## Stack

| Layer     | Tech                         |
|-----------|------------------------------|
| Frontend  | Vanilla HTML + JS + MapLibre GL |
| Backend   | Python 3 · Flask             |
| Database  | SQLite (via Python `sqlite3`) |

## Quick start

```bash
# 1. Install dependencies (Python 3.8+)
pip install flask

# 2. Run (auto-creates & seeds the DB on first run)
python app.py

# 3. Open in browser
open http://localhost:5000
```

## Project structure

```
maketrip/
├── app.py          ← Flask server + REST API
├── database.py     ← SQLite schema, seed data & query helpers
├── maketrip.db     ← SQLite file (auto-created on first run)
├── requirements.txt
├── README.md
└── templates/
    └── index.html  ← Full single-page app (HTML + CSS + JS)
```

## REST API

| Method | Endpoint                        | Description               |
|--------|---------------------------------|---------------------------|
| GET    | `/`                             | Serve the HTML app        |
| GET    | `/api/health`                   | Health check + DB status  |
| GET    | `/api/stops`                    | All stops                 |
| GET    | `/api/stops?category=trek`      | Filter stops by category  |
| GET    | `/api/stops/<id>`               | Stop detail + reviews     |
| GET    | `/api/stops/<id>/reviews`       | Reviews for a stop        |
| POST   | `/api/stops/<id>/reviews`       | Add a review              |
| GET    | `/api/routes`                   | Saved routes              |
| GET    | `/api/top10/<type>`             | Top 10 list               |
| GET    | `/api/plans`                    | Saved trip plans          |
| POST   | `/api/plans`                    | Save a new plan           |

### Example: Add a review

```bash
curl -X POST http://localhost:5000/api/stops/1/reviews \
  -H "Content-Type: application/json" \
  -d '{
    "reviewer": "Jane Doe",
    "location": "London, UK",
    "rating": 5,
    "comment": "Absolutely stunning. Worth every step.",
    "visited_at": "April 2024"
  }'
```

### Example: Get Top 10 worldwide

```bash
curl http://localhost:5000/api/top10/worldwide
```

## Database schema

| Table         | Description                              |
|---------------|------------------------------------------|
| `stops`       | Recommended places along a route         |
| `routes`      | Saved routes (from → to)                 |
| `route_stops` | Junction: which stops belong to a route  |
| `reviews`     | User reviews per stop                    |
| `top10`       | Curated top-10 lists                     |
| `saved_plans` | User-saved trip plans                    |
