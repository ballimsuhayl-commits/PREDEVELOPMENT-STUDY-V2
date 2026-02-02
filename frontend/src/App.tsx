import { useEffect, useMemo, useState } from 'react'
import type { CheckResponse, HistoryRow } from './types'
import { apiCheck, apiHistory } from './api'
import { MapView } from './components/MapView'

function Card(props: { title: string; children: any }) {
  return (
    <div style={{
      background: 'white',
      border: '1px solid #e5e7eb',
      borderRadius: 14,
      padding: 16,
      boxShadow: '0 1px 2px rgba(0,0,0,0.05)'
    }}>
      <div style={{ fontWeight: 700, marginBottom: 10 }}>{props.title}</div>
      {props.children}
    </div>
  )
}

function Row(props: { label: string; value?: any }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, padding: '6px 0' }}>
      <div style={{ color: '#6b7280' }}>{props.label}</div>
      <div style={{ fontWeight: 600, textAlign: 'right' }}>{props.value ?? '—'}</div>
    </div>
  )
}

export default function App() {
  const [address, setAddress] = useState('')
  const [country, setCountry] = useState('South Africa')
  const [lat, setLat] = useState('')
  const [lon, setLon] = useState('')
  const [result, setResult] = useState<CheckResponse | null>(null)
  const [history, setHistory] = useState<HistoryRow[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const canUseCoords = useMemo(() => {
    const la = Number(lat)
    const lo = Number(lon)
    return Number.isFinite(la) && Number.isFinite(lo)
  }, [lat, lon])

  async function refreshHistory() {
    try {
      const rows = await apiHistory(50)
      setHistory(rows)
    } catch {
      // ignore
    }
  }

  useEffect(() => {
    refreshHistory()
  }, [])

  async function onCheck() {
    setBusy(true)
    setError(null)
    setResult(null)
    try {
      const payload: any = { address: address.trim(), country: country.trim() || undefined }
      if (canUseCoords) {
        payload.lat = Number(lat)
        payload.lon = Number(lon)
      }
      const r = await apiCheck(payload)
      setResult(r)
      refreshHistory()
    } catch (e: any) {
      setError(e?.message || 'Failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={{
      minHeight: '100vh',
      background: '#f3f4f6',
      padding: 20,
      fontFamily: 'ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial'
    }}>
      <div style={{ maxWidth: 1100, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: 16 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 12 }}>
          <div>
            <div style={{ fontSize: 22, fontWeight: 800 }}>Municipality Address Check</div>
            <div style={{ color: '#6b7280', marginTop: 2 }}>Geocode (optional) + polygon classification + audit log</div>
          </div>
          <div style={{ color: '#6b7280', fontSize: 12 }}>Backend: <code>/api</code></div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
          <Card title="Check">
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              <label>
                <div style={{ fontSize: 12, color: '#6b7280', marginBottom: 4 }}>Address</div>
                <input
                  value={address}
                  onChange={(e) => setAddress(e.target.value)}
                  placeholder="e.g. 166 KE Masinga Rd, Durban"
                  style={{ width: '100%', padding: 10, borderRadius: 10, border: '1px solid #d1d5db' }}
                />
              </label>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                <label>
                  <div style={{ fontSize: 12, color: '#6b7280', marginBottom: 4 }}>Country (optional)</div>
                  <input
                    value={country}
                    onChange={(e) => setCountry(e.target.value)}
                    placeholder="South Africa"
                    style={{ width: '100%', padding: 10, borderRadius: 10, border: '1px solid #d1d5db' }}
                  />
                </label>
                <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'flex-end' }}>
                  <button
                    onClick={onCheck}
                    disabled={busy || !address.trim()}
                    style={{
                      padding: '10px 14px',
                      borderRadius: 10,
                      border: '1px solid #111827',
                      background: busy ? '#111827' : '#111827',
                      color: 'white',
                      cursor: busy ? 'not-allowed' : 'pointer',
                      width: '100%'
                    }}
                  >
                    {busy ? 'Checking…' : 'Check'}
                  </button>
                </div>
              </div>

              <div style={{ color: '#6b7280', fontSize: 12 }}>
                If geocoding is disabled on the backend, fill lat/lon below.
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
                <label>
                  <div style={{ fontSize: 12, color: '#6b7280', marginBottom: 4 }}>Latitude</div>
                  <input
                    value={lat}
                    onChange={(e) => setLat(e.target.value)}
                    placeholder="-29.8587"
                    style={{ width: '100%', padding: 10, borderRadius: 10, border: '1px solid #d1d5db' }}
                  />
                </label>
                <label>
                  <div style={{ fontSize: 12, color: '#6b7280', marginBottom: 4 }}>Longitude</div>
                  <input
                    value={lon}
                    onChange={(e) => setLon(e.target.value)}
                    placeholder="31.0218"
                    style={{ width: '100%', padding: 10, borderRadius: 10, border: '1px solid #d1d5db' }}
                  />
                </label>
              </div>

              {error ? (
                <div style={{ background: '#fee2e2', border: '1px solid #fecaca', padding: 10, borderRadius: 10 }}>
                  <div style={{ fontWeight: 700, marginBottom: 2 }}>Error</div>
                  <div style={{ fontSize: 13 }}>{error}</div>
                </div>
              ) : null}
            </div>
          </Card>

          <Card title="Result">
            {!result ? (
              <div style={{ color: '#6b7280' }}>Run a check to see the classification.</div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                <div style={{
                  padding: 10,
                  borderRadius: 10,
                  background: result.ok ? '#dcfce7' : '#fee2e2',
                  border: result.ok ? '1px solid #bbf7d0' : '1px solid #fecaca'
                }}>
                  <div style={{ fontWeight: 800 }}>{result.ok ? 'OK' : 'Not matched'}</div>
                  <div style={{ fontSize: 13, color: '#374151' }}>{result.message}</div>
                </div>

                <Row label="Municipality" value={result.municipality} />
                <Row label="NSC" value={result.nsc_region} />
                <Row label="MPR" value={result.mpr_region} />
                <Row label="Custom" value={result.custom_region} />
                <Row label="Lat" value={result.lat?.toFixed(6)} />
                <Row label="Lon" value={result.lon?.toFixed(6)} />

                {typeof result.lat === 'number' && typeof result.lon === 'number' ? (
                  <MapView
                    lat={result.lat}
                    lon={result.lon}
                    label={result.municipality || result.nsc_region || result.mpr_region || 'Location'}
                  />
                ) : null}
              </div>
            )}
          </Card>
        </div>

        <Card title="History (latest 50)">
          {history.length === 0 ? (
            <div style={{ color: '#6b7280' }}>No history yet.</div>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr style={{ textAlign: 'left', fontSize: 12, color: '#6b7280' }}>
                    <th style={{ padding: 8 }}>Time (UTC)</th>
                    <th style={{ padding: 8 }}>Address</th>
                    <th style={{ padding: 8 }}>Municipality</th>
                    <th style={{ padding: 8 }}>NSC</th>
                    <th style={{ padding: 8 }}>MPR</th>
                    <th style={{ padding: 8 }}>OK</th>
                  </tr>
                </thead>
                <tbody>
                  {history.map((h) => (
                    <tr key={h.id} style={{ borderTop: '1px solid #e5e7eb', fontSize: 13 }}>
                      <td style={{ padding: 8, whiteSpace: 'nowrap' }}>{new Date(h.created_at).toISOString()}</td>
                      <td style={{ padding: 8 }}>{h.input_address}</td>
                      <td style={{ padding: 8 }}>{h.municipality || '—'}</td>
                      <td style={{ padding: 8 }}>{h.nsc_region || '—'}</td>
                      <td style={{ padding: 8 }}>{h.mpr_region || '—'}</td>
                      <td style={{ padding: 8 }}>{h.ok ? '✓' : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>
    </div>
  )
}
