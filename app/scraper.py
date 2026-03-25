"""Módulo de scraping para consulta de débitos no site da PGE-SP.

Usa httpx para requests HTTP e Capsolver para resolver reCAPTCHA v2.
Mantém uma sessão HTTP persistente — o CAPTCHA só é resolvido uma vez
e as consultas seguintes reutilizam a sessão validada.

Fluxo na primeira consulta (ou quando a sessão expira):
1. GET na página (obtém ViewState j_id1 e JSESSIONID)
2. POST AJAX para mudar tipo de pesquisa para CNPJ (obtém ViewState j_id2)
3. Resolver reCAPTCHA via Capsolver
4. POST final com CNPJ + token CAPTCHA + ViewState j_id2

Consultas seguintes na mesma sessão:
1. POST AJAX para mudar tipo de pesquisa para CNPJ (obtém novo ViewState)
2. POST final com CNPJ + ViewState (sem CAPTCHA)
"""

import asyncio
import logging
import os
import re

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

URL_CONSULTA = (
    "https://www.dividaativa.pge.sp.gov.br/sc/pages/consultas/consultarDebito.jsf"
)

RECAPTCHA_SITEKEY = "6Le9EjMUAAAAAPKi-JVCzXgY_ePjRV9FFVLmWKB_"
CAPSOLVER_API_URL = "https://api.capsolver.com"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,image/apng,*/*;"
        "q=0.8,application/signed-exchange;v=b3;q=0.7"
    ),
    "Accept-Language": "en-US,en;q=0.9,pt-BR;q=0.8,pt;q=0.7,es;q=0.6",
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "Pragma": "no-cache",
    "Upgrade-Insecure-Requests": "1",
}

MAX_TENTATIVAS = 3
REGEX_VIEW_STATE = re.compile(
    r'name="javax\.faces\.ViewState"[^>]+value="([^"]*)"'
)

POST_HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded",
    "Referer": URL_CONSULTA,
    "Origin": "https://www.dividaativa.pge.sp.gov.br",
}


class ScraperError(Exception):
    """Erro genérico do scraper de consulta PGE-SP."""


class SessaoPGE:
    """Mantém uma sessão HTTP persistente com o site da PGE-SP.

    Resolve o CAPTCHA apenas na primeira consulta. As seguintes
    reutilizam o JSESSIONID validado.
    """

    def __init__(self):
        self._client: httpx.AsyncClient | None = None
        self._captcha_resolvido = False
        self._lock = asyncio.Lock()
        self._proxy_ports: list[int] = []
        self._proxy_index = 0

    async def _obter_proxy_ports(self) -> list[int]:
        """Busca portas disponíveis na API do Cortex."""
        api_url = os.getenv("CORTEX_API_URL")
        api_key = os.getenv("CORTEX_API_KEY")
        if not api_url or not api_key:
            return []

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{api_url}/v1/ports",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                data = resp.json()
                ports = [info["port"] for info in data.get("ips", {}).values()]
                logger.info("Cortex: %d IPs disponíveis (portas: %s)", len(ports), ports)
                return ports
        except Exception:
            logger.warning("Falha ao buscar portas do Cortex")
            return []

    async def _proximo_proxy(self) -> str | None:
        """Retorna a próxima URL de proxy disponível (rotação de IPs)."""
        if not self._proxy_ports:
            self._proxy_ports = await self._obter_proxy_ports()
        if not self._proxy_ports:
            return os.getenv("PROXY_URL")

        proxy_host = os.getenv("CORTEX_PROXY_HOST", "cortex-http.was.dev.br")
        port = self._proxy_ports[self._proxy_index % len(self._proxy_ports)]
        self._proxy_index += 1
        return f"http://{proxy_host}:{port}"

    async def _garantir_client(self) -> httpx.AsyncClient:
        if self._client is None:
            proxy_url = await self._proximo_proxy()
            self._client = httpx.AsyncClient(
                headers=HEADERS,
                timeout=httpx.Timeout(120.0, connect=15.0),
                follow_redirects=True,
                proxy=proxy_url,
            )
            if proxy_url:
                logger.info("Usando proxy: %s", proxy_url)
        return self._client

    async def invalidar(self) -> None:
        """Fecha a sessão atual, forçando nova sessão + CAPTCHA com outro IP."""
        if self._client:
            await self._client.aclose()
            self._client = None
        self._captcha_resolvido = False
        logger.info("Sessão PGE invalidada, próximo IP será diferente")

    async def consultar(self, cnpj_limpo: str) -> str:
        """Consulta um CNPJ usando a sessão persistente.

        Usa lock para serializar consultas e evitar conflitos de ViewState.
        """
        async with self._lock:
            return await self._consultar_interno(cnpj_limpo)

    async def consultar_detalhes(
        self, html_resumo: str, indice_tipo: int = 0,
    ) -> str:
        """Clica no link de um tipo de débito para obter detalhes das CDAs.

        Args:
            html_resumo: HTML da página de resultado (após consultar CNPJ).
            indice_tipo: Índice do tipo de débito na tabela (0 = primeiro).

        Returns:
            HTML da página com detalhes das CDAs.
        """
        async with self._lock:
            client = await self._garantir_client()

            campos = _extrair_campos_formulario(html_resumo)

            link_param = (
                f"consultaDebitoForm:dataTable:{indice_tipo}:lnkConsultaDebito"
            )
            campos[link_param] = link_param

            resp = await client.post(
                URL_CONSULTA, data=campos, headers=POST_HEADERS,
            )
            resp.raise_for_status()

            html = resp.text
            logger.info(
                "Detalhe tipo %d: %d bytes", indice_tipo, len(html),
            )
            return html

    async def consultar_detalhe_cda(
        self, html_lista_cdas: str, indice_cda: int,
    ) -> str:
        """Clica em uma CDA individual para obter seus detalhes completos.

        Args:
            html_lista_cdas: HTML da página com lista de CDAs.
            indice_cda: Índice da CDA na tabela (0 = primeira).

        Returns:
            HTML da página com detalhes da CDA.
        """
        async with self._lock:
            client = await self._garantir_client()

            campos = _extrair_campos_formulario(html_lista_cdas)

            link_param = (
                f"consultaDebitoForm:dataTable2:{indice_cda}:j_id232"
            )
            campos[link_param] = link_param

            # Retry com espera progressiva para rate limiting
            esperas = [10, 30, 60, 120]
            for tentativa, espera in enumerate(esperas):
                resp = await client.post(
                    URL_CONSULTA, data=campos, headers=POST_HEADERS,
                )
                if resp.status_code == 403:
                    logger.warning(
                        "Rate limited (403) CDA %d, aguardando %ds...",
                        indice_cda, espera,
                    )
                    await asyncio.sleep(espera)
                    continue
                resp.raise_for_status()
                logger.info(
                    "Detalhe CDA %d: %d bytes", indice_cda, len(resp.text),
                )
                return resp.text

            raise ScraperError(f"Rate limited CDA {indice_cda}")

    async def _consultar_interno(self, cnpj_limpo: str) -> str:
        client = await self._garantir_client()

        # 1. GET para obter/renovar sessão e ViewState
        resp_get = await client.get(URL_CONSULTA)
        resp_get.raise_for_status()
        view_state = _extrair_view_state(resp_get.text)

        # 2. AJAX POST para mudar tipo de pesquisa para CNPJ
        ajax_data = {
            "consultaDebitoForm": "consultaDebitoForm",
            "consultaDebitoForm:decLblTipoConsulta:opcoesPesquisa": "CNPJ",
            "javax.faces.ViewState": view_state,
            "ajaxSingle": "consultaDebitoForm:decLblTipoConsulta:opcoesPesquisa",
            "consultaDebitoForm:decLblTipoConsulta:j_id88": (
                "consultaDebitoForm:decLblTipoConsulta:j_id88"
            ),
            "AJAX:EVENTS_COUNT": "1",
        }
        resp_ajax = await client.post(
            URL_CONSULTA, data=ajax_data, headers=POST_HEADERS,
        )
        resp_ajax.raise_for_status()
        view_state = _extrair_view_state(resp_ajax.text)

        # 3. Resolver CAPTCHA (só na primeira vez da sessão)
        recaptcha_token = ""
        if not self._captcha_resolvido:
            recaptcha_token = await _resolver_recaptcha()

        # 4. POST final
        data = {
            "consultaDebitoForm": "consultaDebitoForm",
            "consultaDebitoForm:decLblTipoConsulta:opcoesPesquisa": "CNPJ",
            "consultaDebitoForm:decTxtTipoConsulta:cnpj": cnpj_limpo,
            "consultaDebitoForm:decTxtTipoConsulta:tiposDebitosCnpj": "0",
            "consultaDebitoForm:j_id116": "Consultar",
            "consultaDebitoForm:modalSelecionarDebitoOpenedState": "",
            "consultaDebitoForm:modalDadosCartorioOpenedState": "",
            "javax.faces.ViewState": view_state,
        }
        if recaptcha_token:
            data["g-recaptcha-response"] = recaptcha_token

        resp_post = await client.post(
            URL_CONSULTA, data=data, headers=POST_HEADERS,
        )
        resp_post.raise_for_status()
        html = resp_post.text

        # Verificar se precisa de CAPTCHA (sessão expirou)
        if "Recaptcha não validado" in html:
            if self._captcha_resolvido:
                # Sessão expirou — invalidar e tentar de novo
                logger.info("Sessão expirou, resolvendo CAPTCHA novamente")
                self._captcha_resolvido = False
                return await self._consultar_interno(cnpj_limpo)
            raise ScraperError("reCAPTCHA não foi aceito pelo site.")

        if "erro interno no sistema" in html.lower():
            raise ScraperError("Erro interno no sistema da PGE-SP.")

        # Sucesso — marcar sessão como validada
        if not self._captcha_resolvido:
            self._captcha_resolvido = True
            logger.info("Sessão PGE validada com CAPTCHA")

        logger.info(
            "Consulta CNPJ %s: %d bytes",
            cnpj_limpo,
            len(html),
        )

        return html


# Instância global da sessão
_sessao = SessaoPGE()


def _limpar_cnpj(cnpj: str) -> str:
    """Remove caracteres não numéricos do CNPJ."""
    return re.sub(r"\D", "", cnpj)


def _extrair_view_state(html: str) -> str:
    """Extrai o valor de javax.faces.ViewState do HTML."""
    match = REGEX_VIEW_STATE.search(html)
    if not match:
        raise ScraperError(
            "Não foi possível extrair javax.faces.ViewState da página."
        )
    return match.group(1)


def _extrair_campos_formulario(html: str) -> dict[str, str]:
    """Extrai todos os campos do formulário consultaDebitoForm.

    Coleta inputs hidden, inputs text e selects com suas opções
    selecionadas para reproduzir o submit completo do formulário.
    """
    soup = BeautifulSoup(html, "lxml")
    form = soup.find("form", id="consultaDebitoForm")
    if not form:
        raise ScraperError(
            "Formulário 'consultaDebitoForm' não encontrado no HTML."
        )

    campos: dict[str, str] = {}

    for inp in form.find_all("input", attrs={"type": "hidden"}):
        nome = inp.get("name")
        if nome:
            campos[nome] = inp.get("value", "")

    for inp in form.find_all("input", attrs={"type": "text"}):
        nome = inp.get("name")
        if nome:
            campos[nome] = inp.get("value", "")

    for select in form.find_all("select"):
        nome = select.get("name")
        if not nome:
            continue
        selected = select.find("option", selected=True)
        if selected:
            campos[nome] = selected.get("value", "")
        else:
            first_option = select.find("option")
            if first_option:
                campos[nome] = first_option.get("value", "")

    return campos


def _contar_tipos_debito(html: str) -> int:
    """Conta quantos tipos de débito existem no resultado.

    Busca links com IDs no padrão
    ``consultaDebitoForm:dataTable:{n}:lnkConsultaDebito``.
    """
    matches = re.findall(
        r"consultaDebitoForm:dataTable:\d+:lnkConsultaDebito", html,
    )
    # Cada link aparece pelo menos uma vez; contar valores únicos
    return len(set(matches))


async def _resolver_recaptcha() -> str:
    """Resolve reCAPTCHA v2 usando Capsolver API."""
    api_key = os.getenv("CAPSOLVER_API_KEY")
    if not api_key:
        raise ScraperError("CAPSOLVER_API_KEY não configurada.")

    async with httpx.AsyncClient(timeout=120) as client:
        payload = {
            "clientKey": api_key,
            "task": {
                "type": "ReCaptchaV2TaskProxyLess",
                "websiteURL": URL_CONSULTA,
                "websiteKey": RECAPTCHA_SITEKEY,
            },
        }

        logger.info("Enviando reCAPTCHA para Capsolver...")
        resp = await client.post(f"{CAPSOLVER_API_URL}/createTask", json=payload)
        resultado = resp.json()

        if resultado.get("errorId", 0) != 0:
            raise ScraperError(
                f"Capsolver createTask erro: "
                f"{resultado.get('errorDescription', 'desconhecido')}"
            )

        task_id = resultado["taskId"]
        logger.info("Capsolver task criada: %s", task_id)

        for _ in range(60):
            await asyncio.sleep(2)

            resp = await client.post(
                f"{CAPSOLVER_API_URL}/getTaskResult",
                json={"clientKey": api_key, "taskId": task_id},
            )
            resultado = resp.json()

            if resultado.get("errorId", 0) != 0:
                raise ScraperError(
                    f"Capsolver erro: "
                    f"{resultado.get('errorDescription', 'desconhecido')}"
                )

            if resultado.get("status") == "ready":
                token = resultado["solution"]["gRecaptchaResponse"]
                logger.info("reCAPTCHA resolvido com sucesso")
                return token

        raise ScraperError("Timeout ao resolver reCAPTCHA via Capsolver.")


async def consultar_cnpj(cnpj: str) -> str:
    """Consulta débitos de dívida ativa por CNPJ no site da PGE-SP.

    Reutiliza sessão HTTP — CAPTCHA resolvido apenas uma vez.

    Args:
        cnpj: CNPJ a ser consultado (com ou sem formatação).

    Returns:
        HTML bruto da resposta.

    Raises:
        ScraperError: Se a consulta falhar após todas as tentativas.
    """
    cnpj_limpo = _limpar_cnpj(cnpj)
    if len(cnpj_limpo) != 14:
        raise ScraperError(
            f"CNPJ inválido: esperados 14 dígitos, recebidos {len(cnpj_limpo)}."
        )

    ultima_excecao: BaseException | None = None

    for tentativa in range(1, MAX_TENTATIVAS + 1):
        try:
            return await _sessao.consultar(cnpj_limpo)
        except (httpx.HTTPError, ScraperError) as exc:
            ultima_excecao = exc
            # Invalidar sessão em caso de erro para tentar do zero
            await _sessao.invalidar()
            if tentativa < MAX_TENTATIVAS:
                espera = 2 ** (tentativa - 1)
                logger.warning(
                    "Tentativa %d/%d falhou: %s. Aguardando %ds...",
                    tentativa,
                    MAX_TENTATIVAS,
                    exc,
                    espera,
                )
                await asyncio.sleep(espera)
            else:
                logger.error(
                    "Todas as %d tentativas falharam para CNPJ %s.",
                    MAX_TENTATIVAS,
                    cnpj_limpo,
                )

    raise ScraperError(
        f"Falha ao consultar CNPJ após {MAX_TENTATIVAS} tentativas."
    ) from ultima_excecao


async def consultar_detalhes(html_resumo: str, indice_tipo: int = 0) -> str:
    """Busca detalhes de um tipo de débito usando a sessão persistente.

    Args:
        html_resumo: HTML da página de resultado (após consultar CNPJ).
        indice_tipo: Índice do tipo de débito na tabela (0 = primeiro).

    Returns:
        HTML da página com a lista de CDAs individuais.
    """
    return await _sessao.consultar_detalhes(html_resumo, indice_tipo)


async def consultar_detalhe_cda(html_lista_cdas: str, indice_cda: int) -> str:
    """Busca detalhes de uma CDA individual usando a sessão persistente.

    O JSESSIONID está vinculado ao IP — deve usar o mesmo proxy da sessão.
    """
    return await _sessao.consultar_detalhe_cda(html_lista_cdas, indice_cda)
