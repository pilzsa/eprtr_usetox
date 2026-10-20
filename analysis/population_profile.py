"""Population living within 0.5, 1, 3 and 5 km of every E-PRTR facility.

Source
------
JRC-ESTAT census population grid 2021, 100 m cells (EPSG:3035).  The GeoTIFF is
5 GB and is not part of the repository; pass it with ``--census-tif`` or set
``EPRTR_CENSUS_TIF``.  The grid covers the EU-27 plus Norway and Switzerland;
the United Kingdom, Serbia and Iceland (and overseas territories) are nodata.

Method
------
* WGS84 coordinates are projected to EPSG:3035 with the closed-form Lambert
  azimuthal equal-area formula (copied from ``poc-de/dashboard/census_profile.py``,
  which validates it against pyproj/GDAL to < 1 mm for Germany).
* For each *unique* coordinate the 5 km window is read once; the 0.5/1/3/5 km
  discs are evaluated on the same array, so the I/O cost is one window per
  point.
* A sum is only meaningful if the disc is covered by data.  Coverage is
  ``valid_cells * cell_area / (pi r^2)`` and is reported per facility, because
  ``nansum`` over an all-nodata window silently returns 0 - the bug that made
  London, Belgrade and Reykjavik look uninhabited in the first prototype.
* ``status``: 2 covered (>= 99 % of the disc), 1 partial (>= 50 %), 0 outside
  (< 50 %), 3 no coordinate.  A partial or outside facility has no usable
  population estimate; the site must say so instead of printing 0.

Outputs
-------
`analysis/outputs/facility_population.csv`  per facility, all radii + status
`dashboard/data/population.json`            compact rows for both map shells
`analysis/outputs/quality_report.json`      new `population` section (also
                                            copied to `dashboard/data/`)
"""

from __future__ import annotations

import argparse
import json
import math
import os
import time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "analysis" / "outputs"
DASH = ROOT / "dashboard" / "data"
QUALITY = OUT / "quality_report.json"
FACILITY_YEAR = OUT / "facility_year.csv"

DEFAULT_TIF = Path(
    os.environ.get(
        "EPRTR_CENSUS_TIF",
        "/home/sarah/Documents/GitHub/poc-de/JRC-ESTAT_Census_Population_2021_100m/"
        "JRC-ESTAT_Census_Population_2021_100m_rev0726.tif",
    )
)

RADII = (500, 1000, 3000, 5000)
POP_COLUMNS = {500: "pop_500m", 1000: "pop_1km", 3000: "pop_3km", 5000: "pop_5km"}
STATUS = {0: "outside", 1: "partial", 2: "covered", 3: "no_coordinate"}
COVERED_MIN = 0.99
PARTIAL_MIN = 0.50

# EPSG:3035 definition, GRS80 ellipsoid.
_LAEA_A = 6378137.0
_LAEA_F = 1.0 / 298.257222101
_LAEA_LAT0 = math.radians(52.0)
_LAEA_LON0 = math.radians(10.0)
_LAEA_FE = 4321000.0
_LAEA_FN = 3210000.0


def _authalic_latitude(phi: np.ndarray, e2: float) -> np.ndarray:
    """q(phi) of the ellipsoidal Lambert azimuthal equal-area (EPSG method 9820)."""
    e = math.sqrt(e2)
    sin_phi = np.sin(phi)
    return (1 - e2) * (sin_phi / (1 - e2 * sin_phi**2)
                       - (1 / (2 * e)) * np.log((1 - e * sin_phi) / (1 + e * sin_phi)))


