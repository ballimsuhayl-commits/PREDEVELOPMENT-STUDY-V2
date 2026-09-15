# eThekwini Property Development Intelligence — Final App

Production-oriented single-file FastAPI application for eThekwini/Durban property and pre-development screening.

## Included

- Address or coordinate input.
- Approved municipal parcel retrieval.
- Current eThekwini zoning lookup.
- Municipal road-layer analysis with **1, 2, 3 or more road frontages**.
- Separate street / side / rear setbacks **measured inward from the cadastral site boundary**.
- Buildable-envelope geometry and editable 3D extrusion.
- Parcel corner beacon display.
- Beacon/ground-height screening from a municipal beacon elevation attribute where available; otherwise the nearest 2 m contour is shown and explicitly marked approximate.
- Mapped servitude intersection screening.
- SDF land-use screening.
- Building-footprint count and coverage.
- Suburb spatial lookup and Suburb Overview table join.
- PDF report export, source provenance and planning/legal qualification.
- Optional local Roads GeoJSON override for deterministic frontage analysis.

## Current eThekwini layer IDs

The canonical `WebViewers/EXT_Cadastral/MapServer` layer IDs used by this app are:

| Dataset | Layer |
|---|---:|
| Address points | 1 |
| Roads | 3 |
| Contours 2 m | 6 |
| Beacons | 13 |
| Servitudes | 14 |
| Parcels | 17 |
| Suburbs | 19 |
| Zoning | **28** |
| SDF Landuse 2021 | 29 |

**Important:** layer 26 is Inner City LAP; it is not the zoning layer.

## Install

```bash
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python property_system.py
```

Then open `http://localhost:5000`.

## Use the attached Roads GeoJSON locally

The app queries the eThekwini Roads service by default. To force the project export `Roads_4522439532045033586.geojson`:

```powershell
$env:ROAD_GEOJSON="C:\path\Roads_4522439532045033586.geojson"
python property_system.py
```

The local road file is optional. If it is absent or cannot be read, the municipal ArcGIS road layer is used.

## Tests

```bash
pip install pytest
pytest -q test_property_system.py
```

Regression coverage includes:

- ArcGIS polygon/ring conversion with holes;
- one street frontage;
- two street frontages on a corner site;
- three street frontages;
- no-road behavior (no invented frontage);
- setback distance measured from the original cadastral site boundary;
- significant parcel-corner extraction;
- nearest-2 m-contour beacon height screening.

## Data and legal status

This is a feasibility and due-diligence screening tool. Public GIS layers can be stale, generalized or legally non-determinative. The application does **not** represent its output as a zoning certificate, surveyed beacon RL, cadastral survey, title search, registered-servitude determination, approved-plan record or municipal approval. Confirm those matters from the legally authoritative source before relying on the output for design, purchase or statutory submission.
