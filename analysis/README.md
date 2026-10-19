# EPRTR Atlas — data build and analysis

This directory contains the reproducible data build for the **EPRTR Atlas**, a
browser dashboard of reported air and water releases from the European
Pollutant Release and Transfer Register (E-PRTR), 2007–2024.

The build converts the two EEA release tables into compact dashboard JSON,
classifies every E-PRTR pollutant label against official hazard lists, joins
facilities to 2024 LAU municipalities and writes an auditable quality report.

## Quick start

Requirements:

* Python 3.10+ with `pandas`, `openpyxl` and the GDAL Python bindings (`osgeo`)
* the source files already present in this repository:
  * `eea_t_ied-eprtr_p_2007-2024_v16_r00/User friendly .csv files/`
  * `LAU/LAU_RG_01M_2024_3035.gpkg`
  * `official_classification/*.xlsx`

Build (from the repository root):

```bash
python3 analysis/build_dataset.py
```

Serve the dashboard over HTTP — opening `frontend/index.html` from disk will not
work because browsers block the JSON and JSX loads:

```bash
python3 -m http.server 8000 --directory dashboard
# open http://localhost:8000/frontend/
```

The first map load fetches `facilities.json` (9.1 MB), `cities.json` (2.5 MB),
the country outline (228 KB), the LAU outline (6.6 MB) and one year file
(0.9–1.4 MB). Later years are cached in the browser for the session.

## What gets built

| Output | Size | Content |
|---|---:|---|
| `dashboard/data/facilities.json` | 9.1 MB | 32,155 facility records, a compact 18-year mass history and optional LAU metadata |
| `dashboard/data/releases/YYYY.json` | 0.9–1.4 MB each | one record per facility-year; 245,515 records in total |
| `dashboard/data/cities.json` | 2.5 MB | 37,237 LAU search entries (12,490 with at least one facility) |
| `dashboard/data/pollutants.json` | 28 KB | all 94 E-PRTR labels with CAS, flags, notes and air/water hazard levels |
| `dashboard/data/boundaries/countries.topojson` | 228 KB | pre-baked country outlines in EPSG:3035 |
| `dashboard/data/boundaries/lau/lau3035.topojson` | 6.6 MB | pre-baked simplified 2024 LAU outlines, one for every 37,237 city-index entry |
| `analysis/outputs/facility_year.csv` | flat audit table | 245,515 facility-year rows with all aggregates |
| `analysis/outputs/country_year.csv` | flat audit table | country × year totals (542 rows) |
| `analysis/outputs/pollutant_year.csv` | flat audit table | pollutant × year × medium totals (2,213 rows) |
| `analysis/outputs/quality_report.json` | machine-readable audit | every cleaning count and join diagnostic |
| `analysis/outputs/facilities_without_lau.csv` | exception list | 4,581 facilities without a LAU match |
| `analysis/outputs/lau_lookup.csv` | join cache | 30,429 unique coordinate → LAU lookups |

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

* Python build completes with no unmapped pollutants and writes all outputs.
* `app.jsx` compiles with the vendored Babel and the JavaScript modules pass
  `node --check`.
* Playwright smoke tests cover city search/focus (Berlin), reset, URL-hash
  restoration, medium/level filtering, zoom marker counter-scaling, tooltip and
  facility detail, mobile horizontal overflow and console errors. All pass with
  no console errors.
