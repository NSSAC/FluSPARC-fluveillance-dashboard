# Fluveillance Dashboard (FluSPARC)

One place to look at the influenza surveillance streams we use for forecasting, side by side,
nationally and for every state. A small pipeline downloads each source, keeps every release it
downloads, builds one harmonized weekly table, and writes a single-file HTML dashboard.

```bash
python pipeline.py status     # what has a new release upstream vs. what we have (no downloads)
python pipeline.py run        # pull what is new -> harmonize -> rebuild the dashboard
```

Open **`dashboard/index.html`** in a browser. It is self-contained (no network needed); in
JupyterLab, click *Trust HTML*. Pick a state on the hex map, with the search box, or with the ← → keys.
Click a source name to add or remove it, and the smaller chips under it for individual signals. The
selection, seasons, view, and axis mode stay the same as you move between states, and the URL
(`#loc=VA&s=...&r=2023,2025,2026`) can be bookmarked or sent to a colleague.

* **Seasons:** one button per season (MMWR week 30 to week 29, about Aug to Jul), any combination, plus
  quick picks (latest, last 2, last 5, all). Dashed season buttons have no data for the selected
  signals. In the *Timeline* view, skipped seasons are cut out of the time axis and shown as a two-week
  break marked ⫽.
* **Overlay seasons:** the selected seasons are drawn over each other, aligned by MMWR week. The latest
  selected season is the bold line; earlier ones are fainter the older they are and labeled at their peak.
* **Values panel:** the strip below the chart is the legend and the readout, with one column per source (it
  always sits under the chart, never over it). A
  guideline follows the mouse over the chart and the panel shows every series' value for that week; off the
  chart it shows the latest week. Press **space** (or *pause*) to freeze the guideline, then scroll the
  panel or move the mouse freely; **Shift+← →** moves the frozen guideline a week; space again resumes.
  *−* folds the panel to one line.
* **Hex map colors** follow the most recently selected signal: either its change in the latest week
  (blue falling, grey within ±10%, red rising) or the latest week as a % of last season's peak. Hover a
  hex for the numbers. Dashed hexes have no data, or a last report more than two weeks older than the
  newest. The selected state has a heavy outline.

The page's season boundary (week 30) differs from the harmonized table's `season` column, which keeps
CDC's week-40 convention.

## Sources

| key | source | what we keep | upstream | updated |
|---|---|---|---|---|
| `flusight` | **FluSight targets** | NHSN flu admissions (count, per 100k); NSSP flu ED % as FluSight scores it | GitHub `cdcepi/FluSight-forecast-hub` `target-data/` | Wed |
| `nhsn_hrd` | **NHSN HRD** (preliminary) | flu admissions since 2020, pediatric admissions, % inpatient beds with flu, % hospitals reporting | data.cdc.gov `mpgq-jmmr` | Wed |
| `nssp` | **NSSP ED visits** | % of ED visits for flu (raw, smoothed); % for any acute respiratory illness (ARI) | data.cdc.gov `rdmq-nq56`; ARI from Delphi V5 | Fri |
| `ilinet` | **ILINet** | % ILI (states unweighted; US also weighted wILI) | Delphi Epidata V5 `fluview_ilinet` | Fri |
| `flusurv` | **FluSurv-NET** | lab-confirmed flu hospitalization rate /100k (all ages; US also 65+, 0-4) | data.cdc.gov `kvib-3txy` (RESP-NET) | Fri |
| `kinsa` | **Kinsa** (licensed) | % ill for cough/cold/flu (the composite), fever, sore throat, cough, nasal; weekly mean of daily values | Kinsa Insights API | daily |

Caveats you will see in the charts:

* **FluSurv-NET "US"** is the network catchment (about 9% of the population, 13-15 states), not a
  national estimate. Most states have no FluSurv-NET site.
* **NHSN reporting was voluntary May-Oct 2024**, so admissions in that window are near zero. Turn on
  *NHSN HRD → % hospitals reporting* to see coverage. The latest week is preliminary and often
  incomplete (for example, 73% of VA hospitals had reported for 2026-11-07).
* **NSSP ARI** comes from Delphi's mirror and has lagged CDC's flu series by about 4 weeks. CDC's own
  "combined" COVID+flu+RSV column stopped on 2024-09-28, so it is not used.
* **ILINet** comes from Delphi's V5 API. The old `/epidata/fluview/` endpoint (used in
  `CSTE/notebooks/get_ili_data.ipynb`) returns nothing after 2026-09-22.
* **Kinsa** has no data for AK and HI. Weekly values use complete Sun-Sat weeks only, so the current
  partial week is not shown. COUGH_COLD_FLU is Kinsa's composite: it sits above the highest single
  symptom on most days and tracks fever most closely (r = 0.98 nationally). Age cohorts (0-12, 13-100)
  exist only in the history file (to 2026-04-28) because current pulls return the all-age cohort, so
  they are not harmonized.

## Commands

```bash
python pipeline.py status [-s nssp,ilinet]          # remote vs local, per source
python pipeline.py update [-s ...] [--force]         # pull sources whose remote changed
python pipeline.py harmonize                         # rebuild data/harmonized/ from raw snapshots
python pipeline.py dashboard [--public] [--out F]    # rebuild the HTML (--public drops Kinsa)
python pipeline.py run [-s ...] [--public]           # update + harmonize + dashboard
```

Every source also runs on its own, with the same flags:

```bash
python pull/pull_nssp.py --check     # JSON: remote release vs. newest local snapshot
python pull/pull_nssp.py             # pull if new
python pull/pull_nssp.py --force     # pull even if unchanged
python pull/pull_nssp.py --list      # local snapshots
python pull/pull_<source>.py --help  # source-specific options
```

Source-specific options:

