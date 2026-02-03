import React from "react";
import { MapContainer, TileLayer, Marker, Popup } from "react-leaflet";
import L from "leaflet";
import type { CheckResult } from "../types";
import "leaflet/dist/leaflet.css";

// Leaflet default marker icons don't bundle well in Vite; use CDN URLs.
const DefaultIcon = L.icon({
  iconUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png",
  iconRetinaUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png",
  shadowUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png",
  iconSize: [25, 41],
  iconAnchor: [12, 41]
});
L.Marker.prototype.options.icon = DefaultIcon;

export function MapView({ result }: { result: CheckResult | null }) {
  const lat = result?.lat ?? null;
  const lon = result?.lon ?? null;
  if (lat === null || lon === null) return null;

  return (
    <div className="card">
      <div className="cardTitle">Map</div>
      <div style={{ height: 340, borderRadius: 12, overflow: "hidden" }}>
        <MapContainer center={[lat, lon]} zoom={13} style={{ height: "100%", width: "100%" }}>
          <TileLayer
            attribution='&copy; OpenStreetMap contributors'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          <Marker position={[lat, lon]}>
            <Popup>
              <div style={{ fontSize: 12 }}>
                <div><b>Municipality:</b> {String(result?.municipality ?? "—")}</div>
                <div><b>NSC:</b> {String(result?.nsc_region ?? "—")}</div>
                <div><b>MPR:</b> {String(result?.mpr_region ?? "—")}</div>
                <div><b>Custom:</b> {String(result?.custom_region ?? "—")}</div>
              </div>
            </Popup>
          </Marker>
        </MapContainer>
      </div>
    </div>
  );
}
