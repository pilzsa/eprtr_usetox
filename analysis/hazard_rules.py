"""Hazard rules for the E-PRTR air/water release dashboard.

The E-PRTR pollutant labels are *not* a clean substance list.  Some labels are
single substances (benzene), some are element/compound groups (chromium and
compounds), some are indicator parameters (PAHs, PCBs, dioxins as TEQ), and some
are aggregate parameters that have no substance-level hazard classification at
all (NOx, SOx, NMVOC, PM10, TOC, total nitrogen).  This module makes that
distinction explicit and maps every E-PRTR label to:

* a CAS number (or `None` for aggregates),
* the official lists in `official_classification/`,
* a five-step hazard level used by the map,
* a machine-readable explanation of the choice.

The levels are a *screening* device, not a risk assessment.  They say "this
reported substance is on a hazard list", not "this facility is dangerous".
Read `analysis/reports/03_hazard_classification.md` before using them.

Levels (base, before medium-specific additions)
-----------------------------------------------
0  no hazard classification possible (aggregate/climate/confidential/unknown)
1  CAS known, but no classification found in the supplied lists
2  CLP health or environmental classification (e.g. Acute Tox., Aquatic Chronic)
3  IARC 2B, CLP Carc. 2, or a US EPA HAP (air only), or WFD priority (water only)
4  IARC 2A, CLP Carc. 1B, or ECHA SVHC (PBT/vPvB/endocrine concern)
5  IARC 1 or CLP Carc. 1A

Medium-specific additions
-------------------------
* EPA HAP raises an **air** release to at least level 3.
* WFD priority raises a **water** release to at least level 3.
The intrinsic IARC/CLP/SVHC level applies to both media.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
REF = ROOT / "official_classification"

# ---------------------------------------------------------------------------
# E-PRTR labels.  `cas` is the substance or the *indicator* used for a group.
# `assessable=False` means: do not turn this label into a hazard level.
# ---------------------------------------------------------------------------
POLLUTANT_META = {
    # --- greenhouse gases / ozone-depleting substances: not toxicity hazards
    "Carbon dioxide (CO2)": dict(cas="124-38-9", category="climate", assessable=False,
                                 note="Greenhouse gas; no toxicity classification."),
    "Carbon dioxide (CO2) excluding biomass": dict(cas="124-38-9", category="climate", assessable=False,
                                                   note="Greenhouse gas; no toxicity classification."),
    "Methane (CH4)": dict(cas="74-82-8", category="climate", assessable=False,
                          note="Greenhouse gas; no toxicity classification."),
    "Nitrous oxide (N2O)": dict(cas="10024-97-2", category="climate", assessable=False,
                                note="Greenhouse gas; no toxicity classification."),
    "Sulphur hexafluoride (SF6)": dict(cas="2551-62-4", category="climate", assessable=False,
                                       note="Extremely potent greenhouse gas; no toxicity classification."),
    "Hydro-fluorocarbons (HFCS)": dict(cas=None, category="climate", assessable=False,
                                       note="Group of greenhouse gases; no single CAS."),
    "Hydrochlorofluorocarbons (HCFCs)": dict(cas=None, category="climate", assessable=False,
                                             note="Group of ozone-depleting/greenhouse gases; no single CAS."),
    "Chlorofluorocarbons (CFCs)": dict(cas=None, category="climate", assessable=False,
                                       note="Group of ozone-depleting gases; no single CAS."),
    "Perfluorocarbons (PFCs)": dict(cas=None, category="climate", assessable=False,
                                    note="Group of greenhouse gases; no single CAS."),
    "Halons": dict(cas=None, category="climate", assessable=False,
                   note="Group of ozone-depleting gases; no single CAS."),

    # --- aggregate air parameters
    "Nitrogen oxides (NOX)": dict(cas=None, category="aggregate", assessable=False,
                                  note="Aggregate NO+NO2; no single CAS. Not classified to avoid labelling every combustion plant."),
    "Sulphur oxides (SOX)": dict(cas=None, category="aggregate", assessable=False,
                                 note="Aggregate SO2+SO3; no single CAS."),
    "Non-methane volatile organic compounds (NMVOC)": dict(cas=None, category="aggregate", assessable=False,
                                                          note="Aggregate of many substances; composition unknown."),
    "Particulate matter (PM10)": dict(cas=None, category="aggregate", assessable=False,
                                      note="Size fraction, not a substance; toxicity depends on composition."),
    "Fine particulate matter (PM2.5)": dict(cas=None, category="aggregate", assessable=False,
                                            note="Size fraction, not a substance; toxicity depends on composition."),
    "Carbon monoxide (CO)": dict(cas="630-08-0", category="inorganic gas", assessable=True,
                                 note="CLP Acute Tox. 3 (inhalation); not carcinogenic."),
    "Ammonia (NH3)": dict(cas="7664-41-7", category="inorganic gas", assessable=True,
                          note="CLP Acute Tox. 3, Skin Corr. 1B, Aquatic Acute 1."),
    "Chlorine and inorganic compounds (as HCl)": dict(cas="7647-01-0", category="inorganic gas", assessable=True,
                                                      note="Reported as HCl; CLP Skin Corr. 1B, STOT SE 3."),
    "Fluorine and inorganic compounds (as HF)": dict(cas="7664-39-3", category="inorganic gas", assessable=True,
                                                     note="Reported as HF; CLP Acute Tox. 2, Skin Corr. 1A."),
    "Hydrogen cyanide (HCN)": dict(cas="74-90-8", category="inorganic gas", assessable=True,
                                   note="CLP Acute Tox. 2, Aquatic Acute 1."),

    # --- aggregate water parameters
    "Total nitrogen": dict(cas=None, category="aggregate", assessable=False,
                           note="Nutrient aggregate; no substance-level hazard classification."),
    "Total phosphorus": dict(cas=None, category="aggregate", assessable=False,
                             note="Nutrient aggregate; no substance-level hazard classification."),
    "Total organic carbon(as total C or COD/3) (TOC)": dict(cas=None, category="aggregate", assessable=False,
                                                            note="Aggregate oxygen-demand parameter; no substance-level hazard classification."),
    "Halogenated organic compounds (as AOX)": dict(cas=None, category="aggregate", assessable=False,
                                                   note="Adsorbable organically bound halogens; mixture, no single CAS."),
    "Chlorides (as total Cl)": dict(cas=None, category="aggregate", assessable=False,
                                    note="Salinity parameter; not a toxicity hazard at the reported level."),
    "Fluorides (as total F)": dict(cas="16984-48-8", category="inorganic ion", assessable=True,
                                   note="Fluoride ion; CLP Acute Tox. 3/4 depending on salt."),
    "Cyanides (as total CN)": dict(cas="57-12-5", category="inorganic ion", assessable=True,
                                   note="Cyanide ion; CLP Acute Tox. 1/2, Aquatic Acute 1."),
    "Phenols (as total C)": dict(cas="108-95-2", category="indicator", assessable=True, indicator=True,
                                 note="Phenol used as indicator for the total-phenol parameter."),
    "Organotin compounds (as total Sn)": dict(cas="56-35-9", category="indicator", assessable=True, indicator=True,
                                              note="Tributyltin used as indicator for the organotin group; WFD priority and SVHC."),

    # --- metals and element/compound groups
    "Arsenic and compounds (as As)": dict(cas="7440-38-2", category="metal", assessable=True,
                                          note="Arsenic and inorganic arsenic compounds: IARC 1."),
    "Cadmium and compounds (as Cd)": dict(cas="7440-43-9", category="metal", assessable=True,
                                          note="Cadmium and compounds: IARC 1, CLP Carc. 1B, WFD priority."),
    "Chromium and compounds (as Cr)": dict(cas="7440-47-3", category="metal", assessable=True,
                                           note="Total Cr; metallic Cr (IARC 3) used. Cr(VI) is IARC 1 but cannot be separated in EPRTR."),
    "Copper and compounds (as Cu)": dict(cas="7440-50-8", category="metal", assessable=True,
                                         note="Copper compounds are mainly aquatic hazards."),
    "Lead and compounds (as Pb)": dict(cas="7439-92-1", category="metal", assessable=True,
                                       note="Lead compounds: IARC 2A, CLP Repr. 1A, WFD priority."),
    "Mercury and compounds (as Hg)": dict(cas="7439-97-6", category="metal", assessable=True,
                                          note="Mercury compounds: IARC 3 for mercury/inorganic, methylmercury 2B; WFD priority hazardous."),
    "Nickel and compounds (as Ni)": dict(cas="7440-02-0", category="metal", assessable=True,
                                         note="Metallic Ni (IARC 2B) used; nickel compounds are IARC 1 but cannot be separated."),
    "Zinc and compounds (as Zn)": dict(cas="7440-66-6", category="metal", assessable=True,
                                       note="Zinc compounds are mainly aquatic hazards."),
    "Asbestos": dict(cas="1332-21-4", category="mineral", assessable=True,
                     note="All forms: IARC 1."),


    # --- chlorinated solvents / VOCs
    "Benzene": dict(cas="71-43-2", category="VOC", assessable=True, note="IARC 1, CLP Carc. 1A."),
    "Ethyl benzene": dict(cas="100-41-4", category="VOC", assessable=True, note="IARC 2B."),
    "Toluene": dict(cas="108-88-3", category="VOC", assessable=True, note="IARC 3; CLP Repr. 2/STOT."),
    "Xylenes": dict(cas="1330-20-7", category="VOC", assessable=True, note="IARC 3; CLP Acute Tox./STOT."),
    "Naphthalene": dict(cas="91-20-3", category="PAH", assessable=True, note="IARC 2B, CLP Carc. 2."),
    "Anthracene": dict(cas="120-12-7", category="PAH", assessable=True, note="IARC 3; aquatic hazard."),
    "Fluoranthene": dict(cas="206-44-0", category="PAH", assessable=True,
                         note="IARC 3; WFD priority substance (indicator for PAHs)."),
    "Benzo(g,h,i)perylene": dict(cas="191-24-2", category="PAH", assessable=True, note="IARC 3; aquatic hazard."),
    "Polycyclic aromatic hydrocarbons (PAHs)": dict(cas="50-32-8", category="PAH", assessable=True, indicator=True,
                                                    note="Benzo[a]pyrene used as indicator for the PAH group; IARC 1."),
    "Dichloromethane (DCM)": dict(cas="75-09-2", category="VOC", assessable=True, note="IARC 2A."),
    "Trichloromethane": dict(cas="67-66-3", category="VOC", assessable=True, note="IARC 2B."),
    "Tetrachloromethane (TCM)": dict(cas="56-23-5", category="VOC", assessable=True, note="IARC 2B."),
    "1,1,1-trichloroethane (TCE-1,1,1)": dict(cas="71-55-6", category="VOC", assessable=True, note="IARC 3; ozone-depleting."),
    "1,1,2,2-tetrachloroethane (TETRACHLOROETHANE-1,1,2,2)": dict(cas="79-34-5", category="VOC", assessable=True,
                                                                  note="IARC 2B; CLP Acute Tox."),
    "1,2-dichloroethane (DCE-1,2)": dict(cas="107-06-2", category="VOC", assessable=True, note="IARC 2A; CLP Carc. 1B."),
    "Trichloroethylene (TRI)": dict(cas="79-01-6", category="VOC", assessable=True, note="IARC 1, CLP Carc. 1B."),
    "Tetrachloroethylene": dict(cas="127-18-4", category="VOC", assessable=True, note="IARC 2A."),
    "Vinyl chloride": dict(cas="75-01-4", category="VOC", assessable=True, note="IARC 1, CLP Carc. 1A."),
    "Ethylene oxide": dict(cas="75-21-8", category="VOC", assessable=True, note="IARC 1, CLP Carc. 1B."),

    # --- pesticides / biocides
    "Alachlor": dict(cas="15972-60-8", category="pesticide", assessable=True, note="IARC 2A; WFD priority."),
    "Aldrin": dict(cas="309-00-2", category="pesticide", assessable=True, note="IARC 3; WFD priority."),
    "Atrazine": dict(cas="1912-24-9", category="pesticide", assessable=True, note="IARC 2A; WFD priority."),
    "Chlordane": dict(cas="57-74-9", category="pesticide", assessable=True, note="IARC 2B; WFD priority."),
    "Chlordecone": dict(cas="143-50-0", category="pesticide", assessable=True, note="IARC 2A; WFD priority."),
    "Chlorfenvinphos": dict(cas="470-90-6", category="pesticide", assessable=True, note="CLP Acute Tox.; WFD priority."),
    "Chlorpyrifos": dict(cas="2921-88-2", category="pesticide", assessable=True, note="IARC 2A; WFD priority."),
    "DDT (DDT)": dict(cas="50-29-3", category="pesticide", assessable=True, note="IARC 2A; WFD priority."),
    "Dieldrin": dict(cas="60-57-1", category="pesticide", assessable=True, note="IARC 2A; WFD priority."),
    "Diuron": dict(cas="330-54-1", category="pesticide", assessable=True, note="IARC 2B/CLP Carc. 2; WFD priority."),
    "Endosulphan": dict(cas="115-29-7", category="pesticide", assessable=True, note="WFD priority; CLP Acute Tox./Aquatic."),
    "Endrin": dict(cas="72-20-8", category="pesticide", assessable=True, note="IARC 3; WFD priority."),
    "Heptachlor": dict(cas="76-44-8", category="pesticide", assessable=True, note="IARC 2B; WFD priority."),
    "1,2,3,4,5,6-hexachlorocyclohexane (HCH)": dict(cas="608-73-1", category="pesticide", assessable=True,
                                                    note="Technical HCH (isomer mixture); IARC 2B; WFD priority. Lindane is reported separately."),
    "Isodrin": dict(cas="465-73-6", category="pesticide", assessable=True, note="WFD priority; no IARC/CLP entry found."),
    "Isoproturon": dict(cas="34123-59-6", category="pesticide", assessable=True, note="CLP Carc. 2; WFD priority."),
    "Lindane": dict(cas="58-89-9", category="pesticide", assessable=True, note="IARC 1; WFD priority."),
    "Mirex": dict(cas="2385-85-5", category="pesticide", assessable=True, note="IARC 2B; WFD priority."),
    "Simazine": dict(cas="122-34-9", category="pesticide", assessable=True, note="IARC 3/CLP Carc. 2; WFD priority."),
    "Toxaphene": dict(cas="8001-35-2", category="pesticide", assessable=True, note="IARC 2B; WFD priority."),
    "Trifluralin": dict(cas="1582-09-8", category="pesticide", assessable=True, note="IARC 3/CLP Carc. 2; WFD priority."),
    "Pentachlorophenol (PCP)": dict(cas="87-86-5", category="pesticide", assessable=True, note="IARC 2B; WFD priority."),


    # --- industrial organics / group indicators
    "Hexachlorobenzene (HCB)": dict(cas="118-74-1", category="POP", assessable=True, note="IARC 2B, CLP Carc. 2; WFD priority."),
    "Hexachlorobutadiene (HCBD)": dict(cas="87-68-3", category="POP", assessable=True, note="IARC 3/CLP Carc. 2; WFD priority."),
    "Pentachlorobenzene": dict(cas="608-93-5", category="POP", assessable=True, note="IARC 2B; WFD priority."),
    "Hexabromobiphenyl": dict(cas="36355-01-8", category="POP", assessable=True, note="IARC 2B; WFD priority."),
    "Polychlorinated biphenyls (PCBs)": dict(cas="1336-36-3", category="POP", assessable=True, indicator=True,
                                             note="PCB group: IARC 1; WFD priority."),
    "Brominated diphenylethers (PBDE)": dict(cas="67774-32-7", category="POP", assessable=True, indicator=True,
                                             note="PBDE group; no single CAS. SVHC/PBT and WFD priority."),
    "PCDD + PCDF (dioxins + furans) (as Teq)": dict(cas="1746-01-6", category="POP", assessable=True, indicator=True,
                                                    note="2,3,7,8-TCDD used as TEQ indicator; IARC 1."),
    "Chloro-alkanes, C10-C13": dict(cas="85535-84-8", category="POP", assessable=True,
                                    note="Short-chain chlorinated paraffins; SVHC/PBT; WFD priority."),
    "Trichlorobenzenes (TCB)": dict(cas="120-82-1", category="POP", assessable=True, indicator=True,
                                    note="1,2,4-Trichlorobenzene used as indicator; WFD priority."),
    "Di-(2-ethyl hexyl) phthalate (DEHP)": dict(cas="117-81-7", category="plasticiser", assessable=True,
                                                note="IARC 2B, CLP Repr. 1B, SVHC; WFD priority."),
    "Nonylphenol and Nonylphenol ethoxylates": dict(cas="25154-52-3", category="industrial chemical", assessable=True,
                                                    indicator=True, note="Nonylphenol indicator; SVHC/endocrine disruptor; WFD priority."),
    "Octylphenols and Octylphenol ethoxylates": dict(cas="140-66-9", category="industrial chemical", assessable=True,
                                                     indicator=True, note="4-tert-octylphenol indicator; SVHC/endocrine disruptor; WFD priority."),
    "Tributyltin and compounds": dict(cas="56-35-9", category="organotin", assessable=True,
                                      note="No IARC entry; SVHC/PBT; WFD priority."),
    "Triphenyltin and compounds": dict(cas="668-34-8", category="organotin", assessable=True,
                                       note="WFD priority; SVHC."),

    # --- confidential marker row
    "CONFIDENTIAL": dict(cas=None, category="confidential", assessable=False,
                         note="Mass suppressed under E-PRTR Art. 4(2); no value, no substance name."),
}


# Manual corrections for group labels where the CAS entry in IARC/CLP is not the
# group indicator, or where a group is classified only as a group.
MANUAL = {
    "Polychlorinated biphenyls (PCBs)": dict(iarc="1", wfd=True),
    "Brominated diphenylethers (PBDE)": dict(wfd=True, svhc=True),
    "PCDD + PCDF (dioxins + furans) (as Teq)": dict(iarc="1", wfd=True),
    "Polycyclic aromatic hydrocarbons (PAHs)": dict(iarc="1", wfd=True),
    "Organotin compounds (as total Sn)": dict(svhc=True, wfd=True),
    "Tributyltin and compounds": dict(svhc=True, wfd=True),
    "Triphenyltin and compounds": dict(svhc=True, wfd=True),
    "Nonylphenol and Nonylphenol ethoxylates": dict(svhc=True, wfd=True),
    "Octylphenols and Octylphenol ethoxylates": dict(svhc=True, wfd=True),
    "Chloro-alkanes, C10-C13": dict(svhc=True, wfd=True),
    "Di-(2-ethyl hexyl) phthalate (DEHP)": dict(iarc="2B", clp_carc="1B", svhc=True, wfd=True),
    "Trichlorobenzenes (TCB)": dict(wfd=True),
    "Hexachlorobenzene (HCB)": dict(iarc="2B", wfd=True),
    "Hexachlorobutadiene (HCBD)": dict(iarc="3", wfd=True),
    "Pentachlorobenzene": dict(iarc="2B", wfd=True),
    "Hexabromobiphenyl": dict(iarc="2B", wfd=True),
    "Lindane": dict(iarc="1", wfd=True),
    "Mercury and compounds (as Hg)": dict(wfd=True),
    "Cadmium and compounds (as Cd)": dict(iarc="1", clp_carc="1B", wfd=True),
    "Lead and compounds (as Pb)": dict(iarc="2A", wfd=True),
    "Nickel and compounds (as Ni)": dict(iarc="2B", wfd=True),
    "Arsenic and compounds (as As)": dict(iarc="1", wfd=True),
    "Chromium and compounds (as Cr)": dict(iarc="3", wfd=True),
    "Copper and compounds (as Cu)": dict(wfd=True),
    "Zinc and compounds (as Zn)": dict(wfd=True),
    "Fluoranthene": dict(iarc="3", wfd=True),
    "Naphthalene": dict(iarc="2B"),
    "Anthracene": dict(iarc="3"),
    "Benzo(g,h,i)perylene": dict(iarc="3"),
    "Benzene": dict(iarc="1", clp_carc="1A"),
    "Vinyl chloride": dict(iarc="1", clp_carc="1A"),
    "Trichloroethylene (TRI)": dict(iarc="1", clp_carc="1B"),
    "Ethylene oxide": dict(iarc="1", clp_carc="1B"),
    "1,2-dichloroethane (DCE-1,2)": dict(iarc="2A", clp_carc="1B"),
    "Tetrachloroethylene": dict(iarc="2A"),
    "Dichloromethane (DCM)": dict(iarc="2A"),
    "Trichloromethane": dict(iarc="2B"),
    "Tetrachloromethane (TCM)": dict(iarc="2B"),
    "1,1,2,2-tetrachloroethane (TETRACHLOROETHANE-1,1,2,2)": dict(iarc="2B"),
    "1,1,1-trichloroethane (TCE-1,1,1)": dict(iarc="3"),
    "Ethyl benzene": dict(iarc="2B"),
    "Toluene": dict(iarc="3"),
    "Xylenes": dict(iarc="3"),
    "Asbestos": dict(iarc="1"),
    "Aldrin": dict(iarc="3", wfd=True),
    "Dieldrin": dict(iarc="2A", wfd=True),
    "Endrin": dict(iarc="3", wfd=True),
    "Chlordane": dict(iarc="2B", wfd=True),
    "Heptachlor": dict(iarc="2B", wfd=True),
    "Mirex": dict(iarc="2B", wfd=True),
    "Toxaphene": dict(iarc="2B", wfd=True),
    "DDT (DDT)": dict(iarc="2A", wfd=True),
    "Chlordecone": dict(iarc="2A", wfd=True),
    "Atrazine": dict(iarc="2A", wfd=True),
    "Alachlor": dict(iarc="2A", wfd=True),
    "Chlorpyrifos": dict(iarc="2A", wfd=True),
    "Diuron": dict(iarc="2B", clp_carc="2", wfd=True),
    "Isoproturon": dict(clp_carc="2", wfd=True),
    "Simazine": dict(iarc="3", clp_carc="2", wfd=True),
    "Trifluralin": dict(iarc="3", clp_carc="2", wfd=True),
    "Chlorfenvinphos": dict(wfd=True),
    "Endosulphan": dict(wfd=True),
    "Isodrin": dict(wfd=True),
    "Pentachlorophenol (PCP)": dict(iarc="2B", wfd=True),
    "1,2,3,4,5,6-hexachlorocyclohexane (HCH)": dict(iarc="2B", wfd=True),
    # CLP's harmonised list does not contain the cyanide anion row; the
    # inorganic cyanide salts are nevertheless Acute Tox. 1/2 and Aquatic 1.
    "Cyanides (as total CN)": dict(base_override=2),
}

# Labels in the data that are not single substances but are still useful as
# indicator parameters.  They are flagged in the UI and in the report.
INDICATORS = {k for k, v in POLLUTANT_META.items() if v.get("indicator")}



def cas_key(value) -> str | None:
    """Return a digits-only CAS key (71-43-2 -> 71432)."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return None
    digits = re.sub(r"\D", "", text)
    return digits or None


