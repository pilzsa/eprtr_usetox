"""Build the per-substance mass table behind the composition panel.

Inputs (all produced by earlier pipeline steps, all in the repository)
----------------------------------------------------------------------
`analysis/outputs/pollutant_year.csv`  substance x year x medium masses
`dashboard/data/pollutants.json`       hazard level of every label and medium
`dashboard/data/releases/YYYY.json`    facility records, used for a check only

Outputs
-------
`dashboard/data/substances.json`        compact table for the browser
`analysis/outputs/quality_report.json`  new `substances` section
`dashboard/data/quality_report.json`    copy of the same section

Mass basis
----------
The table sums ``kg_counted`` from ``pollutant_year.csv``, not the raw ``kg``
column.  "CO2 excluding biomass" is nested inside "CO2" and is subtracted once
per facility-year in `build_dataset.py`; using ``kg_counted`` keeps the
substance table consistent with the map's "total mass" metric and with
``releases/YYYY.json``.  This script reconciles the two sources per year and
stops if they differ by more than one kilogram (rounding drift is < 1 kg).

A substance is *hazard-classified* when its level for the reported medium is
2 or higher, exactly the rule used for the "classified mass" metric.  The
browser derives the same split from ``pollutants.json``; this script records
the totals so the split can be audited without a browser.

The script uses the standard library only, because `scripts/build_site.sh` and
the Pages workflow run it before rendering; neither installs numpy/pandas.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "analysis" / "outputs"
DASH = ROOT / "dashboard" / "data"
POLLUTANT_YEAR = OUT / "pollutant_year.csv"
POLLUTANTS = DASH / "pollutants.json"
RELEASES = DASH / "releases"
QUALITY = OUT / "quality_report.json"
TARGET = DASH / "substances.json"

TOLERANCE_KG = 1.0
MEDIA = ("air", "water")


def load_pollutants(path: Path = POLLUTANTS) -> dict[int, dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {int(row["i"]): row for row in payload["pollutants"]}


def clean_mass(value: float) -> float:
    """Round to grams and normalise negative zero for stable JSON."""
    number = round(float(value), 3)
    return 0.0 if number == 0 else number


def number_or_none(value):
    """`float(value)`, or None for blanks, NaN and infinities (pandas parity)."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def build_rows(pollutant_year: Path, pollutants: dict[int, dict]) -> list[list]:
    """Return [year, p_idx, air_kg, water_kg, air_facilities, water_facilities]."""
    cells: dict[tuple[int, int], list] = {}
    with pollutant_year.open(newline="", encoding="utf-8") as handle:
        for record in csv.DictReader(handle):
            medium = (record.get("medium") or "").strip()
            if medium not in MEDIA:
                continue
            try:
                year = int(float(record["year"]))
                p_idx = int(float(record["p_idx"]))
            except (KeyError, TypeError, ValueError) as exc:
                raise SystemExit(f"{pollutant_year}: bad year/p_idx: {exc}")
            kg = number_or_none(record.get("kg_counted")) or 0.0
            facilities = number_or_none(record.get("facilities_counted")) or 0.0
            slot = cells.setdefault((year, p_idx), [0.0, 0.0, 0, 0])
            if medium == "air":
                slot[0] += max(kg, 0.0)
                slot[2] += int(facilities)
            else:
                slot[1] += max(kg, 0.0)
                slot[3] += int(facilities)

    unknown = sorted({p_idx for _, p_idx in cells} - set(pollutants))
    if unknown:
        raise SystemExit(f"pollutant ids missing from pollutants.json: {unknown}")

    rows = [
        [year, p_idx, clean_mass(air_kg), clean_mass(water_kg),
         air_facilities, water_facilities]
        for (year, p_idx), (air_kg, water_kg, air_facilities, water_facilities)
        in sorted(cells.items())
        if air_kg > 0 or water_kg > 0
    ]
    if not rows:
        raise SystemExit(f"{pollutant_year} produced no substance rows")
    return rows


def substance_totals(rows: list[list], pollutants: dict[int, dict]):
    """Mass per year and the part carried by substances with level >= 2."""
    total: dict[int, float] = defaultdict(float)
    hazardous: dict[int, float] = defaultdict(float)
    for year, p_idx, air_kg, water_kg, _, _ in rows:
        levels = pollutants[p_idx]["levels"]
        total[year] += air_kg + water_kg
        if int(levels["air"]) >= 2:
            hazardous[year] += air_kg
        if int(levels["water"]) >= 2:
            hazardous[year] += water_kg
    return total, hazardous


