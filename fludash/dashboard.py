"""Build the single-file HTML dashboard from data/harmonized/.

The page is self-contained (plotly.js-basic is inlined from fludash/vendor/), so it opens from the
file system, Open OnDemand, or JupyterLab ("Trust HTML") with no network access.
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import math
from pathlib import Path

import pandas as pd

from .common import HARMONIZED, ROOT, locations, log

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "dashboard_template.html"
PLOTLY = HERE / "vendor" / "plotly-basic-2.35.2.min.js"
ASSETS = HERE / "assets" / "web"          # small copies made by fludash/assets/make_web_assets.py
DEFAULT_SINCE = "2010-08-01"


def _round(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    if v == 0:
        return 0
    return float(f"{v:.4g}")


def load_harmonized() -> pd.DataFrame:
    pq = HARMONIZED / "surveillance_weekly.parquet"
    if pq.exists():
        try:
            return pd.read_parquet(pq)
        except ImportError:
            pass
    return pd.read_csv(HARMONIZED / "surveillance_weekly.csv", dtype={"location": str},
                       parse_dates=["date"])


def payload(public: bool = False, since: str = DEFAULT_SINCE) -> dict:
    df = load_harmonized()
    manifest = json.loads((HARMONIZED / "manifest.json").read_text())
    cat = pd.read_csv(HARMONIZED / "signals.csv")
    srcs = [s for s in manifest["sources"].values() if not (public and s.get("restricted"))]
    keep = {s["key"] for s in srcs}
    df = df[df["source"].isin(keep) & (df["date"] >= pd.Timestamp(since))].copy()
    df["date"] = pd.to_datetime(df["date"])

    t0 = df["date"].min()
    t1 = df["date"].max()
    df["i"] = ((df["date"] - t0).dt.days // 7).astype(int)
    df["sid"] = df["source"] + "." + df["signal"]

    series, last = {}, {}
    for (abbr, sid), g in df.groupby(["abbr", "sid"], sort=True):
        g = g.sort_values("i")
        i0, i1 = int(g["i"].iloc[0]), int(g["i"].iloc[-1])
        vals = [None] * (i1 - i0 + 1)
        for i, v in zip(g["i"], g["value"]):
            vals[int(i) - i0] = _round(float(v))
        series.setdefault(abbr, {})[sid] = [i0, vals]
        last[sid] = max(last.get(sid, ""), f"{g['date'].iloc[-1]:%Y-%m-%d}")

    loc = locations()
    present = set(df["abbr"].dropna())
    locs = [{"code": r.abbreviation, "name": "United States" if r.abbreviation == "US" else
             r.location_name} for r in loc.itertuples() if r.abbreviation in present]
    locs = sorted(locs, key=lambda d: (d["code"] != "US", d["code"]))

    sources = []
    for slot, s in enumerate(srcs):
        sigs = cat[cat["source"] == s["key"]]
        sources.append({
            "key": s["key"], "label": s["label"], "description": s["description"],
            "homepage": s["homepage"], "cadence": s["cadence"], "restricted": s["restricted"],
            "snapshot": s.get("snapshot"), "remote_updated": s.get("remote_updated"),
            "fetched_at": s.get("fetched_at"), "error": s.get("error"), "slot": slot,
            "signals": [{"key": r.signal, "label": r.label, "unit": r.unit,
                         "description": r.description, "default": bool(r.default),
                         "last_week": last.get(f"{s['key']}.{r.signal}")}
                        for r in sigs.itertuples() if f"{s['key']}.{r.signal}" in last]})
    return {"generated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "harmonized_at": manifest.get("built_at"), "public": public,
            "t0": f"{t0:%Y-%m-%d}", "nweeks": int((t1 - t0).days // 7 + 1),
            "data_through": f"{t1:%Y-%m-%d}", "locations": locs, "sources": sources,
            "series": series}


def _img(name: str, tag: str) -> str:
    """Inline a small PNG from fludash/assets/web as a data: URI (empty if the file is missing)."""
    f = ASSETS / name
    if not f.exists():
        return ""
    return tag.format("data:image/png;base64," + base64.b64encode(f.read_bytes()).decode())


def build(public: bool = False, out: str | None = None, since: str = DEFAULT_SINCE) -> Path:
    data = payload(public=public, since=since)
    out = Path(out) if out else ROOT / "dashboard" / ("index-public.html" if public else "index.html")
    out.parent.mkdir(parents=True, exist_ok=True)
    html = TEMPLATE.read_text()
    js = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    plotly = PLOTLY.read_text().replace("</script", "<\\/script")
    html = html.replace("/*__PLOTLY__*/", plotly, 1).replace("/*__DATA__*/null", js, 1)
    html = html.replace("<!--__LOGO__-->", _img("logo-header.png", '<img class="logo" src="{}" alt="FluSPARC" height="32">'), 1)
    html = html.replace("<!--__ICON__-->", _img("favicon.png", '<link rel="icon" type="image/png" href="{}">'), 1)
    out.write_text(html)
    log(f"dashboard: {out} ({out.stat().st_size / 1e6:.1f} MB, {len(data['locations'])} locations, "
        f"{sum(len(s['signals']) for s in data['sources'])} signals"
        f"{', public (licensed sources removed)' if public else ''})")
    return out
