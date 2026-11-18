#!/usr/bin/env python3
"""FluSight hub target data: the NHSN influenza admissions (and NSSP flu ED %) exactly as the
CDC FluSight forecast hub publishes them as forecast targets.

Remote : github.com/cdcepi/FluSight-forecast-hub, folder target-data/ (updated Wednesdays)
Files  : target-hospital-admissions.csv  (date, location, location_name, value, weekly_rate)
         target-ed-visits-prop.csv       (date, location_name, value = proportion, location)
         time-series.csv                 (all as_of vintages, ~100 MB; only with --with-vintages)
Version: the latest commit touching target-data/ (its SHA is stored in _meta.json).

    python pull/pull_flusight.py --check          # is GitHub ahead of us?
    python pull/pull_flusight.py                  # pull if new
    python pull/pull_flusight.py --from-clone /project/biocomplexity/aniadiga/forecast/gits/FluSight-forecast-hub
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pandas as pd  # noqa: E402

from fludash.common import Remote, Signal, Source, download, http_json, to_location  # noqa: E402

REPO = "cdcepi/FluSight-forecast-hub"
FILES = ["target-hospital-admissions.csv", "target-ed-visits-prop.csv"]
VINTAGES = "time-series.csv"


class FluSight(Source):
    key = "flusight"
    label = "FluSight targets"
    description = ("NHSN weekly influenza hospital admissions and NSSP % of ED visits for influenza, "
                   "as published by the CDC FluSight forecast hub (target-data/).")
    homepage = f"https://github.com/{REPO}/tree/main/target-data"
    cadence = "weekly (Wednesday)"
    signals = [
        Signal("nhsn_flu_admissions", "NHSN flu admissions", "Admissions per week",
               "Total new influenza hospital admissions (NHSN HRD), FluSight target.", default=True),
        Signal("nhsn_flu_rate", "NHSN flu admissions / 100k", "Per 100,000 per week",
               "Admissions per 100,000 population (FluSight locations.csv population)."),
        Signal("nssp_flu_ed_pct", "NSSP flu ED % (FluSight)", "% of ED visits",
               "Percent of ED visits with influenza diagnosed, FluSight target (unsmoothed)."),
    ]

    def add_arguments(self, ap):
        ap.add_argument("--from-clone", metavar="PATH",
                        help="copy target-data from a local git clone instead of GitHub "
                             "(config.json: flusight.from_clone)")
        ap.add_argument("--with-vintages", action="store_true", default=None,
                        help=f"also store {VINTAGES} (every as_of vintage, ~100 MB)")

    def _clone(self):
        c = self.opt("from_clone")
        return Path(c) if c else None

    def remote(self) -> Remote:
        clone = self._clone()
        if clone:
            out = subprocess.run(["git", "-c", "safe.directory=*", "-C", str(clone), "log", "-1",
                                  "--format=%H %cI", "--", "target-data"],
                                 capture_output=True, text=True, check=True).stdout.split()
            return Remote(version=out[0], updated=out[1], detail=f"clone {clone} @ {out[0][:8]}")
        c = http_json(f"https://api.github.com/repos/{REPO}/commits",
                      params={"path": "target-data", "per_page": 1}, timeout=60)[0]
        return Remote(version=c["sha"], updated=c["commit"]["committer"]["date"],
                      detail=f"GitHub {REPO}@{c['sha'][:8]}: {c['commit']['message'][:60]}")

    def fetch(self, snap_dir: Path, remote: Remote) -> dict:
        files = FILES + ([VINTAGES] if self.opt("with_vintages", False) else [])
        clone = self._clone()
        for f in files:
            if clone:
                shutil.copy2(clone / "target-data" / f, snap_dir / f)
            else:
                download(f"https://raw.githubusercontent.com/{REPO}/{remote.version}/target-data/{f}",
                         snap_dir / f)
        return {"origin": str(clone) if clone else f"github:{REPO}", "commit": remote.version}

    def harmonize(self, snapshots):
        snap = snapshots[-1]          # the hub file already holds the latest value for every week
        h = pd.read_csv(snap.path / "target-hospital-admissions.csv", dtype={"location": str},
                        parse_dates=["date"])
        h["location"] = to_location(h["location"])
        out = [
            h.assign(signal="nhsn_flu_admissions")[["date", "location", "signal", "value"]],
            h.assign(signal="nhsn_flu_rate", value=h["weekly_rate"])[["date", "location", "signal", "value"]],
        ]
        ed = snap.path / "target-ed-visits-prop.csv"
        if ed.exists():
            e = pd.read_csv(ed, dtype={"location": str}, parse_dates=["date"])
            e["location"] = to_location(e["location"])
            out.append(e.assign(signal="nssp_flu_ed_pct", value=100 * e["value"])
                       [["date", "location", "signal", "value"]])
        df = pd.concat(out, ignore_index=True)
        df["snapshot"] = snap.name
        return df


SOURCE = FluSight

if __name__ == "__main__":
    sys.exit(FluSight().cli())
