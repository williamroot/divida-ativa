# Consulta Divida Ativa PGE-SP

Sistema de consulta automatizada de debitos inscritos na divida ativa do Estado de Sao Paulo, via site da Procuradoria Geral do Estado (PGE-SP).

## Funcionalidades

- **Consulta por CNPJ** — busca debitos de divida ativa de qualquer empresa
- **Detalhamento completo** — lista todas as CDAs com valores individuais, situacao, receitas (principal, juros, multa, honorarios)
- **Consulta em lote** — multiplos CNPJs via textarea ou upload CSV
- **Cache inteligente** — resultados armazenados por 24h em SQLite, com opcao de forcar nova busca
- **Interface web** — pagina responsiva com resultados em accordion expansivel
- **Exportacao JSON** — download dos resultados em formato JSON
- **Resolucao automatica de CAPTCHA** — via Capsolver API
- **Proxy residencial** — rotacao de IP via Cortex para evitar bloqueios

## Stack

| Componente | Tecnologia |
|------------|-----------|
| Backend | Python 3.12 + FastAPI |
| Scraping | httpx (async) + BeautifulSoup4 |
| Frontend | Jinja2 + CSS puro + JS vanilla |
| Banco | SQLite (aiosqlite) |
| CAPTCHA | Capsolver API |
| Proxy | Cortex (Port-per-IP) |
| Deploy | Docker + Docker Compose |

## Setup

### Pre-requisitos

- Docker + Docker Compose
- Conta no [Capsolver](https://www.capsolver.com/) (para resolver reCAPTCHA)
- Acesso ao proxy Cortex (opcional, recomendado para evitar rate limiting)

### Configuracao

Crie o arquivo `.env` na raiz do projeto:

```env
CAPSOLVER_API_KEY=sua_api_key_capsolver
DATABASE_PATH=/data/divida.db

# Proxy (opcional, mas recomendado)
PROXY_URL=http://cortex-http.was.dev.br:50258
CORTEX_API_URL=https://cortex.was.dev.br/api
CORTEX_API_KEY=sua_api_key_cortex
CORTEX_PROXY_HOST=cortex-http.was.dev.br
```

### Rodando

```bash
docker compose up -d
```

Acesse: [http://localhost:8000](http://localhost:8000)

### Desenvolvimento

O Docker Compose monta o codigo como volume com hot-reload:

```bash
docker compose up -d
docker compose logs -f    # acompanhar logs
```

## Uso

### Interface Web

1. Acesse `http://localhost:8000`
2. Digite o CNPJ e clique em "Consultar"
3. Resultados aparecem com devedor, resumo, debitos por tipo e CDAs individuais
4. Clique em cada CDA para expandir os detalhes (situacao, receitas, natureza)

### API

```bash
# Consulta individual
curl -X POST http://localhost:8000/api/consulta \
  -H "Content-Type: application/json" \
  -d '{"cnpj": "82110818000393"}'

# Forcar nova busca (ignorar cache)
curl -X POST http://localhost:8000/api/consulta \
  -H "Content-Type: application/json" \
  -d '{"cnpj": "82110818000393", "forcar": true}'

# Consulta em lote
curl -X POST http://localhost:8000/api/consulta/lote \
  -H "Content-Type: application/json" \
  -d '{"cnpjs": ["82110818000393", "33000167000101"]}'

# Status do lote
curl http://localhost:8000/api/consulta/lote/1/status

# Historico recente
curl http://localhost:8000/api/consultas/recentes
```

## Estrutura

```
divida/
├── app/
│   ├── main.py          # FastAPI app + rotas
│   ├── scraper.py       # Sessao HTTP, CAPTCHA, proxy
│   ├── parser.py        # Parsing HTML → JSON
│   ├── database.py      # SQLite async
│   ├── models.py        # Pydantic schemas
│   ├── templates/       # Jinja2 (base, index, resultado)
│   └── static/          # CSS + JS
├── .ia/                 # Documentacao para IA
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

## Como Funciona

O site da PGE-SP (`dividaativa.pge.sp.gov.br`) usa JavaServer Faces (JSF) com RichFaces. O scraping segue este fluxo:

1. **GET** na pagina para obter sessao (JSESSIONID) e ViewState
2. **AJAX POST** para mudar o tipo de pesquisa para CNPJ (atualiza ViewState)
3. **Resolver reCAPTCHA** via Capsolver (apenas 1x por sessao)
4. **POST** com CNPJ + token CAPTCHA para obter resumo de debitos
5. **POST** para cada tipo de debito para listar CDAs individuais
6. **POST** para cada CDA para obter detalhes (receitas, situacao, natureza)

O CAPTCHA so e resolvido na primeira consulta — as seguintes reutilizam a sessao validada.

## Rate Limiting

O site da PGE bloqueia apos ~15 requests rapidos (HTTP 403). O sistema lida com isso:

- **Proxy Cortex** com IPs dedicados (Port-per-IP)
- **Retry com backoff** progressivo (10s, 30s, 60s, 120s)
- **Rotacao de IP** automatica quando um IP e bloqueado
- Bloqueios duram ~5 minutos por IP
