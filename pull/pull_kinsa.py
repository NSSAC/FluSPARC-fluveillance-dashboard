#!/usr/bin/env python3
"""Kinsa smart-thermometer illness signals (Kinsa Insights API v1).  LICENSED DATA -- see README.

Remote : https://apiv2.kinsainsights.com/api/v1  (POST /auth/login, POST /signal); daily data.
         Same calls as forecast/Kinsa/kinsa_api_pull.py, made non-interactive and incremental.
Files  : kinsa_<start>_<end>.csv -- national + 49 states (no AK/HI), signal types COUGH_COLD_FLU,
         SORE_THROAT, FEVER, COUGH, NASAL, the API's columns plus `date`.
Version: the download date (the API has no release metadata), so `--check` reports "due" once a day.
         Each pull re-requests the last --overlap days (default 28) so revised days are refreshed.

History: the team's existing store (/project/bii_nssac/data/kinsa-health, history back to 2017)
can be linked instead of re-downloaded:
    python pull/pull_kinsa.py --link-store /project/bii_nssac/data/kinsa-health
which symlinks its kinsa_data_*.csv into data/raw/kinsa/_store/. Where files overlap, the newest
file wins (our snapshots by snapshot date, store files by modification time).

Credentials (first that works): env KINSA_EMAIL + KINSA_PASSWORD; ~/.config/fludash/kinsa.json
{"email": "...", "password": "..."} (chmod 600); otherwise an interactive prompt.

    python pull/pull_kinsa.py --check
    python pull/pull_kinsa.py                    # incremental
    python pull/pull_kinsa.py --start 20250701   # explicit window start
"""
from __future__ import annotations

import datetime as dt
import getpass
import json
import os
import stat
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pandas as pd  # noqa: E402

from fludash.common import Remote, Signal, Source, http_get, log, to_location, week_ending  # noqa: E402

API = "https://apiv2.kinsainsights.com/api/v1"
SIGNAL_TYPES = ["COUGH_COLD_FLU", "SORE_THROAT", "FEVER", "COUGH", "NASAL"]
# same list as /project/bii_nssac/data/kinsa-health/state_codes.pkl (Kinsa has no AK / HI)
STATES = ["AL", "AR", "AZ", "CA", "CO", "CT", "DC", "DE", "FL", "GA", "IA", "ID", "IL", "IN", "KS",
          "KY", "LA", "MA", "MD", "ME", "MI", "MN", "MO", "MS", "MT", "NC", "ND", "NE", "NH", "NJ",
          "NM", "NV", "NY", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VA", "VT",
          "WA", "WI", "WV", "WY"]
COHORT = "0-100_age_wght"
HARMONIZE = {"ccf_pct_ill": "COUGH_COLD_FLU", "fever_pct_ill": "FEVER", "sore_throat_pct_ill": "SORE_THROAT",
             "cough_pct_ill": "COUGH", "nasal_pct_ill": "NASAL"}
CRED_FILE = Path.home() / ".config" / "fludash" / "kinsa.json"


class KinsaClient:
    def __init__(self):
        self.headers = {"Content-Type": "application/json", "Accept": "application/json"}

    def _post(self, path, payload, timeout=60):
        body = http_get(f"{API}/{path}", data=json.dumps(payload).encode(), headers=self.headers,
                        timeout=timeout)
        return json.loads(body)

    def login(self, email, password):
        r = self._post("auth/login", {"email": email, "password": password})
        tok = r.get("token") or r.get("access_token")
        if not tok:
            raise RuntimeError(f"Kinsa login returned no token (keys: {list(r)})")
        self.headers["Authorization"] = f"Bearer {tok}"

    def signal(self, region_type, region_id=None, start=None, end=None):
        p = {"signal_type": SIGNAL_TYPES, "region_type": [region_type], "start_date": start,
             "end_date": end}
        if region_id:
            p["region_id"] = region_id
        return pd.DataFrame(self._post("signal", p, timeout=120).get("data", []))


def credentials():
    e, p = os.environ.get("KINSA_EMAIL"), os.environ.get("KINSA_PASSWORD")
    if e and p:
        return e, p
    if CRED_FILE.exists():
        if CRED_FILE.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO):
            log(f"warning: {CRED_FILE} is readable by others; run chmod 600 {CRED_FILE}")
        c = json.loads(CRED_FILE.read_text())
        return c["email"], c["password"]
    if sys.stdin.isatty():
        print("Kinsa Insights API login", file=sys.stderr)
        return input("email: "), getpass.getpass("password: ")
    raise RuntimeError("no Kinsa credentials: set KINSA_EMAIL/KINSA_PASSWORD or create "
                       f"{CRED_FILE} (see pull/pull_kinsa.py docstring)")