def cas_keys(value) -> list[str]:
    """Split a field that may contain several CAS numbers and return keys."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    text = str(value)
    keys = []
    for part in re.split(r"[;,]", text):
        key = cas_key(part)
        if key and 5 <= len(key) <= 10:
            keys.append(key)
    # SVHC exports sometimes concatenate EC and CAS ("203-777-6110-54-3").
    for match in re.findall(r"\d{2,7}-\d{2}-\d", text):
        key = cas_key(match)
        if key and key not in keys:
            keys.append(key)
    return keys


def _strongest_iarc(groups) -> str | None:
    order = {"1": 5, "2A": 4, "2B": 3, "3": 2}
    best = None
    best_rank = -1
    for group in groups:
        text = str(group).strip().upper().replace("GROUP", "").strip()
        if text in order and order[text] > best_rank:
            best, best_rank = text, order[text]
    return best


def _strongest_clp_carc(tokens) -> str | None:
    order = {"1A": 4, "1B": 3, "1": 2, "2": 1}
    best = None
    best_rank = -1
    for token in tokens:
        text = str(token).upper().replace(" ", "")
        if text in order and order[text] > best_rank:
            best, best_rank = text, order[text]
    return best


def _has_clp_health(text: str) -> bool:
    text = str(text)
    triggers = [
        "Acute Tox", "Skin Corr", "Skin Irrit", "Skin Sens", "Eye Dam", "Eye Irrit",
        "STOT", "Carc", "Muta", "Repr", "Resp. Sens", "Asp. Tox", "Lact",
        "Aquatic", "Ozone",
    ]
    return any(trigger in text for trigger in triggers)



def load_references(ref_dir: Path = REF) -> dict:
    """Load the five supplied classification sources into CAS-keyed maps."""
    iarc_by_cas: dict[str, set] = {}
    iarc = pd.read_excel(ref_dir / "Agents Classified by the IARC Monographs, Volumes 1–142.xlsx", skiprows=1)
    for _, row in iarc.iterrows():
        group = row.get("Group")
        if pd.isna(group):
            continue
        for key in cas_keys(row.get("CAS No.")):
            iarc_by_cas.setdefault(key, set()).add(str(group).strip())

    clp_by_cas: dict[str, list[str]] = {}
    clp = pd.read_excel(ref_dir / "Harmonised_List_2026-10-03 11_18_19.xlsx")
    for _, row in clp.iterrows():
        cas = row.get("CAS number")
        text = row.get("Hazard class, category and statement code(s)")
        if pd.isna(cas) or pd.isna(text):
            continue
        key = cas_key(cas)
        if key:
            clp_by_cas.setdefault(key, []).append(str(text))

    hap_keys: set[str] = set()
    hap = pd.read_excel(ref_dir / "epa_hap_list.xlsx", sheet_name="hap_table")
    for value in hap["CAS Number"]:
        key = cas_key(value)
        if key:
            hap_keys.add(key)

    wfd_keys: set[str] = set()
    wfd = pd.read_excel(
        ref_dir / "water-framework-directive-annex-x-priority-substances-export.xlsx",
        sheet_name="results", skiprows=4,
    )
    # Normalise headers; the export has an empty first column and duplicate names.
    wfd.columns = ["Substance Name", "EC No.", "CAS No.", "Name", "EC Number", "CAS", "Priority", "Group", "Notes"][:len(wfd.columns)]
    for _, row in wfd.iterrows():
        if str(row.get("Priority", "")).strip().lower() != "yes":
            continue
        for key in cas_keys(row.get("CAS No.")) + cas_keys(row.get("CAS")):
            wfd_keys.add(key)

    svhc_keys: set[str] = set()
    svhc = pd.read_excel(ref_dir / "candidate_list_full-2026-10-02.xlsx", sheet_name="List_results")
    for value in svhc["CAS number"]:
        for key in cas_keys(value):
            svhc_keys.add(key)

    return {
        "iarc": iarc_by_cas,
        "clp": clp_by_cas,
        "hap": hap_keys,
        "wfd": wfd_keys,
        "svhc": svhc_keys,
    }



def _level_from_flags(iarc: str | None, clp_carc: str | None, svhc: bool) -> int:
    if iarc == "1" or clp_carc == "1A":
        return 5
    if iarc == "2A" or clp_carc == "1B" or svhc:
        return 4
    if iarc == "2B" or clp_carc is not None:
        return 3
    return 2


def build_pollutant_table(ref_dir: Path = REF) -> list[dict]:
    """Build one row per E-PRTR pollutant label with all hazard flags."""
    refs = load_references(ref_dir)
    rows = []
    for label, meta in POLLUTANT_META.items():
        manual = MANUAL.get(label, {})
        key = cas_key(meta.get("cas"))
        iarc = manual.get("iarc")
        if iarc is None and key:
            iarc = _strongest_iarc(refs["iarc"].get(key, set()))
        clp_text = " | ".join(refs["clp"].get(key, [])) if key else ""
        clp_tokens = re.findall(r"Carc\.\s*(1A|1B|1|2)", clp_text)
        clp_carc = manual.get("clp_carc")
        if clp_carc is None:
            clp_carc = _strongest_clp_carc(clp_tokens)
        hap = bool(key and key in refs["hap"]) or bool(manual.get("hap"))
        wfd = bool(key and key in refs["wfd"]) or bool(manual.get("wfd"))
        svhc = bool(manual.get("svhc")) or bool(key and key in refs["svhc"])
        assessable = bool(meta.get("assessable", True))

        if not assessable:
            base = 0
        elif manual.get("base_override") is not None:
            base = int(manual["base_override"])
        elif iarc or clp_carc or svhc:
            base = _level_from_flags(iarc, clp_carc, svhc)
        elif clp_text and _has_clp_health(clp_text):
            base = 2
        elif key:
            base = 1  # CAS known, but no classification found
        else:
            base = 0

        level_air = max(base, 3) if hap else base
        level_water = max(base, 3) if wfd else base
        flags = []
        if meta.get("indicator"):
            flags.append("indicator/group")
        if not assessable:
            flags.append("not assessable")
        if meta.get("cas") is None:
            flags.append("no CAS")
        if hap:
            flags.append("EPA HAP (air)")
        if wfd:
            flags.append("WFD priority (water)")
        if svhc:
            flags.append("ECHA SVHC")
        if iarc:
            flags.append(f"IARC {iarc}")
        if clp_carc:
            flags.append(f"CLP Carc. {clp_carc}")

        rows.append({
            "label": label,
            "cas": meta.get("cas"),
            "cas_key": key,
            "category": meta.get("category", ""),
            "assessable": assessable,
            "indicator": bool(meta.get("indicator")),
            "iarc": iarc or "",
            "clp_carc": clp_carc or "",
            "clp_health": bool(clp_text and _has_clp_health(clp_text)),
            "hap": hap,
            "wfd_priority": wfd,
            "svhc": svhc,
            "level_base": base,
            "level_air": level_air,
            "level_water": level_water,
            "flags": "; ".join(flags),
            "note": meta.get("note", ""),
        })
    return rows


def missing_labels(label_set) -> set[str]:
    return set(label_set) - set(POLLUTANT_META)


if __name__ == "__main__":
    table = build_pollutant_table()
    print(f"{len(table)} pollutant labels")
    for row in table:
        print(f"{row['level_air']}/{row['level_water']}  {row['label']:<58} {row['cas'] or '-':<12} {row['flags']}")

