"""Build the E-PRTR air/water dashboard dataset.

Inputs (all already in the repository):
  * `eea_t_ied-eprtr_p_2007-2024_v16_r00/User friendly .csv files/F1_4_Air_Releases_Facilities.csv`
  * `eea_t_ied-eprtr_p_2007-2024_v16_r00/User friendly .csv files/F2_4_Water_Releases_Facilities.csv`
  * `LAU/LAU_RG_01M_2024_3035.gpkg`
  * the five classification tables in `official_classification/`

Outputs:
  * `dashboard/data/pollutants.json`        pollutant/hazard dictionary
  * `dashboard/data/facilities.json`        static facility metadata + yearly history
  * `dashboard/data/releases/YYYY.json`     compact facility-year records
  * `dashboard/data/cities.json`            LAU search index
  * `analysis/outputs/facility_year.csv`    flat table for inspection
  * `analysis/outputs/quality_report.json`  every cleaning decision, with counts

Design rules (documented in `analysis/reports/02_data_cleaning.md`):
  * One row in the source is one facility x year x medium x pollutant.
  * `Releases` is numeric kg/year.  The user-friendly CSV has no unit column;
    E-PRTR reporting uses kg/year for air and water releases.
  * Exact duplicate rows are removed.  Remaining duplicates on
    facility x year x medium x pollutant are summed (they are separate records).
  * Negative masses (none in v16) and missing masses are excluded from mass sums
    but counted in the quality report.  Zero is kept as "reported zero".
  * Coordinates outside a broad Europe window, (0,0), or missing are kept in the
    data but not plotted; they are counted by country.
  * A facility is joined to the 2024 LAU polygon that contains its coordinate
    (EPSG:3035, point-in-polygon through GDAL's spatial filter).  No nearest-
    neighbour guessing: if no polygon contains the point, `lau` is null.
"""

from __future__ import annotations

import json
import math
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

import pandas as pd
from osgeo import ogr, osr

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "analysis"))
from hazard_rules import build_pollutant_table, cas_key  # noqa: E402

CSV_DIR = ROOT / "eea_t_ied-eprtr_p_2007-2024_v16_r00" / "User friendly .csv files"
AIR_CSV = CSV_DIR / "F1_4_Air_Releases_Facilities.csv"
WATER_CSV = CSV_DIR / "F2_4_Water_Releases_Facilities.csv"
LAU_GPKG = ROOT / "LAU" / "LAU_RG_01M_2024_3035.gpkg"
LAU_LAYER = "LAU_RG_01M_2024_3035.gpkg"

OUT = ROOT / "dashboard" / "data"
RELEASES_OUT = OUT / "releases"
ANALYSIS_OUT = ROOT / "analysis" / "outputs"
CACHE = ANALYSIS_OUT / "lau_lookup.csv"

YEARS = list(range(2007, 2025))
DEFAULT_YEAR = 2022
# Broad Europe window.  It includes the Canary Islands and the Azores/Madeira,
# but excludes the overseas territories (Reunion, French Guiana, Caribbean).
LON_MIN, LON_MAX = -32.0, 45.0
LAT_MIN, LAT_MAX = 27.0, 72.0

# Codes used in the compact year records.
MEDIUM_CODE = {"air": 0, "water": 1}


def json_round(value, digits=3):
    """Round a number for JSON, preserving None and returning 0 for -0.0."""
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    rounded = round(number, digits)
    return 0 if rounded == 0 else rounded


def valid_coord(lon, lat) -> bool:
    if lon is None or lat is None:
        return False
    try:
        lon = float(lon); lat = float(lat)
    except (TypeError, ValueError):
        return False
    if math.isnan(lon) or math.isnan(lat):
        return False
    if lon == 0 and lat == 0:
        return False
    return LON_MIN <= lon <= LON_MAX and LAT_MIN <= lat <= LAT_MAX


def read_releases() -> pd.DataFrame:
    frames = []
    for medium, path in (("air", AIR_CSV), ("water", WATER_CSV)):
        frame = pd.read_csv(path, low_memory=False)
        frame.columns = [str(column).lstrip("\ufeff") for column in frame.columns]
        frame["medium"] = medium
        frames.append(frame)
    data = pd.concat(frames, ignore_index=True)
    data["kg"] = pd.to_numeric(data["Releases"], errors="coerce")
    data["lon"] = pd.to_numeric(data["Longitude"], errors="coerce")
    data["lat"] = pd.to_numeric(data["Latitude"], errors="coerce")
    data["year"] = pd.to_numeric(data["reportingYear"], errors="coerce").astype("Int64")
    return data


