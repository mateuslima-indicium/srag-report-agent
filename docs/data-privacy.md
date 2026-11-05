# Dados sensíveis e privacidade

O Sivep-Gripe público já não traz nome, CPF, endereço ou telefone, mas contém
quase-identificadores (data de nascimento, raça/cor, etnia, ocupação, município, zona, gestação,
IMC) e campos de texto livre que podem carregar nomes. A combinação deles permite reidentificação.
O projeto trata isso em quatro camadas.

## 1. O que nunca entra no dataset processado

`scripts/build_dataset.py` lê apenas as colunas de `schema.RAW_COLUMNS_TO_READ`; todo o resto do
CSV (194 colunas) nem é carregado. A lista `schema.PRIVACY_DROPPED_COLUMNS` documenta o que é
descartado explicitamente, e um teste (`test_pipeline.py`) falha se qualquer uma aparecer no
Parquet:

| Categoria | Colunas |
|---|---|
| Quase-identificadores | `DT_NASC`, `NU_IDADE_N` (só a idade em anos arredondada e a faixa ficam), `TEM_CPF`, `ESTRANG`, `CS_ETINIA`, `CS_RACA`, `PAC_COCBO`, `PAC_DSCBO`, `CS_GESTANT`, `OBES_IMC` |
| Texto livre | `MORB_DESC`, `OUTRO_DES`, `OUT_ANTIV`, `OUT_TRAT`, `OUT_AMOST`, `OUT_SOR`, `CLASSI_OUT`, `RAIOX_OUT`, `TOMO_OUT`, `DS_PCR_OUT`, `DS_AN_OUT`, `VG_OMSOUT`, `VG_METOUT` |
| Localização fina | `ID_MUNICIP`, `CO_MUN_NOT`, `ID_MN_RESI`, `CO_MUN_RES`, `ID_REGIONA`, `CO_REGIONA`, `ID_RG_RESI`, `CO_RG_RESI`, `CS_ZONA`, `ID_MN_INTE`, `CO_MU_INTE`, `ID_RG_INTE`, `CO_RG_INTE`, `NM_UN_INTE`, `SG_UF_INTE`, `LO_PS_VGM`, `CO_PS_VGM`, `PAIS_VGM` |
| Lotes de vacina e identificador | `LOTE_1_COV`, `LOTE_2_COV`, `LOTE_REF`, `LOTE_REF2`, `LOTE_ADIC`, `LOT_RE_BI`, `VG_CODEST`, `NU_NOTIFIC` |

Transformações nas colunas mantidas:

- `NU_NOTIFIC` vira `notif_hash` (SHA-256 truncado a 16 hex), usado só para deduplicar; o número original não é gravado.
- Idade vira `age_years` (anos, duas casas) e `age_band` (faixas de 10 anos, `0-9` … `80+`).
- Localização fica apenas na UF (`sg_uf_not`, `sg_uf`).
- Datas implausíveis (ano 8202, datas futuras) viram nulo; vacinação só aceita datas a partir de 2020-12.

Resultado: 577.038 linhas e 30 colunas, sem nenhum campo que identifique uma pessoa.
O Parquet versionado (`data/processed/srag.parquet`, 12 MB) é esse dataset; os CSVs brutos
ficam fora do repositório (`.gitignore`).

## 2. O LLM só vê agregados

O modelo nunca recebe linhas individuais:

- As métricas e séries chegam como `MetricResult`/`SeriesResult` (contagens, razões, janelas).
- `run_readonly_sql` devolve no máximo `sql_row_limit` (200) linhas, e o prompt e a descrição da tool orientam consultas agregadas. Mesmo que o modelo peça `SELECT * FROM cases`, as colunas disponíveis já são as de-identificadas acima.
- O guardrail `pii` bloqueia CPF, e-mail, telefone, CNS e números de notificação no texto final, como última barreira.

## 3. Segredos e configuração

- `ANTHROPIC_API_KEY` e `TAVILY_API_KEY` vivem em `.env` (ignorado pelo Git) e são lidas em `SecretStr`; nunca aparecem em `repr`, logs, auditoria ou relatório. `.env.example` mostra o formato.
- A trilha de auditoria registra o prompt apenas por hash; resultados de SQL registrados são os agregados devolvidos ao modelo.
- O cliente da Anthropic recebe só o conteúdo das mensagens; nenhum dado bruto é enviado.

## 4. Notícias

Notícias são conteúdo público. Mesmo assim, o agente guarda apenas título, fonte, URL, data e um
resumo de até 600 caracteres, já sem HTML, e descarta itens com padrões de injeção. O relatório
cita cada notícia com link para a fonte original, sem reproduzir o texto integral.

## Base legal e uso

Os dados são públicos (Open DATASUS, Sivep-Gripe), disponibilizados pelo Ministério da Saúde para
reutilização. O projeto reduz ainda mais o risco de reidentificação ao agregar e descartar
quase-identificadores, e produz apenas estatísticas populacionais, em linha com a LGPD para dados
de saúde (art. 11), que tolera o tratamento para estudos em saúde pública quando os dados são
anonimizados sempre que possível.
