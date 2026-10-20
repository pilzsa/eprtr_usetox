"""Recompute the findings behind `findings.qmd` and `data-checks.qmd`.

Everything on the narrative pages is produced here: tables (as Markdown
includes), figures (SVG) and headline numbers.  Quarto then renders plain
Markdown, so the CI runner needs no Python kernel - only the committed outputs.

Inputs (committed / generated)
------------------------------
`analysis/outputs/facility_year.csv`     facility x year mass and hazard flags
`analysis/outputs/country_year.csv`      country x year mass, including carc_kg
`analysis/outputs/pollutant_year.csv`    pollutant x year mass
`analysis/outputs/permits_facility.csv`  permit linkage (build_permits.py)
`analysis/outputs/facility_population.csv` population within 0.5/1/3/5 km
`dashboard/data/facilities.json`         LAU population and area per facility
`dashboard/data/releases/YYYY.json`      top pollutants per facility-year
F1_4/F2_4 release CSVs                   needed only for per-facility carc mass

Outputs
-------
`analysis/data/tables/*.md`              Markdown tables included by the pages
`analysis/data/figures/*.svg`            figures referenced by the pages
`analysis/data/findings.json`            headline numbers for the home page
`analysis/outputs/facility_carc.csv`     per-facility carcinogenic mass

Definitions used on the site
----------------------------
total mass        all reported air + water mass (CO2 counted once)
classified mass   mass of substances with a hazard level >= 2
carcinogenic mass mass of IARC 1/2A/2B or CLP Carc. substances.  The pipeline's
                  own `n_carc` flag is wider (any IARC or CLP entry, including
                  IARC group 3); this script reports the strict subset and
                  validates the wider number against `country_year.csv`.
The three definitions disagree on purpose; `q7_ranking.md` shows the overlap.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
from datetime import date
from pathlib import Path
from urllib.parse import quote_plus

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
ANALYSIS = ROOT / "analysis"
OUT = ANALYSIS / "outputs"
DASH = ROOT / "dashboard" / "data"
SITE_DATA = ANALYSIS / "data"
TABLES = SITE_DATA / "tables"
FIGURES = SITE_DATA / "figures"

RELEASES_DIR = Path(
    os.environ.get(
        "EPRTR_RELEASES_DIR",
        "/home/sarah/Documents/projects/2026/Toxic Zones/eprtr_data/"
        "eea_t_ied-eprtr_p_2007-2024_v16_r00/User friendly .csv files",
    )
)

# Colours mirror `dashboard/frontend/tokens.css`; figures must match the map.
INK = "#17212c"
INK2 = "#536273"
LINE = "#d7dfe8"
BRAND = "#0d5b83"
BRAND2 = "#117a68"
HAZ3 = "#e0783b"
HAZ4 = "#bd3f5c"


def fmt_int(value) -> str:
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return "—"
    return f"{value:,.0f}"


def fmt_mass(kg) -> str:
    """kg -> human units, keeping three significant digits at most."""
    if kg is None or (isinstance(kg, float) and not math.isfinite(kg)):
        return "—"
    if kg >= 1e9:
        return f"{kg / 1e9:,.2f} Mt"
    if kg >= 1e6:
        return f"{kg / 1e3:,.0f} t"
    if kg >= 1e3:
        return f"{kg / 1e3:,.1f} t"
    return f"{kg:,.0f} kg"


def fmt_pct(value, digits: int = 1) -> str:
    if value is None or (isinstance(value, float) and not math.isfinite(value)):
        return "—"
    return f"{value:.{digits}f} %"


def md_table(frame: pd.DataFrame, align: str | None = None) -> str:
    """Render a DataFrame of *already formatted* strings as a pipe table."""
    columns = list(frame.columns)
    aligns = align or ("l" + "r" * (len(columns) - 1))
    separator = ["---:" if a == "r" else ":--" for a in aligns]
    lines = ["| " + " | ".join(columns) + " |",
             "| " + " | ".join(separator) + " |"]
    for row in frame.itertuples(index=False):
        cells = [str(value).replace("|", "\\|") for value in row]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def write_table(name: str, text: str) -> Path:
    TABLES.mkdir(parents=True, exist_ok=True)
    path = TABLES / f"{name}.md"
    path.write_text(text, encoding="utf-8")
    return path


def clean_name(name: str, limit: int = 46) -> str:
    name = " ".join(str(name).split())
    return name if len(name) <= limit else name[: limit - 1] + "…"


def facility_link(name: str, index: int, metric: str, year: int) -> str:
    label = clean_name(name)
    return (f"[{label}](map.html?year={year}&metric={metric}"
            f"&focus={int(index)}&name={quote_plus(label)})")


def spearman(left: pd.Series, right: pd.Series) -> float:
    """Rank correlation without scipy (both series must be aligned)."""
    joined = pd.concat([left, right], axis=1).dropna()
    if len(joined) < 3:
        return float("nan")
    return float(joined.iloc[:, 0].rank().corr(joined.iloc[:, 1].rank()))


def load_all_facilities() -> pd.DataFrame:
    """One row per E-PRTR facility (32,155) with the last reported metadata."""
    frame = pd.read_csv(
        OUT / "facility_year.csv",
        usecols=["fac_index", "FacilityInspireId", "name", "country_name", "cc",
                 "city", "sector", "lon", "lat", "plot", "year"],
        dtype={"FacilityInspireId": str},
    )
    frame = (frame.sort_values(["fac_index", "year"])
             .drop_duplicates("fac_index", keep="last")
             .drop(columns=["year"])
             .reset_index(drop=True))
    return frame


def load_enrichment(frame: pd.DataFrame, year: int) -> pd.DataFrame:
    """Attach permits, population and LAU context to a facility frame."""
    permits = pd.read_csv(
        OUT / "permits_facility.csv",
        usecols=["fac_index", "has_permit", "permit_url", "date_of_granting",
                 "date_of_last_update", "grant_year", "n_installations", "last_year", "flags"],
        dtype={"permit_url": str},
    )
    population = pd.read_csv(
        OUT / "facility_population.csv",
        usecols=["fac_index", "pop_500m", "pop_1km", "pop_3km", "pop_5km",
                 "valid_frac_3km", "status"],
    )
    lau = load_lau_density()
    frame = (frame.merge(permits, on="fac_index", how="left")
                  .merge(population, on="fac_index", how="left")
                  .merge(lau, on="fac_index", how="left"))
    frame["has_permit"] = frame["has_permit"].fillna(False).astype(bool)
    frame["pop3"] = frame["pop_3km"].where(frame["status"].eq("covered"))
    frame["density3"] = frame["pop3"] / (math.pi * 9.0)
    return frame


def load_lau_density() -> pd.DataFrame:
    """LAU population/area from the dashboard payload (not in facility_year)."""
    payload = json.loads((DASH / "facilities.json").read_text(encoding="utf-8"))
    rows = []
    for record in payload["facilities"]:
        lau = record[10]
        if not lau or len(lau) < 5:
            continue
        population, area = lau[3], lau[4]
        if not population or not area:
            continue
        rows.append((record[0], float(population), float(area),
                     float(population) / float(area)))
    return pd.DataFrame(rows, columns=["fac_index", "lau_pop", "lau_area", "lau_density"])


def build_carc() -> tuple[pd.DataFrame, dict]:
    """Per facility-year carcinogenic mass, reproducing build_dataset's cleaning.

    The value is validated against `country_year.csv`, which build_dataset
    writes with the same definition; a mismatch above 1 kg aborts the build.
    """
    cached = OUT / "facility_carc.csv"
    air = RELEASES_DIR / "F1_4_Air_Releases_Facilities.csv"
    water = RELEASES_DIR / "F2_4_Water_Releases_Facilities.csv"
    if not (air.exists() and water.exists()):
        if cached.exists():
            return pd.read_csv(cached), {"source": "cached", "file": str(cached)}
        raise SystemExit(
            f"release CSVs not found in {RELEASES_DIR}\n"
            "Set EPRTR_RELEASES_DIR to the 'User friendly .csv files' directory."
        )

    from hazard_rules import build_pollutant_table

    meta = {row["label"]: row for row in build_pollutant_table()}

    def strict_flag(row: dict) -> bool:
        """IARC 1/2A/2B or CLP Carc.; IARC group 3 is *not* carcinogenic."""
        return str(row.get("iarc") or "") in {"1", "2A", "2B"} or bool(row.get("clp_carc"))

    is_carc = {label: strict_flag(row) for label, row in meta.items()}
    is_flagged = {label: bool(row["iarc"] or row["clp_carc"])
                  for label, row in meta.items()}

    frames = []
    for medium, path in (("air", air), ("water", water)):
        frame = pd.read_csv(
            path, low_memory=False,
            usecols=["FacilityInspireId", "Pollutant", "Releases",
                     "reportingYear", "countryName"],
        )
        frame.columns = [str(column).lstrip("\ufeff") for column in frame.columns]
        frame["medium"] = medium
        frames.append(frame)
    data = pd.concat(frames, ignore_index=True)
    for column in ("FacilityInspireId", "Pollutant", "countryName"):
        data[column] = data[column].astype("string").str.strip()
    data["year"] = pd.to_numeric(data["reportingYear"], errors="coerce").astype("Int64")
    data["kg"] = pd.to_numeric(data["Releases"], errors="coerce")
    data = data[data["year"].notna() & data["FacilityInspireId"].notna()
                & data["Pollutant"].notna()]
    data = data[~data.duplicated(keep="first")]
    data["is_carc"] = data["Pollutant"].map(is_carc)
    data["is_flagged"] = data["Pollutant"].map(is_flagged)
    valid = data[data["kg"] >= 0]
    carc = valid[valid["is_carc"].fillna(False)]

    key = ["FacilityInspireId", "year"]
    totals = (carc.groupby(key, observed=True)["kg"].sum()
              .rename("carc_kg").reset_index())
    counts = (carc.groupby(key, observed=True)["Pollutant"].nunique()
              .rename("n_carc_strict").reset_index())
    top = (carc.loc[carc.groupby(key, observed=True)["kg"].idxmax(),
                    ["FacilityInspireId", "year", "Pollutant"]]
           .rename(columns={"Pollutant": "carc_substance"}))
    totals = totals.merge(top, on=key, how="left").merge(counts, on=key, how="left")
    mapping = pd.read_csv(
        OUT / "facility_year.csv",
        usecols=["fac_index", "FacilityInspireId", "country_name"],
        dtype={"FacilityInspireId": str},
    ).drop_duplicates("fac_index")
    totals = totals.merge(mapping, on="FacilityInspireId", how="inner")
    totals = totals[totals["carc_kg"] > 0].copy()
    totals["carc_kg"] = totals["carc_kg"].round(3)
    totals[["fac_index", "year", "carc_kg", "carc_substance", "n_carc_strict"]].to_csv(
        cached, index=False)

    # The pipeline's own `carc_kg` uses the wider "IARC or CLP flag" definition,
    # which includes IARC group 3.  Reproducing *that* number is the meaningful
    # validation of the extraction; the site then narrows it to IARC 1/2A/2B.
    flagged = (valid[valid["is_flagged"].fillna(False)]
               .groupby(key, observed=True)["kg"].sum()
               .rename("flagged_kg").reset_index()
               .merge(mapping, on="FacilityInspireId", how="inner"))
    reference = pd.read_csv(OUT / "country_year.csv")
    mine = (flagged.groupby(["country_name", "year"])["flagged_kg"].sum()
            .rename("mine").reset_index())
    check = reference.merge(mine, on=["country_name", "year"], how="left").fillna({"mine": 0})
    check["delta"] = (check["mine"] - check["carc_kg"]).abs()
    strict_by_year = totals.groupby("year")["carc_kg"].sum()
    flagged_by_year = flagged.groupby("year")["flagged_kg"].sum()
    stats = {
        "source": "F1_4 + F2_4 release CSVs",
        "facility_years": int(len(totals)),
        "definition": "IARC 1/2A/2B or CLP Carc.; IARC group 3 excluded",
        "max_abs_delta_kg": round(float(check["delta"].max()), 6),
        "max_rel_delta": round(float((check["delta"] / check["carc_kg"].abs().clip(lower=1)).max()), 9),
        "year_total_kg": {int(year): float(value) for year, value in strict_by_year.items()},
        "year_flagged_kg": {int(year): float(value) for year, value in flagged_by_year.items()},
    }
    if stats["max_abs_delta_kg"] > 1.0:
        raise SystemExit(f"flagged carc mass does not reconcile with country_year.csv: {stats}")
    return totals[["fac_index", "year", "carc_kg", "carc_substance", "n_carc_strict"]], stats


def load_pollutant_meta() -> pd.DataFrame:
    payload = json.loads((DASH / "pollutants.json").read_text(encoding="utf-8"))
    return pd.DataFrame(payload["pollutants"])


def load_top_map(year: int) -> dict[int, list]:
    payload = json.loads((DASH / "releases" / f"{year}.json").read_text(encoding="utf-8"))
    return {int(record[0]): record[15] for record in payload["records"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--year", type=int, default=None,
                        help="reporting year (default: the latest in the data)")
    parser.add_argument("--no-figures", action="store_true")
    args = parser.parse_args()

    all_fac = load_all_facilities()
    latest_year = args.year or int(pd.read_csv(
        OUT / "facility_year.csv", usecols=["year"])["year"].max())
    all_fac = load_enrichment(all_fac, latest_year)

    year_frame = pd.read_csv(
        OUT / "facility_year.csv",
        usecols=["fac_index", "year", "air_all", "water_all", "all_kg", "air_haz",
                 "water_haz", "haz_kg", "max_level", "n_sub", "n_haz", "n_carc", "conf"],
    )
    year_frame = year_frame[year_frame["year"] == latest_year]
    latest = all_fac.merge(year_frame.drop(columns=["year"]), on="fac_index", how="inner")

    carc, carc_stats = build_carc()
    latest = latest.merge(carc[carc["year"] == latest_year].drop(columns=["year"]),
                          on="fac_index", how="left")
    latest["carc_kg"] = pd.to_numeric(latest["carc_kg"], errors="coerce").fillna(0.0)
    latest["carc_substance"] = latest["carc_substance"].fillna("")
    latest["n_carc_strict"] = pd.to_numeric(latest["n_carc_strict"],
                                            errors="coerce").fillna(0).astype(int)

    pollutants = load_pollutant_meta()
    top_map = load_top_map(latest_year)

    findings = {
        "generated": date.today().isoformat(),
        "year": latest_year,
        "carc_reconciliation": carc_stats,
    }
    findings["q1"] = q1_total(latest, latest_year)
    findings["q2"] = q2_classified(latest, top_map, pollutants, latest_year)
    findings["q3"] = q3_carc(latest, pollutants, latest_year)
    findings["q4"] = q4_trend(latest_year, carc_stats)
    findings["q5"] = q5_countries(latest, latest_year)
    findings["q6"] = q6_population(latest)
    findings["q7"] = q7_exposed(latest, latest_year)
    findings["q8"] = q8_permits(all_fac, latest, latest_year)
    findings["checks"] = data_checks(all_fac, latest, latest_year, carc_stats)
    findings["headline"] = headline(findings, all_fac, latest)

    if not args.no_figures:
        make_figures(latest, findings)

    SITE_DATA.mkdir(parents=True, exist_ok=True)
    (SITE_DATA / "findings.json").write_text(
        json.dumps(findings, indent=2, ensure_ascii=False, default=float) + "\n",
        encoding="utf-8")
    print(f"year {latest_year}: {len(latest):,} facilities")
    print(f"total {fmt_mass(findings['q1']['total_kg'])}, "
          f"classified {fmt_mass(findings['q1']['class_kg'])}, "
          f"carcinogenic {fmt_mass(findings['q1']['carc_kg'])}")
    print(f"tables -> {TABLES}")
    print(f"figures -> {FIGURES}")

def q4_trend(year: int, carc_stats: dict) -> dict:
    country_year = pd.read_csv(OUT / "country_year.csv")
    yearly = (country_year.groupby("year")
              .agg(air_kg=("air_kg", "sum"), water_kg=("water_kg", "sum"),
                   class_kg=("haz_kg", "sum")))
    yearly["total_kg"] = yearly["air_kg"] + yearly["water_kg"]
    yearly["carc_kg"] = pd.Series(carc_stats["year_total_kg"]).reindex(yearly.index)
    counts = (pd.read_csv(OUT / "facility_year.csv", usecols=["year", "fac_index"])
              .groupby("year")["fac_index"].nunique())
    yearly["facilities"] = counts
    base = int(yearly.index.min())
    yearly["class_index"] = 100 * yearly["class_kg"] / yearly.loc[base, "class_kg"]
    yearly["carc_index"] = 100 * yearly["carc_kg"] / yearly.loc[base, "carc_kg"]
    yearly["total_index"] = 100 * yearly["total_kg"] / yearly.loc[base, "total_kg"]
    yearly["class_per_facility"] = yearly["class_kg"] / yearly["facilities"]

    rows = []
    for index, row in yearly.iterrows():
        rows.append([int(index), fmt_int(row["facilities"]), fmt_mass(row["total_kg"]),
                     fmt_mass(row["class_kg"]), fmt_mass(row["carc_kg"]),
                     fmt_mass(row["class_per_facility"]), f"{row['class_index']:.0f}"])
    write_table("q4_trend", md_table(
        pd.DataFrame(rows, columns=["Year", "Facilities", "Total mass", "Classified mass",
                                    "Carcinogenic mass", "Classified per facility",
                                    "Index (2007 = 100)"]),
        align="rrrrrrr"))
    yearly.reset_index().to_csv(SITE_DATA / "trend.csv", index=False)

    def change(column: str) -> float:
        return float(100 * (yearly.loc[year, column] / yearly.loc[base, column] - 1))

    return {
        "base_year": base,
        "year": int(year),
        "class_change_pct": change("class_kg"),
        "carc_change_pct": change("carc_kg"),
        "total_change_pct": change("total_kg"),
        "facilities_change_pct": change("facilities"),
        "class_per_facility_change_pct": change("class_per_facility"),
        "yearly": {int(index): {"facilities": int(row.facilities),
                                "class_kg": float(row.class_kg),
                                "carc_kg": float(row.carc_kg),
                                "total_kg": float(row.total_kg)}
                   for index, row in yearly.iterrows()},
    }


def q5_countries(latest: pd.DataFrame, year: int) -> dict:
    grouped = (latest.groupby(["cc", "country_name"])
               .agg(facilities=("fac_index", "size"),
                    total_kg=("all_kg", "sum"),
                    class_kg=("haz_kg", "sum"),
                    carc_kg=("carc_kg", "sum"),
                    covered=("pop3", "count"),
                    people_3km=("pop3", "sum"),
                    median_pop_3km=("pop3", "median"),
                    permit_pct=("has_permit", "mean"))
               .reset_index())
    grouped["class_per_facility"] = grouped["class_kg"] / grouped["facilities"]
    grouped["permit_pct"] = 100 * grouped["permit_pct"]
    grouped = grouped.sort_values("class_kg", ascending=False)
    grouped.to_csv(SITE_DATA / "countries_latest.csv", index=False)

    rows = []
    for rank, row in enumerate(grouped.head(15).itertuples(index=False), start=1):
        rows.append([rank, row.cc, row.country_name, fmt_int(row.facilities),
                     fmt_mass(row.total_kg), fmt_mass(row.class_kg), fmt_mass(row.carc_kg),
                     fmt_mass(row.class_per_facility), fmt_pct(row.permit_pct, 0)])
    write_table("q5_countries", md_table(
        pd.DataFrame(rows, columns=["#", "CC", "Country", "Facilities", "Total mass",
                                    "Classified mass", "Carcinogenic mass",
                                    "Classified per facility", "Permit records"]),
        align="rllrrrrrr"))
    top = grouped.head(3)
    return {
        "countries": int(len(grouped)),
        "class_kg": float(grouped["class_kg"].sum()),
        "top3": [{"country": row.country_name, "kg": float(row.class_kg),
                  "share": 100 * float(row.class_kg) / float(grouped["class_kg"].sum())}
                 for row in top.itertuples()],
        "no_permit": [row.country_name for row in grouped.itertuples()
                      if row.permit_pct == 0],
    }


def q6_population(latest: pd.DataFrame) -> dict:
    rows = []
    covered = latest[latest["status"].eq("covered")]
    for level in range(6):
        level_rows = latest[latest["max_level"] == level]
        level_covered = level_rows[level_rows["status"].eq("covered")]
        dense = (float((level_covered["density3"] >= 1000).mean() * 100)
                 if len(level_covered) else float("nan"))
        rows.append([
            level,
            fmt_int(len(level_rows)),
            fmt_mass(level_rows["haz_kg"].sum()),
            fmt_int(len(level_covered)),
            fmt_int(level_covered["pop3"].sum()),
            fmt_int(level_covered["pop3"].median() if len(level_covered) else None),
            fmt_int(level_covered["density3"].median() if len(level_covered) else None),
            fmt_pct(dense, 0),
        ])
    write_table("q6_levels", md_table(
        pd.DataFrame(rows, columns=["Level", "Facilities", "Classified mass",
                                    "With population", "People ≤ 3 km (sum)",
                                    "Median people ≤ 3 km", "Median density /km²",
                                    "Dense ≥ 1,000/km²"]),
        align="rrrrrrrr"))

    level3 = latest[latest["max_level"] >= 3]
    level3_covered = level3[level3["status"].eq("covered")]
    total_people = float(covered["pop3"].sum())
    return {
        "covered": int(len(covered)),
        "covered_pct": 100 * len(covered) / len(latest),
        "people_3km_all": total_people,
        "people_3km_level3": float(level3_covered["pop3"].sum()),
        "share_level3": 100 * float(level3_covered["pop3"].sum()) / total_people,
        "facilities_level3": int(len(level3)),
        "covered_level3": int(len(level3_covered)),
        "dense_level3": int((level3_covered["density3"] >= 1000).sum()),
        "median_pop_3km": float(covered["pop3"].median()),
        "p90_pop_3km": float(covered["pop3"].quantile(0.9)),
        "no_population_data": int(latest["pop3"].isna().sum()),
    }


def q7_exposed(latest: pd.DataFrame, year: int) -> dict:
    exposed = latest[latest["max_level"].ge(3) & latest["pop3"].notna()].sort_values(
        "pop3", ascending=False).head(20)
    rows = []
    for rank, row in enumerate(exposed.itertuples(index=False), start=1):
        rows.append([
            rank,
            facility_link(row.name, row.fac_index, "haz", year),
            row.country_name,
            clean_name(row.sector, 24),
            fmt_int(row.pop3),
            fmt_int(row.density3),
            fmt_mass(row.haz_kg),
            fmt_mass(row.carc_kg),
            int(row.max_level),
            "yes" if row.has_permit else "no",
        ])
    write_table("q7_exposed", md_table(
        pd.DataFrame(rows, columns=["#", "Facility", "Country", "Sector",
                                    "People ≤ 3 km", "Density /km²", "Classified mass",
                                    "Carcinogenic", "Level", "Permit record"]),
        align="rlllrrrrls"))

    hazard = latest[latest["status"].eq("covered") & latest["pop3"].notna()].copy()
    hazard["log_class"] = np.log10(hazard["haz_kg"].clip(lower=1))
    hazard["log_pop"] = np.log10(hazard["pop3"].clip(lower=1))
    rho_mass = spearman(hazard["log_class"], hazard["log_pop"])
    rho_level = spearman(hazard["max_level"], hazard["log_pop"])

    sets = {
        "Total mass": set(latest.nlargest(20, "all_kg")["fac_index"]),
        "Classified mass": set(latest.nlargest(20, "haz_kg")["fac_index"]),
        "Carcinogenic mass": set(latest.nlargest(20, "carc_kg")["fac_index"]),
        "People ≤ 3 km": set(latest.nlargest(20, "pop3")["fac_index"]),
    }
    names = list(sets)
    rows = []
    for left in names:
        rows.append([left] + [f"{len(sets[left] & sets[right])}" for right in names])
    write_table("q7_overlap", md_table(
        pd.DataFrame(rows, columns=["Top 20 by"] + names), align="l" + "r" * len(names)))
    return {
        "spearman_class_pop": rho_mass,
        "spearman_level_pop": rho_level,
        "covered_analysed": int(len(hazard)),
        "top": [{"index": int(row.fac_index), "name": row.name,
                 "pop3": float(row.pop3), "haz_kg": float(row.haz_kg)}
                for row in exposed.itertuples()],
        "overlap": {left: {right: len(sets[left] & sets[right]) for right in names}
                    for left in names},
    }


def q8_permits(all_fac: pd.DataFrame, latest: pd.DataFrame, year: int) -> dict:
    total = int(len(all_fac))
    matched = int(all_fac["has_permit"].sum())
    matched_rows = all_fac[all_fac["has_permit"]]
    grant_age = year - pd.to_numeric(matched_rows["grant_year"], errors="coerce")
    update_year = pd.to_datetime(matched_rows["date_of_last_update"], errors="coerce").dt.year
    update_age = year - update_year

    def buckets(age: pd.Series) -> list[tuple[str, int]]:
        return [
            ("No valid date", int(age.isna().sum())),
            ("0–5 years", int(((age >= 0) & (age <= 5)).sum())),
            ("6–10 years", int(((age > 5) & (age <= 10)).sum())),
            ("11–20 years", int(((age > 10) & (age <= 20)).sum())),
            ("> 20 years", int((age > 20).sum())),
            ("After reporting year", int((age < 0).sum())),
        ]

    grant_buckets = buckets(grant_age)
    update_buckets = buckets(update_age)
    write_table("q8_dates", md_table(
        pd.DataFrame([[label, fmt_int(count), fmt_pct(100 * count / len(matched_rows))]
                      for label, count in grant_buckets],
                     columns=["Permit granted", "Facilities", "Share of matched"]),
        align="lrr"))

    top50 = latest.nlargest(50, "haz_kg")
    top50_stats = {
        "with_record": 100 * float(top50["has_permit"].mean()),
        "with_url": 100 * float(top50["permit_url"].notna().mean()),
        "with_grant": 100 * float(pd.to_numeric(top50["grant_year"],
                                                errors="coerce").notna().mean()),
        "median_grant_year": float(pd.to_numeric(top50["grant_year"], errors="coerce").median()),
    }

    by_country = pd.read_csv(OUT / "permit_coverage.csv")
    by_country = by_country.sort_values(["matched_pct", "facilities"], ascending=[True, False])
    rows = []
    for row in by_country.itertuples(index=False):
        rows.append([row.cc, row.country_name, fmt_int(row.facilities), fmt_int(row.matched),
                     fmt_pct(row.matched_pct), fmt_pct(row.url_pct),
                     fmt_pct(row.grant_pct), fmt_int(row.median_grant_year)])
    write_table("q8_country", md_table(
        pd.DataFrame(rows, columns=["CC", "Country", "Facilities", "Matched", "Coverage",
                                    "With URL", "With grant date", "Median grant year"]),
        align="llrrrrrr"))

    missing = latest[(latest["max_level"] >= 3) & (~latest["has_permit"])].nlargest(10, "haz_kg")
    rows = []
    for rank, row in enumerate(missing.itertuples(index=False), start=1):
        rows.append([rank, facility_link(row.name, row.fac_index, "haz", year),
                     row.country_name, clean_name(row.sector, 26),
                     fmt_mass(row.haz_kg), int(row.max_level), fmt_int(row.pop3)])
    write_table("q8_missing", md_table(
        pd.DataFrame(rows, columns=["#", "Facility", "Country", "Sector",
                                    "Classified mass", "Level", "People ≤ 3 km"]),
        align="rlllrrr"))

    return {
        "facilities": total,
        "matched": matched,
        "coverage_pct": 100 * matched / total,
        "no_permit_countries": [row.country_name for row in by_country.itertuples()
                                if row.matched == 0],
        "countries_under_50": [row.country_name for row in by_country.itertuples()
                               if row.matched_pct < 50],
        "grant_missing_pct": 100 * float(pd.to_numeric(matched_rows["grant_year"],
                                                       errors="coerce").isna().mean()),
        "update_missing_pct": 100 * float(update_year.isna().mean()),
        "median_grant_age": float(grant_age.median()),
        "grant_buckets": {label: count for label, count in grant_buckets},
        "update_buckets": {label: count for label, count in update_buckets},
        "top50": top50_stats,
        "missing_level3": int(((latest["max_level"] >= 3) & (~latest["has_permit"])).sum()),
        "missing_level3_pct": 100 * float(((latest["max_level"] >= 3)
                                           & (~latest["has_permit"])).mean()),
    }


def data_checks(all_fac: pd.DataFrame, latest: pd.DataFrame, year: int,
                carc_stats: dict) -> dict:
    report = json.loads((OUT / "quality_report.json").read_text(encoding="utf-8"))
    permits = report.get("permits", {})
    population = report.get("population", {})
    rows = [
        ["E-PRTR facilities", fmt_int(report["facilities"]["total"])],
        ["Countries", fmt_int(report["facilities"]["countries"])],
        ["Facility-year rows", fmt_int(report["outputs"]["facility_year_rows"])],
        ["Release rows (air + water)", fmt_int(report["sources"]["rows"])],
        ["Facilities with a plottable point",
         fmt_int(report["facilities"]["total"]
                 - report["coordinates"]["facilities_without_plottable_point"])],
        ["Facilities joined to a LAU", fmt_int(report["lau"]["facilities_with_lau"])],
        ["Permit rows used", fmt_int(permits["source"]["rows_used"])],
        ["Facilities with a permit record", fmt_int(permits["linkage"]["matched"])],
        ["Facilities with covered population", fmt_int(population["status_counts"]["covered"])],
        ["Facilities with partial population", fmt_int(population["status_counts"]["partial"])],
        ["Facilities without population data",
         fmt_int(population["status_counts"]["outside"]
                 + population["status_counts"]["no_coordinate"])],
        ["Carcinogenic mass reconciliation (max abs. delta)",
         f"{carc_stats['max_abs_delta_kg']:.2f} kg"],
    ]
    write_table("checks_summary", md_table(
        pd.DataFrame(rows, columns=["Check", "Value"]), align="lr"))

    coverage = pd.read_csv(OUT / "population_coverage.csv").sort_values("covered_pct")
    rows = []
    for row in coverage.itertuples(index=False):
        rows.append([row.cc, row.country_name, fmt_int(row.facilities), fmt_int(row.covered),
                     fmt_pct(row.covered_pct), fmt_int(row.median_pop_3km)])
    write_table("checks_population", md_table(
        pd.DataFrame(rows, columns=["CC", "Country", "Facilities", "Covered",
                                    "Coverage", "Median people ≤ 3 km"]), align="llrrrr"))

    notes = report.get("notes", []) + permits.get("notes", []) + population.get("notes", [])
    write_table("checks_notes", "\n".join(f"- {note}" for note in notes) + "\n")
    return {
        "notes": len(notes),
        "graph_coverage_pct": 100 * int(report["lau"]["facilities_with_lau"])
        / int(report["facilities"]["total"]),
    }


def headline(findings: dict, all_fac: pd.DataFrame, latest: pd.DataFrame) -> dict:
    q1, q6, q8 = findings["q1"], findings["q6"], findings["q8"]
    cards = [
        (fmt_int(len(all_fac)), "facilities"),
        (fmt_int(latest["country_name"].nunique()), f"countries reporting {findings['year']}"),
        (fmt_mass(q1["class_kg"]), f"classified mass {findings['year']}"),
        (fmt_int(q6["people_3km_level3"]), "people ≤ 3 km of level ≥ 3 sites"),
        (fmt_pct(q6["covered_pct"], 0), "facilities with population data"),
        (fmt_pct(q8["coverage_pct"], 0), "facilities with a permit record"),
    ]
    html = ['<div class="kpi-grid">']
    for value, label in cards:
        html.append(f'  <div class="kpi"><span class="kpi__value">{value}</span>'
                    f'<span class="kpi__label">{label}</span></div>')
    html.append("</div>")
    write_table("headline", "\n".join(html) + "\n")
    return {"cards": [{"value": value, "label": label} for value, label in cards]}


def make_figures(latest: pd.DataFrame, findings: dict) -> None:
    """Six SVG figures; white background so they read in light and dark mode."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({
        "figure.facecolor": "#ffffff", "axes.facecolor": "#ffffff",
        "savefig.facecolor": "#ffffff", "font.size": 8.5,
        "font.family": "DejaVu Sans", "text.color": INK,
        "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
        "axes.edgecolor": LINE, "axes.linewidth": 0.8, "svg.fonttype": "none",
        "legend.frameon": False,
    })
    FIGURES.mkdir(parents=True, exist_ok=True)

    def finish(ax, grid_axis: str = "y") -> None:
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        ax.grid(axis=grid_axis, color=LINE, linewidth=0.6)
        ax.set_axisbelow(True)
        ax.tick_params(length=2)

    # 1. Trend -----------------------------------------------------------------
    trend = pd.read_csv(SITE_DATA / "trend.csv")
    fig, (left, right) = plt.subplots(1, 2, figsize=(9.4, 3.1))
    left.plot(trend["year"], trend["class_index"], color=HAZ4, lw=2, label="Classified mass")
    left.plot(trend["year"], trend["carc_index"], color=HAZ3, lw=2, label="Carcinogenic mass")
    left.plot(trend["year"], trend["total_index"], color=BRAND, lw=1.5, label="Total mass")
    left.axhline(100, color=INK2, lw=0.7, ls=":")
    left.set_ylabel("Index (2007 = 100)")
    left.legend(loc="upper right")
    right.plot(trend["year"], trend["facilities"], color=BRAND2, lw=2)
    right.set_ylabel("Facilities reporting")
    for ax in (left, right):
        finish(ax)
        ax.set_xticks(range(2007, 2025, 3))
    fig.tight_layout()
    fig.savefig(FIGURES / "trend.svg", bbox_inches="tight")
    plt.close(fig)

    # 2. Population by hazard level --------------------------------------------
    covered = latest[latest["status"].eq("covered")]
    levels = (covered.groupby("max_level")
              .agg(median_pop=("pop3", "median"),
                   dense=("density3", lambda s: float((s >= 1000).mean() * 100)))
              .reindex(range(6))
              .fillna(0))
    counts = latest.groupby("max_level").size().reindex(range(6)).fillna(0)
    fig, ax = plt.subplots(figsize=(5.2, 3.0))
    ax.bar(counts.index, counts.values, color=[BRAND if level < 3 else HAZ3
                                               for level in counts.index], width=0.7)
    ax.set_xlabel("Maximum hazard level at the facility")
    ax.set_ylabel("Facilities")
    twin = ax.twinx()
    twin.plot(levels.index, levels["median_pop"], color=INK, lw=1.6, marker="o", ms=3)
    twin.set_ylabel("Median people ≤ 3 km")
    twin.grid(False)
    for side in ("top",):
        ax.spines[side].set_visible(False)
        twin.spines[side].set_visible(False)
    ax.grid(axis="y", color=LINE, linewidth=0.6)
    ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(FIGURES / "population_by_level.svg", bbox_inches="tight")
    plt.close(fig)

    # 3. Permit coverage per country -------------------------------------------
    coverage = pd.read_csv(OUT / "permit_coverage.csv").nlargest(18, "facilities")
    coverage = coverage.sort_values("matched_pct")
    fig, ax = plt.subplots(figsize=(5.6, 3.6))
    colors = [HAZ4 if value == 0 else BRAND for value in coverage["matched_pct"]]
    ax.barh(coverage["cc"], coverage["matched_pct"], color=colors, height=0.72)
    for y, (value, matched, total) in enumerate(zip(coverage["matched_pct"],
                                                    coverage["matched"], coverage["facilities"])):
        ax.text(value + 1.5, y, f"{value:.0f} %  ({matched:,}/{total:,})",
                va="center", fontsize=7, color=INK2)
    ax.set_xlim(0, 112)
    ax.set_xlabel("Facilities with a permit record, 2017–2024 (%)")
    finish(ax, grid_axis="x")
    fig.tight_layout()
    fig.savefig(FIGURES / "permit_coverage.svg", bbox_inches="tight")
    plt.close(fig)

    # 4. Top classified facilities ---------------------------------------------
    top = latest.nlargest(15, "haz_kg").iloc[::-1]
    labels = [f"{clean_name(name, 30)} ({cc})"
              for name, cc in zip(top["name"], top["cc"])]
    fig, ax = plt.subplots(figsize=(6.4, 4.0))
    ax.barh(range(len(top)), top["haz_kg"] / 1e6, color=HAZ4, height=0.7)
    ax.set_yticks(range(len(top)), labels, fontsize=7)
    ax.set_xlabel("Classified mass 2024 (thousand tonnes)")
    finish(ax, grid_axis="x")
    fig.tight_layout()
    fig.savefig(FIGURES / "top_classified.svg", bbox_inches="tight")
    plt.close(fig)

    # 5. Exposure scatter ------------------------------------------------------
    hazard = latest[latest["status"].eq("covered") & latest["pop3"].notna()
                    & latest["haz_kg"].gt(0)]
    fig, ax = plt.subplots(figsize=(5.6, 3.6))
    ax.scatter(hazard["haz_kg"], hazard["pop3"], s=5, alpha=0.25,
               color=BRAND, linewidths=0, rasterized=True)
    highlighted = hazard.nlargest(20, "pop3")
    ax.scatter(highlighted["haz_kg"], highlighted["pop3"], s=18, color=HAZ4,
               linewidths=0.4, edgecolors="white", zorder=3)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("Classified mass 2024 (kg, log scale)")
    ax.set_ylabel("People within 3 km (log scale)")
    finish(ax, grid_axis="both")
    fig.tight_layout()
    fig.savefig(FIGURES / "exposure.svg", bbox_inches="tight")
    plt.close(fig)

    # 6. Carcinogenic substances ----------------------------------------------
    substances = findings["q3"]["substances"][:8][::-1]
    fig, ax = plt.subplots(figsize=(6.0, 3.0))
    ax.barh(range(len(substances)), [item["kg"] / 1e3 for item in substances],
            color=HAZ3, height=0.7)
    ax.set_yticks(range(len(substances)),
                  [clean_name(item["name"], 34) for item in substances], fontsize=7)
    ax.set_xlabel("Carcinogenic mass 2024 (tonnes)")
    finish(ax, grid_axis="x")
    fig.tight_layout()
    fig.savefig(FIGURES / "carc_substances.svg", bbox_inches="tight")
    plt.close(fig)