def wgs84_to_laea3035(lon, lat):
    """WGS84 degrees -> EPSG:3035 easting/northing in metres (no PROJ needed)."""
    lon = np.radians(np.asarray(lon, dtype=np.float64))
    lat = np.radians(np.asarray(lat, dtype=np.float64))
    e2 = _LAEA_F * (2.0 - _LAEA_F)
    q_pole = float(_authalic_latitude(np.array([math.pi / 2]), e2)[0])
    q0 = float(_authalic_latitude(np.array([_LAEA_LAT0]), e2)[0])
    q = _authalic_latitude(lat, e2)
    beta = np.arcsin(np.clip(q / q_pole, -1.0, 1.0))
    beta0 = math.asin(q0 / q_pole)
    rq = _LAEA_A * math.sqrt(q_pole / 2.0)
    m0 = math.cos(_LAEA_LAT0) / math.sqrt(1 - e2 * math.sin(_LAEA_LAT0) ** 2)
    d = _LAEA_A * m0 / (rq * math.cos(beta0))
    dlon = lon - _LAEA_LON0
    b = rq * np.sqrt(2.0 / (1 + math.sin(beta0) * np.sin(beta)
                            + math.cos(beta0) * np.cos(beta) * np.cos(dlon)))
    east = _LAEA_FE + b * d * np.cos(beta) * np.sin(dlon)
    north = _LAEA_FN + (b / d) * (math.cos(beta0) * np.sin(beta)
                                  - math.sin(beta0) * np.cos(beta) * np.cos(dlon))
    return east, north


class CensusRaster:
    """Windowed reader for the JRC 100 m population grid."""

    def __init__(self, path: Path):
        from osgeo import gdal

        gdal.UseExceptions()
        self.path = Path(path)
        self.dataset = gdal.Open(str(self.path))
        if self.dataset is None:
            raise RuntimeError(f"cannot open {self.path}")
        self.band = self.dataset.GetRasterBand(1)
        self.gt = self.dataset.GetGeoTransform()
        self.width = self.dataset.RasterXSize
        self.height = self.dataset.RasterYSize
        self.nodata = self.band.GetNoDataValue()
        self.cell_area = abs(self.gt[1] * self.gt[5])

    def profile(self, px: float, py: float, radii=RADII):
        """Return ``[(population, coverage), ...]`` for one projected point.

        ``coverage`` is the share of the disc covered by valid cells.  It is
        computed against the full disc area, not against the cells that happen
        to fall inside the raster window, so a facility on the coastline cannot
        look "complete".
        """
        origin_x, pixel_x = self.gt[0], self.gt[1]
        origin_y, pixel_y = self.gt[3], self.gt[5]
        span = int(math.ceil(max(radii) / abs(pixel_x))) + 1
        centre_x = int((px - origin_x) / pixel_x)
        centre_y = int((py - origin_y) / pixel_y)
        x0 = max(0, centre_x - span)
        y0 = max(0, centre_y - span)
        x1 = min(self.width, centre_x + span + 1)
        y1 = min(self.height, centre_y + span + 1)
        if x1 <= x0 or y1 <= y0:
            return [(math.nan, 0.0) for _ in radii]
        window = self.band.ReadAsArray(x0, y0, x1 - x0, y1 - y0)
        if window is None:
            return [(math.nan, 0.0) for _ in radii]
        values = window.astype(np.float64)
        if self.nodata is not None:
            values[values == self.nodata] = np.nan
        centres_x = origin_x + (x0 + np.arange(x1 - x0) + 0.5) * pixel_x
        centres_y = origin_y + (y0 + np.arange(y1 - y0) + 0.5) * pixel_y
        distance_squared = ((centres_x[None, :] - px) ** 2
                            + (centres_y[:, None] - py) ** 2)
        valid = np.isfinite(values)

        results = []
        for radius in radii:
            inside = distance_squared <= float(radius) ** 2
            count = int(inside.sum())
            if count == 0:
                results.append((math.nan, 0.0))
                continue
            total = float(np.nansum(np.where(inside, values, 0.0)))
            covered = (float(valid[inside].sum()) * self.cell_area
                       / (math.pi * float(radius) ** 2))
            results.append((total, min(1.0, covered)))
        return results


