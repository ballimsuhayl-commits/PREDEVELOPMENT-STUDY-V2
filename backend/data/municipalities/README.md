# Municipalities

Put municipality boundary polygons here.

Supported formats:
- GeoJSON (*.geojson)
- ESRI JSON (*.json) with `features[].geometry.rings` (ArcGIS REST export)

Expected name field(s) (first match wins):
- `MUNICNAME`, `municname`, `MUNIC_NAME`, `municipality`, `NAME`, `name`

Province is optional, parsed from:
- `PROVINCE`, `province`, `PROVNAME`
