# Publishing: git remote and the public dashboard on GitHub Pages

This covers two things: pushing the code to a remote repository, and publishing the **public** dashboard
(no Kinsa) at `https://<owner>.github.io/<repo>/`.

## The one rule

**Kinsa data never leaves the cluster.** It is licensed. Nothing in this repository contains it:

* `data/` (raw downloads, harmonized table) and `dashboard/*.html` are in `.gitignore`.
* Kinsa credentials live in environment variables or `~/.config/fludash/kinsa.json`, never in the repo.
* The published page is built with `--public`, which drops every source marked `restricted` (Kinsa).
* The GitHub build below never pulls Kinsa at all, and fails if a Kinsa entry shows up in the page anyway.

`dashboard/index.html` (with Kinsa) stays on the cluster for the team.

## 1. Before the first push

| Item | What to do |
|---|---|
| Visibility | Decide private or public. Pages from a **private** repo needs a paid GitHub plan (Pro, Team, or Enterprise). On Enterprise Cloud the Pages site can also be limited to org members. |
| License | Add a `LICENSE` file (for example MIT or BSD-3) if the repo will be public. Third-party notices are already in `THIRD_PARTY_NOTICES.md` (plotly.js is MIT and inlined into every page). |
| Internal paths | `README.md`, `pull/pull_flusight.py` and `pull/pull_kinsa.py` mention cluster paths (`/project/bii_nssac/...`, a team member's FluSight clone). They are fine in a private repo. For a public repo, replace them with placeholders such as `<kinsa-store>`. |
| Check what will be committed | `git status --short` should list only code, docs, `config.example.json`, and `fludash/vendor/`. Nothing under `data/` or `dashboard/`. |

Then:

```bash
cd /project/bii_nssac/people/bl4zc/flu-dashboard     # already `git init`-ed, branch main
git add -A
git status --short                                   # review
git commit -m "Flu surveillance ingest pipeline and dashboard"
git remote add origin git@github.com:<owner>/<repo>.git
git push -u origin main
```

This folder is its own git repository. The surrounding `bii_nssac` repository ignores `people/`, so the
two do not interfere.

## 2. Recommended: GitHub Actions builds and deploys the public page

A scheduled workflow on GitHub's runners downloads the public sources from scratch, builds
`--public`, and deploys the single HTML file to Pages. Nothing is pushed from the cluster, and no cluster
credentials are needed.

A clean run like this was tested on 2026-11-17 in an empty data folder:

* 1.5 minutes end to end
* 50 MB of downloads, discarded after the run
* a 2.1 MB page with 15 signals and 53 locations

### 2a. Repository settings

1. **Settings → Pages → Build and deployment → Source: GitHub Actions.**
2. **Settings → Secrets and variables → Actions → New repository secret:**
   * `DELPHI_EPIDATA_KEY`: get a free key from https://api.delphi.cmu.edu/epidata/admin/registration_form.
     Anonymous Delphi use is limited to 3 requests per minute. GitHub runners share IP addresses with other
     users, so ILINet and NSSP ARI pulls will eventually be refused without a key. The pull scripts send the
     key automatically when the variable is set.
3. **Settings → Actions → General:** allow GitHub Actions. If the repo is in an organization, an owner may
   need to allow Pages and the `actions/*` actions.

### 2b. Workflow file: `.github/workflows/pages.yml`

```yaml
name: Public dashboard

on:
  schedule:
    - cron: "0 20 * * 3"     # Wed 20:00 UTC: after the NHSN / FluSight release
    - cron: "0 20 * * 5"     # Fri 20:00 UTC: after NSSP, ILINet, FluSurv-NET
  workflow_dispatch: {}      # "Run workflow" button
  push:
    branches: [main]
    paths: ["fludash/**", "pull/**", "pipeline.py", ".github/workflows/pages.yml"]

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: pages
  cancel-in-progress: false

jobs:
  build:
    runs-on: ubuntu-latest
    timeout-minutes: 30
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - run: pip install -r requirements.txt
      - name: Pull public sources, harmonize, build the public page
        env:
          DELPHI_EPIDATA_KEY: ${{ secrets.DELPHI_EPIDATA_KEY }}
        run: |
          python pipeline.py run -s flusight,nhsn_hrd,nssp,ilinet,flusurv --public --out site/index.html
      - name: Refuse to publish licensed data
        run: |
          if grep -q '"key":"kinsa"' site/index.html; then
            echo "::error::Kinsa found in the public page"; exit 1
          fi
          grep -q '"public":true' site/index.html
      - uses: actions/configure-pages@v5
      - uses: actions/upload-pages-artifact@v3
        with:
          path: site

  deploy:
    needs: build
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - id: deployment
        uses: actions/deploy-pages@v4
```

The action versions above were current at the time of writing; GitHub may show newer major versions.

Note on the `-s` list: `kinsa` is left out, so the runner never tries to log in to Kinsa. The harmonize
step prints `[kinsa] no local data yet`. That message is expected.

### 2c. First run and checks

1. **Actions → Public dashboard → Run workflow.**
2. When it finishes, open `https://<owner>.github.io/<repo>/`. The header should say "public build".
   *About the sources* should list FluSight, NHSN HRD, NSSP, ILINet and FluSurv-NET only.
3. If a pull fails (network, Delphi limit), that source is skipped and the page is built without it. The
   job log shows `FAILED` next to the source. Re-run the workflow, or add the Delphi key if that was the
   cause.

### 2d. Things to know

* **Scheduled workflows stop after 60 days without repository activity** (GitHub's rule for public repos).
  GitHub emails a warning. Any commit, or pressing *Run workflow*, re-enables it.
* Schedules run in UTC and can start late (minutes, occasionally longer) when GitHub is busy.
* The runner keeps no download history: every run starts from scratch. The cluster copy (`data/raw/`) remains
  the archive of past releases (backfill studies).
* The page embeds data back to 2010 (2.1 MB). Pages allows sites up to 1 GB, so size is not a concern.
* CDC's data portal (data.cdc.gov, Socrata) works without a token at this volume. If it starts throttling,
  add a Socrata app token (`X-App-Token` header in `fludash/common.py`) as a second secret.

## 3. Alternative: build on the cluster, push the HTML

Use this only if the public page must come from exactly the same downloads as the team's copy.

* The existing cron job (`pipeline.py run`) already builds `dashboard/index-public.html`.
* Add a step that copies it to `index.html` in a checkout of a `gh-pages` branch (or a separate small
  repo), commits, and pushes.
* Authenticate with a **deploy key** that only has write access to that repo, stored on the cluster with
  `chmod 600`.
* Set **Settings → Pages → Source: Deploy from a branch → gh-pages / (root)**, and add an empty `.nojekyll`
  file.

Downsides: a GitHub write credential sits on the cluster, and publishing depends on the cluster's cron
running.

## 4. Suggested additions before announcing the page

* **Footer:** "Not an official CDC product. Data: CDC (NHSN, NSSP, ILINet via Delphi Epidata,
  FluSurv-NET), FluSight hub." Add a link to the repository.
* **Monitoring:** turn on GitHub's email notification for failed workflow runs (Settings → Notifications →
  Actions) for whoever maintains the page.
* **Pinned link:** add the Pages URL to the repository's *About* box.
