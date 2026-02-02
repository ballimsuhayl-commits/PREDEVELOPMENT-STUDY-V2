import type { CheckRequest, CheckResponse, HistoryRow } from './types'

export async function apiCheck(payload: CheckRequest): Promise<CheckResponse> {
  const r = await fetch('/api/check', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  })
  if (!r.ok) {
    const t = await r.text()
    throw new Error(t || `HTTP ${r.status}`)
  }
  return r.json()
}

export async function apiHistory(limit = 50): Promise<HistoryRow[]> {
  const r = await fetch(`/api/history?limit=${limit}`)
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return r.json()
}
