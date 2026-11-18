#!/usr/bin/env python3
"""FluSurv-NET laboratory-confirmed influenza hospitalization rates (CDC RESP-NET).

Remote : data.cdc.gov dataset kvib-3txy "RESP-NET Rates and Clinical Data" (weekly, Friday)
Files  : flusurv.csv -- every FluSurv-NET row (all ages / sex / race strata, weekly + cumulative
         rates, clinical percentages); COVID-NET and RSV-NET rows are not downloaded.
Version: the dataset's rowsUpdatedAt timestamp.

Coverage: FluSurv-NET is a catchment network (~9% of the US population in ~13-15 states:
CA CO CT GA MD MI MN NM NY NC OH OR TN UT WA). "Overall" = the whole network and is shown under
"US" in the dashboard -- it is not a national estimate. Outside the season (Oct-Apr) recent seasons
report year-round, older ones do not.

    python pull/pull_flusurv.py --check
    python pull/pull_flusurv.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pandas as pd  # noqa: E402

from fludash.common import Signal, Source, socrata_csv, socrata_remote, to_location  # noqa: E402

DATASET = "kvib-3txy"
AGES = {"hosp_rate": "Overall", "hosp_rate_65plus": "65+ yr", "hosp_rate_0_4": "0-4 yr"}


class FluSurv(Source):
    key = "flusurv"
    label = "FluSurv-NET"
    description = ("Weekly laboratory-confirmed influenza hospitalization rate per 100,000 in the "
                   "FluSurv-NET catchment (RESP-NET, data.cdc.gov kvib-3txy). 'US' = network overall.")
    homepage = "https://data.cdc.gov/d/kvib-3txy"
    cadence = "weekly (Friday)"
    signals = [
        Signal("hosp_rate", "FluSurv-NET rate", "Per 100,000 per week",
               "Observed weekly rate, all ages, catchment population.", default=True),
        Signal("hosp_rate_65plus", "FluSurv-NET rate 65+", "Per 100,000 per week",
               "Observed weekly rate, ages 65+."),
        Signal("hosp_rate_0_4", "FluSurv-NET rate 0-4", "Per 100,000 per week",
               "Observed weekly rate, ages 0-4."),
    ]

    def remote(self):
        return socrata_remote(DATASET)

    def fetch(self, snap_dir, remote):
        n = socrata_csv(DATASET, snap_dir / "flusurv.csv",
                        where="surveillance_network = 'FluSurv-NET'")
        return {"dataset": DATASET, "rows": n, "filter": "surveillance_network = 'FluSurv-NET'"}

    def harmonize(self, snapshots):
        snap = snapshots[-1]
        d = pd.read_csv(snap.path / "flusurv.csv")
        d = d[(d["date_type"] == "Week Ending Date") & (d["data_type"] == "Weekly Rate")
              & (d["rate_type"] == "Observed") & (d["sex"] == "All") & (d["race"] == "All")]
        out = []
        for sig, age in AGES.items():
            a = d[d["age_category"] == age]
            out.append(pd.DataFrame({
                "date": pd.to_datetime(a["date"]),
                "location": to_location(a["state"].replace({"Overall": "US"})),
                "signal": sig, "value": pd.to_numeric(a["estimate"], errors="coerce")}))
        df = pd.concat(out, ignore_index=True)
        df["snapshot"] = snap.name
        return df


SOURCE = FluSurv

if __name__ == "__main__":
    sys.exit(FluSurv().cli())