def top_substance(entries, names: dict, min_level: int) -> str:
    """Largest substance in a facility's top-emitter list at or above a level."""
    best = None
    for entry in entries or []:
        p_idx, kg, _medium, level = entry
        if int(level) < min_level:
            continue
        if best is None or kg > best[1]:
            best = (int(p_idx), kg)
    if best is None:
        return "—"
    return f"{names.get(best[0], '?')} ({fmt_mass(best[1])})"


def q1_total(latest: pd.DataFrame, year: int) -> dict:
    total_kg = float(latest["all_kg"].sum())
    class_kg = float(latest["haz_kg"].sum())
    carc_kg = float(latest["carc_kg"].sum())
    top = latest.sort_values("all_kg", ascending=False).head(12)
    rows = []
    for rank, row in enumerate(top.itertuples(index=False), start=1):
        rows.append([
            rank,
            facility_link(row.name, row.fac_index, "total", year),
            row.country_name,
            clean_name(row.sector, 28),
            fmt_mass(row.all_kg),
            fmt_mass(row.haz_kg),
            int(row.max_level),
            fmt_int(row.pop3),
        ])
    table = pd.DataFrame(rows, columns=["#", "Facility", "Country", "Sector",
                                        "Total mass", "Classified", "Level", "People ≤ 3 km"])
    write_table("q1_top_total", md_table(table, align="rllllrrr"))
    latest[["fac_index", "name", "country_name", "sector", "all_kg", "haz_kg",
            "carc_kg", "max_level", "pop3", "status"]].sort_values(
        "all_kg", ascending=False).to_csv(SITE_DATA / "facilities_latest.csv", index=False)

    pollutants = pd.read_csv(OUT / "pollutant_year.csv")
    year_rows = pollutants[pollutants["year"] == year]
    by_substance = (year_rows.groupby("pollutant")["kg_counted"].sum()
                    .sort_values(ascending=False))
    co2_kg = float(by_substance[by_substance.index.str.startswith("Carbon dioxide")].sum())
    sub_rows = []
    for name, kg in by_substance.head(8).items():
        sub_rows.append([name, fmt_mass(kg), fmt_pct(100 * kg / total_kg)])
    write_table("q1_substances", md_table(
        pd.DataFrame(sub_rows, columns=["Substance (E-PRTR label)", "Mass", "Share of total"]),
        align="lrr"))
    return {
        "total_kg": total_kg,
        "class_kg": class_kg,
        "carc_kg": carc_kg,
        "co2_kg": co2_kg,
        "co2_share": 100 * co2_kg / total_kg,
        "top": [{"index": int(row.fac_index), "name": row.name, "kg": float(row.all_kg)}
                for row in top.itertuples()],
    }


