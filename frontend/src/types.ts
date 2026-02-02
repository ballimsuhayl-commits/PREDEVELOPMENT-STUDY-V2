export type CheckRequest = {
  address: string
  country?: string
  lat?: number
  lon?: number
}

export type LayerHit = {
  layer: string
  match?: string | null
  reason?: string | null
}

export type CheckResponse = {
  ok: boolean
  input_address: string
  normalized_address?: string | null
  lat?: number | null
  lon?: number | null
  municipality?: string | null
  nsc_region?: string | null
  mpr_region?: string | null
  custom_region?: string | null
  hits: LayerHit[]
  message?: string | null
}

export type HistoryRow = {
  id: number
  created_at: string
  input_address: string
  normalized_address?: string | null
  lat?: number | null
  lon?: number | null
  municipality?: string | null
  nsc_region?: string | null
  mpr_region?: string | null
  custom_region?: string | null
  ok: boolean
  message?: string | null
}
