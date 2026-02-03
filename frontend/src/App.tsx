import React, { useEffect, useState } from "react";
import { apiCheck, apiHistory } from "./api";
import type { CheckLog, CheckRequest, CheckResult } from "./types";
import { AddressForm } from "./components/AddressForm";
import { ResultCard } from "./components/ResultCard";
import { HistoryTable } from "./components/HistoryTable";
import { MapView } from "./components/MapView";

export default function App() {
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<CheckResult | null>(null);
  const [history, setHistory] = useState<CheckLog[]>([]);
  const [error, setError] = useState<string | null>(null);

  async function refreshHistory() {
    try {
      const rows = await apiHistory(25);
      setHistory(rows);
    } catch {
      // ignore
    }
  }

  useEffect(() => {
    refreshHistory();
  }, []);

  async function onSubmit(payload: CheckRequest) {
    setError(null);
    setBusy(true);
    try {
      const res = await apiCheck(payload);
      setResult(res);
      await refreshHistory();
    } catch (e: any) {
      setError(e?.message || "Request failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="container">
      <div className="header">
        <div>
          <h1 className="h1">Municipality Address Check</h1>
          <div className="sub">eThekwini: Municipality + NSC + MPR + Custom Regions (offline cache + optional live refresh)</div>
        </div>
      </div>

      <div className="grid">
        <div>
          <AddressForm busy={busy} onSubmit={onSubmit} />
          {error ? <div className="card" style={{ borderColor: "#ff4d4d" }}>{error}</div> : null}
          <ResultCard result={result} />
        </div>
        <div>
          <MapView result={result} />
          <HistoryTable rows={history} />
        </div>
      </div>
    </div>
  );
}
