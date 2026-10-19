# Hazard classification

> **This is a screening classification, not a risk assessment.** A level says
> that a reported substance appears on a hazard list; it says nothing about
> exposure, dose, bioavailability, local conditions or actual harm. The
> dashboard uses levels to order and colour facilities, not to rank safety.

The rules live in `analysis/hazard_rules.py`; the reproducible output is the
`pollutants.json` table and the `pollutants.table` section of
`analysis/outputs/quality_report.json`. Run
`python analysis/hazard_rules.py` to print the full label-by-label table.

## 1. Why E-PRTR labels need curation

E-PRTR `Pollutant` is a reporting label, not a substance identifier. The 94
labels in the 2007–2024 extract fall into five groups:

| Kind | Examples | Consequence |
|---|---|---|
| Single substances | benzene, cadmium, lindane | CAS lookup works directly |
| Element/compound groups | “chromium and compounds (as Cr)” | the CAS is the element/indicator, not the mixture actually released |
| Group indicators | PAHs, PCBs, dioxins as TEQ | one CAS represents a family with different potencies |
| Aggregate parameters | NOx, SOx, NMVOC, PM10, TOC | no substance-level hazard classification is possible |
| Climate gases and markers | CO₂, CH₄, SF₆, `CONFIDENTIAL` | not toxicity hazards / no substance name |

Applying a CAS lookup blindly would classify NOx as if it were NO₂, or label
every combustion plant as hazardous because it emits CO₂. Instead, the module
has an explicit entry for every one of the 94 labels.

## 2. Reference lists

All reference files are in `official_classification/` and are read on every
build; none of the classifications are typed in by hand except the documented
overrides below.

| List | File | Used for |
|---|---|---|
| IARC Monographs, Vols 1–142 | `Agents Classified by the IARC Monographs, Volumes 1–142.xlsx` | intrinsic carcinogenicity (groups 1, 2A, 2B, 3) |
| CLP harmonised classification | `Harmonised_List_2026-10-03 11_18_19.xlsx` | `Carc. 1A/1B/2` and other health/environmental classes |
| ECHA candidate list (SVHC) | `candidate_list_full-2026-10-02.xlsx` | PBT/vPvB, endocrine and other SVHC concern |
| US EPA hazardous air pollutants | `epa_hap_list.xlsx` | air-specific addition |
| Water Framework Directive Annex X | `water-framework-directive-annex-x-priority-substances-export.xlsx` | water-specific addition (priority substances only) |

The IARC, CLP and SVHC files are snapshots taken in October 2026 (the CLP and
SVHC dates are in their filenames); earlier assessments are not reconstructed.
IARC classifies **hazard**, not risk, and “group 3” means *not classifiable*,
not “safe”.

## 3. Decision rule

For each label, the module computes the strongest applicable signal:

1. If `assessable = False`, level 0. This covers greenhouse gases, aggregate
   parameters and the `CONFIDENTIAL` marker.
2. Otherwise, take the **maximum** of the available evidence:
   * IARC 1 or CLP `Carc. 1A` → **5**
   * IARC 2A, CLP `Carc. 1B`, or ECHA SVHC → **4**
   * IARC 2B or CLP `Carc. 2` → **3**
   * IARC 3 (not classifiable) or any other CLP health/environmental
     classification → **2**
   * CAS known but no hazard-list entry at all → **1**
   * no CAS and no classification → **0**
3. Apply medium-specific floors:
   * **air**: an EPA HAP is at least **3**;
   * **water**: a WFD Annex X priority substance, or a label in the water-specific
     screen described in §8, is at least **3**.
4. A manual override may replace the base level where the CAS row does not
   represent the E-PRTR group (for example inorganic cyanides).

This is deliberately a *maximum*, not a sum or average: one clear carcinogen
signal is not diluted by several “not classified” entries. In this snapshot the
lowest observed level for an assessable label is 2, because every assessable
label has at least one hazard-list entry; the level 1 fallback exists in the
schema but is unused.

Important consequences:

* **WFD does not make an air release hazardous.** It raises water only. Mercury
  is a WFD priority substance; copper, zinc and chromium receive the same
  water-specific floor through the conservative screen, so all four are level 3
  on water and level 2 on air. Arsenic is also screened, but its IARC 1 base
  already puts it at level 5.
* **EPA HAP raises air only.** A substance can therefore have different air and
  water levels; the dashboard stores both (`max_air`, `max_water`).
* The intrinsic IARC/CLP/SVHC level applies to both media because it describes
  the substance, not the receiving compartment.
* CLP environmental classifications (e.g. Aquatic Chronic) count as level 2,
  even though they are not human-health endpoints. This is a screening choice;
  the flag `clp_health` only records whether a *health* class was present.


## 4. Manual overrides

The following are the only hand-written classifications. They cover group
indicators whose CAS is absent from a list, missing list rows, and labels where
the strongest applicable signal is pinned explicitly.