def q2_classified(latest: pd.DataFrame, top_map: dict, pollutants: pd.DataFrame,
                  year: int) -> dict:
    names = {int(row.i): row.name for row in pollutants.itertuples()}
    class_kg = float(latest["haz_kg"].sum())
    positive = latest[latest["haz_kg"] > 0].sort_values("haz_kg", ascending=False)
    top10_share = float(positive.head(10)["haz_kg"].sum()) / class_kg
    hhi = float(((positive["haz_kg"] / class_kg) ** 2).sum() * 10000)
    rows = []
    for rank, row in enumerate(positive.head(20).itertuples(index=False), start=1):
        rows.append([
            rank,
            facility_link(row.name, row.fac_index, "haz", year),
            row.country_name,
            clean_name(row.sector, 26),
            fmt_mass(row.haz_kg),
            fmt_pct(100 * row.haz_kg / class_kg),
            top_substance(top_map.get(int(row.fac_index)), names, 2),
            int(row.max_level),
        ])
    table = pd.DataFrame(rows, columns=["#", "Facility", "Country", "Sector",
                                        "Classified mass", "Share", "Largest classified substance",
                                        "Level"])
    write_table("q2_top_classified", md_table(table, align="rlllrrlr"))
    return {
        "class_kg": class_kg,
        "facilities_positive": int(len(positive)),
        "top10_share": 100 * top10_share,
        "hhi": hhi,
        "top": [{"index": int(row.fac_index), "name": row.name, "kg": float(row.haz_kg)}
                for row in positive.head(20).itertuples()],
    }