class Kinsa(Source):
    key = "kinsa"
    label = "Kinsa"
    description = ("Kinsa smart-thermometer network: % of users reporting illness, age-weighted, "
                   "daily -> weekly mean over complete Sun-Sat weeks. Licensed data.")
    homepage = "https://www.kinsahealth.co/"
    cadence = "daily"
    restricted = True
    signals = [
        Signal("ccf_pct_ill", "Kinsa cough/cold/flu % ill", "% ill (Kinsa)",
               "COUGH_COLD_FLU percent_ill: Kinsa's composite of the respiratory symptoms (sits above the "
               "highest single symptom on most days); cohort 0-100_age_wght, weekly mean.", default=True),
        Signal("fever_pct_ill", "Kinsa fever % ill", "% ill (Kinsa)",
               "FEVER percent_ill, cohort 0-100_age_wght, weekly mean."),
        Signal("sore_throat_pct_ill", "Kinsa sore throat % ill", "% ill (Kinsa)",
               "SORE_THROAT percent_ill, cohort 0-100_age_wght, weekly mean."),
        Signal("cough_pct_ill", "Kinsa cough % ill", "% ill (Kinsa)",
               "COUGH percent_ill, cohort 0-100_age_wght, weekly mean."),
        Signal("nasal_pct_ill", "Kinsa nasal % ill", "% ill (Kinsa)",
               "NASAL (congestion / runny nose) percent_ill, cohort 0-100_age_wght, weekly mean."),
    ]

    def add_arguments(self, ap):
        ap.add_argument("--start", help="window start YYYYMMDD (default: last local day - overlap)")
        ap.add_argument("--overlap", type=int, help="days re-requested before the last local day "
                        "(default 28)")
        ap.add_argument("--link-store", metavar="PATH",
                        help="symlink an existing Kinsa CSV store into data/raw/kinsa/_store and exit")

    # -- files on disk ----------------------------------------------------------------------
    def files(self):
        """[(as_of, path)] oldest first: linked store files, then our snapshots."""
        out = []
        store = self.raw_dir / "_store"
        if store.exists():
            for f in store.glob("*.csv"):
                out.append((dt.datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d"), f))
        for s in self.snapshots():
            for f in s.path.glob("*.csv"):
                out.append((s.name, f))
        return sorted(out, key=lambda t: (t[0], t[1].name))

    def last_local_day(self):
        last = None
        for s in self.snapshots():
            e = s.meta.get("data_end")
            last = max(last, e) if last and e else (e or last)
        if not last:
            for _, f in self.files():
                if f.parent.name == "_store":
                    d = pd.read_csv(f, usecols=["yyyymmdd"], engine="pyarrow")["yyyymmdd"]
                    m = pd.to_datetime(d).max().strftime("%Y-%m-%d")
                    last = max(last, m) if last else m
        return last

    def link_store(self, path):
        store = self.raw_dir / "_store"
        store.mkdir(parents=True, exist_ok=True)
        n = 0
        for f in sorted(Path(path).glob("kinsa_data_*.csv")):
            link = store / f.name
            if link.is_symlink() or link.exists():
                link.unlink()
            link.symlink_to(f.resolve())
            n += 1
        (store / "_SOURCE.txt").write_text(f"symlinks to {Path(path).resolve()} "
                                           f"(linked {dt.date.today()})\n")
        log(f"[kinsa] linked {n} file(s) from {path} into {store}")

    # -- Source interface ----------------------------------------------------------------------
    def remote(self):
        today = dt.date.today().isoformat()
        last = self.last_local_day()
        return Remote(version=f"download-{today}", updated=dt.datetime.now(dt.timezone.utc).isoformat(
            timespec="seconds"), detail=f"no release metadata; local data through {last or 'none'}")

    def fetch(self, snap_dir, remote):
        today = dt.date.today()
        start = self.opt("start")
        if not start:
            last = self.last_local_day()
            s0 = (pd.Timestamp(last) - pd.Timedelta(days=int(self.opt("overlap", 28)))) if last \
                else pd.Timestamp("2025-07-01")
            start = s0.strftime("%Y%m%d")
        end = today.strftime("%Y%m%d")
        api = KinsaClient()
        api.login(*credentials())
        frames = [api.signal("national", start=start, end=end)]
        for sc in self.opt("states", STATES):
            frames.append(api.signal("state", region_id=sc, start=start, end=end))
        df = pd.concat(frames, ignore_index=True)
        df["date"] = pd.to_datetime(df["yyyymmdd"])
        f = snap_dir / f"kinsa_{start}_{end}.csv"
        df.to_csv(f, index=False)
        log(f"[kinsa] {len(df):,} rows {df['date'].min():%Y-%m-%d} .. {df['date'].max():%Y-%m-%d}")
        return {"window": [start, end], "rows": len(df),
                "data_end": df["date"].max().strftime("%Y-%m-%d")}

    def harmonize(self, snapshots):
        parts = []
        for k, (as_of, f) in enumerate(self.files()):
            d = pd.read_csv(f, usecols=["region_id", "signal_type", "cohort", "yyyymmdd",
                                        "percent_ill"], engine="pyarrow")
            d = d[(d["cohort"] == COHORT) & d["signal_type"].isin(HARMONIZE.values())]
            parts.append(d.assign(order=k, snapshot=as_of if f.parent.name != "_store"
                                  else f"store:{f.name}"))
        if not parts:
            return pd.DataFrame(columns=["date", "location", "signal", "value", "snapshot"])
        d = pd.concat(parts, ignore_index=True)
        d["day"] = pd.to_datetime(d["yyyymmdd"])
        d = d.sort_values("order").drop_duplicates(["region_id", "signal_type", "day"], keep="last")
        d["date"] = week_ending(d["day"])
        g = d.groupby(["region_id", "signal_type", "date"]).agg(
            value=("percent_ill", "mean"), days=("percent_ill", "count"),
            snapshot=("snapshot", "last")).reset_index()
        g = g[g["days"] == 7]                                   # complete weeks only
        g["location"] = to_location(g["region_id"])
        g["signal"] = g["signal_type"].map({v: k for k, v in HARMONIZE.items()})
        return g[["date", "location", "signal", "value", "snapshot"]]

    def cli(self, argv=None):
        import argparse
        pre = argparse.ArgumentParser(add_help=False)
        pre.add_argument("--link-store")
        a, _ = pre.parse_known_args(argv)
        if a.link_store:
            self.link_store(a.link_store)
            return 0
        return super().cli(argv)


SOURCE = Kinsa

if __name__ == "__main__":
    sys.exit(Kinsa().cli())
