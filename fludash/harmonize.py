"""Bring every source's latest raw snapshot(s) into one long weekly table.

Outputs in data/harmonized/:
  surveillance_weekly.csv(.parquet)  one row per (source, signal, location, week)
      date           week-ending Saturday (MMWR week)       mmwr_year, mmwr_week, season
      location       FluSight code ('US', '01', ... '72')    abbr, location_name
      source, signal, value, unit                            snapshot = raw folder it came from
  signals.csv        catalog: source, signal, label, unit, description, default
  manifest.json      per source: snapshot used, remote update time, rows, weeks, locations
"""
from __future__ import annotations

import datetime as dt
import json

import pandas as pd

from .common import HARMONIZED, locations, log, mmwr_week, season_of

COLUMNS = ["date", "mmwr_year", "mmwr_week", "season", "location", "abbr", "location_name",
           "source", "signal", "value", "unit", "snapshot"]


def _one(src) -> pd.DataFrame | None:
    snaps = src.snapshots()
    has_files = bool(snaps) or (src.key == "kinsa" and any(True for _ in src.files()))
    if not has_files:
        log(f"[{src.key}] no local data yet -- run: python pull/pull_{src.key}.py")
        return None
    df = src.harmonize(snaps)
    n0 = len(df)
    df = df.dropna(subset=["location", "value", "date"]).copy()
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    bad = df["date"].dt.dayofweek != 5
    if bad.any():
        raise ValueError(f"[{src.key}] {bad.sum()} rows are not week-ending Saturdays")
    known = {s.key for s in src.signals}
    extra = set(df["signal"]) - known
    if extra:
        raise ValueError(f"[{src.key}] signals not declared in the source: {sorted(extra)}")
    dup = df.duplicated(["signal", "location", "date"], keep="last")
    if dup.any():
        log(f"[{src.key}] dropping {dup.sum()} duplicate rows (kept the last)")
        df = df[~dup]
    df["source"] = src.key
    log(f"[{src.key}] {len(df):,} rows ({n0 - len(df):,} dropped: unmapped location / missing value), "
        f"{df['date'].min():%Y-%m-%d} .. {df['date'].max():%Y-%m-%d}, "
        f"{df['location'].nunique()} locations")
    return df


def harmonize(sources, write: bool = True) -> pd.DataFrame:
    frames, manifest, catalog = [], {}, []
    for src in sources:
        for s in src.signals:
            catalog.append({"source": src.key, "source_label": src.label, "signal": s.key,
                            "label": s.label, "unit": s.unit, "default": s.default,
                            "description": s.description})
        try:
            df = _one(src)
        except Exception as e:
            log(f"[{src.key}] harmonize FAILED: {type(e).__name__}: {e}")
            manifest[src.key] = {**src.info(), "error": f"{type(e).__name__}: {e}"}
            continue
        latest = src.latest()
        manifest[src.key] = {**src.info(),
                             "snapshot": latest.name if latest else None,
                             "remote_updated": latest.meta.get("remote_updated") if latest else None,
                             "fetched_at": latest.meta.get("fetched_at") if latest else None}
        if df is None or df.empty:
            continue
        manifest[src.key].update({
            "rows": int(len(df)), "first_week": f"{df['date'].min():%Y-%m-%d}",
            "last_week": f"{df['date'].max():%Y-%m-%d}", "locations": int(df["location"].nunique()),
            "last_week_by_signal": {k: f"{v:%Y-%m-%d}" for k, v in
                                    df.groupby("signal")["date"].max().items()}})
        frames.append(df)

    cat = pd.DataFrame(catalog)
    if not frames:
        raise SystemExit("nothing to harmonize: no source has local data")
    df = pd.concat(frames, ignore_index=True)
    df = df.join(mmwr_week(df["date"]))
    df["season"] = season_of(df["date"])
    loc = locations().rename(columns={"abbreviation": "abbr"})
    df = df.merge(loc[["location", "abbr", "location_name"]], on="location", how="left")
    df = df.merge(cat[["source", "signal", "unit"]], on=["source", "signal"], how="left")
    df = df[COLUMNS].sort_values(["source", "signal", "location", "date"]).reset_index(drop=True)

    if write:
        HARMONIZED.mkdir(parents=True, exist_ok=True)
        out = df.assign(date=df["date"].dt.strftime("%Y-%m-%d"))
        out.to_csv(HARMONIZED / "surveillance_weekly.csv", index=False)
        try:
            df.to_parquet(HARMONIZED / "surveillance_weekly.parquet", index=False)
        except ImportError:
            log("pyarrow not installed: wrote CSV only")
        cat.to_csv(HARMONIZED / "signals.csv", index=False)
        (HARMONIZED / "manifest.json").write_text(json.dumps(
            {"built_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
             "rows": int(len(df)), "sources": manifest}, indent=2))
        log(f"harmonized: {len(df):,} rows -> {HARMONIZED}")
    return df