def open_lau():
    driver = ogr.GetDriverByName("GPKG")
    dataset = driver.Open(str(LAU_GPKG), 0)
    if dataset is None:
        raise RuntimeError(f"Cannot open {LAU_GPKG}")
    layer = dataset.GetLayerByName(LAU_LAYER)
    if layer is None:
        raise RuntimeError(f"Cannot find layer {LAU_LAYER}")
    source = osr.SpatialReference()
    source.ImportFromEPSG(4326)
    target = layer.GetSpatialRef()
    # EPSG:3035 advertises Northing/Easting axis order.  GeoPackage geometries
    # are stored as Easting/Northing, so use the traditional GIS order.
    source.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    target.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    transform = osr.CoordinateTransformation(source, target)
    return dataset, layer, transform


def lau_fields(feature) -> dict:
    return {
        "id": feature.GetField("GISCO_ID") or "",
        "name": feature.GetField("LAU_NAME") or "",
        "cc": feature.GetField("CNTR_CODE") or "",
        "pop": json_round(feature.GetField("POP_2024"), 0),
        "area": json_round(feature.GetField("AREA_KM2"), 2),
    }


def lookup_one(layer, transform, lon: float, lat: float) -> dict | None:
    point = ogr.Geometry(ogr.wkbPoint)
    point.AddPoint_2D(lon, lat)
    point.Transform(transform)
    x, y = point.GetX(), point.GetY()
    layer.SetSpatialFilterRect(x - 2.0, y - 2.0, x + 2.0, y + 2.0)
    fallback = None
    for feature in layer:
        geometry = feature.GetGeometryRef()
        if geometry is None:
            continue
        if geometry.Contains(point):
            layer.SetSpatialFilter(None)
            return lau_fields(feature)
        if fallback is None and geometry.Intersects(point):
            fallback = lau_fields(feature)
    layer.SetSpatialFilter(None)
    return fallback


def attach_lau(facilities: pd.DataFrame, report: dict) -> pd.DataFrame:
    """Attach LAU id/name/country/population to every facility with a valid point."""
    facilities = facilities.copy()
    facilities["lau_id"] = None
    facilities["lau_name"] = None
    facilities["lau_cc"] = None
    facilities["lau_pop"] = None
    facilities["lau_area"] = None

    facilities["coord_key"] = facilities["lon"].map(lambda v: f"{v:.6f}") + "," + facilities["lat"].map(lambda v: f"{v:.6f}")
    points = facilities.loc[facilities["plot"], ["lon", "lat", "coord_key"]].drop_duplicates("coord_key")
    points = points.set_index("coord_key")
    by_key = facilities.groupby("coord_key").groups
    cached = {}
    if CACHE.exists():
        cache = pd.read_csv(CACHE)
        for _, row in cache.iterrows():
            cached[str(row["key"])] = row.to_dict()

    dataset, layer, transform = open_lau()
    found = 0
    missing = 0
    try:
        for key, row in points.iterrows():
            if key in cached:
                cached_row = cached[key]
                if pd.isna(cached_row.get("lau_id")):
                    hit = None
                else:
                    hit = {
                        "id": cached_row.get("lau_id"),
                        "name": cached_row.get("lau_name"),
                        "cc": cached_row.get("lau_cc"),
                        "pop": cached_row.get("lau_pop"),
                        "area": cached_row.get("lau_area"),
                    }
            else:
                hit = lookup_one(layer, transform, float(row["lon"]), float(row["lat"]))
                cached[key] = {
                    "key": key, "lon": row["lon"], "lat": row["lat"],
                    "lau_id": (hit or {}).get("id"), "lau_name": (hit or {}).get("name"),
                    "lau_cc": (hit or {}).get("cc"), "lau_pop": (hit or {}).get("pop"),
                    "lau_area": (hit or {}).get("area"),
                }
            if hit:
                found += 1
                rows = by_key[key]
                facilities.loc[rows, "lau_id"] = hit.get("id")
                facilities.loc[rows, "lau_name"] = hit.get("name")
                facilities.loc[rows, "lau_cc"] = hit.get("cc")
                facilities.loc[rows, "lau_pop"] = hit.get("pop")
                facilities.loc[rows, "lau_area"] = hit.get("area")
            else:
                missing += 1
    finally:
        dataset = None

    cache_frame = pd.DataFrame(cached.values())
    if not cache_frame.empty:
        cache_frame.to_csv(CACHE, index=False)
    report["lau"] = {
        "unique_points": int(len(points)),
        "points_matched": int(found),
        "points_unmatched": int(missing),
        "facilities_with_lau": int(facilities["lau_id"].notna().sum()),
        "facilities_without_lau": int(facilities["lau_id"].isna().sum()),
        "layer": f"{LAU_GPKG.name}:{LAU_LAYER} (EPSG:3035, 2024 boundaries)",
    }
    return facilities


