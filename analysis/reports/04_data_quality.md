# Data quality and coverage

This report audits the built dataset rather than the upstream EEA compilation.
The authoritative machine-readable source is
`analysis/outputs/quality_report.json`; the flat tables
`facility_year.csv`, `country_year.csv` and `pollutant_year.csv` are the
cross-checkable exports. Every number below is reproducible with
`python3 analysis/build_dataset.py`.

No values are imputed, gap-filled or winsorised. The only mass adjustment is
the documented CO₂ nested-label correction described below.

## 1. Coverage at a glance

| Check | Result |
|---|---:|
| Source rows (air + water) | 626,362 |
| Exact duplicate rows removed | 28 |
| Rows after deduplication | 626,334 |
| Duplicate facility × year × medium × pollutant keys | 0 |
| Facilities | 32,155 |
| Countries | 32 |
| Pollutant labels (assessable) | 94 (73) |
| Facility-year records | 245,515 |
| Release-file records (18 files) | 245,515 |
| Positive mass groups after CO₂ correction | 619,021 |
| Reported zero masses | 634 |
| Missing / confidential masses | 53 |
| Negative masses | 0 |
| Total reported mass, raw | 35.49 Gt |
| Nested CO₂ double count removed | 4.43 Gt |
| **Total reported mass, counted** | **31.06 Gt** |
| Hazard-classified mass (level ≥ 2) | 58.59 Mt |
| Classified share of counted mass | 0.19% |
| Plottable facilities | 31,956 (99.4%) |
| Facilities without a plottable point | 199 (0.6%) |
| Facilities matched to a 2024 LAU | 27,574 (85.8%) |
| Facilities without a LAU | 4,581 (14.2%) |
| City-index entries (with facilities) | 37,237 (12,490) |

`facility_year.csv` has exactly one row per facility-year, so its row count
equals the number of distinct facilities reporting in each year. Every one of
those rows has a corresponding record in exactly one `releases/YYYY.json` file.

## 2. Reporting coverage by year

| Year | Source rows | Facility-years | Countries | Total Gt | Classified Mt | Conf. rows |
|---:|---:|---:|---:|---:|---:|---:|
| 2007 | 38,675 | 14,092 | 30 | 2.249 | 4.538 | 0 |
| 2008 | 39,822 | 14,390 | 30 | 2.178 | 4.176 | 0 |
| 2009 | 38,012 | 14,253 | 31 | 2.004 | 3.096 | 0 |
| 2010 | 38,778 | 14,226 | 31 | 2.100 | 3.529 | 0 |
| 2011 | 38,644 | 14,339 | 31 | 1.995 | 3.695 | 0 |
| 2012 | 38,490 | 14,265 | 31 | 1.991 | 3.491 | 0 |
| 2013 | 38,701 | 14,470 | 31 | 1.920 | 3.564 | 0 |
| 2014 | 38,544 | 14,676 | 32 | 1.867 | 3.600 | 0 |
| 2015 | 38,268 | 14,877 | 32 | 1.829 | 3.456 | 0 |
| 2016 | 37,784 | 14,886 | 32 | 1.779 | 3.301 | 2 |
| 2017 | 38,302 | 15,089 | 32 | 1.789 | 3.217 | 2 |
| 2018 | 36,028 | 14,696 | 31 | 1.702 | 3.390 | 7 |
| 2019 | 34,655 | 14,130 | 31 | 1.573 | 3.244 | 4 |
| 2020 | 28,292 | 12,845 | 30 | 1.268 | 2.648 | 7 |
| 2021 | 28,587 | 12,508 | 30 | 1.357 | 3.138 | 9 |
| 2022 | 27,091 | 11,650 | 30 | 1.351 | 2.580 | 9 |
| 2023 | 23,819 | 10,111 | 24 | 1.097 | 1.955 | 4 |
| 2024 | 23,842 | 10,012 | 23 | 1.013 | 1.976 | 9 |

Coverage is not a uniform panel. Facility-years peak at 15,089 in 2017, fall to
12,845 in 2020 and 10,012 in 2024. Country coverage is also unstable: Norway
last reports in 2017 and the United Kingdom in 2019, reducing the country count
from 32 to 31 and then 30. In 2023 there are no reports from Czechia, Iceland,
Lithuania, Malta, Slovakia or Switzerland (24 countries), and 2024 additionally
has no Cyprus (23). These are **reporting-participation and completeness gaps in
the extract**, not verified plant closures.

The falling mass column must be read in that light. It combines closures,
lower output, fuel switching, threshold effects and the shrinking reporting
population. It is not an emissions trend and is not normalised by production or
activity.

## 3. Confidentiality and missing mass