* `pull_flusight.py --from-clone PATH` copies `target-data/` from a local git clone instead of
  GitHub. `--with-vintages` also keeps `time-series.csv` (every as-of vintage, ~100 MB). The
  pipeline refuses to store a clone that is *older* than what we already have. On 2026-11-17 the
  team clone at `/project/biocomplexity/aniadiga/forecast/gits/FluSight-forecast-hub` had
  `target-data` from 2026-11-04, while GitHub had 2026-11-12. That is why GitHub is the default.
* `pull_nssp.py --with-counties` also keeps the county/HSA table.
* `pull_kinsa.py --start YYYYMMDD`, `--overlap DAYS` (default 28 days re-requested to catch revisions),
  and `--link-store PATH` (see Kinsa below).

Defaults for these can go in `config.json` (copy `config.example.json`). Command-line flags win.

A source that fails (network, credentials) is reported and skipped. The others still run, and
`harmonize` keeps using that source's last good snapshot.

## Data layout

```
data/raw/<source>/<snapshot>/...      every downloaded release, never edited
data/raw/<source>/<snapshot>/_meta.json   URL/dataset, remote version + update time, sha256 per file
data/raw/kinsa/_store/                symlinks to the team's existing Kinsa history
data/harmonized/surveillance_weekly.csv / .parquet
data/harmonized/signals.csv           signal catalog (label, unit, description)
data/harmonized/manifest.json         which snapshot each source came from, weeks covered
dashboard/index.html                  full dashboard (contains Kinsa: team only)
dashboard/index-public.html           without licensed sources
```

`<snapshot>` is the date the *remote* last changed (e.g. `2026-11-12`), so the same release always
lands in the same folder. A second change on the same day gets `_HHMM`. Old snapshots are kept so
revisions (backfill) can be studied later. Harmonization uses the newest snapshot of each source
(Kinsa: all files, newest wins day by day).

### Harmonized table (`surveillance_weekly`)

One row per source × signal × location × week.

| column | meaning |
|---|---|
| `date` | week-ending Saturday (MMWR week) |
| `mmwr_year`, `mmwr_week`, `season` | MMWR year/week; CDC season label, week 40 → 39 (e.g. `2026-27`) |
| `location`, `abbr`, `location_name` | FluSight location code (`US`, `01` … `72`), postal code, name |
| `source`, `signal` | e.g. `nssp`, `flu_ed_pct` (see `signals.csv`) |
| `value`, `unit` | the number and its unit (`Admissions per week`, `% of ED visits`, …) |
| `snapshot` | raw folder the value came from |

```python
import pandas as pd
d = pd.read_parquet("data/harmonized/surveillance_weekly.parquet")
va = d[(d.abbr == "VA") & (d.season == "2026-27")].pivot_table(index="date", columns=["source", "signal"], values="value")
```

## Kinsa (licensed)

Kinsa data is provided under our agreement with Kinsa. Keep `dashboard/index.html` and `data/`
inside the project. Use `python pipeline.py dashboard --public` for anything shared more widely.

* History: link the team's existing store once, instead of re-downloading it:
  `python pull/pull_kinsa.py --link-store /project/bii_nssac/data/kinsa-health`
* Credentials, checked in order: `KINSA_EMAIL` + `KINSA_PASSWORD` environment variables;
  `~/.config/fludash/kinsa.json` with `{"email": "...", "password": "..."}` (`chmod 600` it); an
  interactive prompt. Without credentials in a non-interactive run, Kinsa is skipped and everything
  else still updates.
* The API calls are the same as in `forecast/Kinsa/kinsa_api_pull.py` (login, then one `/signal`
  request for the nation and one per state).

## Running it weekly

CDC releases land Wednesday (NHSN, FluSight) and Friday (NSSP, ILINet, FluSurv-NET). A run on
Wednesday afternoon and one on Friday afternoon catch everything. Example crontab on a login node:

```
0 15 * * 3,5  cd /project/bii_nssac/people/bl4zc/flu-dashboard && /path/to/python-with-pandas pipeline.py run >> data/run.log 2>&1
```

(cron starts with a bare environment, so give the full path of a Python that has pandas.)

Delphi's anonymous limit is 3 snapshot requests per minute, and the ILINet pull waits between
calls. If you have a Delphi API key, export `DELPHI_EPIDATA_KEY`.

## Environment

Python ≥ 3.9 with **pandas** (pyarrow optional; without it the parquet file is skipped). HTTP uses
the standard library, so `requests` is not needed. Plotly.js (basic bundle 2.35.2, MIT) is vendored in
`fludash/vendor/` and inlined into the HTML.

## Publishing

Pushing to a remote and publishing the public dashboard on GitHub Pages (Kinsa never leaves the cluster):
see [docs/PUBLISHING.md](docs/PUBLISHING.md).

## Branding

The header logo and the browser-tab icon come from `fludash/assets/`. The page inlines small copies from
`fludash/assets/web/` (so it stays a single file). After replacing a hi-res logo, regenerate them with
`python fludash/assets/make_web_assets.py` (needs Pillow; nothing else in the project does).

## Adding a source

1. Copy the closest `pull/pull_*.py`. Set `key`, `label`, `description`, `signals`, and implement
   `remote()` (cheap "what is the latest release?"), `fetch()` (download into the snapshot
   folder) and `harmonize()` (return `date, location, signal, value, snapshot`).
2. Add the module name to `MODULES` in `pull/__init__.py`. Its position sets the button order and color.
3. `python pull/pull_new.py && python pipeline.py harmonize dashboard`.

Easy candidates: CDC/Delphi clinical-lab % positive (`fluview_resp_lab_clinical`), NWSS wastewater
influenza A, and NSSP county/HSA data (already downloadable with `--with-counties`).