COUNTRY_CODE = {
    "Austria": "AT", "Belgium": "BE", "Bulgaria": "BG", "Croatia": "HR", "Cyprus": "CY",
    "Czechia": "CZ", "Denmark": "DK", "Estonia": "EE", "Finland": "FI", "France": "FR",
    "Germany": "DE", "Greece": "GR", "Hungary": "HU", "Iceland": "IS", "Ireland": "IE",
    "Italy": "IT", "Latvia": "LV", "Lithuania": "LT", "Luxembourg": "LU", "Malta": "MT",
    "Netherlands": "NL", "Norway": "NO", "Poland": "PL", "Portugal": "PT", "Romania": "RO",
    "Serbia": "RS", "Slovakia": "SK", "Slovenia": "SI", "Spain": "ES", "Sweden": "SE",
    "Switzerland": "CH", "United Kingdom": "GB",
}


def prepare_facilities(data: pd.DataFrame, report: dict) -> pd.DataFrame:
    """One row per facility, with the most recent non-empty metadata."""
    data["city_clean"] = data["city"].astype("string").str.strip()
    data.loc[data["city_clean"].isin(["", "--", "nan"]), "city_clean"] = None
    data["valid_mass"] = data["kg"].notna() & (data["kg"] >= 0)
    data["plot"] = [valid_coord(lon, lat) for lon, lat in zip(data["lon"], data["lat"])]

    latest = data.sort_values(["FacilityInspireId", "year"], ascending=[True, False])
    latest = latest.drop_duplicates("FacilityInspireId")

    # Most frequent real city name (the field is often "--" or empty).
    city_counts = (data.dropna(subset=["city_clean"])
                   .groupby(["FacilityInspireId", "city_clean"]).size()
                   .reset_index(name="n")
                   .sort_values(["FacilityInspireId", "n"], ascending=[True, False])
                   .drop_duplicates("FacilityInspireId")
                   .set_index("FacilityInspireId")["city_clean"])

    # Most recent valid coordinate; if none, keep the most recent raw coordinate
    # so the quality report can still count it.
    valid_coords = data[data["plot"]].sort_values(["FacilityInspireId", "year"], ascending=[True, False])
    valid_coords = valid_coords.drop_duplicates("FacilityInspireId").set_index("FacilityInspireId")
    raw_coords = data.sort_values(["FacilityInspireId", "year"], ascending=[True, False])
    raw_coords = raw_coords.drop_duplicates("FacilityInspireId").set_index("FacilityInspireId")

    facilities = pd.DataFrame(index=latest["FacilityInspireId"].values)
    facilities.index.name = "fac_id"
    facilities["name"] = latest.set_index("FacilityInspireId")["facilityName"].fillna("Unknown facility")
    facilities["country_name"] = latest.set_index("FacilityInspireId")["countryName"].fillna("Unknown")
    facilities["sector"] = latest.set_index("FacilityInspireId")["EPRTR_SectorName"].fillna("")
    facilities["activity"] = latest.set_index("FacilityInspireId")["EPRTRAnnexIMainActivity"].fillna("")
    facilities["city"] = city_counts.reindex(facilities.index)
    facilities["lon"] = valid_coords["lon"].reindex(facilities.index)
    facilities["lat"] = valid_coords["lat"].reindex(facilities.index)
    facilities["plot"] = facilities["lon"].notna() & facilities["lat"].notna()
    # Keep raw coordinates for the report (missing/outside/0,0).
    facilities["raw_lon"] = raw_coords["lon"].reindex(facilities.index)
    facilities["raw_lat"] = raw_coords["lat"].reindex(facilities.index)
    facilities["cc"] = facilities["country_name"].map(COUNTRY_CODE).fillna("")

    raw_valid = facilities["raw_lon"].notna() & facilities["raw_lat"].notna()
    zero_zero = (facilities["raw_lon"] == 0) & (facilities["raw_lat"] == 0)
    report["coordinates"] = {
        "rows_missing_or_invalid": int((~data["plot"]).sum()),
        "facilities_without_plottable_point": int((~facilities["plot"]).sum()),
        "facilities_zero_zero": int(zero_zero.sum()),
        "facilities_outside_window": int((raw_valid & ~zero_zero & ~facilities["plot"]).sum()),
        "window": {"lon": [LON_MIN, LON_MAX], "lat": [LAT_MIN, LAT_MAX]},
    }
    return facilities