All 53 missing masses are `CONFIDENTIAL` placeholder rows. There are no blank
numeric releases outside this mechanism. The 53 rows cover 50 facility-years
and 28 facilities; a facility-year can contain more than one suppressed row.

| Country | Rows | Year | Rows |
|---|---:|---:|---:|
| Poland | 25 | 2016 | 2 |
| Belgium | 8 | 2017 | 2 |
| Bulgaria | 7 | 2018 | 7 |
| Croatia | 7 | 2019 | 4 |
| Germany | 4 | 2020 | 7 |
| Luxembourg | 1 | 2021 | 9 |
| Romania | 1 | 2022 | 9 |
| | | 2023 | 4 |
| | | 2024 | 9 |

The rows carry no pollutant identity or mass, so they cannot be assigned to a
pollutant, medium or hazard class. The affected facility-years have `conf = 1`
in `facility_year.csv` and in the dashboard record, but their totals are lower
bounds. No mean, zero or country average is substituted, because any imputation
would invent a release that the register deliberately withholds.

## 4. Country coverage and concentration

All 32 country names map to a two-letter code; the country field is never
missing. Mass and facility counts are very unevenly distributed.

| Country | Facilities | Total Gt | Mass share | Classified Mt |
|---|---:|---:|---:|---:|
| Germany | 3,027 | 7.520 | 24.21% | 15.193 |
| Poland | 1,437 | 3.319 | 10.69% | 4.862 |
| United Kingdom | 2,713 | 2.865 | 9.23% | 4.879 |
| Italy | 3,632 | 2.645 | 8.52% | 3.726 |
| Spain | 5,450 | 1.968 | 6.34% | 4.864 |
| France | 4,304 | 1.922 | 6.19% | 4.912 |
| Netherlands | 864 | 1.598 | 5.14% | 1.555 |
| Czechia | 1,074 | 1.094 | 3.52% | 2.321 |
| Sweden | 487 | 0.888 | 2.86% | 0.857 |
| Finland | 544 | 0.884 | 2.84% | 0.340 |

The top five countries carry **58.97%** of counted mass and the top ten
**79.53%**. Facility counts tell a different story: 3,784 of Spain's 5,450
facilities (69%) are intensive-livestock sites and together produce less than
0.1% of Spanish mass, while Germany's 294 energy facilities supply 71% of
German mass. Neither ranking is a sustainability ranking.

Outside the top ten, all 22 countries are individually below 3% of mass. Several
are small reporting populations rather than small economies: Iceland has 43
facilities and 0.07% of mass, Malta has 17 facilities and 0.06%.

## 5. Sector coverage

Sector and activity are taken from each facility's latest reporting-year row,
not reconstructed for every year. A blank in that row stays unknown even if an
earlier year carried a value. Counts are facilities, so they sum to 32,155.

| Sector | Facilities | Total Gt | Mass share | Classified Mt |
|---|---:|---:|---:|---:|
| Energy sector | 2,281 | 20.381 | 65.62% | 6.820 |
| Mineral industry | 2,031 | 2.933 | 9.44% | 6.989 |
| Production and processing of metals | 1,710 | 2.499 | 8.05% | 36.360 |
| Chemical industry | 1,654 | 2.093 | 6.74% | 3.120 |
| Waste and wastewater management | 4,896 | 1.429 | 4.60% | 0.514 |
| Paper and wood production and processing | 671 | 1.406 | 4.53% | 0.906 |
| Animal and vegetable products (food and beverage) | 1,238 | 0.155 | 0.50% | 0.219 |
| Intensive livestock production and aquaculture | 15,940 | 0.054 | 0.18% | 2.854 |
| Other activities | 821 | 0.017 | 0.06% | 0.098 |
| Unknown / blank sector | 913 | 0.092 | 0.30% | 0.716 |
| **Total** | **32,155** | **31.060** | **100%** | **58.594** |

Three patterns matter for interpretation:

* **Energy** is two thirds of total mass but only 7% of facilities. Its
  classified mass is comparatively low because most of its mass is CO₂.
* **Metals** produce 8% of total mass but **62% of all classified mass**
  (36.36 of 58.59 Mt), reflecting process emissions of metals and other
  classified substances.
* **Intensive livestock** is half of all facilities (15,940) but 0.18% of mass.
  Facility counts and mass answer different questions.

The 913 facilities without a sector are 2.8% of facilities and 0.30% of mass.
They are retained under an explicit unknown label rather than silently dropped.
Sector labels are the source's E-PRTR Annex I names; no independent sector
validation was performed.

## 6. Metadata, coordinates and spatial coverage