def q3_carc(latest: pd.DataFrame, pollutants: pd.DataFrame, year: int) -> dict:
    carc_kg = float(latest["carc_kg"].sum())
    positive = latest[latest["carc_kg"] > 0].sort_values("carc_kg", ascending=False)
    top10_share = float(positive.head(10)["carc_kg"].sum()) / carc_kg
    rows = []
    for rank, row in enumerate(positive.head(20).itertuples(index=False), start=1):
        rows.append([
            rank,
            facility_link(row.name, row.fac_index, "carc", year),
            row.country_name,
            clean_name(row.sector, 26),
            fmt_mass(row.carc_kg),
            fmt_pct(100 * row.carc_kg / carc_kg),
            clean_name(row.carc_substance, 30),
            int(row.n_carc_strict),
            fmt_int(row.pop3),
        ])
    table = pd.DataFrame(rows, columns=["#", "Facility", "Country", "Sector",
                                        "Carcinogenic mass", "Share", "Largest carcinogen",
                                        "Substances", "People ≤ 3 km"])
    write_table("q3_top_carc", md_table(table, align="rlllrrlrr"))

    meta = pollutants.set_index("name")
    strict_labels = set(pollutants.loc[
        pollutants["iarc"].isin(["1", "2A", "2B"]) | pollutants["clp_carc"].ne(""), "name"])
    by_year = pd.read_csv(OUT / "pollutant_year.csv")
    substances = (by_year[(by_year["year"] == year) & by_year["pollutant"].isin(strict_labels)]
                  .groupby("pollutant")["kg_counted"].sum().sort_values(ascending=False))
    sub_rows = []
    for name, kg in substances.head(10).items():
        row = meta.loc[name]
        sub_rows.append([name, fmt_mass(kg), fmt_pct(100 * kg / carc_kg),
                         str(row.get("iarc", "") or "—"), str(row.get("clp_carc", "") or "—")])
    write_table("q3_substances", md_table(
        pd.DataFrame(sub_rows, columns=["Substance (E-PRTR label)", "Mass", "Share",
                                        "IARC", "CLP Carc."]), align="lrrll"))
    return {
        "carc_kg": carc_kg,
        "facilities_positive": int(len(positive)),
        "top10_share": 100 * top10_share,
        "substances": [{"name": name, "kg": float(kg)}
                       for name, kg in substances.head(10).items()],
        "top": [{"index": int(row.fac_index), "name": row.name, "kg": float(row.carc_kg)}
                for row in positive.head(20).itertuples()],
    }


if __name__ == "__main__":
    main()