def aggregate(data: pd.DataFrame, pollutants: list[dict], report: dict):
    """Aggregate source rows to facility x year and build compact year records."""
    p_index = {row["label"]: index for index, row in enumerate(pollutants)}
    p_meta = {row["label"]: row for row in pollutants}
    unknown = sorted(set(data["Pollutant"].dropna()) - set(p_index))
    if unknown:
        raise RuntimeError(f"Unmapped pollutants: {unknown}")

    data = data.copy()
    data["p_idx"] = data["Pollutant"].map(p_index).astype("Int64")
    data["level"] = [
        p_meta[label]["level_air"] if medium == "air" else p_meta[label]["level_water"]
        for label, medium in zip(data["Pollutant"], data["medium"])
    ]
    data["assessable"] = data["Pollutant"].map(lambda label: p_meta[label]["assessable"])
    data["is_carc"] = data["Pollutant"].map(
        lambda label: bool(p_meta[label]["iarc"] or p_meta[label]["clp_carc"])
    )
    data["conf"] = data["Pollutant"].eq("CONFIDENTIAL") | data["confidentialityReason"].notna()
    # Only non-negative, reported masses enter the sums.  Missing/confidential
    # masses stay visible through the `conf` flag and the quality report.
    data["kg_clean"] = data["kg"].where(data["valid_mass"], 0.0)

    by = (data.groupby(["FacilityInspireId", "year", "medium", "p_idx"], dropna=False)
          .agg(kg=("kg_clean", "sum"), conf=("conf", "any"))
          .reset_index())

    # "CO2 excluding biomass" is a subset of total CO2, not an additional
    # emission.  Facilities that report both would otherwise be counted twice.
    # Keep one estimate per facility-year: the larger of the two labels.  The
    # nested (smaller) mass is removed from the "excluding biomass" row, so
    # `kg_counted` sums to max(total, excluding biomass) while the raw reported
    # mass remains visible in `kg`.
    co2_idx = p_index["Carbon dioxide (CO2)"]
    co2_excl_idx = p_index["Carbon dioxide (CO2) excluding biomass"]
    co2 = by[by["medium"].eq("air") & by["p_idx"].isin([co2_idx, co2_excl_idx])]
    co2_wide = co2.pivot_table(
        index=["FacilityInspireId", "year"], columns="p_idx", values="kg", aggfunc="sum"
    ).dropna()
    nested = co2_wide.min(axis=1).rename("co2_nested_kg").reset_index()
    by = by.merge(nested, on=["FacilityInspireId", "year"], how="left")
    by["co2_nested_kg"] = by["co2_nested_kg"].fillna(0.0)
    by["kg_counted"] = by["kg"] - by["co2_nested_kg"].where(
        by["medium"].eq("air") & by["p_idx"].eq(co2_excl_idx), 0.0
    )
    by["kg_counted"] = by["kg_counted"].clip(lower=0.0)
    report["co2_double_count"] = {
        "facility_years_reporting_both": int(len(co2_wide)),
        "nested_mass_kg": float(nested["co2_nested_kg"].sum()),
        "note": "CO2 excluding biomass is nested in total CO2; the smaller label is subtracted once per facility-year.",
    }

    levels = pd.DataFrame([
        {"p_idx": index, "level_air": row["level_air"], "level_water": row["level_water"],
         "assessable": row["assessable"], "is_carc": bool(row["iarc"] or row["clp_carc"])}
        for index, row in enumerate(pollutants)
    ])
    by = by.merge(levels, on="p_idx", how="left")
    by["level"] = by["level_air"].where(by["medium"] == "air", by["level_water"])
    by["kg_pos"] = by["kg_counted"] > 0
    by["is_haz"] = by["kg_pos"] & (by["level"] >= 3)
    by["is_haz_mass"] = by["kg_pos"] & (by["level"] >= 2)
    by["is_unassessed"] = by["kg_pos"] & (~by["assessable"])

    # Indicator columns for the groupby below.
    by["kg_air_all"] = by["kg_counted"].where(by["medium"] == "air", 0)
    by["kg_water_all"] = by["kg_counted"].where(by["medium"] == "water", 0)
    by["kg_air_haz"] = by["kg_counted"].where((by["medium"] == "air") & by["is_haz_mass"], 0)
    by["kg_water_haz"] = by["kg_counted"].where((by["medium"] == "water") & by["is_haz_mass"], 0)
    by["level_air_pos"] = by["level"].where((by["medium"] == "air") & by["kg_pos"], -1)
    by["level_water_pos"] = by["level"].where((by["medium"] == "water") & by["kg_pos"], -1)
    by["pid_sub"] = by["p_idx"].where(by["kg_pos"])
    by["pid_haz"] = by["p_idx"].where(by["is_haz"])
    by["pid_carc"] = by["p_idx"].where(by["kg_pos"] & by["is_carc"])
    by["pid_unassessed"] = by["p_idx"].where(by["is_unassessed"])

    grouped = by.groupby(["FacilityInspireId", "year"], dropna=False)
    summary = grouped.agg(
        air_all=("kg_air_all", "sum"),
        water_all=("kg_water_all", "sum"),
        air_haz=("kg_air_haz", "sum"),
        water_haz=("kg_water_haz", "sum"),
        max_air=("level_air_pos", "max"),
        max_water=("level_water_pos", "max"),
        n_sub=("pid_sub", "nunique"),
        n_haz=("pid_haz", "nunique"),
        n_carc=("pid_carc", "nunique"),
        n_unassessed=("pid_unassessed", "nunique"),
        conf=("conf", "any"),
    ).reset_index()
    summary["max_air"] = summary["max_air"].clip(lower=0).astype(int)
    summary["max_water"] = summary["max_water"].clip(lower=0).astype(int)
    summary["max_level"] = summary[["max_air", "max_water"]].max(axis=1)
    summary["all_kg"] = summary["air_all"] + summary["water_all"]
    summary["haz_kg"] = summary["air_haz"] + summary["water_haz"]

    # Top three by mass, plus the highest-level pollutant if it is not already
    # in that top three.  This keeps the tooltip informative even when a very
    # small mass carries the highest hazard level.
    positive = by[by["kg_pos"]].copy()
    top_mass = (positive.sort_values(["FacilityInspireId", "year", "kg_counted", "level"],
                                     ascending=[True, True, False, False])
                .groupby(["FacilityInspireId", "year"]).head(3))
    top_level = (positive.sort_values(["FacilityInspireId", "year", "level", "kg_counted"],
                                      ascending=[True, True, False, False])
                 .groupby(["FacilityInspireId", "year"]).head(1))
    top = pd.concat([top_mass, top_level]).drop_duplicates(
        ["FacilityInspireId", "year", "p_idx", "medium"])
    top["medium_code"] = top["medium"].map(MEDIUM_CODE)
    top = top.sort_values(["FacilityInspireId", "year", "kg_counted"], ascending=[True, True, False])

    top_map = {}
    for (fac_id, year), group in top.groupby(["FacilityInspireId", "year"]):
        top_map[(fac_id, int(year))] = [
            [int(row.p_idx), json_round(row.kg_counted, 3), int(row.medium_code), int(row.level)]
            for row in group.itertuples()
        ]

    report["aggregation"] = {
        "source_rows": int(len(data)),
        "groups_facility_year_medium_pollutant": int(len(by)),
        "facility_years": int(len(summary)),
        "positive_mass_rows": int((data["kg"] > 0).sum()),
        "zero_mass_rows": int((data["kg"] == 0).sum()),
        "missing_mass_rows": int(data["kg"].isna().sum()),
        "negative_mass_rows": int((data["kg"] < 0).sum()),
        "confidential_rows": int(data["conf"].sum()),
        "unknown_pollutant_labels": unknown,
    }
    return summary, by, top_map


