#!/usr/bin/env python3
"""ILINet outpatient influenza-like illness (CDC FluView), via the Delphi Epidata V5 API.

Remote : https://delphi.cmu.edu/epidata/v5/snapshot/?source=fluview_ilinet  (weekly, Friday)
         NOTE: Delphi's legacy /epidata/fluview/ endpoint returns nothing after 2026-09-22;
         the V5 API is its replacement (docs: cmu-delphi.github.io/delphi-epidata/api/v5.html).
Files  : ili_state.csv   unweighted % ILI, states (+ PR, VI, DC, NYC split), since 2010
         ili_nation.csv  unweighted % ILI, US
         wili_nation.csv population-weighted % ILI, US, since 1997
Version: Delphi's latest_update for fluview_ilinet.

Anonymous use is rate-limited (3 snapshot requests/min, 60/h). If you have a Delphi key, export
DELPHI_EPIDATA_KEY and it is sent as api_key=...

    python pull/pull_ilinet.py --check
    python pull/pull_ilinet.py
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pandas as pd  # noqa: E402

from fludash.common import Remote, Signal, Source, download, http_json, to_location  # noqa: E402

V5 = "https://delphi.cmu.edu/epidata/v5"
PULLS = [("ili", "state"), ("ili", "nation"), ("wili", "nation")]


def _key():
    k = os.environ.get("DELPHI_EPIDATA_KEY")
    return {"api_key": k} if k else {}


class IliNet(Source):
    key = "ilinet"
    label = "ILINet"
    description = ("CDC ILINet: percent of outpatient visits for influenza-like illness. "
                   "States are unweighted (% ILI); national is also given population-weighted (wILI).")
    homepage = "https://www.cdc.gov/fluview/"
    cadence = "weekly (Friday)"
    signals = [
        Signal("ili_pct", "ILINet % ILI", "% of outpatient visits",
               "Unweighted % of outpatient visits for ILI (states and US).", default=True),
        Signal("wili_pct", "ILINet % wILI (US)", "% of outpatient visits",
               "Population-weighted % ILI, national only."),
    ]

    def remote(self):
        m = http_json(f"{V5}/metadata/", params={"source": "fluview_ilinet", **_key()}, timeout=60)
        m = m["fluview_ilinet"]
        latest = m["reference_time_range"]["latest"]
        return Remote(version=m["latest_update"], updated=m["latest_update"],
                      detail=f"Delphi fluview_ilinet, data through week ending {latest}")

    def fetch(self, snap_dir, remote):
        for i, (sig, geo) in enumerate(PULLS):
            if i:
                time.sleep(21)                 # anonymous limit: 3 snapshot calls / minute
            download(f"{V5}/snapshot/", snap_dir / f"{sig}_{geo}.csv",
                     params={"source": "fluview_ilinet", "signal": sig, "geo_type": geo, **_key()})
        return {"api": V5, "pulls": [f"{s}/{g}" for s, g in PULLS]}

    def harmonize(self, snapshots):
        snap = snapshots[-1]
        out = []
        for sig, geo in PULLS:
            f = snap.path / f"{sig}_{geo}.csv"
            if not f.exists():
                continue
            d = pd.read_csv(f)
            if "age_group" in d:
                d = d[d["age_group"].fillna("all") == "all"]
            d = d[~d["geo_value"].isin(["nyc", "ny_minus_nyc"])]
            out.append(pd.DataFrame({
                "date": pd.to_datetime(d["reference_time"]),
                "location": to_location(d["geo_value"]),
                "signal": f"{sig}_pct", "value": pd.to_numeric(d["value"], errors="coerce")}))
        df = pd.concat(out, ignore_index=True)
        df["snapshot"] = snap.name
        return df


SOURCE = IliNet

if __name__ == "__main__":
    sys.exit(IliNet().cli())
