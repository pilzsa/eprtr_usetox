"""Link IED installation permits (F6_1) to E-PRTR facilities.

Input
-----
`F6_1_IED_Installations.csv` (comma-separated, utf-8-sig BOM), the
"User friendly" permit table of the EEA IED/E-PRTR data package.  The file is
not part of the repository (320 MB); pass its location with ``--permits-csv``
or set ``EPRTR_PERMITS_CSV``.

Outputs
-------
`analysis/outputs/permits_facility.csv`     one row per E-PRTR facility
`analysis/outputs/permit_coverage.csv`      coverage per country
`analysis/outputs/permit_year_coverage.csv` coverage per reporting year
`dashboard/data/permits.json`               compact per-facility permit record
`analysis/outputs/quality_report.json`      new `permits` section (also copied
                                            to `dashboard/data/quality_report.json`)

Linkage rule
------------
* Exact match on ``parent_facilityInspireId`` == ``FacilityInspireId``.
  Case-folding or stripping punctuation adds no matches (checked in the audit),
  so the rule stays exact and therefore reproducible.
* One row per facility x reporting year: prefer a non-empty ``permitURL``,
  then the most recent ``dateOfLastUpdate``, then ``dateOfGranting``.
* One row per facility: the latest reporting year wins; missing dates fall back
  to the most recent non-null value of earlier years.
* ``1900-01-01`` is the placeholder used by the reporting tool and becomes
  null.  Dates outside 1990-2026 become null.  Every replacement is counted in
  the quality report so the site can state the loss.

The permit table covers 2017-2023 only.  A facility without a permit row may
still hold a permit - absence in this table is not evidence of non-compliance.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "analysis" / "outputs"
DASH = ROOT / "dashboard" / "data"
QUALITY = OUT / "quality_report.json"
FACILITY_YEAR = OUT / "facility_year.csv"

DEFAULT_PERMITS = Path(
    os.environ.get(
        "EPRTR_PERMITS_CSV",
        "/home/sarah/Documents/projects/2026/Toxic Zones/eprtr_data/"
        "eea_t_ied-eprtr_p_2007-2024_v16_r00/User friendly .csv files/"
        "F6_1_IED_Installations.csv",
    )
)

COLUMNS = [
    "reportingYear",
    "CountryName",
    "parent_facilityInspireId",
    "InstallationInspireId",
    "permitURL",
    "dateOfGranting",
    "dateOfLastUpdate",
]
PERMIT_MIN_YEAR, PERMIT_MAX_YEAR = 2017, 2024
DATE_MIN_YEAR, DATE_MAX_YEAR = 1990, 2026
PLACEHOLDER_DATE = pd.Timestamp("1900-01-01")


def parse_dates(series: pd.Series, label: str, stats: dict) -> pd.Series:
    """Parse ISO dates, null out the 1900 placeholder and implausible years."""
    text = series.astype("string").str.strip()
    empty = text.isna() | text.eq("")
    text = text.where(~empty, None)
    parsed = pd.to_datetime(text, errors="coerce", format="%Y-%m-%d")
    placeholder = parsed.eq(PLACEHOLDER_DATE)
    year = parsed.dt.year
    out_of_range = parsed.notna() & ((year < DATE_MIN_YEAR) | (year > DATE_MAX_YEAR))
    stats[label] = {
        "empty": int(empty.sum()),
        "placeholder_1900_01_01": int(placeholder.sum()),
        "out_of_range": int((out_of_range & ~placeholder).sum()),
        "unparsable": int((parsed.isna() & ~empty).sum()),
        "valid": int((parsed.notna() & ~out_of_range).sum()),
    }
    return parsed.where(parsed.notna() & ~out_of_range)


def clean_url(series: pd.Series, stats: dict) -> pd.Series:
    text = series.astype("string").str.strip()
    empty = text.isna() | text.eq("") | text.isin(["nan", "None", "--"])
    text = text.where(~empty, None)
    http = text.str.match(r"^https?://", case=False, na=False)
    stats["empty"] = int(empty.sum())
    stats["not_http"] = int((text.notna() & ~http).sum())
    stats["http"] = int(http.sum())
    return text


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--permits-csv", type=Path, default=DEFAULT_PERMITS)
    parser.add_argument("--dry-run", action="store_true",
                        help="print the summary without writing any file")
    args = parser.parse_args()

    path = args.permits_csv
    if not path.exists():
        raise SystemExit(
            f"permit table not found: {path}\n"
            "Pass --permits-csv PATH or set EPRTR_PERMITS_CSV."
        )

    raw = pd.read_csv(path, sep=",", encoding="utf-8-sig", dtype=str,
                      keep_default_na=False, usecols=COLUMNS, engine="c")
    raw["reporting_year"] = pd.to_numeric(raw["reportingYear"], errors="coerce")
    raw = raw[raw["reporting_year"].between(DATE_MIN_YEAR, DATE_MAX_YEAR)].copy()
    raw["reporting_year"] = raw["reporting_year"].astype(int)
    raw["parent"] = raw["parent_facilityInspireId"].astype(str).str.strip()
    raw["installation"] = raw["InstallationInspireId"].astype(str).str.strip()

    date_stats: dict = {}
    raw["date_of_granting"] = parse_dates(raw["dateOfGranting"], "dateOfGranting", date_stats)
    raw["date_of_last_update"] = parse_dates(raw["dateOfLastUpdate"], "dateOfLastUpdate", date_stats)
    url_stats: dict = {}
    raw["permit_url"] = clean_url(raw["permitURL"], url_stats)

    rows_by_year = {int(year): int(count)
                    for year, count in raw.groupby("reporting_year").size().items()}
    permit_years = sorted(rows_by_year)
    missing_years = [year for year in permit_years
                     if year < PERMIT_MIN_YEAR or year > PERMIT_MAX_YEAR]
    if missing_years:
        raise SystemExit(
            f"unexpected permit years outside {PERMIT_MIN_YEAR}-{PERMIT_MAX_YEAR}: {missing_years}")

    # --- one row per facility x reporting year ------------------------------
    raw["has_url"] = raw["permit_url"].notna().astype(int)
    per_year = raw.sort_values(
        ["parent", "reporting_year", "has_url", "date_of_last_update", "date_of_granting"],
        ascending=[True, True, False, False, False], na_position="last",
    ).drop_duplicates(["parent", "reporting_year"])

    per_year = per_year.sort_values(["parent", "reporting_year"])
    grouped = per_year.groupby("parent", sort=True)
    latest = grouped.agg(
        permit_url=("permit_url", "last"),
        date_of_granting=("date_of_granting", "last"),
        date_of_last_update=("date_of_last_update", "last"),
        first_year=("reporting_year", "min"),
        last_year=("reporting_year", "max"),
        n_years=("reporting_year", "nunique"),
        n_installations=("installation", lambda s: int(s[s.str.len() > 0].nunique())),
    )
    latest["permit_years"] = grouped["reporting_year"].apply(
        lambda s: ";".join(str(int(year)) for year in sorted(set(s)))
    )

    # --- join to the E-PRTR facility index ----------------------------------
    fac = pd.read_csv(
        FACILITY_YEAR,
        usecols=["fac_index", "FacilityInspireId", "cc", "country_name"],
        dtype={"FacilityInspireId": str},
    ).drop_duplicates("fac_index")
    if fac["fac_index"].nunique() != len(fac):
        raise SystemExit("facility_year.csv has duplicate fac_index values")
    fac["fac_id"] = fac["FacilityInspireId"].str.strip()

    merged = fac.merge(latest, left_on="fac_id", right_index=True, how="left")
    merged["has_permit"] = merged["last_year"].notna()

    def flags_for(row) -> str:
        """Name every cleaning decision that applies to this facility."""
        if not row["has_permit"]:
            return "no_permit_record"
        flags = []
        url = row["permit_url"]
        if url is None or pd.isna(url):
            flags.append("no_url")
        elif not str(url).lower().startswith(("http://", "https://")):
            flags.append("url_not_http")
        if pd.isna(row["date_of_granting"]):
            flags.append("no_grant_date")
        if pd.isna(row["date_of_last_update"]):
            flags.append("no_update_date")
        if int(row["n_installations"]) > 1:
            flags.append("multi_installation")
        return ";".join(flags)

    merged["flags"] = merged.apply(flags_for, axis=1)
    merged["grant_year"] = merged["date_of_granting"].dt.year

    out_cols = [
        "fac_index", "FacilityInspireId", "cc", "country_name", "has_permit",
        "permit_url", "date_of_granting", "date_of_last_update", "grant_year",
        "n_installations", "n_years", "permit_years", "first_year", "last_year", "flags",
    ]
    table = merged[out_cols].sort_values("fac_index").reset_index(drop=True)
    for column in ("date_of_granting", "date_of_last_update"):
        table[column] = table[column].dt.strftime("%Y-%m-%d")

    matched = int(table["has_permit"].sum())
    total = int(len(table))
    permit_only = sorted(set(latest.index) - set(fac["fac_id"]))

    # --- coverage tables -----------------------------------------------------
    table["_matched"] = table["has_permit"].astype(int)
    table["_url"] = table["permit_url"].notna().astype(int)
    table["_grant"] = table["date_of_granting"].notna().astype(int)
    by_country = (table.groupby(["cc", "country_name"], dropna=False)
                  .agg(facilities=("fac_index", "size"),
                       matched=("_matched", "sum"),
                       url=("_url", "sum"),
                       grant=("_grant", "sum"),
                       median_grant_year=("grant_year", "median"))
                  .reset_index())
    by_country["matched_pct"] = (100 * by_country["matched"] / by_country["facilities"]).round(1)
    by_country["url_pct"] = (100 * by_country["url"] /
                             by_country["matched"].where(by_country["matched"] > 0)).round(1)
    by_country["grant_pct"] = (100 * by_country["grant"] /
                               by_country["matched"].where(by_country["matched"] > 0)).round(1)
    by_country["median_grant_year"] = by_country["median_grant_year"].round(0)
    by_country = by_country.sort_values(["facilities", "cc"], ascending=[False, True])

    year_sets = {int(row.fac_index): {int(year) for year in str(row.permit_years).split(";")}
                 if isinstance(row.permit_years, str) and row.permit_years else set()
                 for row in table.itertuples()}
    reporting = pd.read_csv(FACILITY_YEAR, usecols=["fac_index", "year"]).drop_duplicates()
    by_year = []
    for year in sorted(int(value) for value in reporting["year"].unique()):
        idx = reporting.loc[reporting["year"] == year, "fac_index"]
        with_permit = sum(1 for value in idx if year in year_sets.get(int(value), set()))
        by_year.append({
            "year": year,
            "facilities": int(len(idx)),
            "matched": int(with_permit),
            "pct": round(100 * with_permit / len(idx), 1) if len(idx) else 0.0,
        })

    payload = {
        "source": {
            "file": path.name,
            "rows_used": int(len(raw)),
            "rows_by_year": rows_by_year,
            "permit_years": [min(permit_years), max(permit_years)],
        },
        "linkage": {
            "rule": "exact parent_facilityInspireId == FacilityInspireId",
            "eprtr_facilities": total,
            "matched": matched,
            "matched_pct": round(100 * matched / total, 1),
            "unmatched": total - matched,
            "permit_parents": int(len(latest)),
            "permit_parents_not_in_eprtr": len(permit_only),
        },
        "date_quality": date_stats,
        "url_quality": url_stats,
        "by_country": by_country.drop(columns=["_matched", "_url", "_grant"], errors="ignore")
                                  .to_dict("records"),
        "by_year": by_year,
        "notes": [
            "Permit records exist for 2017-2024 only; earlier years have no permit snapshot.",
            "Absence of a permit row is not evidence that a facility operates without a permit.",
            "1900-01-01 is the reporting tool's placeholder; it is reported as missing, not as a date.",
            "One permit per facility-year: non-empty URL first, then latest dateOfLastUpdate.",
        ],
    }

    if args.dry_run:
        summary = {key: payload[key] for key in
                   ("source", "linkage", "date_quality", "url_quality")}
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        print(f"countries: {len(by_country)}, years: {len(by_year)}")
        return

    OUT.mkdir(parents=True, exist_ok=True)
    clean_country = by_country.drop(columns=["_matched", "_url", "_grant"], errors="ignore")
    table.drop(columns=["_matched", "_url", "_grant"]).to_csv(
        OUT / "permits_facility.csv", index=False)
    clean_country.to_csv(OUT / "permit_coverage.csv", index=False)
    pd.DataFrame(by_year).to_csv(OUT / "permit_year_coverage.csv", index=False)

    # --- compact JSON for the two map shells --------------------------------
    def iso(value) -> str | None:
        if value is None or pd.isna(value):
            return None
        return str(value)

    compact = {}
    for row in table[table["has_permit"]].itertuples():
        compact[str(int(row.fac_index))] = [
            iso(row.permit_url),
            iso(row.date_of_granting),
            iso(row.date_of_last_update),
            int(row.n_installations),
            int(row.n_years),
            int(row.first_year),
            int(row.last_year),
        ]
    permits_json = {
        "source": "F6_1_IED_Installations.csv (EEA IED/E-PRTR v16)",
        "generated": date.today().isoformat(),
        "permit_years": [min(permit_years), max(permit_years)],
        "fields": ["url", "date_of_granting", "date_of_last_update",
                   "n_installations", "n_years", "first_year", "last_year"],
        "facilities": compact,
    }
    DASH.mkdir(parents=True, exist_ok=True)
    (DASH / "permits.json").write_text(
        json.dumps(permits_json, ensure_ascii=False, separators=(",", ":"), allow_nan=False),
        encoding="utf-8")

    # --- merge into the quality report (both copies) ------------------------
    if QUALITY.exists():
        for target in (QUALITY, DASH / "quality_report.json"):
            report = json.loads(target.read_text(encoding="utf-8"))
            report["permits"] = payload
            target.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                              encoding="utf-8")

    print(f"permit table : {len(raw):,} rows, years {min(permit_years)}-{max(permit_years)}")
    print(f"linkage      : {matched:,} / {total:,} facilities ({100 * matched / total:.1f} %)")
    print(f"permit-only  : {len(permit_only):,} parent ids absent from E-PRTR")
    print(f"written      : {OUT / 'permits_facility.csv'}, {DASH / 'permits.json'}")


if __name__ == "__main__":
    main()
