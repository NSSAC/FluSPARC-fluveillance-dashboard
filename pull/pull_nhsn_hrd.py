#!/usr/bin/env python3
"""NHSN Weekly Hospital Respiratory Data (HRD), preliminary release, from data.cdc.gov.

Remote : data.cdc.gov dataset mpgq-jmmr ("... (Preliminary)"; Wednesday release, the one FluSight
         uses). The Friday "final" release is ua7e-t2fy -- set config.json nhsn_hrd.dataset to switch.
Files  : hrd.csv -- every column, every jurisdiction (states, territories, HHS regions, USA),
         machine field names (e.g. totalconfflunewadm = "Total Influenza Admissions").
Version: the dataset's rowsUpdatedAt timestamp.

Adds what the FluSight target does not carry: history back to Oct 2020, pediatric admissions,
% of inpatient beds occupied by flu patients, and the % of hospitals reporting (data quality).

    python pull/pull_nhsn_hrd.py --check
    python pull/pull_nhsn_hrd.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pandas as pd  # noqa: E402

from fludash.common import Signal, Source, socrata_csv, socrata_remote, to_location  # noqa: E402

DATASET = "mpgq-jmmr"

FIELDS = {  # harmonized signal -> HRD field (percent fields are already 0-100)
    "flu_admissions": "totalconfflunewadm",
    "flu_admissions_ped": "totalconfflunewadmped",
    "pct_inpatient_beds_flu": "pctconffluinptbeds",
    "pct_hosp_reporting_flu": "totalconfflunewadmperchosprep",
}


class NhsnHrd(Source):
    key = "nhsn_hrd"
    label = "NHSN HRD"
    description = ("NHSN Weekly Hospital Respiratory Data, preliminary jurisdiction release "
                   "(data.cdc.gov mpgq-jmmr): influenza admissions, bed occupancy, reporting.")
    homepage = "https://data.cdc.gov/d/mpgq-jmmr"
    cadence = "weekly (Wednesday, preliminary)"
    signals = [
        Signal("flu_admissions", "HRD flu admissions", "Admissions per week",
               "Total Influenza Admissions (same quantity as the FluSight target).", default=True),
        Signal("flu_admissions_ped", "HRD pediatric flu admissions", "Admissions per week",
               "Total Pediatric Influenza Admissions."),
        Signal("pct_inpatient_beds_flu", "% inpatient beds with flu", "% of inpatient beds",
               "Percent of inpatient beds occupied by influenza patients."),
        Signal("pct_hosp_reporting_flu", "% hospitals reporting", "% of hospitals reporting",
               "Percent of hospitals reporting influenza admissions (data completeness)."),
    ]

    def remote(self):
        return socrata_remote(self.opt("dataset", DATASET))

    def fetch(self, snap_dir, remote):
        ds = self.opt("dataset", DATASET)
        n = socrata_csv(ds, snap_dir / "hrd.csv", order="weekendingdate,jurisdiction")
        return {"dataset": ds, "rows": n}

    def harmonize(self, snapshots):
        snap = snapshots[-1]
        cols = ["weekendingdate", "jurisdiction"] + list(FIELDS.values())
        d = pd.read_csv(snap.path / "hrd.csv", usecols=lambda c: c in cols)
        d["date"] = pd.to_datetime(d["weekendingdate"]).dt.normalize()
        d["location"] = to_location(d["jurisdiction"])       # drops HHS regions / territories w/o code
        out = []
        for sig, field in FIELDS.items():
            if field in d:
                out.append(pd.DataFrame({"date": d["date"], "location": d["location"], "signal": sig,
                                         "value": pd.to_numeric(d[field], errors="coerce")}))
        df = pd.concat(out, ignore_index=True)
        df["snapshot"] = snap.name
        return df


SOURCE = NhsnHrd

if __name__ == "__main__":
    sys.exit(NhsnHrd().cli())
