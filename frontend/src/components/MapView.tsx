import { MapContainer, TileLayer, Marker, Popup } from 'react-leaflet'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'

// Fix default marker icons in bundlers
import markerIcon2x from 'leaflet/dist/images/marker-icon-2x.png'
import markerIcon from 'leaflet/dist/images/marker-icon.png'
import markerShadow from 'leaflet/dist/images/marker-shadow.png'

delete (L.Icon.Default.prototype as any)._getIconUrl
L.Icon.Default.mergeOptions({
  iconRetinaUrl: markerIcon2x,
  iconUrl: markerIcon,
  shadowUrl: markerShadow
})

export function MapView(props: {
  lat: number
  lon: number
  label?: string
}) {
  const { lat, lon, label } = props
  return (
    <MapContainer center={[lat, lon]} zoom={14} style={{ height: 360, width: '100%', borderRadius: 12 }}>
      <TileLayer
        attribution="&copy; OpenStreetMap contributors"
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      <Marker position={[lat, lon]}>
        <Popup>
          {label || 'Location'}<br />
          {lat.toFixed(6)}, {lon.toFixed(6)}
        </Popup>
      </Marker>
    </MapContainer>
  )
}
