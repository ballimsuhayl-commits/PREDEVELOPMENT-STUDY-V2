import React from "react";
import type { CheckResult } from "../types";

export function ResultCard({ result }: { result: CheckResult | null }) {
  if (!result) return null;

  const v = (x: any) => (x === null || x === undefined || x === "" ? "—" : String(x));

  return (
    <div className="card">
      <div className="cardTitle">Result</div>
      <div className="kv">
        <div className="k">OK</div><div className="v">{result.ok ? "Yes" : "No"}</div>
        <div className="k">Municipality</div><div className="v">{v(result.municipality)}</div>
        <div className="k">Province</div><div className="v">{v(result.province)}</div>
        <div className="k">NSC</div><div className="v">{v(result.nsc_region)}</div>
        <div className="k">MPR</div><div className="v">{v(result.mpr_region)}</div>
        <div className="k">Custom</div><div className="v">{v(result.custom_region)}</div>
        <div className="k">Lat, Lon</div><div className="v">{v(result.lat)}, {v(result.lon)}</div>
        <div className="k">Reason</div><div className="v">{v(result.reason)}</div>
      </div>
    </div>
  );
}
