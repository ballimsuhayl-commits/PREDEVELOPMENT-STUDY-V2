import React from "react";
import type { CheckLog } from "../types";

export function HistoryTable({ rows }: { rows: CheckLog[] }) {
  return (
    <div className="card">
      <div className="cardTitle">Recent checks</div>
      <div style={{ overflowX: "auto" }}>
        <table className="table">
          <thead>
            <tr>
              <th>When</th>
              <th>Address</th>
              <th>Municipality</th>
              <th>NSC</th>
              <th>MPR</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={String(r.id)}>
                <td>{String(r.created_at).replace("T", " ").slice(0, 19)}</td>
                <td>{String(r.address || "").slice(0, 80)}</td>
                <td>{r.municipality ?? "—"}</td>
                <td>{r.nsc_region ?? "—"}</td>
                <td>{r.mpr_region ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