| Metadata check | Result |
|---|---:|
| Facilities with a city name | 32,044 (99.65%) |
| Facilities without a city name | 111 (0.35%) |
| Facilities with a sector | 31,242 (97.16%) |
| Facilities without a sector | 913 (2.84%) |
| Plottable facilities | 31,956 (99.38%) |
| No plottable point | 199 (0.62%) |
| — coordinate exactly `(0, 0)` | 3 |
| — outside the Europe window | 59 |
| — missing coordinates | 137 |

A facility is plottable if it has at least one reporting year with a non-null
coordinate, not `(0, 0)`, longitude in `[-32, 45]` and latitude in `[27, 72]`.
The latest valid point is used. The quality report counts **2,464 source rows**
with missing or out-of-window coordinates; those rows are still included in
mass totals, and a facility is only unplottable when no year has a valid point.

The strict LAU join produced:

| LAU join result | Count | Share |
|---|---:|---:|
| Unique facility coordinates | 30,429 | 100% |
| Coordinates matched | 26,395 | 86.7% |
| Coordinates unmatched | 4,034 | 13.3% |
| Facilities with a LAU | 27,574 | 85.8% |
| Facilities without a LAU | 4,581 | 14.2% |

Unmatched facilities are concentrated where the 2024 GISCO layer has no or
partial polygons: United Kingdom 2,713, Norway 1,515, Belgium 112, Italy 67,
France 60, Spain 37, Denmark 15, Ireland 9, Germany 8 and 45 across the other
23 countries. There is no nearest-neighbour fallback; an unmatched point stays
unlabelled. The facility is still plotted if its coordinate is valid.

The city index has 37,237 entries, of which 12,490 contain at least one
facility. It is built from LAU polygons (all facility LAUs plus LAUs with
population ≥ 1,000), not from the free-text `city` field. French and Spanish
source populations are 0, so the boundary underlay is built from city-index IDs
rather than a population filter; otherwise those countries would disappear.

## 7. Facility concentration

Mass is highly concentrated. The single largest facility, Bełchatów in Poland,
reported 0.597 Gt over 2007–2024, **1.92%** of all counted mass. The ten largest
facilities account for **10.71%**, the top 50 for 25.06% and the top 100 for
35.39%.

| Facility | Country | Total Gt | Classified Mt |
|---|---|---:|---:|
| Elektrownia Bełchatów | Poland | 0.597 | 0.300 |
| RWE Power AG (Grevenbroich) | Germany | 0.430 | 0.095 |
| RWE Kraftwerk Niederaußem | Germany | 0.418 | 0.081 |
| LEAG Kraftwerk Jänschwalde | Germany | 0.379 | 0.200 |
| Drax Power Station | United Kingdom | 0.311 | 0.144 |
| RWE Power AG (Eschweiler) | Germany | 0.306 | 0.143 |
| Kraftwerk Boxberg | Germany | 0.288 | 0.089 |
| ENEA Wytwarzanie | Poland | 0.221 | 0.051 |
| LEAG Kraftwerk Schwarze Pumpe | Germany | 0.196 | 0.027 |
| LEAG Kraftwerk Lippendorf | Germany | 0.180 | 0.009 |

The top of the total-mass ranking is almost entirely large combustion
plants. Their classified share is tiny because most of their mass is CO₂. The
pattern reverses for heavy industry: ArcelorMittal France ranks 11th by total mass
(0.176 Gt) but reports 1.883 Mt of classified mass, about 1.1% of its own
release mass, versus 0.05% at Bełchatów.

This concentration has two consequences. National totals and rankings can be
moved by a handful of sites, and a map scaled by total mass mostly shows large
combustion plants. The dashboard therefore offers classified mass as a separate
metric instead of treating total kilograms as a hazard score.

## 8. Reconciliation checks

| Check | Result |
|---|---|
| `facility_year.all_kg` total | 31,060,266,958,075.6 kg |
| `country_year` air + water total | 31,060,266,958,075.6 kg |
| `pollutant_year.kg_counted` total | 31,060,266,958,075.6 kg |
| `hazard_mass.total_mass_kg` | 31,060,266,958,075.6 kg |
| Classified total across exports | 58,594,048,749.0 kg |
| Facility-year rows = release records | 245,515 = 245,515 |
| Country-year rows | 542 |
| Pollutant-year rows | 2,213 |
| Raw mass before CO₂ correction | 35,490,921,724,015.2 kg |
| Nested CO₂ mass removed | 4,430,654,765,939.6 kg |
| Counted mass after CO₂ correction | 31,060,266,958,075.6 kg |

The CO₂ correction is internally consistent: raw minus nested equals counted.
The correction removes **12.48%** of the raw total. The counted total is
therefore **12.48%** smaller than raw, and the removed mass equals **14.26%** of
the counted total. It is not a general estimate of biomass emissions; it removes
only the nested duplicate mass.

