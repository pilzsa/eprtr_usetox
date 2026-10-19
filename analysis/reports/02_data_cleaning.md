# Data cleaning and aggregation

The build is implemented in `analysis/build_dataset.py`. It is deterministic
apart from the `generated` date and the LAU lookup cache; re-running it on the
same inputs produces the same tables.

## 1. Reading

```python
pd.read_csv(path, low_memory=False)
```

* Air and water files are concatenated; `medium` is set from the file, not from
  `TargetRelease`.
* The UTF-8 BOM is stripped from the first column name.
* `Releases` → numeric `kg`, `Longitude`/`Latitude` → numeric `lon`/`lat`,
  `reportingYear` → nullable integer `year`. Non-numeric values become missing
  rather than raising.
* No unit conversion is applied: the E-PRTR user-friendly tables report air and
  water releases in **kg/year**.

## 2. Row filtering and duplicate policy

| Step | Rows | Removed |
|---|---:|---:|
| Air + water source rows | 626,362 | — |
| Missing facility ID / pollutant / reporting year | 626,362 | 0 |
| Outside 2007–2024 | 626,362 | 0 |
| Exact duplicate rows | 626,334 | **28** |
| Remaining rows sharing facility × year × medium × pollutant | 626,334 | **0** |

String fields (`FacilityInspireId`, `facilityName`, `countryName`, `Pollutant`,
`city`, sector, activity, `TargetRelease`) are stripped of leading/trailing
whitespace before duplicate detection.

The 28 exact duplicates are removed because they are value-for-value repeats
of an existing report after whitespace trimming. There are **no** remaining
duplicate keys, so no legitimate separate records are summed. The code still
sums duplicate keys defensively if a future extract introduces them.

## 3. Mass handling

| Category | Rows | Treatment |
|---|---:|---|
| Positive mass | 625,647 | raw positive rows; CO₂ nested rows deduplicated below |
| Reported zero | 634 | kept as a reported zero (not missing) |
| Missing mass | 53 | excluded from sums; `conf` flag set |
| Negative mass | 0 | would be excluded; none present |

`kg_clean = kg` where `kg ≥ 0`, otherwise `0`. A facility-year aggregate
therefore never becomes negative or NaN. Missing and suppressed masses remain
visible through the facility-year `conf` flag (`1` if any pollutant row is
`CONFIDENTIAL` or has a non-empty `confidentialityReason`) and in the quality
report.

The dashboard's **total mass** includes all reported positive kilograms after the
CO₂ deduplication described below, including aggregate indicators. The
**classified mass** is restricted to pollutants with hazard level ≥ 2; this
distinction is essential because CO₂ alone dominates the total.

## 4. Facility metadata

`prepare_facilities()` creates one row per `FacilityInspireId`:

* **Name, country, sector, activity**: from the most recent reporting year.
* **City**: the most frequent non-empty city across all years; `--`, empty and
  the literal string `nan` are treated as missing (10,568 `--` rows).
* **Coordinates**: the most recent valid coordinate within the Europe window,
  where valid means non-null, not `(0, 0)`, longitude in `[-32, 45]` and
  latitude in `[27, 72]`. If no valid point exists, raw coordinates are kept for
  diagnostics but the facility is not plotted.
* **Country code**: mapped from the country name; unknown names get `""`.

This produces **32,155 facilities in 32 countries**. Of these, 199 have no
plottable point (3 are `(0, 0)`, 59 are outside the window, the rest are
missing). They remain searchable by name and can be opened in the detail panel,
but never appear on the map.

The Europe window deliberately includes the Canary Islands, Azores and Madeira
and excludes overseas territories such as Réunion, French Guiana and the
Caribbean. This prevents the map from fitting to the whole globe.

## 5. Aggregation to facility × year

Source rows are first grouped by `FacilityInspireId × year × medium × pollutant`
(626,334 groups). For each group the build stores:

* summed kilograms (`kg`);
* the pollutant's air or water hazard level;
* whether the mass is positive, high-hazard (`level ≥ 3`), classified
  (`level ≥ 2`), carcinogenic, or unassessable;
* whether any underlying row is confidential.

The second grouping is `FacilityInspireId × year`, producing **245,515
facility-year rows**. Aggregated fields:

| Field | Definition |
|---|---|
| `air_all`, `water_all` | all positive reported kg by medium |
| `all_kg` | `air_all + water_all` |
| `air_haz`, `water_haz` | kg of pollutants with level ≥ 2 by medium |
| `haz_kg` | `air_haz + water_haz` |
| `max_air`, `max_water`, `max_level` | highest air/water hazard class among positive masses |
| `n_sub` | distinct positive pollutants in the facility-year |
| `n_haz` | distinct pollutants with level ≥ 3 (counted once across media) |
| `n_carc` | distinct positive pollutants with an IARC or CLP carcinogen flag |
| `n_unassessed` | distinct positive unassessable labels |
| `conf` | any confidential/missing mass in the facility-year |

Counts are **distinct pollutant labels**, not kilograms and not release rows.
`n_haz` in particular is a substance count; summing it across facilities, as
the overview tile does, produces a count of facility-pollutant matches, not a
count of facilities.

### CO₂ double-counting correction

The air table contains two nested labels: `Carbon dioxide (CO2)` (total,
including biomass) and `Carbon dioxide (CO2) excluding biomass`. In 6,783
facility-years both are reported. Adding both would count the fossil share
twice. The build therefore keeps one CO₂ estimate per facility-year:

* if only one label is reported, its mass is used unchanged;
* if both are reported, the **smaller mass is treated as the nested subset** and
  subtracted once from the `excluding biomass` row.

