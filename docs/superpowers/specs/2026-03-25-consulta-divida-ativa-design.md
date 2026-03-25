# Consulta Dívida Ativa PGE-SP — Design Spec

## Objetivo

Projeto Python com Docker que consulta débitos de dívida ativa no site da PGE-SP (`dividaativa.pge.sp.gov.br`), parametrizando o CNPJ, parseando o HTML retornado para JSON, com interface web simples.

## Arquitetura

Monolito async com FastAPI em container Docker único.

```
Docker Container
├── FastAPI App
│   ├── Rotas API (consulta individual + lote)
│   ├── Rotas UI (templates Jinja2)
│   ├── Scraper (httpx async)
│   ├── Parser (BeautifulSoup4)
│   └── Database (SQLite + aiosqlite)
```

## Estrutura de Pastas

```
divida/
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── app/
│   ├── main.py              # FastAPI app, rotas API e UI
│   ├── scraper.py           # Request ao site da PGE (GET + POST)
│   ├── parser.py            # Parsing HTML → dict
│   ├── database.py          # SQLite async
│   ├── models.py            # Schemas Pydantic
│   ├── static/
│   │   ├── style.css
│   │   └── app.js
│   └── templates/
│       ├── base.html
│       ├── index.html
│       └── resultado.html
```

## Scraper

- `httpx.AsyncClient` com fluxo de 2 etapas:
  1. GET na página de consulta → captura `JSESSIONID` (cookie) e `ViewState` (hidden field no HTML)
  2. POST com CNPJ + dados do formulário JSF
- Retry: máximo 3 tentativas com backoff exponencial
- Timeout: 30s por request
- Headers que simulam navegador real

## Parser

- BeautifulSoup4 para extrair dados do HTML
- Dados extraídos:
  - Dados do devedor (nome, CNPJ, endereço)
  - Lista de CDAs (número, valor, origem, data inscrição, situação)
  - Dados de cartório/protesto
  - Qualquer informação adicional presente na página
- Retorna dict estruturado, validado via Pydantic

## API

| Método | Rota | Descrição |
|--------|------|-----------|
| POST | `/api/consulta` | Consulta individual por CNPJ |
| POST | `/api/consulta/lote` | Inicia consulta em lote |
| GET | `/api/consulta/lote/{id}/status` | Status do lote |
| GET | `/api/consulta/{id}` | Resultado de uma consulta |

## Banco de Dados

SQLite com aiosqlite.

**Tabela `consultas`:**
- id (INTEGER PK)
- cnpj (TEXT)
- resultado_json (TEXT)
- status (TEXT: pendente/concluido/erro)
- criado_em (TIMESTAMP)

**Tabela `lotes`:**
- id (INTEGER PK)
- status (TEXT: processando/concluido)
- total (INTEGER)
- concluidos (INTEGER)
- criado_em (TIMESTAMP)

**Tabela `lote_consultas`:**
- lote_id (FK)
- consulta_id (FK)

Cache de 24h — evita re-consultar o mesmo CNPJ em período curto.

## Consulta em Lote

- Input: lista de CNPJs via textarea ou upload CSV
- Processamento via `BackgroundTask` do FastAPI
- Delay de 1-2s entre consultas para não sobrecarregar o site
- Polling de status via `/api/consulta/lote/{id}/status`
- Resultados disponíveis quando o lote finaliza

## Interface Web

- FastAPI + Jinja2 templates
- CSS puro, sem framework
- JavaScript vanilla (fetch API)
- Página única com duas abas: "Individual" e "Lote"
- Máscara de CNPJ no campo de input
- Histórico de consultas na parte inferior
- Botão de exportação JSON

## Docker

- `Dockerfile`: Python 3.12 slim, instala requirements, roda uvicorn
- `docker-compose.yml`: serviço único, porta 8000, volume para SQLite
- Hot-reload em dev (volume mount do código)

## Dependências

- fastapi
- uvicorn
- httpx
- beautifulsoup4
- lxml
- aiosqlite
- pydantic
- jinja2
- python-multipart