def write_pollutants(pollutants: list[dict]):
    payload = []
    for index, row in enumerate(pollutants):
        payload.append({
            "i": index,
            "name": row["label"],
            "cas": row["cas"],
            "category": row["category"],
            "assessable": row["assessable"],
            "indicator": row["indicator"],
            "iarc": row["iarc"],
            "clp_carc": row["clp_carc"],
            "hap": row["hap"],
            "wfd": row["wfd_priority"],
            "svhc": row["svhc"],
            "levels": {"air": row["level_air"], "water": row["level_water"]},
            "flags": row["flags"],
            "note": row["note"],
        })
    (OUT / "pollutants.json").write_text(
        json.dumps({"pollutants": payload}, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    return payload


def write_facilities(facilities: pd.DataFrame, summary: pd.DataFrame):
    """Static metadata plus a compact 18-year history per facility."""
    order = facilities.sort_values(["country_name", "name", "fac_id"]).reset_index()
    fac_index = {fac_id: index for index, fac_id in enumerate(order["fac_id"])}

    history = {}
    for row in summary.itertuples():
        year = int(row.year)
        if 2007 <= year <= 2024:
            history.setdefault(row.FacilityInspireId, {})[year] = json_round(row.all_kg, 3)

    records = []
    for row in order.itertuples():
        lau = None
        if isinstance(row.lau_id, str) and row.lau_id:
            lau = [row.lau_id, row.lau_name or "", row.lau_cc or "", json_round(row.lau_pop, 0), json_round(row.lau_area, 2)]
        city = row.city
        if not isinstance(city, str) or not city:
            city = row.lau_name if isinstance(row.lau_name, str) else ""
        cc = row.cc if isinstance(row.cc, str) and row.cc else (row.lau_cc if isinstance(row.lau_cc, str) else "")
        values = history.get(row.fac_id, {})
        records.append([
            fac_index[row.fac_id],
            row.name,
            city or "",
            cc or "",
            row.country_name,
            row.sector or "",
            row.activity or "",
            json_round(row.lon, 6),
            json_round(row.lat, 6),
            1 if row.plot else 0,
            lau,
            [values.get(year) for year in YEARS],
        ])
    (OUT / "facilities.json").write_text(
        json.dumps({"years": YEARS, "facilities": records}, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    return fac_index


def clean_data(data: pd.DataFrame, report: dict) -> pd.DataFrame:
    """Normalise strings, count defects, drop exact duplicates."""
    data = data.copy()
    for column in ("FacilityInspireId", "facilityName", "countryName", "Pollutant",
                   "city", "EPRTR_SectorName", "EPRTRAnnexIMainActivity", "TargetRelease"):
        data[column] = data[column].astype("string").str.strip()
    data = data[data["year"].notna() & data["FacilityInspireId"].notna() & data["Pollutant"].notna()]
    data["year"] = data["year"].astype(int)
    data = data[data["year"].between(YEARS[0], YEARS[-1])]

    exact = data.duplicated(keep="first")
    data = data[~exact]
    key = ["FacilityInspireId", "year", "medium", "Pollutant"]
    duplicate_groups = data[data.duplicated(key, keep=False)]
    extra_duplicate_rows = int(len(duplicate_groups) - duplicate_groups.drop_duplicates(key).shape[0])

    report["cleaning"] = {
        "rows_before": int(len(exact)),
        "exact_duplicate_rows_removed": int(exact.sum()),
        "rows_after_dedupe": int(len(data)),
        "rows_sharing_facility_year_medium_pollutant": int(len(duplicate_groups)),
        "extra_rows_summed_by_key": extra_duplicate_rows,
        "missing_facility_id": int(data["FacilityInspireId"].isna().sum()),
        "missing_pollutant": int(data["Pollutant"].isna().sum()),
        "missing_country": int(data["countryName"].isna().sum()),
        "missing_city": int(data["city"].isna().sum()),
        "city_placeholder_dashdash": int(data["city"].eq("--").sum()),
        "missing_coordinates": int((data["lon"].isna() | data["lat"].isna()).sum()),
        "outside_europe_window": int((~(
            data["lon"].between(LON_MIN, LON_MAX)
            & data["lat"].between(LAT_MIN, LAT_MAX)
            & ~((data["lon"] == 0) & (data["lat"] == 0))
        )).sum()),
        "missing_mass": int(data["kg"].isna().sum()),
        "negative_mass": int((data["kg"] < 0).sum()),
        "zero_mass": int((data["kg"] == 0).sum()),
        "positive_mass": int((data["kg"] > 0).sum()),
        "confidential_mass_rows": int(data["confidentialityReason"].notna().sum()),
    }
    return data


def build_cities(facilities: pd.DataFrame, report: dict):
    """LAU search index: all facility LAUs plus reasonably sized settlements."""
    facility_lau = set(facilities["lau_id"].dropna())
    facility_count = facilities["lau_id"].value_counts().to_dict()

    dataset, layer, _ = open_lau()
    target = layer.GetSpatialRef()
    source = osr.SpatialReference()
    source.ImportFromEPSG(4326)
    target.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    source.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    inverse = osr.CoordinateTransformation(target, source)

    cities = []
    try:
        for feature in layer:
            identifier = feature.GetField("GISCO_ID") or ""
            if not identifier:
                continue
            population = feature.GetField("POP_2024")
            try:
                population = float(population)
            except (TypeError, ValueError):
                population = 0.0
            if population < 1000 and identifier not in facility_lau:
                continue
            geometry = feature.GetGeometryRef()
            if geometry is None:
                continue
            centroid = geometry.Centroid()
            centroid.Transform(inverse)
            lon, lat = centroid.GetX(), centroid.GetY()
            if not valid_coord(lon, lat):
                continue
            area = feature.GetField("AREA_KM2")
            try:
                radius = round(math.sqrt(max(float(area), 0.0) / math.pi), 2)
            except (TypeError, ValueError):
                radius = None
            cities.append([
                identifier,
                feature.GetField("LAU_NAME") or "",
                feature.GetField("CNTR_CODE") or "",
                json_round(lon, 5),
                json_round(lat, 5),
                json_round(population, 0),
                radius,
                int(facility_count.get(identifier, 0)),
            ])
    finally:
        dataset = None

    cities.sort(key=lambda row: (-row[5], row[1], row[0]))
    (OUT / "cities.json").write_text(
        json.dumps({"cities": cities}, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    report["cities"] = {
        "entries": len(cities),
        "with_facilities": int(sum(1 for row in cities if row[7] > 0)),
        "population_threshold": 1000,
        "note": "All LAUs containing a facility plus LAUs with POP_2024 >= 1000.",
    }
    return cities


def write_year_records(summary: pd.DataFrame, fac_index: dict, top_map: dict):
    """One compact file per year.

    Record layout:
      0 facility index         8 max level air
      1 air mass (kg)          9 max level water
      2 water mass (kg)       10 distinct pollutants
      3 total mass (kg)       11 pollutants with hazard level >= 3
      4 air classified mass   12 carcinogenic pollutants (IARC/CLP)
      5 water classified mass 13 unassessable pollutant groups
      6 classified mass       14 any confidential/missing mass
      7 max hazard level      15 top pollutants [p_idx, kg, medium, level]
    """
    RELEASES_OUT.mkdir(parents=True, exist_ok=True)
    counts = {}
    for year in YEARS:
        subset = summary[summary["year"] == year]
        records = []
        for row in subset.itertuples():
            fi = fac_index.get(row.FacilityInspireId)
            if fi is None:
                continue
            records.append([
                fi,
                json_round(row.air_all, 3),
                json_round(row.water_all, 3),
                json_round(row.all_kg, 3),
                json_round(row.air_haz, 3),
                json_round(row.water_haz, 3),
                json_round(row.haz_kg, 3),
                int(row.max_level),
                int(row.max_air),
                int(row.max_water),
                int(row.n_sub),
                int(row.n_haz),
                int(row.n_carc),
                int(row.n_unassessed),
                1 if row.conf else 0,
                top_map.get((row.FacilityInspireId, year), []),
            ])
        records.sort(key=lambda record: record[0])
        (RELEASES_OUT / f"{year}.json").write_text(
            json.dumps({"year": year, "records": records}, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        counts[year] = len(records)
    return counts


def write_tables(facilities: pd.DataFrame, summary: pd.DataFrame, by: pd.DataFrame,
                 pollutants: list[dict], fac_index: dict, report: dict):
    ANALYSIS_OUT.mkdir(parents=True, exist_ok=True)
    meta = facilities.reset_index()
    meta["fac_index"] = meta["fac_id"].map(fac_index)

    facility_year = summary.merge(meta, left_on="FacilityInspireId", right_on="fac_id", how="left")
    facility_year = facility_year[[
        "fac_index", "FacilityInspireId", "name", "country_name", "cc", "city", "sector",
        "activity", "lon", "lat", "plot", "lau_id", "lau_name", "year", "air_all", "water_all",
        "all_kg", "air_haz", "water_haz", "haz_kg", "max_level", "max_air", "max_water",
        "n_sub", "n_haz", "n_carc", "n_unassessed", "conf",
    ]].sort_values(["country_name", "name", "year"])
    facility_year.to_csv(ANALYSIS_OUT / "facility_year.csv", index=False)

    by = by.copy()
    by["country_name"] = by["FacilityInspireId"].map(facilities["country_name"])
    by["haz_kg"] = by["kg_counted"].where(by["is_haz_mass"], 0)
    by["carc_kg"] = by["kg_counted"].where(by["kg_pos"] & by["is_carc"], 0)
    country_year = by.groupby(["country_name", "year"]).agg(
        air_kg=("kg_air_all", "sum"), water_kg=("kg_water_all", "sum"),
        haz_kg=("haz_kg", "sum"), carc_kg=("carc_kg", "sum"),
        facilities=("FacilityInspireId", "nunique"), pollutants=("p_idx", "nunique"),
    ).reset_index()
    country_year.to_csv(ANALYSIS_OUT / "country_year.csv", index=False)

    p_names = {index: row["label"] for index, row in enumerate(pollutants)}
    pollutant_year = by.groupby(["p_idx", "year", "medium"]).agg(
        kg=("kg", "sum"), kg_counted=("kg_counted", "sum"),
        facilities=("FacilityInspireId", "nunique"),
        confidential=("conf", "any"),
    ).reset_index()
    counted_facilities = (by[by["kg_counted"] > 0]
                          .groupby(["p_idx", "year", "medium"])["FacilityInspireId"].nunique()
                          .rename("facilities_counted"))
    pollutant_year = pollutant_year.merge(
        counted_facilities, on=["p_idx", "year", "medium"], how="left")
    pollutant_year["facilities_counted"] = pollutant_year["facilities_counted"].fillna(0).astype(int)
    pollutant_year["pollutant"] = pollutant_year["p_idx"].map(p_names)
    pollutant_year["level"] = [
        pollutants[p]["level_air"] if medium == "air" else pollutants[p]["level_water"]
        for p, medium in zip(pollutant_year["p_idx"], pollutant_year["medium"])
    ]
    pollutant_year.to_csv(ANALYSIS_OUT / "pollutant_year.csv", index=False)

    missing_lau = facilities[facilities["lau_id"].isna()].reset_index()
    missing_lau.to_csv(ANALYSIS_OUT / "facilities_without_lau.csv", index=False)
    report["outputs"] = {
        "facility_year_rows": int(len(facility_year)),
        "country_year_rows": int(len(country_year)),
        "pollutant_year_rows": int(len(pollutant_year)),
        "facilities_without_lau_rows": int(len(missing_lau)),
    }


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    ANALYSIS_OUT.mkdir(parents=True, exist_ok=True)
    report = {
        "generated": date.today().isoformat(),
        "years": YEARS,
        "default_year": DEFAULT_YEAR,
        "sources": {},
    }

    raw = read_releases()
    report["sources"] = {
        "air_csv": str(AIR_CSV.relative_to(ROOT)),
        "water_csv": str(WATER_CSV.relative_to(ROOT)),
        "rows": int(len(raw)),
        "air_rows": int((raw["medium"] == "air").sum()),
        "water_rows": int((raw["medium"] == "water").sum()),
        "columns": list(raw.columns),
        "air_years": sorted(int(v) for v in raw.loc[raw["medium"] == "air", "year"].dropna().unique()),
        "water_years": sorted(int(v) for v in raw.loc[raw["medium"] == "water", "year"].dropna().unique()),
    }

    data = clean_data(raw, report)
    report["year_counts"] = {
        str(year): {
            "air": int(((data["year"] == year) & (data["medium"] == "air")).sum()),
            "water": int(((data["year"] == year) & (data["medium"] == "water")).sum()),
        } for year in YEARS
    }

    facilities = prepare_facilities(data, report)
    facilities = attach_lau(facilities, report)
    pollutants = build_pollutant_table()
    payload = write_pollutants(pollutants)

    summary, by, top_map = aggregate(data, pollutants, report)
    fac_index = write_facilities(facilities, summary)
    release_counts = write_year_records(summary, fac_index, top_map)
    write_tables(facilities, summary, by, pollutants, fac_index, report)
    build_cities(facilities, report)
    report["release_file_records"] = {str(year): count for year, count in release_counts.items()}

    report["facilities"] = {
        "total": int(len(facilities)),
        "countries": int(facilities["country_name"].nunique()),
        "with_city": int(facilities["city"].notna().sum()),
        "with_sector": int(facilities["sector"].ne("").sum()),
    }
    report["pollutants"] = {
        "total": len(pollutants),
        "assessable": int(sum(1 for row in pollutants if row["assessable"])),
        "group_indicators": int(sum(1 for row in pollutants if row["indicator"])),
        "level_air": {str(level): int(sum(1 for row in pollutants if row["level_air"] == level))
                      for level in range(6)},
        "level_water": {str(level): int(sum(1 for row in pollutants if row["level_water"] == level))
                        for level in range(6)},
        "labels": [row["label"] for row in pollutants],
        "table": payload,
    }

    positive = by[by["kg_pos"]]
    report["hazard_mass"] = {
        "positive_groups": int(len(positive)),
        "groups_level_3plus": int((positive["level"] >= 3).sum()),
        "groups_level_2": int((positive["level"] == 2).sum()),
        "groups_level_1": int((positive["level"] == 1).sum()),
        "groups_level_0": int((positive["level"] == 0).sum()),
        "confidential_groups": int(by["conf"].sum()),
        "classified_mass_kg": float(positive.loc[positive["is_haz_mass"], "kg_counted"].sum()),
        "total_mass_kg": float(positive["kg_counted"].sum()),
        "co2_nested_mass_kg": report["co2_double_count"]["nested_mass_kg"],
    }

    report["country_facilities"] = {
        str(key): int(value) for key, value in facilities["country_name"].value_counts().items()
    }
    report["missing_lau_by_country"] = {
        str(key): int(value)
        for key, value in facilities.loc[facilities["lau_id"].isna(), "country_name"].value_counts().items()
    }

    year = DEFAULT_YEAR
    subset = summary[summary["year"] == year].merge(
        facilities[["name", "country_name"]], left_on="FacilityInspireId", right_index=True
    )
    report["default_year_top"] = [
        {
            "facility": row.name, "country": row.country_name,
            "all_kg": json_round(row.all_kg, 3), "haz_kg": json_round(row.haz_kg, 3),
            "max_level": int(row.max_level),
        }
        for row in subset.sort_values("all_kg", ascending=False).head(15).itertuples()
    ]

    report["notes"] = [
        "Mass sums exclude missing and negative values; zero is kept as a reported zero.",
        "CO2 excluding biomass is nested in total CO2; the smaller label is counted once per facility-year to avoid double counting.",
        "Classified mass includes only substances with a hazard level >= 2 (CLP/IARC/EPA HAP/WFD).",
        "Aggregate indicators (NOx, SOx, PM, TOC, total N/P, AOX, chlorides) and climate gases are not assessed.",
        "LAU join is a strict point-in-polygon test against 2024 LAU boundaries; unmatched facilities stay unlabelled.",
        "The 2024 LAU layer is used for every year because the dashboard needs one stable geographic reference.",
    ]

    (ANALYSIS_OUT / "quality_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"facilities: {len(facilities):,}")
    print(f"facility-years: {len(summary):,}")
    print(f"pollutant labels: {len(pollutants)}")
    print(f"release files: {len(release_counts)}")
    print(f"quality report: {ANALYSIS_OUT / 'quality_report.json'}")


if __name__ == "__main__":
    main()
