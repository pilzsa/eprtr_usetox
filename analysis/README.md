# EPRTR Atlas — data build and site

This directory contains the reproducible data build and the Quarto pages for
the **EPRTR Atlas**, a browser atlas of reported air and water releases from the
European Pollutant Release and Transfer Register (E-PRTR), 2007–2024.

One map engine, two shells: the React explorer in `dashboard/frontend/` and the
native Quarto map page `map.qmd` both load the same `lib/map.js`, `lib/data.js`
and CSS tokens. The site adds eight research findings, permits, population
within 0.5–5 km and a data-check appendix.

The build converts the two EEA release tables into compact dashboard JSON,
classifies every E-PRTR pollutant label against official hazard lists, joins
facilities to 2024 LAU municipalities, links the IED permit table and samples
the JRC population grid, and writes an auditable quality report.

## Quick start

Requirements:

* Python 3.10+ with `pandas`, `numpy`, `matplotlib`, `openpyxl` and the GDAL
  Python bindings (`osgeo`)
* Quarto 1.9+
* the data sources (all outside git, see `data-checks.qmd`):
  * E-PRTR v16 release CSVs (`EPRTR_RELEASES_DIR`)
  * the IED permit table F6_1 (`EPRTR_PERMITS_CSV`)
  * the JRC-ESTAT 2021 census grid (`EPRTR_CENSUS_TIF`)

Rebuild the data (only needed when the inputs change):

```bash
python3 analysis/build_dataset.py        # releases, facilities, LAU join
python3 analysis/build_permits.py        # permit linkage (2017–2024)
python3 analysis/population_profile.py   # population within 0.5/1/3/5 km
python3 analysis/build_findings.py       # tables, figures, findings.json
```

Render the site (CI does exactly this):

```bash
scripts/build_site.sh          # check tokens, stage dashboard, render
scripts/build_site.sh --serve  # ... then http://localhost:8000
```

Serve the explorer alone (no Quarto needed):

```bash
python3 -m http.server 8000 --directory dashboard
# open http://localhost:8000/frontend/
```

The first map load fetches `facilities.json` (9.5 MB), `cities.json` (2.5 MB),
the country outline (228 KB), the LAU outline (6.6 MB), one year file
(0.9–1.4 MB) and, optionally, `permits.json` (2.6 MB) and `population.json`
(633 KB). Later years are cached in the browser for the session.

## Publish on GitHub Pages

The atlas is static: HTML, CSS, JavaScript and JSON. Python is only needed to
rebuild the data, not to run the site. Pushing to `main` triggers
[`../.github/workflows/pages.yml`](../.github/workflows/pages.yml), which:

1. checks that every colour on `styles.qmd` exists in the design tokens,
2. runs `quarto render analysis`,
3. prunes build caches and adds `.nojekyll`,
4. keeps `/frontend/` and `/data/` redirects for the pre-Quarto URLs,
5. publishes `analysis/_site`.

One-time setup: open **Settings → Pages** in the GitHub repository and set
**Build and deployment → Source** to **GitHub Actions**. The site is then at
`https://<user>.github.io/<repository>/`.

The workflow publishes only the rendered site, not the multi-gigabyte source
directories. The explorer is at `/map/frontend/` and reads its JSON from
`/map/data/`; the Quarto map page uses the same files.

## What gets built

| Output | Size | Content |
|---|---:|---|
| `dashboard/data/facilities.json` | 9.5 MB | 32,155 facility records, a compact 18-year mass history and optional LAU metadata |
| `dashboard/data/releases/YYYY.json` | 0.9–1.4 MB each | one record per facility-year |
| `dashboard/data/cities.json` | 2.5 MB | 37,237 LAU search entries (12,490 with at least one facility) |
| `dashboard/data/pollutants.json` | 28 KB | all 94 E-PRTR labels with CAS, flags, notes and air/water hazard levels |
| `dashboard/data/permits.json` | 2.6 MB | IED permit record per facility, 2017–2024 (20,788 facilities) |
| `dashboard/data/population.json` | 633 KB | people within 0.5/1/3/5 km per facility, 2021 grid |
| `dashboard/data/quality_report.json` | 90 KB | audit copy with the `permits` and `population` sections |
| `dashboard/data/boundaries/countries.topojson` | 228 KB | pre-baked country outlines in EPSG:3035 |
| `dashboard/data/boundaries/lau/lau3035.topojson` | 6.6 MB | pre-baked simplified 2024 LAU outlines |
| `analysis/outputs/facility_year.csv` | flat audit table | facility-year rows with all aggregates |
| `analysis/outputs/facility_carc.csv` | flat audit table | strict carcinogenic mass and its largest substance per facility-year |
| `analysis/outputs/permits_facility.csv` | flat audit table | one permit row per facility with quality flags |
| `analysis/outputs/facility_population.csv` | flat audit table | population, coverage fraction and status per facility |
| `analysis/data/tables/*.md` | site includes | every table on Findings and Data checks |
| `analysis/data/figures/*.svg` | site figures | trend, exposure, permit coverage, top facilities, carcinogens |
| `analysis/outputs/quality_report.json` | machine-readable audit | every cleaning count, join diagnostic and coverage count |

