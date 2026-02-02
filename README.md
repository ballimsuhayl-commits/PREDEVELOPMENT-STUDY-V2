# PREDEVELOPMENT-STUDY-V2 — Municipality Address Check

Full-stack app to:

1) Geocode an address (optional — you can also supply lat/lon)
2) Classify the point by polygon layers:
   - Municipality boundary
   - NSC regions (North / South / Central)
   - MPR regions (municipal planning regions)
   - Custom regions (optional)
3) Log every query to a local SQLite database.

## Folder structure

```
municipality-address-check/
  backend/   (FastAPI + SQLite + boundary loader)
  frontend/  (React + Vite)
```

## Data (important)

Put boundary files here (GeoJSON or ESRI JSON):

* `backend/data/municipalities/`
* `backend/data/nsc_regions/`
* `backend/data/mpr_regions/`
* `backend/data/custom_regions/`

Each layer must contain Polygon or MultiPolygon in **EPSG:4326** (WGS84 lon/lat).

### Quick dataset fetch

If your machine has internet, you can fetch the public eThekwini municipal boundary using:

```bash
cd backend
python -m scripts.fetch_datasets
```

This downloads the municipal boundary into `backend/data/municipalities/`.
NSC/MPR datasets vary by source; if you have the FeatureServer layer URLs, paste them into the script config.

## Run locally (dev)

### Backend

```bash
cd backend
python -m venv .venv
./.venv/Scripts/activate   # Windows PowerShell: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open the UI at `http://localhost:5173`.

## API

* `POST /api/check` — { address, country?, lat?, lon? }
* `GET  /api/history?limit=50`
* `GET  /api/health`
