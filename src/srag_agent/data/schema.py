"""Column contract of the processed SRAG dataset and DATASUS code dictionaries.

Column names follow the Sivep-Gripe data dictionary (lower-cased) so that every field can be
traced back to `data/raw/dicionario-de-dados-2019-a-2025.pdf`.
"""

from __future__ import annotations

from typing import Final

RAW_IDENTIFIER: Final = "NU_NOTIFIC"
"""Notification number: read only to derive `notif_hash`, never stored."""

EVENT_DATE_COLUMNS: Final[tuple[str, ...]] = (
    "DT_SIN_PRI",
    "DT_NOTIFIC",
    "DT_INTERNA",
    "DT_EVOLUCA",
    "DT_ENTUTI",
    "DT_SAIDUTI",
)
"""Dates of the SRAG episode itself; must fall inside the epidemiological window."""

VACCINE_DATE_COLUMNS: Final[tuple[str, ...]] = (
    "DT_UT_DOSE",
    "DOSE_1_COV",
    "DOSE_2_COV",
    "DOSE_REF",
    "DOSE_2REF",
    "DOSE_ADIC",
)
"""Vaccination dates; may legitimately predate the episode by years."""

CODE_COLUMNS: Final[tuple[str, ...]] = (
    "SEM_PRI",
    "TP_IDADE",
    "HOSPITAL",
    "UTI",
    "SUPORT_VEN",
    "EVOLUCAO",
    "CLASSI_FIN",
    "VACINA",
    "VACINA_COV",
    "FATOR_RISC",
)
"""Small integer codes (see `CODE_LABELS`)."""

TEXT_COLUMNS: Final[tuple[str, ...]] = ("SG_UF_NOT", "SG_UF", "CS_SEXO")

RAW_AGE_COLUMN: Final = "NU_IDADE_N"
"""Raw age value (unit in `TP_IDADE`): read only to derive `age_years` and `age_band`."""

RAW_COLUMNS_TO_READ: Final[tuple[str, ...]] = (
    RAW_IDENTIFIER,
    *EVENT_DATE_COLUMNS,
    *VACCINE_DATE_COLUMNS,
    *CODE_COLUMNS,
    *TEXT_COLUMNS,
    RAW_AGE_COLUMN,
)
"""Every raw column the pipeline touches (27 of 194). Everything else is never loaded."""

DERIVED_COLUMNS: Final[tuple[str, ...]] = ("age_years", "age_band", "notif_hash", "source_file")

PROCESSED_COLUMNS: Final[tuple[str, ...]] = (
    *(c.lower() for c in EVENT_DATE_COLUMNS),
    *(c.lower() for c in VACCINE_DATE_COLUMNS),
    *(c.lower() for c in CODE_COLUMNS),
    *(c.lower() for c in TEXT_COLUMNS),
    *DERIVED_COLUMNS,
)
"""Exact column set of `data/processed/srag.parquet`."""

PRIVACY_DROPPED_COLUMNS: Final[frozenset[str]] = frozenset(
    {
        # quasi-identifiers
        "DT_NASC",
        "TEM_CPF",
        "ESTRANG",
        "CS_ETINIA",
        "CS_RACA",
        "PAC_COCBO",
        "PAC_DSCBO",
        "CS_GESTANT",
        "OBES_IMC",
        RAW_AGE_COLUMN,
        # free text that may carry names
        "MORB_DESC",
        "OUTRO_DES",
        "OUT_ANTIV",
        "OUT_TRAT",
        "OUT_AMOST",
        "OUT_SOR",
        "CLASSI_OUT",
        "RAIOX_OUT",
        "TOMO_OUT",
        "DS_PCR_OUT",
        "DS_AN_OUT",
        "VG_OMSOUT",
        "VG_METOUT",
        # fine-grained location
        "ID_MUNICIP",
        "CO_MUN_NOT",
        "ID_MN_RESI",
        "CO_MUN_RES",
        "ID_REGIONA",
        "CO_REGIONA",
        "ID_RG_RESI",
        "CO_RG_RESI",
        "CS_ZONA",
        "ID_MN_INTE",
        "CO_MU_INTE",
        "ID_RG_INTE",
        "CO_RG_INTE",
        "NM_UN_INTE",
        "SG_UF_INTE",
        "LO_PS_VGM",
        "CO_PS_VGM",
        "PAIS_VGM",
        # vaccine lots and the raw notification number
        "LOTE_1_COV",
        "LOTE_2_COV",
        "LOTE_REF",
        "LOTE_REF2",
        "LOTE_ADIC",
        "LOT_RE_BI",
        "VG_CODEST",
        RAW_IDENTIFIER,
    }
)
"""Columns that must never reach the processed dataset (see docs/data-privacy.md)."""

CODE_LABELS: Final[dict[str, dict[int, str]]] = {
    "evolucao": {1: "Cura", 2: "Óbito", 3: "Óbito por outras causas", 9: "Ignorado"},
    "hospital": {1: "Sim", 2: "Não", 9: "Ignorado"},
    "uti": {1: "Sim", 2: "Não", 9: "Ignorado"},
    "vacina": {1: "Sim", 2: "Não", 9: "Ignorado"},
    "vacina_cov": {1: "Sim", 2: "Não", 9: "Ignorado"},
    "fator_risc": {1: "Sim", 2: "Não", 9: "Ignorado"},
    "suport_ven": {1: "Sim, invasivo", 2: "Sim, não invasivo", 3: "Não", 9: "Ignorado"},
    "classi_fin": {
        1: "SRAG por influenza",
        2: "SRAG por outro vírus respiratório",
        3: "SRAG por outro agente etiológico",
        4: "SRAG não especificado",
        5: "SRAG por covid-19",
    },
    "tp_idade": {1: "Dias", 2: "Meses", 3: "Anos"},
}
"""Portuguese labels for each code column, used to describe the SQL tool to the LLM."""

AGE_BAND_EDGES: Final[tuple[int, ...]] = (0, 10, 20, 30, 40, 50, 60, 70, 80)
AGE_BAND_LABELS: Final[tuple[str, ...]] = (
    "0-9",
    "10-19",
    "20-29",
    "30-39",
    "40-49",
    "50-59",
    "60-69",
    "70-79",
    "80+",
)

BRAZIL_UFS: Final[tuple[str, ...]] = (
    "AC",
    "AL",
    "AM",
    "AP",
    "BA",
    "CE",
    "DF",
    "ES",
    "GO",
    "MA",
    "MG",
    "MS",
    "MT",
    "PA",
    "PB",
    "PE",
    "PI",
    "PR",
    "RJ",
    "RN",
    "RO",
    "RR",
    "RS",
    "SC",
    "SE",
    "SP",
    "TO",
)

EPIDEMIOLOGICAL_WINDOW_START: Final = "2024-12-01"
"""First plausible episode date: epidemiological week 1 of 2025 starts on 2024-12-29."""

VACCINE_WINDOW_START: Final = "2020-12-01"
"""First plausible vaccination date (covid-19 vaccination in Brazil started in Jan/2021)."""
