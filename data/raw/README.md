# Dados brutos SRAG (Sivep-Gripe)

Baixados em 2026-11-05 do Portal de Dados Abertos do SUS. O link original do enunciado
(`opendatasus.saude.gov.br/dataset/srag-2021-a-2024`) foi migrado para o novo portal, onde o
dataset passou a se chamar "SRAG 2019 a 2026", com um arquivo por ano epidemiológico.

Página do dataset: https://dadosabertos.saude.gov.br/dataset/srag-2019-a-2026

| Arquivo | Conteúdo | Fonte |
|---|---|---|
| `dicionario-de-dados-2019-a-2025.pdf` | Dicionário de dados (mesmo resource id citado no enunciado) | https://s3.sa-east-1.amazonaws.com/ckan.saude.gov.br/SRAG/dicionario-de-dados-2019-a-2025.pdf |
| `INFLUD26-02-11-2026.csv` | Banco vivo 2026, extração de 02/11/2026 | https://s3.sa-east-1.amazonaws.com/ckan.saude.gov.br/SRAG/2026/INFLUD26-02-11-2026.csv |
| `INFLUD25-02-11-2026.csv` | Banco vivo 2025, extração de 02/11/2026 | https://s3.sa-east-1.amazonaws.com/ckan.saude.gov.br/SRAG/2025/INFLUD25-02-11-2026.csv |

Formato dos CSVs: separador `;`, campos entre aspas, encoding latin-1, 194 colunas.
Os dois anos foram baixados porque o relatório exige os últimos 12 meses de casos.

Os CSVs somam cerca de 650 MB. Não versionar no Git; adicione `data/raw/*.csv` ao `.gitignore`.