`facility_year.csv` is the easiest table for ad-hoc checks; `quality_report.json`
is the authoritative source for the numbers quoted in the reports.

## Decisions frozen for v1

1. **Hazard priority is “strongest applicable signal wins”.** IARC, CLP
   carcinogenicity and ECHA SVHC set the intrinsic base level. EPA HAP then
   raises **air** releases to at least class 3, and WFD priority raises **water**
   releases to at least class 3 (plus the documented conservative
   water-specific screen for chromium, copper, zinc and arsenic). No single
   list overrides a stronger signal from another list. The exact rules are in
   `hazard_rules.py` and
   [`reports/03_hazard_classification.md`](reports/03_hazard_classification.md).
2. **Default view: 2022, hazard-classified mass, air + water, all classes, LAU
   outlines on.** 2022 is broadly complete in the v16 release. 2023 and 2024
   are selectable but contain visibly fewer reporting facilities and should be
   read as provisional. The URL hash stores year, metric, medium and minimum
   class; reset restores the defaults above.
3. **The map uses pre-baked simplified TopoJSON, not the 75 MB GeoPackage.**
   This keeps the first load practical and avoids client-side simplification.
   The LAU outline is simplified at roughly 1:1M scale and contains one polygon
   for each of the 37,237 city-index entries. It is the same for every year,
   contains no UK polygons and only partial Norwegian coverage; unmatched
   facilities are plotted but have no LAU label or city index entry.

## Headline quality checks

* 626,362 source rows → 626,334 after removing 28 exact duplicates.
* 0 rows with a missing facility ID, pollutant or country; 0 negative masses;
  0 unmapped pollutant labels.
* 53 missing/confidential masses are excluded from mass sums but retained as
  flags; 634 reported zeros are kept.
* 32,155 facilities, 32 countries, 94 pollutant labels (73 assessable).
* 27,574 facilities (85.8%) matched to a 2024 LAU; 4,581 (14.2%) did not.
* 58.59 Mt of the 31.06 Gt counted mass is hazard-classified (level ≥ 2,
  0.19%); unassessed aggregates and CO₂ dominate the total mass.

## Reports

* [`reports/01_data_sources_and_scope.md`](reports/01_data_sources_and_scope.md)
  — inputs, definitions, geographic scope and boundary artifacts
* [`reports/02_data_cleaning.md`](reports/02_data_cleaning.md) — every cleaning
  and aggregation step, with counts
* [`reports/03_hazard_classification.md`](reports/03_hazard_classification.md)
  — hazard sources, priority rules, levels, limitations and the full label table
* [`reports/04_data_quality.md`](reports/04_data_quality.md) — audits, trends,
  LAU coverage, top facilities and known caveats

## Validation performed

* Python builds complete with no unmapped pollutants and write all outputs.
* `app.jsx` compiles with the vendored Babel; `lib/data.js` passes its Node
  unit checks and every JavaScript file passes `node --check`.
* The explorer was checked manually in a browser for search/focus, reset,
  URL-hash restoration, medium/level filtering, tooltip and detail panels. No
  automated browser test is shipped in the repository.
* `build_permits.py` reproduces the audit's exact-match count and counts every
  placeholder date and non-HTTP URL.
* `population_profile.py` returns `p500 ≤ p1 ≤ p3 ≤ p5` for every covered
  facility (0 violations) and a coverage status that never turns no-data into 0.
* `build_findings.py` reconciles the per-facility carcinogenic extraction with
  `country_year.csv` (max abs. delta < 0.02 kg over 53,002 facility-years) and
  aborts if the gap exceeds 1 kg.
* `check_tokens.py` verifies that every colour shown on `styles.qmd` exists in
  `tokens.css`/`tokens-dark.css`; CI runs it before rendering.
