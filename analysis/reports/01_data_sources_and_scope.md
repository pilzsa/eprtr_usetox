# Data sources and scope

## Reporting tables

The build reads the **facility-level** air and water release tables from EEA
industrial reporting dataset v16 (`2007–2024`, published 2026-02-16):

| Input | Data rows | Contents |
|---|---:|---|
| `F1_4_Air_Releases_Facilities.csv` | 372,206 | one row per facility × year × pollutant released to air |
| `F2_4_Water_Releases_Facilities.csv` | 254,156 | one row per facility × year × pollutant released to water |
| **total** | **626,362** | before removal of 28 exact duplicates |

Both files use the same 16 columns:

`PublicationDate`, `countryName`, `reportingYear`, `EPRTR_SectorCode`,
`EPRTR_SectorName`, `EPRTRAnnexIMainActivity`, `FacilityInspireId`,
`facilityName`, `city`, `Longitude`, `Latitude`, `addressConfidentialityReason`,
`TargetRelease`, `Pollutant`, `Releases`, `confidentialityReason`.

The build derives `medium` from the source table, converts `Releases` to
numeric kilograms (`kg`), and parses `reportingYear` to `year`.

### Definitions

* **Release** is an emission to air or a direct discharge to water, in
  **kilograms per facility per year**. Off-site transfers of waste or
  pollutants, waste transfers, LCP energy data and IED installation records are
  outside this dashboard.
* A **record** in the dashboard is a facility-year aggregate across pollutants
  and media; a **pollutant report** is a positive facility-year-medium-pollutant
  group. One facility can report many pollutants to both media in a year.
* `FacilityInspireId` is the facility key. It is stable across the years in the
  extract and is the only identifier used for joins.
* The pollutant labels are E-PRTR's own labels. They include single substances,
  substance groups (e.g. PCBs, dioxins), aggregate indicators (NOx, SOx, PM10,
  PM2.5, TOC, total N/P, AOX, chlorides), greenhouse gases and a
  `CONFIDENTIAL` placeholder. See the classification report for the 94-label
  inventory.

## Years and coverage

The tables cover **2007–2024** for both media. The year counts below are after
removing the 28 exact duplicate rows (all in the air file), so they sum to
626,334 rather than the 626,362 source rows above.

| Year | Air rows | Water rows | Total |
|---:|---:|---:|---:|
| 2007 | 23,779 | 14,896 | 38,675 |
| 2008 | 23,684 | 16,138 | 39,822 |
| 2009 | 22,653 | 15,359 | 38,012 |
| 2010 | 22,796 | 15,982 | 38,778 |
| 2011 | 22,629 | 16,015 | 38,644 |
| 2012 | 22,231 | 16,259 | 38,490 |
| 2013 | 22,162 | 16,539 | 38,701 |
| 2014 | 21,940 | 16,604 | 38,544 |
| 2015 | 21,825 | 16,443 | 38,268 |
| 2016 | 21,702 | 16,082 | 37,784 |
| 2017 | 21,706 | 16,596 | 38,302 |
| 2018 | 21,995 | 14,033 | 36,028 |
| 2019 | 20,882 | 13,773 | 34,655 |
| 2020 | 18,305 | 9,987 | 28,292 |
| 2021 | 18,128 | 10,459 | 28,587 |
| 2022 | 17,154 | 9,937 | 27,091 |
| 2023 | 14,449 | 9,370 | 23,819 |
| 2024 | 14,158 | 9,684 | 23,842 |
| **Total** | **372,178** | **254,156** | **626,334** |

The downward row count is not by itself an emissions trend: it reflects the
changing facility population, reporting obligations and the completeness of the
latest reporting years. 2022 is the default view because 2023 and 2024 contain
noticeably fewer reporting facilities; see the quality report.

## Geographic scope

The extract is **European, not EU-27**. It contains 32 countries and 32,155
distinct facilities, including the United Kingdom, Norway, Switzerland,
Iceland and Serbia.

| Country | Facilities | Country | Facilities |
|---|---:|---|---:|
| Spain | 5,450 | Sweden | 487 |
| France | 4,304 | Serbia | 403 |
| Italy | 3,632 | Bulgaria | 305 |
| Germany | 3,027 | Ireland | 291 |
| United Kingdom | 2,713 | Austria | 238 |
| Norway | 1,736 | Lithuania | 234 |
| Poland | 1,437 | Slovakia | 208 |
| Czechia | 1,074 | Greece | 153 |
| Hungary | 954 | Switzerland | 149 |
| Belgium | 928 | Slovenia | 124 |
| Denmark | 913 | Estonia | 95 |
| Netherlands | 864 | Cyprus | 87 |
| Romania | 864 | Latvia | 71 |
| Portugal | 719 | Croatia | 47 |
| Finland | 544 | Luxembourg | 44 |
| | | Iceland | 43 |
| | | Malta | 17 |

Country names are used for display; `cc` is a two-letter code derived from a
fixed name→ISO map. The map uses the same codes as the country outline
properties.

Facility counts cover the whole 2007–2024 extract, not every year. Norway's last
reporting year is 2017 and the United Kingdom's is 2019, so later-year country
totals exclude both. This is a reporting-participation change, not a statement
about closures.

## Coordinate reference systems

* Source facility coordinates are **WGS84 longitude/latitude** in the CSV.
* The LAU GeoPackage is in **ETRS89-LAEA, EPSG:3035** metres.
* The dashboard stores facility coordinates as WGS84 and draws them with a
  fixed `geoIdentity` transform calibrated to EPSG:3035 metres; no projection
  library is shipped. Boundary coordinates are therefore stored directly in
  EPSG:3035.
* LAU polygons are tested against facility points in EPSG:3035 after
  transformation from WGS84, so the join does not depend on browser projection.

## Boundary artifacts

The dashboard ships two pre-baked TopoJSON files:

| File | Source | Features | Size |
|---|---|---:|---:|
| `boundaries/countries.topojson` | EEA country outline | 74 geometries | 228 KB |
| `boundaries/lau/lau3035.topojson` | GISCO `LAU_RG_01M_2024_3035.gpkg` | 37,237 polygons | 6.6 MB |

The LAU file is generated with mapshaper from the 2024 GeoPackage:

* one polygon for every municipality in the city index (all facility LAUs plus
  LAUs with `POP_2024 ≥ 1000`);
* geometry simplified with a 2 km interval and `keep-shapes`, quantised to
  roughly 46 m, with only the country code (`c`) retained;
* no runtime simplification or spatial join in the browser;
* source population is **0 for every French and Spanish municipality**. The
  underlay is therefore built from the city-index LAU IDs, not from a
  population filter, so France and Spain are fully represented.

Known boundary gaps: the GISCO layer has no United Kingdom LAUs (2,713 UK
facilities are plotted without a municipality), Norwegian coverage is partial,
and LAU IDs that do not match any polygon stay `null`. The LAU layer is a
single 2024 snapshot applied to every reporting year because the dashboard
needs a stable geographic reference, not historical municipal boundaries.

## Source provenance and caveats

The EEA v16 extract is a compiled reporting product. Reported values can be
revised by countries after publication; the dashboard should be read as a
snapshot of v16, not as a live register. Confidential masses are suppressed by
the source and cannot be reconstructed. The `CONFIDENTIAL` pollutant label is
retained as an unassessable category so suppressed records remain visible in
counts without inventing a mass.