def release_totals(directory: Path = RELEASES):
    """Read the browser records: [fac, air, water, all, air_haz, water_haz, haz, ...]."""
    total: dict[int, float] = {}
    hazardous: dict[int, float] = {}
    for path in sorted(directory.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        year = int(payload.get("year") or path.stem)
        records = payload.get("records") or []
        total[year] = math.fsum(float(row[3] or 0) for row in records)
        hazardous[year] = math.fsum(float(row[6] or 0) for row in records)
    return total, hazardous


def reconcile(sub_total, sub_haz, ref_total, ref_haz):
    """Compare the substance table with the release records, year by year."""
    common = sorted(set(sub_total) & set(ref_total))
    if not common:
        raise SystemExit(f"no overlapping years between substances.json and {RELEASES}")
    worst = {"year": None, "delta_kg": 0.0, "metric": ""}
    checks = []
    for year in common:
        for metric, mine, reference in (
            ("total", sub_total[year], ref_total[year]),
            ("hazardous", sub_haz[year], ref_haz[year]),
        ):
            delta = abs(mine - reference)
            checks.append((year, metric, mine, reference, delta))
            if delta > worst["delta_kg"]:
                worst = {"year": year, "delta_kg": delta, "metric": metric}
    missing = sorted(set(ref_total) - set(sub_total))
    if missing:
        raise SystemExit(f"release records exist for years without substances: {missing}")
    if worst["delta_kg"] > TOLERANCE_KG:
        detail = (f"{worst['metric']} {worst['year']}: {worst['delta_kg']:.3f} kg "
                  f"(tolerance {TOLERANCE_KG} kg)")
        raise SystemExit(f"substances.json does not reconcile with releases/*.json: {detail}")
    return checks, worst


def quality_section(rows, sub_total, sub_haz, worst, checks):
    years = sorted(sub_total)
    return {
        "source": "analysis/outputs/pollutant_year.csv",
        "mass_basis": (
            "kg_counted: CO2 excluding biomass is nested in total CO2 and is "
            "subtracted once per facility-year before summing"
        ),
        "substances_with_mass": len({row[1] for row in rows}),
        "substance_year_rows": len(rows),
        "years": years,
        "hazard_rule": "hazardous = substance level >= 2 for the reported medium",
        "totals_by_year": {
            str(year): {
                "total_kg": clean_mass(sub_total[year]),
                "hazardous_kg": clean_mass(sub_haz[year]),
                "hazardous_share": (
                    round(sub_haz[year] / sub_total[year], 6) if sub_total[year] else 0.0
                ),
            }
            for year in years
        },
        "reconciliation": {
            "reference": "dashboard/data/releases/YYYY.json",
            "years_compared": len(years),
            "checks": len(checks),
            "max_abs_delta_kg": clean_mass(worst["delta_kg"]),
            "worst_year": worst["year"],
            "worst_metric": worst["metric"],
            "tolerance_kg": TOLERANCE_KG,
        },
        "notes": [
            "Negative and missing masses are already excluded by build_dataset.py; "
            "this table contains reported, non-negative masses only.",
            "Facility counts are the number of facilities with a positive counted "
            "mass for that substance and medium.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pollutant-year", type=Path, default=POLLUTANT_YEAR,
                        help="substance x year x medium CSV from build_dataset.py")
    parser.add_argument("--out", type=Path, default=TARGET,
                        help="destination for the compact JSON")
    parser.add_argument("--dry-run", action="store_true",
                        help="check and print, but do not write any file")
    args = parser.parse_args()

    if not args.pollutant_year.exists():
        raise SystemExit(
            f"{args.pollutant_year} is missing; run analysis/build_dataset.py first"
        )

    pollutants = load_pollutants()
    rows = build_rows(args.pollutant_year, pollutants)
    sub_total, sub_haz = substance_totals(rows, pollutants)
    ref_total, ref_haz = release_totals()
    checks, worst = reconcile(sub_total, sub_haz, ref_total, ref_haz)
    years = sorted(sub_total)

    payload = {
        "years": years,
        "media": list(MEDIA),
        "columns": ["year", "pollutant", "air_kg", "water_kg",
                    "air_facilities", "water_facilities"],
        "mass_basis": "kg_counted",
        "rows": rows,
    }

    print(f"substances: {len(rows):,} substance-year rows, "
          f"{len({row[1] for row in rows})} substances, {len(years)} years")
    for year in years[-3:]:
        share = sub_haz[year] / sub_total[year] if sub_total[year] else 0.0
        print(f"  {year}: total {sub_total[year]:,.0f} kg · "
              f"hazardous {sub_haz[year]:,.0f} kg ({share:.3%})")
    print(f"reconciliation: max |Δ| = {worst['delta_kg']:.3f} kg over "
          f"{len(checks)} checks (tolerance {TOLERANCE_KG} kg)")

    if args.dry_run:
        print("dry run: no files written")
        return

    args.out.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {args.out} ({args.out.stat().st_size / 1024:.0f} KB)")

    section = quality_section(rows, sub_total, sub_haz, worst, checks)
    for target in (QUALITY, DASH / "quality_report.json"):
        if not target.exists():
            print(f"note: {target} does not exist; section not added there")
            continue
        report = json.loads(target.read_text(encoding="utf-8"))
        report["substances"] = section
        target.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
