import type { CheckRequest, CheckResult, CheckLog } from "./types";

export async function apiCheck(payload: CheckRequest): Promise<CheckResult> {
  const r = await fetch("/api/check", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  if (!r.ok) throw new Error(await r.text());
  return (await r.json()) as CheckResult;
}

export async function apiHistory(limit = 25): Promise<CheckLog[]> {
  const r = await fetch(`/api/history?limit=${encodeURIComponent(String(limit))}`);
  if (!r.ok) throw new Error(await r.text());
  return (await r.json()) as CheckLog[];
}