Other invariants verified by the build:

* 0 missing facility IDs, pollutant labels or country names after filtering;
* 0 negative masses, 0 unknown pollutant labels and 0 duplicate keys;
* 28 exact duplicates removed, with no remaining repeated key;
* 53 confidential rows retained as flags, not converted to zero;
* 73 of 94 labels are assessable; 21 are level 0 on both media;
* no pollutant label remains at level 1 in this snapshot.

## 9. Known gaps and caveats

* **Threshold inventory, not a census.** E-PRTR includes facilities and
  pollutants only above Annex II reporting thresholds. A missing row does not
  mean zero release, and a facility below a threshold can be absent in one year
  and present in another.
* **Mass is not CO₂-equivalent.** Total mass adds kilograms of CO₂, metals,
  nutrients and organic substances. It is a screening volume, not a climate or
  toxicity metric. Greenhouse gases are not converted with global-warming
  potentials, and pollutant masses are not toxicity-weighted.
* **Hazard levels are screening flags, not risk.** IARC, CLP, SVHC, EPA HAP and
  WFD evidence says a substance appears on a list; it does not measure exposure,
  dose, bioavailability or local impact. See
  [`03_hazard_classification.md`](03_hazard_classification.md).
* **Confidential releases are omitted.** The 53 suppressed rows make affected
  facility-year totals lower bounds. Their pollutant identity is unavailable, so
  their hazard class cannot be recovered.
* **The country panel changes over time.** Norway last reports in 2017 and the
  United Kingdom in 2019; 2023 has 24 reporting countries and 2024 has 23,
  against 30–32 earlier. Facility counts and mass in the later years must not be
  read as closures or as a clean trend.
* **The panel is unbalanced.** Facilities enter and leave the register. Mass
  changes mix real emission changes, plant closures, reporting thresholds and
  administrative reporting completeness. No production, capacity or activity
  denominator is available in this extract.
* **One static metadata row per facility.** Name, country, sector and activity
  come from the latest year, while coordinates use the latest valid point. A
  facility that changed owner, sector or location is represented by one current
  description across all years.
* **LAU geography is a 2024 snapshot.** It is applied to every year, contains no
  UK polygons and has partial Norwegian coverage. The strict point-in-polygon
  join leaves 4,581 facilities unlabelled; it does not guess a neighbouring
  municipality.
* **Coordinates are reported, not surveyed.** 199 facilities have no plottable
  point (missing, `(0, 0)` or outside the Europe window). Approximate or
  misplaced points can put a facility in the wrong LAU even when the join
  succeeds.
* **Source values are trusted.** `Releases` is interpreted as kg/year from the
  user-friendly E-PRTR tables; there is no independent unit, transcription or
  laboratory check, and no uncertainty estimate is published with the extract.
* **CO₂ labels overlap.** `Carbon dioxide (CO2)` includes biomass; the
  `excluding biomass` label is nested. The build keeps `max(total, excluding
  biomass)` per facility-year. This prevents 4.43 Gt of double counting but
  cannot reconstruct a biomass-only split where a facility reports only the
  total.
* **Sector is not a complete predictor.** 913 facilities have no sector and are
  kept as unknown. Sector labels are not independently validated against the
  facility's actual Annex I activity.
* **Aggregate labels are not assessable.** NOx, SOx, PM, TOC, total N/P, AOX,
  chloride and similar parameters have no single-substance hazard class. Their
  mass is included in totals but not in the classified metric.

## 10. Reproducing the audit

```bash
python3 analysis/build_dataset.py
```

The build writes `analysis/outputs/quality_report.json` and the three flat
tables. Re-running on the same inputs produces the same tables apart from the
`generated` date. The LAU lookup is cached in
`analysis/outputs/lau_lookup.csv`; delete that cache after changing the LAU
source or coordinate window so the join is recomputed.

A quick reconciliation:

```bash
python3 - <<'PY'
import json
import pandas as pd

fy = pd.read_csv("analysis/outputs/facility_year.csv", low_memory=False)
cy = pd.read_csv("analysis/outputs/country_year.csv")
py = pd.read_csv("analysis/outputs/pollutant_year.csv")
q = json.load(open("analysis/outputs/quality_report.json"))

print(fy.all_kg.sum())
print(cy.air_kg.sum() + cy.water_kg.sum())
print(py.kg_counted.sum())
print(q["hazard_mass"]["total_mass_kg"])
print(fy.haz_kg.sum(), q["hazard_mass"]["classified_mass_kg"])
print(len(fy), sum(q["release_file_records"].values()))
PY
```

All four total-mass lines must agree to floating-point rounding, and the two
classified-mass lines must agree, before quoting any figure in this report.

