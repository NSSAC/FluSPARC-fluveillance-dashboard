#!/usr/bin/env python3
"""Influenza surveillance pipeline: pull -> harmonize -> dashboard.

    python pipeline.py status                 # what's new remotely vs. what we have (no downloads)
    python pipeline.py update                 # pull every source whose remote has a newer release
    python pipeline.py update -s nssp,ilinet  # only some sources
    python pipeline.py update --force -s nssp # re-download even if unchanged
    python pipeline.py harmonize              # rebuild data/harmonized/ from the raw snapshots
    python pipeline.py dashboard [--public]   # rebuild dashboard/index.html (--public drops Kinsa)
    python pipeline.py run                    # update + harmonize + dashboard (the weekly job)

Sources: flusight nhsn_hrd nssp ilinet flusurv kinsa  (each also runs alone: pull/pull_<name>.py)
A failing source (network, credentials) is reported and skipped; the rest still run.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fludash.common import log  # noqa: E402
from pull import sources as all_sources  # noqa: E402


def pick(names: str | None):
    srcs = all_sources()
    if not names:
        return srcs
    want = [n.strip() for n in names.split(",") if n.strip()]
    keys = {s.key for s in srcs}
    unknown = set(want) - keys
    if unknown:
        raise SystemExit(f"unknown source(s) {sorted(unknown)}; choose from {sorted(keys)}")
    return [s for s in srcs if s.key in want]


def _ago(iso: str) -> str:
    if not iso:
        return ""
    import pandas as pd
    t = pd.Timestamp(iso)
    t = t.tz_localize("UTC") if t.tzinfo is None else t
    days = (pd.Timestamp.now(tz="UTC") - t).total_seconds() / 86400
    return f"{t:%Y-%m-%d %H:%M}Z ({days:.0f}d ago)" if days >= 1 else f"{t:%Y-%m-%d %H:%M}Z (today)"


def cmd_status(args) -> int:
    from concurrent.futures import ThreadPoolExecutor
    srcs = pick(args.sources)
    with ThreadPoolExecutor(len(srcs)) as ex:        # data.cdc.gov metadata calls take 5-20 s each
        checks = list(ex.map(lambda s: s.check(), srcs))
    rows, bad = [], 0
    for s, st in zip(srcs, checks):
        if st["error"]:
            state, bad = "ERROR", bad + 1
        elif not st["local_snapshot"]:
            state = "NEW (never pulled)"
        elif st["up_to_date"]:
            state = "up to date"
        else:
            state = "UPDATE AVAILABLE"
        if s.key == "kinsa" and not st["error"]:
            state = "pulled today" if st["up_to_date"] else "due (daily feed)"
        rows.append((s.key, state, _ago(st["remote_updated"]) if s.key != "kinsa" else "-",
                     st["local_snapshot"] or "-", str(st["n_snapshots"]),
                     st["error"] or st["remote_detail"]))
    hdr = ("source", "status", "remote updated", "local snapshot", "#snap", "detail")
    w = [max(len(r[i]) for r in rows + [hdr]) for i in range(5)]
    print("  ".join(h.ljust(w[i]) for i, h in enumerate(hdr[:5])) + "  " + hdr[5])
    for r in rows:
        print("  ".join(c.ljust(w[i]) for i, c in enumerate(r[:5])) + "  " + r[5][:90])
    return 1 if bad else 0


def cmd_update(args) -> int:
    failed = []
    for s in pick(args.sources):
        try:
            s.update(force=args.force)
        except Exception as e:
            log(f"[{s.key}] update FAILED: {type(e).__name__}: {e}")
            failed.append(s.key)
    if failed:
        log(f"failed: {', '.join(failed)}")
    return 1 if failed else 0


def cmd_harmonize(args) -> int:
    from fludash.harmonize import harmonize
    harmonize(all_sources())            # always every source, so the table stays complete
    return 0


def cmd_dashboard(args) -> int:
    from fludash.dashboard import build
    build(public=args.public, out=args.out)
    return 0


def cmd_run(args) -> int:
    rc = cmd_update(args)
    cmd_harmonize(args)
    cmd_dashboard(args)
    return rc


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn, hlp in [("status", cmd_status, "compare remote releases with local snapshots"),
                          ("update", cmd_update, "pull sources with a newer remote release"),
                          ("harmonize", cmd_harmonize, "rebuild data/harmonized/"),
                          ("dashboard", cmd_dashboard, "rebuild the HTML dashboard"),
                          ("run", cmd_run, "update + harmonize + dashboard")]:
        p = sub.add_parser(name, help=hlp)
        p.set_defaults(fn=fn)
        if name in ("status", "update", "run"):
            p.add_argument("-s", "--sources", help="comma-separated subset, e.g. nssp,ilinet")
        if name in ("update", "run"):
            p.add_argument("--force", action="store_true", help="download even if unchanged")
        if name in ("dashboard", "run"):
            p.add_argument("--public", action="store_true",
                           help="leave out licensed sources (Kinsa) for sharing outside the team")
            p.add_argument("--out", help="output HTML path (default dashboard/index.html, "
                                         "or dashboard/index-public.html with --public)")
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
