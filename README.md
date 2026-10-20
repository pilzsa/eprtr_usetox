# EPRTR Atlas

European industrial pollutant releases, hazard, population and permits,
2007–2024 — as a website with one map engine and two shells.

**Live site:** <https://pilzsa.github.io/eprtr_usetox/>

* [Home](https://pilzsa.github.io/eprtr_usetox/) — what the atlas is, six numbers, caveats
* [Map](https://pilzsa.github.io/eprtr_usetox/map.html) — native Quarto map page (~500 KB)
* [Findings](https://pilzsa.github.io/eprtr_usetox/findings.html) — eight questions answered
* [Data checks](https://pilzsa.github.io/eprtr_usetox/data-checks.html) — what was removed, joined and lost
* [Methodology](https://pilzsa.github.io/eprtr_usetox/methodology.html) — definitions and the four long-form reports
* [Full explorer](https://pilzsa.github.io/eprtr_usetox/map/frontend/) — the React app

## Repository layout

```
analysis/            Quarto site, data build and reports
  build_dataset.py       releases → facilities, hazard levels, LAU join
  build_permits.py       IED permit linkage (2017–2024)
  population_profile.py  people within 0.5/1/3/5 km (JRC 2021)
  build_findings.py      tables, figures, findings.json
  reports/               four long-form method reports
dashboard/
  frontend/              React explorer (no build step, Babel in the browser)
  data/                  compact JSON: facilities, releases, permits, population
scripts/
  stage_web.sh           dashboard → analysis/map (gitignored)
  build_site.sh          tokens check + Quarto render
.github/workflows/       pages.yml: render and deploy to GitHub Pages
```

## Build

Data (needs the multi-gigabyte EEA and JRC inputs; see `analysis/README.md`):

```bash
python3 analysis/build_dataset.py
python3 analysis/build_permits.py
python3 analysis/population_profile.py
python3 analysis/build_findings.py
```

Site (Quarto 1.9+, no Python data stack needed):

```bash
scripts/build_site.sh          # → analysis/_site
scripts/build_site.sh --serve  # → http://localhost:8000
```

The committed JSON and Markdown tables mean the site builds without the raw
inputs; only the data scripts need them.

## Data and limits

Releases are self-reported under the E-PRTR Regulation. Hazard levels are a
screening of the reported substances, not a risk assessment. Permit records
cover 2017–2024 and 64.6 % of facilities; Norway, Serbia and Switzerland are
absent from the permit table. Population is a 2021 model on 100 m cells covering
the EU-27 plus Norway and Switzerland. The [data checks](https://pilzsa.github.io/eprtr_usetox/data-checks.html)
and [methodology](https://pilzsa.github.io/eprtr_usetox/methodology.html) pages
state every exclusion and join decision.
