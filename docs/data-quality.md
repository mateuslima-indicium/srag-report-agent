# Qualidade do dataset processado

Gerado em 2026-11-05 por `scripts/build_dataset.py`. Extração do DATASUS: 2026-11-02.

## Linhas por arquivo

| Arquivo | Linhas lidas | Linhas mantidas | Idades implausíveis |
|---|---:|---:|---:|
| `INFLUD25-02-11-2026.csv` | 336,432 | 336,432 | 2 |
| `INFLUD26-02-11-2026.csv` | 240,606 | 240,606 | 1 |

Duplicatas removidas (mesmo hash de notificação): 0.
Total final: **577,038 linhas**, 12.1 MB em Parquet (zstd).

## Datas inválidas ou fora da janela plausível

Valores preenchidos que viraram nulo por não serem datas ou por cair fora de [2024-12-01, extração] (episódio) ou [2020-12-01, extração] (vacinas).

| Coluna | `INFLUD25-02-11-2026.csv` | `INFLUD26-02-11-2026.csv` |
|---|---:|---:|
| `dt_sin_pri` | 0 | 0 |
| `dt_notific` | 0 | 0 |
| `dt_interna` | 87 | 33 |
| `dt_evoluca` | 0 | 0 |
| `dt_entuti` | 34 | 12 |
| `dt_saiduti` | 3 | 1 |
| `dt_ut_dose` | 19 | 3 |
| `dose_1_cov` | 116 | 10 |
| `dose_2_cov` | 102 | 2 |
| `dose_ref` | 0 | 1 |
| `dose_2ref` | 1 | 0 |
| `dose_adic` | 0 | 0 |

## Nulos nas colunas-chave (após limpeza)

| Coluna | % nulos |
|---|---:|
| `dt_sin_pri` | 0.0% |
| `dt_notific` | 0.0% |
| `hospital` | 2.1% |
| `uti` | 9.7% |
| `evolucao` | 7.5% |
| `dt_evoluca` | 16.6% |
| `classi_fin` | 4.6% |
| `vacina` | 5.4% |
| `vacina_cov` | 0.0% |
| `age_years` | 0.0% |
| `sg_uf_not` | 0.0% |

## Faixa de datas

| Coluna | Mínimo | Máximo |
|---|---|---|
| `dt_sin_pri` | 2024-12-29 | 2026-11-01 |
| `dt_notific` | 2024-12-29 | 2026-11-01 |
| `dt_interna` | 2024-12-01 | 2026-11-01 |
| `dt_evoluca` | 2024-12-29 | 2026-10-31 |
| `dt_entuti` | 2024-12-02 | 2026-11-01 |
| `dt_saiduti` | 2024-12-09 | 2026-10-30 |
| `dt_ut_dose` | 2021-01-14 | 2026-10-29 |
| `dose_1_cov` | 2020-12-01 | 2026-10-05 |
| `dose_2_cov` | 2020-12-09 | 2026-10-30 |
| `dose_ref` | 2021-01-06 | 2026-09-16 |
| `dose_2ref` | 2021-03-22 | 2025-11-28 |
| `dose_adic` | 2021-01-19 | 2026-05-24 |

## Colunas removidas por privacidade

Nenhuma das colunas abaixo existe no Parquet nem é lida pelo pipeline além do necessário para derivar o hash de deduplicação:

`CLASSI_OUT`, `CO_MUN_NOT`, `CO_MUN_RES`, `CO_MU_INTE`, `CO_PS_VGM`, `CO_REGIONA`, `CO_RG_INTE`, `CO_RG_RESI`, `CS_ETINIA`, `CS_GESTANT`, `CS_RACA`, `CS_ZONA`, `DS_AN_OUT`, `DS_PCR_OUT`, `DT_NASC`, `ESTRANG`, `ID_MN_INTE`, `ID_MN_RESI`, `ID_MUNICIP`, `ID_REGIONA`, `ID_RG_INTE`, `ID_RG_RESI`, `LOTE_1_COV`, `LOTE_2_COV`, `LOTE_ADIC`, `LOTE_REF`, `LOTE_REF2`, `LOT_RE_BI`, `LO_PS_VGM`, `MORB_DESC`, `NM_UN_INTE`, `NU_IDADE_N`, `NU_NOTIFIC`, `OBES_IMC`, `OUTRO_DES`, `OUT_AMOST`, `OUT_ANTIV`, `OUT_SOR`, `OUT_TRAT`, `PAC_COCBO`, `PAC_DSCBO`, `PAIS_VGM`, `RAIOX_OUT`, `SG_UF_INTE`, `TEM_CPF`, `TOMO_OUT`, `VG_CODEST`, `VG_METOUT`, `VG_OMSOUT`
