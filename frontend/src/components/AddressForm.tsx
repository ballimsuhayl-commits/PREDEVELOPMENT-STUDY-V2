import React, { useMemo, useState } from "react";
import type { CheckRequest } from "../types";

export function AddressForm({ onSubmit, busy }: { onSubmit: (v: CheckRequest) => void; busy: boolean }) {
  const [address, setAddress] = useState("");
  const [lat, setLat] = useState("");
  const [lon, setLon] = useState("");

  const latNum = useMemo(() => (lat.trim() === "" ? null : Number(lat)), [lat]);
  const lonNum = useMemo(() => (lon.trim() === "" ? null : Number(lon)), [lon]);
  const validLatLon = useMemo(() => {
    if (lat.trim() === "" && lon.trim() === "") return true;
    if (!Number.isFinite(latNum) || !Number.isFinite(lonNum)) return false;
    if (latNum === null || lonNum === null) return false;
    return latNum >= -90 && latNum <= 90 && lonNum >= -180 && lonNum <= 180;
  }, [lat, lon, latNum, lonNum]);

  return (
    <form
      className="card"
      onSubmit={(e) => {
        e.preventDefault();
        if (!address.trim()) return;
        if (!validLatLon) return;
        onSubmit({ address: address.trim(), lat: lat.trim() === "" ? null : latNum!, lon: lon.trim() === "" ? null : lonNum! });
      }}
    >
      <div className="row">
        <label className="label">
          Address
          <input className="input" value={address} onChange={(e) => setAddress(e.target.value)} placeholder="e.g. 1 Walnut Rd, Durban" />
        </label>
      </div>
      <div className="row2">
        <label className="label">
          Lat (optional)
          <input className="input" value={lat} onChange={(e) => setLat(e.target.value)} placeholder="-29.8587" />
        </label>
        <label className="label">
          Lon (optional)
          <input className="input" value={lon} onChange={(e) => setLon(e.target.value)} placeholder="31.0218" />
        </label>
        <button className="btn" type="submit" disabled={busy || !address.trim() || !validLatLon}>
          {busy ? "Checking..." : "Check"}
        </button>
      </div>
      {!validLatLon ? <div className="warn">Lat/Lon must be numeric (lat −90..90, lon −180..180)</div> : null}
      <div className="hint">
        Tip: provide lat/lon to bypass geocoding for maximum accuracy.
      </div>
    </form>
  );
}
