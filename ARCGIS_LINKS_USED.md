# ArcGIS links used in this package

These are the ArcGIS REST endpoints that were shared in this chat and are wired into the fetch-and-cache workflow.

## eThekwini municipality boundary (FeatureServer)
- Hosted service root:
  - https://gis.durban.gov.za/server/rest/services/Hosted/Police_bounds_ethekwini/FeatureServer
- Layer (used by fetcher):
  - https://gis.durban.gov.za/server/rest/services/Hosted/Police_bounds_ethekwini/FeatureServer/0

## NSC (North/South/Central) candidate (MapServer)
- Layer (used by fetcher):
  - https://gis.durban.gov.za/server/rest/services/WebViewers/External_Cadastral_Services_Publisher/MapServer/28

## MPR (Municipal Planning Regions) candidate (MapServer)
- MapServer layers list (discovery):
  - https://gis.durban.gov.za/server/rest/services/WebViewers/Infrastructural_Services_Publisher/MapServer/layers
- Layer (used by fetcher):
  - https://gis.durban.gov.za/server/rest/services/WebViewers/Infrastructural_Services_Publisher/MapServer/59

## Notes
- The fetcher writes cached copies into `backend/data/*` so the app can run fully offline after one refresh.
- If any of these endpoints change, update `backend/.env` (or environment variables) and re-run the fetcher.