def classify(frac_3km: float) -> int:
    if not np.isfinite(frac_3km) or frac_3km <= 0:
        return 0
    if frac_3km >= COVERED_MIN:
        return 2
    if frac_3km >= PARTIAL_MIN:
        return 1
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--census-tif", type=Path, default=DEFAULT_TIF)
    parser.add_argument("--limit", type=int, default=0,
                        help="only profile the first N facilities (no files written)")
    parser.add_argument("--dry-run", action="store_true",
                        help="compute and print the summary, write nothing")
    args = parser.parse_args()

    if not args.census_tif.exists():
        raise SystemExit(
            f"census raster not found: {args.census_tif}\n"
            "Pass --census-tif PATH or set EPRTR_CENSUS_TIF."
        )

    fac = pd.read_csv(
        FACILITY_YEAR,
        usecols=["fac_index", "FacilityInspireId", "cc", "country_name", "lon", "lat", "plot"],
        dtype={"FacilityInspireId": str},
    ).drop_duplicates("fac_index")
    fac = fac.sort_values("fac_index").reset_index(drop=True)
    fac["plot"] = fac["plot"].fillna(False).astype(bool)
    fac["key"] = (fac["lon"].round(6).astype(str) + ","
                  + fac["lat"].round(6).astype(str))
    if args.limit:
        fac = fac.head(args.limit).copy()

    plotted = fac[fac["plot"]]
    unique = plotted[["lon", "lat", "key"]].drop_duplicates("key").reset_index(drop=True)
    east, north = wgs84_to_laea3035(unique["lon"].to_numpy(), unique["lat"].to_numpy())

    raster = CensusRaster(args.census_tif)
    started = time.time()
    lookup: dict[str, tuple] = {}
    for position, row in enumerate(unique.itertuples()):
        result = raster.profile(float(east[position]), float(north[position]), RADII)
        lookup[row.key] = tuple(value for value, _ in result) + (result[2][1],
                                                                 classify(result[2][1]))
        if (position + 1) % 5000 == 0:
            print(f"  {position + 1:,} / {len(unique):,} unique points "
                  f"({time.time() - started:.0f} s)")

    missing = (np.nan, np.nan, np.nan, np.nan, np.nan, 3)
    for offset, radius in enumerate(RADII):
        fac[POP_COLUMNS[radius]] = fac["key"].map(
            lambda key: lookup.get(key, missing)[offset])
    fac["valid_frac_3km"] = fac["key"].map(lambda key: lookup.get(key, missing)[4])
    fac["status_code"] = [lookup.get(key, missing)[5] if plotted_flag else 3
                          for key, plotted_flag in zip(fac["key"], fac["plot"])]
    fac["status"] = fac["status_code"].map(STATUS)

    covered = fac["status_code"].eq(2)
    pop3 = pd.to_numeric(fac["pop_3km"], errors="coerce")
    density3 = pop3 / (math.pi * 9.0)
    density3 = density3.where(covered)
    ordered = fac[["pop_500m", "pop_1km", "pop_3km", "pop_5km"]].apply(
        pd.to_numeric, errors="coerce")
    monotonic = (ordered["pop_500m"] <= ordered["pop_1km"]) & \
                (ordered["pop_1km"] <= ordered["pop_3km"]) & \
                (ordered["pop_3km"] <= ordered["pop_5km"])
    monotonic_violations = int((covered & ~monotonic.fillna(False)).sum())

    summary = {
        "source": {
            "raster": str(args.census_tif),
            "resolution_m": round(math.sqrt(raster.cell_area), 1),
            "radii_m": list(RADII),
            "projection": "EPSG:3035 (closed-form LAEA, no PROJ dependency)",
        },
        "generated": date.today().isoformat(),
        "facilities": int(len(fac)),
        "plotted": int(fac["plot"].sum()),
        "unique_points": int(len(unique)),
        "status_counts": {name: int(fac["status"].eq(name).sum()) for name in STATUS.values()},
        "covered_pct": round(100 * float(covered.sum()) / max(len(fac), 1), 1),
        "median_pop_3km": round(float(np.nanmedian(pop3[covered])), 0) if covered.any() else None,
        "p90_pop_3km": round(float(np.nanpercentile(pop3[covered], 90)), 0) if covered.any() else None,
        "median_density_3km": round(float(np.nanmedian(density3[covered])), 1) if covered.any() else None,
        "dense_1000_per_km2": int((density3[covered] >= 1000).sum()) if covered.any() else 0,
        "monotonic_violations": monotonic_violations,
        "notes": [
            "The 2021 JRC-ESTAT grid covers the EU-27 plus Norway and Switzerland.",
            "Coverage below 50 % of the 3 km disc is reported as outside, not as zero population.",
            "Unique coordinates are profiled once; facilities sharing a coordinate share the value.",
            "Population is a model output for 2021, not a count at the facility gate.",
        ],
    }
    by_country = (fac.groupby(["cc", "country_name"], dropna=False)
                  .agg(facilities=("fac_index", "size"),
                       covered=("status_code", lambda s: int((s == 2).sum())),
                       partial=("status_code", lambda s: int((s == 1).sum())),
                       outside=("status_code", lambda s: int((s == 0).sum())),
                       no_coordinate=("status_code", lambda s: int((s == 3).sum())),
                       median_pop_3km=("pop_3km", "median"))
                  .reset_index())
    by_country["covered_pct"] = (100 * by_country["covered"]
                                 / by_country["facilities"]).round(1)
    by_country["median_pop_3km"] = by_country["median_pop_3km"].round(0)
    summary["by_country"] = by_country.sort_values("facilities", ascending=False).to_dict("records")

    if args.dry_run or args.limit:
        keys = ("facilities", "plotted", "unique_points", "status_counts", "covered_pct",
                "median_pop_3km", "p90_pop_3km", "median_density_3km", "monotonic_violations")
        print(json.dumps({key: summary[key] for key in keys}, indent=2, ensure_ascii=False))
        print(by_country.head(12).to_string(index=False))
        return

    OUT.mkdir(parents=True, exist_ok=True)
    out = fac[["fac_index", "FacilityInspireId", "cc", "country_name", "lon", "lat",
               "pop_500m", "pop_1km", "pop_3km", "pop_5km", "valid_frac_3km", "status"]].copy()
    for column in ("pop_500m", "pop_1km", "pop_3km", "pop_5km"):
        out[column] = pd.to_numeric(out[column], errors="coerce").round(0).astype("Int64")
    out["valid_frac_3km"] = pd.to_numeric(out["valid_frac_3km"], errors="coerce").round(3)
    out.to_csv(OUT / "facility_population.csv", index=False)
    by_country.sort_values("facilities", ascending=False).to_csv(
        OUT / "population_coverage.csv", index=False)

    rows = []
    for row in fac.itertuples():
        values = []
        for column in ("pop_500m", "pop_1km", "pop_3km", "pop_5km"):
            number = getattr(row, column)
            values.append(int(round(number)) if number is not None and np.isfinite(number) else None)
        rows.append(values + [int(row.status_code)])
    payload = {
        "source": "JRC-ESTAT census population grid 2021, 100 m cells",
        "generated": date.today().isoformat(),
        "radii_m": list(RADII),
        "status": {str(code): name for code, name in STATUS.items()},
        "fields": ["pop_500m", "pop_1km", "pop_3km", "pop_5km", "status"],
        "facilities": rows,
    }
    DASH.mkdir(parents=True, exist_ok=True)
    (DASH / "population.json").write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False),
        encoding="utf-8")

    if QUALITY.exists():
        for target in (QUALITY, DASH / "quality_report.json"):
            report = json.loads(target.read_text(encoding="utf-8"))
            report["population"] = summary
            target.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                              encoding="utf-8")

    print(f"points       : {len(unique):,} unique of {int(fac['plot'].sum()):,} plotted "
          f"({time.time() - started:.0f} s)")
    print(f"status       : {summary['status_counts']}")
    print(f"median 3 km  : {summary['median_pop_3km']:.0f} people; "
          f"p90 {summary['p90_pop_3km']:.0f}")
    print(f"monotonicity : {monotonic_violations} violations")
    print(f"written      : {OUT / 'facility_population.csv'}, {DASH / 'population.json'}")


if __name__ == "__main__":
    main()