| Label | Override | Reason |
|---|---|---|
| PCBs | IARC 1, WFD | group is IARC 1; WFD priority |
| PBDE | SVHC, WFD | PBT group; no single CAS |
| PCDD/PCDF (TEQ) | IARC 1, WFD | 2,3,7,8-TCDD indicator |
| PAHs | IARC 1, WFD | benzo[a]pyrene indicator |
| Organotin compounds (total Sn) | SVHC, WFD | group classification |
| Tributyltin / triphenyltin | SVHC, WFD | organotin compounds |
| Nonylphenol / octylphenol ethoxylates | SVHC, WFD | endocrine disruptors |
| Chloro-alkanes C10–C13 | SVHC, WFD | short-chain chlorinated paraffins |
| DEHP | IARC 2B, CLP Carc. 1B, SVHC, WFD | strongest signal is CLP 1B → level 4 |
| HCB, HCBD, pentachlorobenzene, hexabromobiphenyl | IARC + WFD | group entries missing from one list |
| Lindane | IARC 1, WFD | IARC 1 |
| Mercury, cadmium, lead, nickel | WFD | Annex X priority substances; lead and nickel are listed in the directive even though their rows in the supplied export lack the priority flag |
| Arsenic, chromium, copper, zinc | `wfd=True` screen | conservative water-specific floor; these four are not Annex X priority substances in the supplied export |
| Cyanides (total CN) | base 2 | CLP harmonised list lacks the anion row; inorganic cyanide salts are Acute Tox. 1/2 and Aquatic 1 |
| Benzene, vinyl chloride, trichloroethylene, ethylene oxide | IARC 1 + CLP Carc. 1A/1B | strongest signal |
| 1,2-dichloroethane | IARC 2A + CLP 1B | level 4 |
| DCM, tetrachloroethylene, DDT, chlordecone, atrazine, alachlor, chlorpyrifos, dieldrin | IARC 2A | level 4 |
| Several pesticides | IARC 2B/3 + CLP Carc. 2 + WFD | level 3 |

Every override is visible in the `MANUAL` dict in `hazard_rules.py`; the table
above gives the interpretation used in this report.

## 5. Results

**94 labels** in the data: 73 assessable and 21 level 0 (10 climate gases,
10 aggregate parameters and the confidential marker). Nine labels are flagged
as group indicators.

| Level | Meaning | Air labels | Water labels |
|---:|---|---:|---:|
| 0 | not classifiable | 21 | 21 |
| 1 | CAS only | 0 | 0 |
| 2 | CLP health/environmental | 13 | 11 |
| 3 | IARC 2B / CLP Carc. 2 / HAP / WFD or manual screen | 27 | 29 |
| 4 | IARC 2A / CLP 1B / SVHC | 22 | 22 |
| 5 | IARC 1 / CLP 1A | 11 | 11 |

The difference between air and water is exactly the medium-specific floors:
chlorine/inorganic compounds (as HCl), fluorine/inorganic compounds (as HF),
phenols, toluene, xylenes and 1,1,1-trichloroethane are level 3 on air through
HAP but level 2 on water. Chromium, copper and zinc are level 3 on water
through the manual screen, while mercury is level 3 through WFD; all four are
level 2 on air. Chlorfenvinphos, endosulphan, endrin and isodrin are level 3 on
water through WFD but level 2 on air.

## 6. What the levels do to the mass totals

Across all years, 619,021 positive pollutant groups carry **31.06 Gt** of
counted mass after the CO₂ nested-label correction. Only **58.59 Mt
(0.189%)** is hazard-classified (level ≥ 2):

| Level | Positive groups | Mass (Mt) | Share of classified mass |
|---:|---:|---:|---:|
| 0 | 271,973 | 31,001.67 | — (not classified) |
| 2 | 165,946 | 57.79 | 98.62% |
| 3 | 107,214 | 0.63 | 1.08% |
| 4 | 31,597 | 0.078 | 0.13% |
| 5 | 42,291 | 0.096 | 0.16% |

(Group counts are positive facility-year-medium-pollutant groups after the CO₂
correction; the raw source has 625,647 positive groups. Masses are summed across
air and water.)

The classified total is dominated by **carbon monoxide and ammonia**, both
level 2, which together account for almost all of the 57.8 Mt. CO₂ alone is
about 30.54 Gt and is level 0 by design. This is why the dashboard never uses
total mass as a hazard measure, and why the default bubble size can be switched
between total and classified mass.

In the default year 2022, the 2.58 Mt of classified mass is 0.19% of the
1.35 Gt total. The largest single facilities by total mass are large combustion
plants (RWE Power, Bełchatów, Lippendorf); their classified mass is orders of
magnitude smaller than their CO₂.

## 7. Validation performed

* All 94 source labels have an explicit `POLLUTANT_META` entry; the build fails
  on an unknown label rather than silently assigning level 0.
* Spot checks: benzene 5, vinyl chloride 5, cadmium 5, lead 4, DEHP 4,
  naphthalene 3, copper water 3 / air 2, CO 2, CO₂ 0.
* Cross-checked that WFD priority substances are at least 3 on water and EPA
  HAPs at least 3 on air.
* No label with a CAS and a classification remains at level 1.
* Manual overrides were reviewed against the source lists and are individually
  listed above.

## 8. Known limitations

* Group indicators (PCBs, PAHs, dioxins, organotins) inherit the hazard of an
  indicator substance; the real mixture may be more or less potent.
* “Chromium and compounds (as Cr)” treats all chromium as the classified
  indicator; hexavalent chromium is the actual concern, but the reported mass
  does not distinguish valence states.
* Metal compounds are classified from the metal ion; solubility and speciation
  are ignored.
* The water-specific `wfd` screen is applied to arsenic, chromium, copper and
  zinc as a conservative floor, although the supplied Annex X export does not
  list them as priority substances. Without that screen, chromium, copper and
  zinc would be level 2 on water; arsenic remains level 5 through IARC 1. The
  code reuses the `wfd` flag for this screen, so the raw `flags` string in
  `pollutants.json` reads “WFD priority (water)” for these four; the same string
  appears for lead and nickel through the manual entry in §4. For these six
  labels the string is not a direct reproduction of the export's `Priority`
  column.
* The lists are snapshots and change over time; results are not comparable with
  dashboards built from different list versions.
* CLP environmental classes are included at level 2, which may overstate
  human-health concern for substances that are only aquatic toxicants.
* No mixture, exposure, persistence-in-environment or local-impact modelling is
  performed.