After subtraction, the two rows sum to `max(total, excluding biomass)` and the
result is stored in `kg_counted`. The raw grouped mass remains in `kg`, and both
columns are exported to `pollutant_year.csv`. The correction removes
**4.43 Gt** of double counting: total reported mass is 35.49 Gt before the
correction and **31.06 Gt** after it. `CO2 excluding biomass` retains 0.022 Gt
for facility-years where only that label is present or where it exceeds the
total label.

All facility-year, country-year and dashboard totals use `kg_counted`. Hazard
mass is unaffected because CO₂ is level 0.

For the tooltip, the build keeps the top three pollutants by counted mass plus
the highest-hazard pollutant if it is not already among them. Each entry is
`[pollutant_index, kg, medium_code, level]` with `medium_code` `0 = air`,
`1 = water`.


## 6. Spatial cleaning and the LAU join

Spatial cleaning uses GDAL/OGR directly:

1. Transform each unique facility point from WGS84 to EPSG:3035 with
   traditional GIS axis order (Easting/Northing).
2. Apply a 2 m spatial filter rectangle around the point.
3. Use `geometry.Contains(point)`; if no polygon contains it, accept the first
   `geometry.Intersects(point)` hit (point exactly on a boundary).
4. If neither test succeeds, leave the facility's LAU fields null. **No
   nearest-neighbour or country-centroid fallback is used.**

Unique coordinates are cached in `analysis/outputs/lau_lookup.csv`
(`lon,lat → LAU id/name/country/pop/area`). The cache is reused when present,
which makes rebuilds fast but means it must be deleted after changing the LAU
source or the coordinate window.

| LAU join result | Count | Share |
|---|---:|---:|
| Unique facility coordinates | 30,429 | 100% |
| Coordinates matched | 26,395 | 86.7% |
| Coordinates unmatched | 4,034 | 13.3% |
| Facilities with a LAU | 27,574 | 85.8% |
| Facilities without a LAU | 4,581 | 14.2% |

Unmatched facilities are concentrated in countries with missing or partial LAU
coverage and at coordinate/boundary mismatches:

| Country | Facilities without LAU | Main reason |
|---|---:|---|
| United Kingdom | 2,713 | no UK LAUs in the GISCO layer |
| Norway | 1,515 | partial Norwegian LAU coverage |
| Belgium | 112 | coordinate/boundary mismatch |
| Italy | 67 | coordinate/boundary mismatch |
| France | 60 | coordinate/boundary mismatch |
| Spain | 37 | coordinate/boundary mismatch |
| Denmark | 15 | coordinate/boundary mismatch |
| Ireland | 9 | coordinate/boundary mismatch |
| Germany | 8 | coordinate/boundary mismatch |
| Other 23 countries | 45 | coordinate/boundary mismatch |

All unmatched facilities are retained in `facilities_without_lau.csv` with
their raw and plottable coordinates. If a facility has a valid point it is
still drawn, even when its LAU is null.

The city search index is built from the LAU polygons, not from the free-text
`city` column:

* every LAU that contains at least one facility is included, regardless of
  population;
* every LAU with `POP_2024 ≥ 1000` is included;
* the centroid is transformed back to WGS84 and kept only inside the Europe
  window;
* `radius` is the radius of a circle with the LAU's area
  (`sqrt(area_km² / π)`), used only to draw the locator circle — it is not a
  settlement radius;
* `nFacilities` counts facilities whose LAU id matches, not facilities
  currently visible after filtering.

Result: **37,237 city entries**, of which **12,490 contain at least one
facility**. The dashboard draws one simplified LAU polygon per entry (see the
sources report); the UK has no source polygons, so UK facilities are searchable
but have no underlay or city entry.

## 7. Output formats

### `dashboard/data/facilities.json`

```json
{"years": [2007, "...", 2024], "facilities": [
  [idx, name, city, cc, country, sector, activity, lon, lat, plot, lau, history]
]}
```

`lau` is `[id, name, country_code, population, area_km²]` or `null`.
`history` is an 18-element array of all-media total kg (or `null`) aligned with
`years`; it powers the facility sparkline and has no hazard split.

### `dashboard/data/releases/YYYY.json`

```json
{"year": 2022, "records": [
  [fac_idx, air_all, water_all, all_kg, air_haz, water_haz, haz_kg,
   max_level, max_air, max_water, n_sub, n_haz, n_carc, n_unassessed,
   conf, top_pollutants]
]}
```

One record per facility-year, **245,515 records** across 18 files. Values are
rounded to 3 decimals; indexes point into `facilities.json` and
`pollutants.json`. `top_pollutants` is a list of
`[pollutant_index, kg, medium_code, level]`.

### Flat audit tables

* `facility_year.csv` — 245,515 rows, all facility metadata and aggregates.
* `country_year.csv` — 542 country-year rows with air, water, classified and
  carcinogenic mass plus distinct facility/pollutant counts.
* `pollutant_year.csv` — 2,213 pollutant-year-medium rows with total kg,
  facility count, hazard level and confidentiality flag.
* `quality_report.json` — machine-readable source of every figure here.
* `facilities_without_lau.csv` — 4,581-row exception list.
* `lau_lookup.csv` — 30,429-row coordinate→LAU cache.

## 8. Known limitations

* The 2024 LAU snapshot is applied to all years; historical municipal mergers
  are not modelled.
* LAU join tolerance is exact point-in-polygon in the source projection; a
  facility just offshore or with a rounded coordinate can miss its municipality.
* A facility's name, sector and activity come from its latest reporting year;
  its city is the most frequent non-empty value and its coordinates come from
  the latest **valid** year. This can mix vintages for facilities that moved or
  were renamed.
* The free-text city field is not geocoded and is not used for the city index.
* `n_haz`, `n_carc` and `n_unassessed` are distinct-label counts, not masses.
