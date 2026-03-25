# Arquitetura

## Stack

- **Python 3.12** + **FastAPI** (monolito async)
- **httpx** (async HTTP client para scraping)
- **BeautifulSoup4 + lxml** (parsing HTML)
- **aiosqlite** (SQLite async para cache/histórico)
- **Pydantic** (validação de schemas)
- **Jinja2** (templates HTML)
- **Docker + Docker Compose**
- **Capsolver** (resolução de reCAPTCHA v2)
- **Cortex proxy** (proxy residencial com IP rotation)

## Estrutura de Pastas

```
divida/
├── CLAUDE.md
├── .ia/                    # Documentação para IA
├── .env                    # Credenciais (CAPSOLVER, proxy, etc)
├── .gitignore
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── data/                   # SQLite (volume Docker, gitignored)
├── docs/
│   └── superpowers/specs/  # Design spec original
└── app/
    ├── __init__.py
    ├── main.py             # FastAPI app, rotas API e UI
    ├── scraper.py           # Sessão PGE, CAPTCHA, proxy, requests
    ├── parser.py            # Parsing HTML → dict/JSON
    ├── database.py          # SQLite async (cache, histórico)
    ├── models.py            # Pydantic schemas
    ├── static/
    │   ├── style.css
    │   └── app.js
    └── templates/
        ├── base.html
        ├── index.html       # Página principal (individual + lote)
        └── resultado.html   # Resultado da consulta (partial AJAX)
```

## Fluxo Geral

1. Usuário digita CNPJ na interface web
2. FastAPI recebe POST `/api/consulta`
3. Verifica cache SQLite (24h)
4. Se não tem cache: scraper consulta site PGE-SP
5. Parser extrai dados do HTML
6. Salva no SQLite e retorna HTML renderizado
7. Frontend exibe resultado com accordion expandível para CDAs

## Rotas

| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/` | Página principal |
| POST | `/api/consulta` | Consulta individual (body: `{cnpj, forcar?}`) |
| POST | `/api/consulta/lote` | Consulta em lote (body: `{cnpjs}`) |
| GET | `/api/consulta/lote/{id}/status` | Status do lote |
| GET | `/api/consulta/{id}` | Resultado por ID |
| GET | `/api/consultas/recentes` | Histórico recente |

## Docker

```bash
docker compose up -d        # Subir
docker compose logs -f      # Logs
docker compose restart      # Reiniciar (hot-reload via volume mount)
```

Porta: `8000`
Volume: `./data:/data` (SQLite), `./app:/app/app` (hot-reload dev)
