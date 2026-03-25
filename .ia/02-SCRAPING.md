# Scraping - Site PGE-SP

## Site Alvo

URL: `https://www.dividaativa.pge.sp.gov.br/sc/pages/consultas/consultarDebito.jsf`

Sistema JSF (JavaServer Faces) com RichFaces/Ajax4jsf. Todos os requests são POST para a mesma URL.

## Fluxo de Consulta (5 etapas)

### 1. GET página inicial
- Obtém `JSESSIONID` (cookie) e `ViewState` (`j_id1`)
- O JSESSIONID fica vinculado ao IP — trocar IP invalida a sessão

### 2. AJAX POST para mudar tipo de pesquisa
- O formulário inicia no modo "CDA" (padrão)
- Precisa simular o `onchange` do `<select>` para trocar para "CNPJ"
- Isso muda o ViewState de `j_id1` para `j_id2`
- **SEM ESTE PASSO, o POST final dá "erro interno"**

Campos do AJAX:
```python
{
    "consultaDebitoForm": "consultaDebitoForm",
    "consultaDebitoForm:decLblTipoConsulta:opcoesPesquisa": "CNPJ",
    "javax.faces.ViewState": "j_id1",
    "ajaxSingle": "consultaDebitoForm:decLblTipoConsulta:opcoesPesquisa",
    "consultaDebitoForm:decLblTipoConsulta:j_id88": "consultaDebitoForm:decLblTipoConsulta:j_id88",
    "AJAX:EVENTS_COUNT": "1",
}
```

### 3. Resolver reCAPTCHA
- Site usa reCAPTCHA v2 (sitekey: `6Le9EjMUAAAAAPKi-JVCzXgY_ePjRV9FFVLmWKB_`)
- Resolvemos via Capsolver API (`ReCaptchaV2TaskProxyLess`)
- O token vai no campo `g-recaptcha-response` do POST
- **O CAPTCHA só precisa ser resolvido 1x por sessão** — consultas seguintes reusam o JSESSIONID

### 4. POST consulta CNPJ
- Envia todos os campos do formulário + token CAPTCHA + ViewState `j_id2`
- Retorna ~50KB HTML com resumo (devedor, tipos de débito, totais)

### 5. POST detalhe (click no tipo de débito)
- O link "ICMS Declarado" (etc) usa `jsfcljs()` que faz form submit
- Precisa enviar **TODOS os campos do formulário** + parâmetro do link
- Parâmetro: `consultaDebitoForm:dataTable:{index}:lnkConsultaDebito`
- Retorna ~180KB HTML com lista de todas as CDAs individuais

### 5b. POST detalhe de CDA individual
- Click no número da CDA (ex: `1005355797`)
- Parâmetro: `consultaDebitoForm:dataTable2:{index}:j_id232`
- Retorna ~89KB HTML com dados completos da CDA (receitas, situação, natureza)

## Sessão Persistente (SessaoPGE)

Classe singleton que mantém uma sessão HTTP com o site:
- `httpx.AsyncClient` compartilhado (preserva cookies)
- Lock asyncio para serializar requests
- Flag `_captcha_resolvido` — só resolve CAPTCHA 1x
- Invalida e recria sessão em caso de erro

## Proxy (Cortex)

- Proxy residencial com IPs dedicados via Port-per-IP
- API: `https://cortex.was.dev.br/api/v1/ports` (Bearer token)
- Cada porta = IP fixo de saída
- A sessão seleciona um IP e usa durante toda a consulta
- Rotação automática: quando dá 403, troca para próximo IP

## Rate Limiting

O site da PGE bloqueia com **403 Forbidden** após ~15 requests rápidos:
- O bloqueio é por **IP** (não por sessão)
- Duração: ~5 minutos
- O JSESSIONID fica vinculado ao IP — trocar IP invalida a sessão
- Solução: retry com backoff progressivo (10s, 30s, 60s, 120s)

## Função jsfcljs

O site JSF usa esta função para submeter formulários via JavaScript:
```javascript
function jsfcljs(form, params, target) {
    // Adiciona hidden inputs com params ao form
    // Submete o form
    // Remove os hidden inputs
}
```

Para simular: coletar todos os campos do formulário + adicionar o parâmetro do link.
