# Municipality Address Check

Full-stack app (FastAPI + React) that classifies an address/point into:
- Municipality boundary
- NSC (North/South/Central) region (via Zoning scheme layer)
- MPR planning region
- Optional custom regions

## Two modes ("DO BOTH")

### 1) Offline mode (default)
The backend loads cached boundary polygons from:
- `backend/data/municipalities/`
- `backend/data/nsc_regions/`
- `backend/data/mpr_regions/`
- `backend/data/custom_regions/`

Supported formats: GeoJSON (*.geojson) and ESRI JSON (*.json with `features[].geometry.rings`).

### 2) Live refresh (updates the offline cache)
Use the CLI fetcher to download official ArcGIS layers into the cache folders ("freeze" the data for offline use).

First set these environment variables (examples shown; use your actual ArcGIS layer URLs):

- `MAC_ETHEKWINI_MUNICIPAL_LAYER_URL`
- `MAC_ETHEKWINI_NSC_LAYER_URL`
- `MAC_ETHEKWINI_MPR_LAYER_URL`

Then run the fetcher:

```bash
cd backend
python -m venv .venv
# Windows PowerShell:
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m scripts.fetch_datasets
```

Or refresh the cache via the admin API (only enabled if you set `MAC_ADMIN_TOKEN`):

```bash
curl -X POST "http://localhost:8000/api/admin/refresh-datasets?which=all" \
  -H "X-Admin-Token: <YOUR_ADMIN_TOKEN>"
```

## Run (dev)

### Backend
```bash
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```

Open: http://localhost:5173

## API
- `POST /api/check`
- `GET /api/history?limit=25`
- `POST /api/admin/refresh-datasets?which=all|municipality|nsc|mpr` (protected with `X-Admin-Token`, disabled if `MAC_ADMIN_TOKEN` is empty)

## Notes

- For truly offline operation, set `MAC_ALLOW_NOMINATIM=false` (otherwise geocoding requires internet).
- The app reads all *.geojson and *.json files in each data folder.
