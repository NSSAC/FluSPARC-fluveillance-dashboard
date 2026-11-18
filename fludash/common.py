"""Shared plumbing for the pull scripts: paths, HTTP, MMWR weeks, locations, and the
`Source` base class that gives every pull script the same snapshot behaviour and CLI.

Raw data layout (one directory per downloaded release, never edited afterwards):

    data/raw/<source>/<snapshot>/<files...>
    data/raw/<source>/<snapshot>/_meta.json     written last; a snapshot without it is ignored

<snapshot> is the date (YYYY-MM-DD) the *remote* data was last updated, so two people pulling the
same release get the same folder name. If the remote changes twice on one day the second one gets
a `_HHMM` suffix.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import io
import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("FLUDASH_DATA", ROOT / "data"))
RAW = DATA / "raw"
HARMONIZED = DATA / "harmonized"
CONFIG_FILE = ROOT / "config.json"
LOCATIONS_FILE = Path(__file__).resolve().parent / "locations.csv"

USER_AGENT = "fludash/0.1 (influenza surveillance ingest; python-urllib)"


# ----------------------------------------------------------------------------- config

def config(section: str | None = None) -> dict:
    """Read config.json (optional). Pull scripts fall back to their own defaults."""
    cfg = {}
    if CONFIG_FILE.exists():
        cfg = json.loads(CONFIG_FILE.read_text())
    return cfg.get(section, {}) if section else cfg


# ----------------------------------------------------------------------------- HTTP

def http_get(url: str, params: dict | None = None, headers: dict | None = None,
             data: bytes | None = None, timeout: int = 300, retries: int = 4) -> bytes:
    """GET (or POST when `data` is given) with retries; 429/5xx back off and retry."""
    if params:
        url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    hdrs = {"User-Agent": USER_AGENT}
    hdrs.update(headers or {})
    last = None
    for attempt in range(retries):
        req = urllib.request.Request(url, data=data, headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            last = e
            if e.code == 429 or e.code >= 500:
                wait = int(e.headers.get("Retry-After") or 0) or 20 * (attempt + 1)
                log(f"  HTTP {e.code} from {urllib.parse.urlsplit(url).netloc}; retrying in {wait}s")
                time.sleep(wait)
                continue
            body = e.read()[:500].decode("utf-8", "replace")
            raise RuntimeError(f"HTTP {e.code} for {url}\n{body}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            last = e
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"giving up on {url}: {last}")


def http_json(url: str, **kw):
    return json.loads(http_get(url, **kw))


def download(url: str, dest: Path, **kw) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(http_get(url, **kw))
    return dest


# ----------------------------------------------------------------------------- dates

def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def week_ending(d) -> pd.Series:
    """Saturday that ends the MMWR (Sun-Sat) week containing each date."""
    d = pd.to_datetime(d)
    return d + pd.to_timedelta((5 - d.dt.dayofweek) % 7, unit="D")


def mmwr_week(sat: pd.Series) -> pd.DataFrame:
    """MMWR year and week for week-ending Saturdays (week 1 = first week with >=4 days in Jan)."""
    sat = pd.to_datetime(sat)
    wed = sat - pd.Timedelta(days=3)  # a week belongs to the year that holds its Wednesday
    year = wed.dt.year
    jan1 = pd.to_datetime(year.astype(str) + "-01-01")
    first_wed = jan1 + pd.to_timedelta((2 - jan1.dt.dayofweek) % 7, unit="D")
    week = (wed - first_wed).dt.days // 7 + 1
    return pd.DataFrame({"mmwr_year": year.values, "mmwr_week": week.values}, index=sat.index)


def season_of(sat: pd.Series) -> pd.Series:
    """CDC influenza season label (MMWR week 40 through week 39), e.g. '2026-27'."""
    w = mmwr_week(sat)
    start = w.mmwr_year.where(w.mmwr_week >= 40, w.mmwr_year - 1)
    return start.astype(str) + "-" + ((start + 1) % 100).astype(str).str.zfill(2)


# ----------------------------------------------------------------------------- locations

def locations() -> pd.DataFrame:
    """FluSight location table: abbreviation, location (FIPS or 'US'), location_name, population."""
    loc = pd.read_csv(LOCATIONS_FILE, dtype={"location": str})
    return loc[["abbreviation", "location", "location_name", "population"]]


_ALIASES = {"USA": "US", "UNITED STATES": "US", "UNITED STATES OF AMERICA": "US", "NATION": "US",
            "NATIONAL": "US"}


def to_location(values: pd.Series) -> pd.Series:
    """Map abbreviations, state names or FIPS codes to FluSight `location` codes (NaN if unknown)."""
    loc = locations()
    lut = {}
    for r in loc.itertuples():
        for k in (r.abbreviation, r.location, r.location_name):
            lut[str(k).upper()] = r.location
    for k, v in _ALIASES.items():
        lut[k] = "US"
    lut["DISTRICT OF COLUMBIA"] = "11"
    return values.astype(str).str.strip().str.upper().map(lut)


# ----------------------------------------------------------------------------- sources

@dataclass
class Signal:
    key: str            # short id, unique within the source
    label: str          # what a colleague sees on the button / legend
    unit: str           # axis title; signals sharing a unit share a y-axis
    description: str = ""
    default: bool = False   # shown when the source is first switched on


@dataclass
class Remote:
    version: str            # opaque id that changes when the remote data changes
    updated: str            # ISO timestamp of the remote update (UTC)
    detail: str = ""


@dataclass
class Snapshot:
    name: str
    path: Path
    meta: dict = field(default_factory=dict)

    @property
    def version(self) -> str:
        return self.meta.get("remote_version", "")


class Source:
    """Base class. A pull script subclasses this and implements remote(), fetch(), harmonize()."""

    key = ""
    label = ""
    description = ""
    homepage = ""
    cadence = ""
    restricted = False      # True = licensed data; excluded from `dashboard --public`
    signals: list[Signal] = []
    args = None             # argparse namespace when run as a script; None inside the pipeline

    def opt(self, name: str, default=None):
        """Option lookup: command-line flag, then config.json[<source key>][name], then default."""
        v = getattr(self.args, name, None) if self.args is not None else None
        if v is None:
            v = config(self.key).get(name)
        return default if v is None else v

    # -- to implement -----------------------------------------------------------------
    def remote(self) -> Remote:
        """Ask the remote what its latest release is (cheap; no data download)."""
        raise NotImplementedError

    def fetch(self, snap_dir: Path, remote: Remote) -> dict:
        """Download the release into snap_dir. Return extra metadata for _meta.json."""
        raise NotImplementedError

    def harmonize(self, snapshots: list[Snapshot]) -> pd.DataFrame:
        """Return columns [date, location, signal, value, snapshot]; date = week-ending Saturday,
        location = FluSight code, signal = Signal.key. `snapshots` are oldest -> newest."""
        raise NotImplementedError

    # -- snapshots ------------------------------------------------------------------------
    @property
    def raw_dir(self) -> Path:
        return RAW / self.key

    def snapshots(self) -> list[Snapshot]:
        out = []
        if self.raw_dir.exists():
            for p in sorted(self.raw_dir.iterdir()):
                m = p / "_meta.json"
                if p.is_dir() and not p.name.startswith(".") and m.exists():
                    out.append(Snapshot(p.name, p, json.loads(m.read_text())))
        return out

    def latest(self) -> Snapshot | None:
        s = self.snapshots()
        return s[-1] if s else None

    def check(self) -> dict:
        """Compare remote release with the newest local snapshot."""
        local = self.latest()
        try:
            rem = self.remote()
            err = ""
        except Exception as e:  # network down, auth missing, ...
            rem, err = None, f"{type(e).__name__}: {e}"
        return {
            "source": self.key,
            "remote_updated": rem.updated if rem else "",
            "remote_version": rem.version if rem else "",
            "remote_detail": rem.detail if rem else err,
            "local_snapshot": local.name if local else "",
            "local_version": local.version if local else "",
            "n_snapshots": len(self.snapshots()),
            "up_to_date": bool(rem and local and local.version == rem.version),
            "error": err,
        }

    def update(self, force: bool = False) -> Snapshot | None:
        """Pull a new snapshot if the remote has changed (or force). Returns it, or None."""
        rem = self.remote()
        local = self.latest()
        if local and local.version == rem.version and not force:
            log(f"[{self.key}] up to date (snapshot {local.name}, remote {rem.updated})")
            return None
        if local and not force and pd.Timestamp(rem.updated) < pd.Timestamp(local.meta["remote_updated"]):
            log(f"[{self.key}] remote ({rem.detail}, {rem.updated}) is OLDER than local snapshot "
                f"{local.name}; skipping (use --force to store it anyway)")
            return None
        stamp = pd.Timestamp(rem.updated)
        name = stamp.strftime("%Y-%m-%d")
        if (self.raw_dir / name).exists():
            name = stamp.strftime("%Y-%m-%d_%H%M")
            if (self.raw_dir / name).exists():
                name = dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")
        tmp = self.raw_dir / f".partial-{name}"
        if tmp.exists():
            shutil.rmtree(tmp)
        tmp.mkdir(parents=True)
        log(f"[{self.key}] pulling {rem.detail or rem.version} -> {self.raw_dir.name}/{name}")
        t0 = time.time()
        extra = self.fetch(tmp, rem) or {}
        files = {}
        for f in sorted(tmp.rglob("*")):
            if f.is_file() or f.is_symlink():
                rel = str(f.relative_to(tmp))
                files[rel] = {"bytes": f.stat().st_size,
                              "sha256": _sha256(f) if not f.is_symlink() else "symlink"}
        meta = {"source": self.key, "snapshot": name, "remote_version": rem.version,
                "remote_updated": rem.updated, "remote_detail": rem.detail,
                "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                "fetched_by": os.environ.get("USER", ""), "seconds": round(time.time() - t0, 1),
                "files": files, **extra}
        (tmp / "_meta.json").write_text(json.dumps(meta, indent=2))
        tmp.rename(self.raw_dir / name)
        log(f"[{self.key}] wrote {len(files)} file(s) in {meta['seconds']}s")
        return Snapshot(name, self.raw_dir / name, meta)

    # -- metadata for harmonized outputs / dashboard -----------------------------------------
    def info(self) -> dict:
        return {"key": self.key, "label": self.label, "description": self.description,
                "homepage": self.homepage, "cadence": self.cadence, "restricted": self.restricted,
                "signals": [vars(s) for s in self.signals]}

    # -- CLI shared by every pull script ------------------------------------------------------
    def cli(self, argv=None) -> int:
        ap = argparse.ArgumentParser(description=f"{self.label}: {self.description}")
        ap.add_argument("--check", action="store_true",
                        help="only report whether the remote has a newer release")
        ap.add_argument("--force", action="store_true",
                        help="download even if the newest local snapshot matches the remote")
        ap.add_argument("--list", action="store_true", help="list local snapshots")
        self.add_arguments(ap)
        args = ap.parse_args(argv)
        self.args = args
        if args.list:
            for s in self.snapshots():
                print(f"{s.name}\t{s.meta.get('remote_updated', '')}\t{s.meta.get('remote_detail', '')}")
            return 0
        if args.check:
            st = self.check()
            print(json.dumps(st, indent=2))
            return 0 if not st["error"] else 1
        self.update(force=args.force)
        return 0

    def add_arguments(self, ap: argparse.ArgumentParser) -> None:
        """Hook for source-specific flags (use default=None so config.json can supply values)."""


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ----------------------------------------------------------------------------- Socrata (data.cdc.gov)

def socrata_remote(dataset: str, domain: str = "data.cdc.gov") -> Remote:
    v = http_json(f"https://{domain}/api/views/metadata/v1/{dataset}", timeout=90)
    ts = pd.Timestamp(v["dataUpdatedAt"]).tz_convert("UTC")
    return Remote(version=f"{dataset}@{v['dataUpdatedAt']}", updated=ts.isoformat(),
                  detail=f"{dataset}: {v['name'].strip()[:70]} (data updated {ts:%Y-%m-%d %H:%M} UTC)")


def socrata_csv(dataset: str, dest: Path, where: str | None = None, order: str = ":id",
                page: int = 200_000, domain: str = "data.cdc.gov") -> int:
    """Download a (filtered) Socrata dataset as CSV, paging so nothing is silently truncated."""
    parts, offset, n = [], 0, 0
    while True:
        params = {"$limit": page, "$offset": offset, "$order": order}
        if where:
            params["$where"] = where
        body = http_get(f"https://{domain}/resource/{dataset}.csv", params=params)
        text = body.decode("utf-8")
        rows = max(sum(1 for _ in csv.reader(io.StringIO(text))) - 1, 0)
        if offset == 0:
            parts.append(body)
        else:  # drop the repeated header line
            parts.append(body.split(b"\n", 1)[1] if b"\n" in body else b"")
        n += rows
        if rows < page:
            break
        offset += page
    dest.write_bytes(b"".join(p if p.endswith(b"\n") else p + b"\n" for p in parts))
    return n
