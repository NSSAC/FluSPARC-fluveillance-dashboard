#!/usr/bin/env python3
"""NSSP emergency department visits (CDC National Syndromic Surveillance Program).

Remote : data.cdc.gov dataset rdmq-nq56 "NSSP Emergency Department Visit Trajectories by State and
         Sub State Regions - COVID-19, Flu, RSV, Combined" (weekly, Fri; from 2022-10).
Files  : nssp_state.csv -- rows with county == "All", i.e. the 50 states + DC + "United States".
         Pass --with-counties to also save the full county/HSA table (~650k rows).
         ari_state.csv, ari_nation.csv -- % of ED visits for acute respiratory illness (ARI, CDC's
         broad respiratory metric that replaced ILI-style syndromes) from the Delphi Epidata V5
         mirror of NSSP (source=nssp, signal=pct_ed_visits_ari); data.cdc.gov only publishes ARI
         nationally or as a categorical level. Delphi's ARI has lagged CDC's flu series by ~4 weeks.
         (data.cdc.gov's percent_visits_combined stopped at 2024-09-28, so it is not harmonized.)
Version: data.cdc.gov dataUpdatedAt + Delphi nssp latest_update (either changing triggers a pull).

    python pull/pull_nssp.py --check
    python pull/pull_nssp.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pandas as pd  # noqa: E402

from fludash.common import (Remote, Signal, Source, download, http_json, socrata_csv,  # noqa: E402
                            socrata_remote, to_location)

DATASET = "rdmq-nq56"
DELPHI = "https://delphi.cmu.edu/epidata/v5"

FIELDS = {
    "flu_ed_pct": "percent_visits_influenza",
    "flu_ed_pct_smoothed": "percent_visits_smoothed_1",      # = percent_visits_smoothed_influenza
}


class Nssp(Source):
    key = "nssp"
    label = "NSSP ED visits"
    description = ("Percent of emergency department visits for influenza (CDC NSSP, data.cdc.gov "
                   "rdmq-nq56) and for any acute respiratory illness (ARI, via Delphi), state and US.")
    homepage = "https://data.cdc.gov/d/rdmq-nq56"
    cadence = "weekly (Friday)"
    signals = [
        Signal("flu_ed_pct", "NSSP flu ED %", "% of ED visits",
               "Percent of ED visits with diagnosed influenza.", default=True),
        Signal("flu_ed_pct_smoothed", "NSSP flu ED % (smoothed)", "% of ED visits",
               "CDC-smoothed percent of ED visits for influenza."),
        Signal("ari_ed_pct", "NSSP ARI ED % (all resp. illness)", "% of ED visits (ARI)",
               "Percent of ED visits for acute respiratory illness of any cause (Delphi V5 mirror)."),
    ]

    def add_arguments(self, ap):
        ap.add_argument("--with-counties", action="store_true", default=None,
                        help="also save the full county / HSA table")

    def remote(self):
        r = socrata_remote(DATASET)
        try:
            m = http_json(f"{DELPHI}/metadata/", params={"source": "nssp"}, timeout=60)["nssp"]
            return Remote(version=f"{r.version}|delphi@{m['latest_update']}",
                          updated=max(r.updated, str(m["latest_update"]).replace("Z", "+00:00")),
                          detail=r.detail)
        except Exception:          # Delphi down: still track the CDC dataset
            return r

    def fetch(self, snap_dir, remote):
        n = socrata_csv(DATASET, snap_dir / "nssp_state.csv", where="county = 'All'",
                        order="week_end,geography")
        extra = {"dataset": DATASET, "rows": n, "filter": "county = 'All'"}
        for geo in ("state", "nation"):
            download(f"{DELPHI}/snapshot/", snap_dir / f"ari_{geo}.csv",
                     params={"source": "nssp", "signal": "pct_ed_visits_ari", "geo_type": geo,
                             **({"api_key": os.environ["DELPHI_EPIDATA_KEY"]}
                                if os.environ.get("DELPHI_EPIDATA_KEY") else {})})
        if self.opt("with_counties", False):
            extra["rows_counties"] = socrata_csv(DATASET, snap_dir / "nssp_county.csv",
                                                 where="county != 'All'", order="week_end,fips")
        return extra

    def harmonize(self, snapshots):
        snap = snapshots[-1]
        d = pd.read_csv(snap.path / "nssp_state.csv")
        d["date"] = pd.to_datetime(d["week_end"]).dt.normalize()
        d["location"] = to_location(d["geography"])
        out = [pd.DataFrame({"date": d["date"], "location": d["location"], "signal": sig,
                             "value": pd.to_numeric(d[f], errors="coerce")})
               for sig, f in FIELDS.items() if f in d]
        for geo in ("state", "nation"):
            f = snap.path / f"ari_{geo}.csv"
            if f.exists():
                a = pd.read_csv(f)
                out.append(pd.DataFrame({"date": pd.to_datetime(a["reference_time"]),
                                         "location": to_location(a["geo_value"]), "signal": "ari_ed_pct",
                                         "value": pd.to_numeric(a["value"], errors="coerce")}))
        df = pd.concat(out, ignore_index=True)
        df["snapshot"] = snap.name
        return df


SOURCE = Nssp

if __name__ == "__main__":
    sys.exit(Nssp().cli())
