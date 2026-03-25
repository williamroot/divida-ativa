# Decisoes Tecnicas e Problemas Conhecidos

## Decisões

### Monolito async (FastAPI)
- Escolhido por simplicidade — um único container Docker
- httpx async para I/O não-bloqueante
- Background tasks do FastAPI para consultas em lote

### Sessão persistente (SessaoPGE)
- O reCAPTCHA só precisa ser resolvido 1x por sessão HTTP
- Economia de ~R$0.002/consulta no Capsolver após a primeira
- Sessão invalidada automaticamente em caso de erro

### SQLite para cache
- Cache de 24h evita re-consultar o mesmo CNPJ
- Flag `forcar` no request para ignorar cache
- Histórico de consultas recentes na interface

### Proxy Cortex com Port-per-IP
- JSESSIONID vinculado ao IP — precisa de IP sticky por sessão
- Portas dedicadas do Cortex garantem IP fixo por sessão
- Rotação entre portas quando um IP é bloqueado

## Problemas Conhecidos

### Rate Limiting da PGE
- Site bloqueia com 403 após ~15 requests rápidos no mesmo IP
- Bloqueio dura ~5 minutos
- Com 4 IPs do Cortex, é possível rotacionar se um for bloqueado
- Para 85 CDAs com detalhes individuais, é necessário retry com backoff

### JSESSIONID vinculado ao IP
- Não é possível fazer requests paralelos com IPs diferentes na mesma sessão
- Tentativa de usar JSESSIONID com IP diferente retorna a página inicial (sem dados)
- Consequência: detalhes de CDAs são buscados sequencialmente no mesmo IP

### ViewState JSF
- O ViewState muda a cada interação (j_id1 → j_id2 → j_id3 → ...)
- Enviar POST com ViewState errado causa "erro interno no sistema"
- Cada click (tipo débito, CDA) altera o ViewState

### IDs JSF dinâmicos
- IDs como `j_id232`, `j_id1025` podem mudar em deploys do servidor
- O parser usa busca por texto/padrão como fallback

## Variáveis de Ambiente

| Variável | Descrição |
|----------|-----------|
| `CAPSOLVER_API_KEY` | API key do Capsolver para resolver reCAPTCHA |
| `DATABASE_PATH` | Path do SQLite (default: `data/divida.db`) |
| `PROXY_URL` | URL do proxy fixo (porta dedicada Cortex) |
| `CORTEX_API_URL` | URL da API Cortex para listar IPs |
| `CORTEX_API_KEY` | Bearer token da API Cortex |
| `CORTEX_PROXY_HOST` | Host do proxy Cortex |
