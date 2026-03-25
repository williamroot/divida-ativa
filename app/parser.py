"""Parser do HTML de resposta da consulta de dívida ativa PGE-SP.

Extrai dados estruturados das páginas HTML retornadas pelo sistema JSF
em dividaativa.pge.sp.gov.br.
"""

import logging
import re
from typing import Any

from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _limpar_texto(texto: str) -> str:
    """Remove espaços extras, quebras de linha e caracteres invisíveis."""
    if not texto:
        return ""
    texto = texto.replace("\xa0", " ")
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip()


def _converter_valor(valor_str: str) -> float | None:
    """Converte valor monetário brasileiro para float.

    Exemplos:
        'R$ 1.234,56' -> 1234.56
        '1.234.567,89' -> 1234567.89
    """
    if not valor_str:
        return None
    texto = _limpar_texto(valor_str)
    texto = texto.replace("R$", "").strip()
    if not texto:
        return None
    try:
        texto = texto.replace(".", "").replace(",", ".")
        return float(texto)
    except (ValueError, AttributeError):
        logger.warning("Não foi possível converter valor: '%s'", valor_str)
        return None


def _converter_data(data_str: str) -> str | None:
    """Converte data dd/mm/yyyy para yyyy-mm-dd."""
    if not data_str:
        return None
    texto = _limpar_texto(data_str)
    match = re.match(r"^(\d{2})/(\d{2})/(\d{4})$", texto)
    if not match:
        return None
    dia, mes, ano = match.groups()
    return f"{ano}-{mes}-{dia}"


# ---------------------------------------------------------------------------
# Extratores específicos do site PGE-SP
# ---------------------------------------------------------------------------

def _extrair_devedor(soup: BeautifulSoup) -> dict[str, Any]:
    """Extrai dados do devedor do bloco consultaDevedor."""
    devedor: dict[str, Any] = {}

    bloco = soup.find(id="consultaDebitoForm:consultaDevedor")
    if not bloco:
        return devedor

    tabela = bloco.find("table")
    if not tabela:
        return devedor

    for linha in tabela.find_all("tr"):
        celulas = linha.find_all("td")
        if len(celulas) < 2:
            continue
        chave = _limpar_texto(celulas[0].get_text()).rstrip(":")
        valor = _limpar_texto(celulas[1].get_text())
        if not chave or not valor:
            continue

        chave_lower = chave.lower()
        if "devedor" in chave_lower or "nome" in chave_lower or "razão" in chave_lower:
            devedor["nome"] = valor
        elif "cnpj" in chave_lower or "cpf" in chave_lower:
            devedor["cnpj"] = valor
        elif "endereço" in chave_lower or "endereco" in chave_lower:
            devedor["endereco"] = valor
        elif "município" in chave_lower or "municipio" in chave_lower:
            devedor["municipio"] = valor
        elif "uf" in chave_lower or "estado" in chave_lower:
            devedor["uf"] = valor
        elif "cep" in chave_lower:
            devedor["cep"] = valor
        else:
            devedor[_normalizar_chave(chave)] = valor

    return devedor


def _extrair_debitos(soup: BeautifulSoup) -> list[dict[str, Any]]:
    """Extrai lista de débitos da tabela rich-table no bloco SearchResultBlock."""
    debitos: list[dict[str, Any]] = []

    bloco = soup.find(id="consultaDebitoForm:consultaDebitoSearchResultBlock")
    if not bloco:
        return debitos

    tabela = bloco.find("table", class_="rich-table")
    if not tabela:
        return debitos

    # Extrair cabeçalho
    headers = []
    for row in tabela.find_all("tr"):
        celulas = row.find_all(["td", "th"], class_=lambda c: c and "headercell" in str(c))
        if celulas:
            headers = [_limpar_texto(c.get_text()) for c in celulas]
            break

    if not headers:
        headers = ["tipo", "qtde", "origem", "valor_total"]

    # Extrair linhas de dados (excluir header e footer)
    for row in tabela.find_all("tr"):
        celulas = row.find_all("td")
        if not celulas:
            continue

        # Pular footer (rich-table-footercell)
        classes = " ".join(celulas[0].get("class", []))
        if "footercell" in classes or "headercell" in classes:
            continue

        # Linhas de dados têm class rich-table-cell
        celulas_dados = [c for c in celulas if "rich-table-cell" in " ".join(c.get("class", []))]
        if not celulas_dados:
            continue

        debito: dict[str, Any] = {}
        textos = [_limpar_texto(c.get_text()) for c in celulas_dados]

        if len(textos) >= 4:
            debito["tipo"] = textos[0]
            debito["quantidade"] = int(textos[1]) if textos[1].isdigit() else textos[1]
            debito["origem"] = textos[2]
            debito["valor_total"] = _converter_valor(textos[3])
        elif len(textos) >= 1:
            debito["tipo"] = textos[0]
            for j, texto in enumerate(textos[1:], 1):
                debito[f"campo_{j}"] = texto

        if debito:
            debitos.append(debito)

    return debitos


def _extrair_resumo(soup: BeautifulSoup) -> dict[str, Any]:
    """Extrai dados do resumo (footer da tabela de resultados)."""
    resumo: dict[str, Any] = {}

    bloco = soup.find(id="consultaDebitoForm:consultaDebitoSearchResultBlock")
    if not bloco:
        return resumo

    tabela = bloco.find("table", class_="rich-table")
    if not tabela:
        return resumo

    for row in tabela.find_all("tr"):
        celulas = row.find_all("td", class_=lambda c: c and "footercell" in str(c))
        if not celulas:
            continue

        textos = [_limpar_texto(c.get_text()) for c in celulas]
        if len(textos) >= 4:
            # "Débitos:" "85" "Valor Total Atualizado (R$):" "105.517.923,12"
            if textos[0].lower().startswith("débito") or textos[0].lower().startswith("debito"):
                resumo["total_debitos"] = int(textos[1]) if textos[1].isdigit() else textos[1]
            if "valor total" in textos[2].lower():
                resumo["label_valor"] = textos[2].rstrip(":")
                resumo["valor_total"] = _converter_valor(textos[3])

    return resumo


def _extrair_cartorio(soup: BeautifulSoup) -> dict[str, Any]:
    """Extrai dados de protesto/cartório do modal."""
    cartorio: dict[str, Any] = {}

    bloco = soup.find(id="consultaDebitoForm:modalDadosCartorio")
    if not bloco:
        return cartorio

    # Extrair pares chave-valor dos spans/labels
    for label_elem in bloco.find_all(["label", "span", "b", "strong"]):
        texto = _limpar_texto(label_elem.get_text())
        if not texto or ":" not in texto:
            continue

        chave, _, valor = texto.partition(":")
        chave = chave.strip()
        valor = valor.strip()

        if not chave:
            continue

        # Se o valor está vazio, tentar pegar do próximo sibling
        if not valor:
            irmao = label_elem.find_next_sibling(["span", "div", "td"])
            if irmao:
                valor = _limpar_texto(irmao.get_text())

        # Ignorar mensagens de "não encontrado" como valores
        if valor and "não foram encontradas" not in valor.lower():
            cartorio[_normalizar_chave(chave)] = valor

    return cartorio


def _detectar_sem_resultado(soup: BeautifulSoup) -> bool:
    """Verifica se a página indica que não há resultados."""
    # Verificar o bloco específico de "nenhum resultado"
    info_block = soup.find(id="consultaDebitoForm:consultaDebitoSearchInfoResultBlock")
    if info_block:
        texto = _limpar_texto(info_block.get_text()).lower()
        if "nenhum resultado" in texto:
            return True

    return False


def _normalizar_chave(texto: str) -> str:
    """Normaliza texto para usar como chave de dicionário."""
    if not texto:
        return ""
    texto = texto.rstrip(":").strip().lower()
    substituicoes = {
        "á": "a", "à": "a", "ã": "a", "â": "a",
        "é": "e", "ê": "e", "í": "i",
        "ó": "o", "ô": "o", "õ": "o",
        "ú": "u", "ü": "u", "ç": "c", "ñ": "n",
    }
    for original, substituto in substituicoes.items():
        texto = texto.replace(original, substituto)
    texto = re.sub(r"[^\w\s]", "", texto)
    texto = re.sub(r"\s+", "_", texto)
    return texto.strip("_")


# ---------------------------------------------------------------------------
# Função principal
# ---------------------------------------------------------------------------

def parsear_resultado(html: str) -> dict[str, Any]:
    """Parseia o HTML de resposta da consulta PGE-SP.

    Returns:
        Dicionário com:
        - encontrado (bool)
        - devedor (dict)
        - debitos (list[dict])
        - resumo (dict)
        - cartorio (dict)
    """
    if not html or not html.strip():
        logger.warning("HTML vazio recebido para parsing")
        return _resultado_vazio()

    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        logger.exception("Erro ao criar parser BeautifulSoup")
        return _resultado_vazio()

    if _detectar_sem_resultado(soup):
        logger.info("Nenhum débito encontrado para o CNPJ consultado")
        return _resultado_vazio()

    devedor = _extrair_devedor(soup)
    debitos = _extrair_debitos(soup)
    resumo = _extrair_resumo(soup)
    cartorio = _extrair_cartorio(soup)

    encontrado = bool(devedor or debitos or resumo)

    if not encontrado:
        logger.warning(
            "Nenhum dado extraído do HTML (%d bytes). Estrutura pode ter mudado.",
            len(html),
        )

    return {
        "encontrado": encontrado,
        "devedor": devedor,
        "debitos": debitos,
        "resumo": resumo,
        "cartorio": cartorio,
    }


# ---------------------------------------------------------------------------
# Parser da página de detalhes (CDAs individuais)
# ---------------------------------------------------------------------------

# Mapeamento de cabeçalhos da tabela para nomes padronizados dos campos
_MAPA_CAMPOS_DETALHE: dict[str, str] = {
    "cpf_cnpj": "cpf_cnpj",
    "cpfcnpj": "cpf_cnpj",
    "ie": "ie",
    "inscricao_estadual": "ie",
    "n_de_registrocda": "cda",
    "no_de_registrocda": "cda",
    "numero_de_registrocda": "cda",
    "registrocda": "cda",
    "cda": "cda",
    "referencia": "referencia",
    "data_de_inscricao": "data_inscricao",
    "data_inscricao": "data_inscricao",
    "valor_atualizado_r": "valor_atualizado",
    "valor_atualizado_rs": "valor_atualizado",
    "valor_atualizado": "valor_atualizado",
    "opcoes_de_pagamento": "opcoes_pagamento",
    "opcoes_pagamento": "opcoes_pagamento",
    "observacao": "observacao",
}


def _extrair_titulo_detalhe(html: str) -> str:
    """Extrai o titulo da pagina de detalhes, como 'Debitos relativos a ICMS Declarado'."""
    if not html:
        return ""
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        return ""

    # Procurar texto que contenha "Débitos relativos a"
    padrao = re.compile(r"D[ée]bitos\s+relativos\s+a\s+.+", re.IGNORECASE)

    # Tentar em elementos de texto visíveis
    for tag in soup.find_all(["span", "td", "th", "div", "label", "b", "strong", "h1", "h2", "h3", "h4"]):
        texto = _limpar_texto(tag.get_text())
        match = padrao.search(texto)
        if match:
            return match.group(0).strip()

    return ""


def parsear_detalhes(html: str) -> list[dict[str, Any]]:
    """Parseia o HTML da pagina de detalhes e extrai a lista de CDAs individuais.

    Args:
        html: HTML da pagina de detalhes (apos clicar no tipo de debito).

    Returns:
        Lista de dicts, cada um representando uma CDA com campos:
        - cpf_cnpj: str
        - ie: str (Inscricao Estadual)
        - cda: str (N de Registro/CDA)
        - referencia: str
        - data_inscricao: str (convertido para ISO yyyy-mm-dd)
        - valor_atualizado: float
        - opcoes_pagamento: str
        - observacao: str
    """
    if not html or not html.strip():
        logger.warning("HTML vazio recebido para parsing de detalhes")
        return []

    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        logger.exception("Erro ao criar parser BeautifulSoup para detalhes")
        return []

    # Localizar a tabela de detalhes
    tabela = soup.find("table", id="consultaDebitoForm:dataTable2")
    if not tabela:
        # Fallback: tabela rich-table que contenha "Registro/CDA"
        for candidata in soup.find_all("table", class_="rich-table"):
            if "Registro/CDA" in candidata.get_text():
                tabela = candidata
                break

    if not tabela:
        logger.warning("Tabela de detalhes nao encontrada no HTML")
        return []

    # Extrair cabecalhos
    headers: list[str] = []
    for row in tabela.find_all("tr"):
        celulas_header = row.find_all(
            ["td", "th"],
            class_=lambda c: c and "headercell" in str(c),
        )
        if celulas_header:
            headers = [_normalizar_chave(_limpar_texto(c.get_text())) for c in celulas_header]
            break

    if not headers:
        logger.warning("Cabecalhos da tabela de detalhes nao encontrados")
        return []

    # Mapear indices dos cabecalhos para nomes padronizados
    campos_por_indice: list[str] = []
    for h in headers:
        campo = _MAPA_CAMPOS_DETALHE.get(h, h)
        campos_por_indice.append(campo)

    # Extrair linhas de dados
    cdas: list[dict[str, Any]] = []
    for row in tabela.find_all("tr"):
        celulas = row.find_all("td")
        if not celulas:
            continue

        # Pular linhas de header e footer
        classes_primeira = " ".join(celulas[0].get("class", []))
        if "headercell" in classes_primeira or "footercell" in classes_primeira:
            continue

        # Somente linhas de dados (rich-table-cell)
        celulas_dados = [
            c for c in celulas
            if "rich-table-cell" in " ".join(c.get("class", []))
        ]
        if not celulas_dados:
            continue

        textos = [_limpar_texto(c.get_text()) for c in celulas_dados]

        cda_dict: dict[str, Any] = {}
        for i, texto in enumerate(textos):
            if i >= len(campos_por_indice):
                break

            campo = campos_por_indice[i]

            if campo == "data_inscricao":
                cda_dict[campo] = _converter_data(texto) or texto
            elif campo == "valor_atualizado":
                cda_dict[campo] = _converter_valor(texto)
            else:
                cda_dict[campo] = texto

        if cda_dict:
            cdas.append(cda_dict)

    logger.info("Extraidas %d CDAs da pagina de detalhes", len(cdas))
    return cdas


# ---------------------------------------------------------------------------
# Parser do detalhe de uma CDA individual
# ---------------------------------------------------------------------------

def _encontrar_painel(soup: BeautifulSoup, texto_titulo: str) -> Tag | None:
    """Encontra um painel RichFaces cujo header contenha o texto informado.

    Paineis seguem o padrão: div com id ``*_header`` contendo o título,
    e div irmã com id ``*_body`` contendo o conteúdo.

    Returns:
        Tag do body do painel, ou None se não encontrado.
    """
    for div in soup.find_all("div", id=lambda x: x and x.endswith("_header")):
        if texto_titulo.lower() in _limpar_texto(div.get_text()).lower():
            body_id = div["id"].replace("_header", "_body")
            body = soup.find("div", id=body_id)
            if body:
                return body
    return None


def _extrair_pares_painel(body: Tag) -> dict[str, str]:
    """Extrai pares chave-valor de divs dentro do body de um painel.

    Cada div contém texto no formato ``Label:\\n\\t\\t\\tValor``.
    """
    pares: dict[str, str] = {}
    for div in body.find_all("div"):
        texto = div.get_text(separator="\n")
        if ":" not in texto:
            continue
        chave, _, valor = texto.partition(":")
        chave = _limpar_texto(chave)
        valor = _limpar_texto(valor)
        if chave and valor:
            pares[chave] = valor
    return pares


def parsear_detalhe_cda(html: str) -> dict[str, Any]:
    """Parseia o HTML do detalhe de uma CDA individual.

    Returns:
        Dict com:
        - cda: str (N° Registro)
        - data_inscricao: str (ISO date)
        - processo_unificado: str
        - processo_outros: str
        - situacao: str
        - saldo: float
        - receitas: list[dict] (each with tipo_receita: str, valor: float)
        - natureza: str (e.g. "ICMS Declarado inscrito por ...")
        - referencias: list[dict] (each with data, valor, data_inicio_juros,
          data_inicio_correcao)
    """
    if not html or not html.strip():
        logger.warning("HTML vazio recebido para parsing de detalhe CDA")
        return {}

    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        logger.exception("Erro ao criar parser BeautifulSoup para detalhe CDA")
        return {}

    resultado: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Painel "Dados N° de Registro/CDA"
    # ------------------------------------------------------------------
    body_dados = _encontrar_painel(soup, "Registro/CDA")
    if body_dados:
        pares = _extrair_pares_painel(body_dados)

        mapa_campos: dict[str, str] = {
            "registro/cda": "cda",
            "n° de registro/cda": "cda",
            "no de registro/cda": "cda",
            "data de inscrição": "data_inscricao",
            "data de inscricao": "data_inscricao",
            "número do processo (unificado)": "processo_unificado",
            "numero do processo (unificado)": "processo_unificado",
            "número do processo (outros)": "processo_outros",
            "numero do processo (outros)": "processo_outros",
            "situação": "situacao",
            "situacao": "situacao",
            "saldo (r$)": "saldo",
            "saldo": "saldo",
        }

        for chave_original, valor in pares.items():
            chave_lower = chave_original.lower().strip()
            # Tentar match exato, senão parcial
            campo = mapa_campos.get(chave_lower)
            if not campo:
                for padrao, nome_campo in mapa_campos.items():
                    if padrao in chave_lower:
                        campo = nome_campo
                        break

            if not campo:
                continue

            if campo == "data_inscricao":
                resultado[campo] = _converter_data(valor) or valor
            elif campo == "saldo":
                resultado[campo] = _converter_valor(valor)
            else:
                resultado[campo] = valor

    # ------------------------------------------------------------------
    # Painel "Receitas do Débito"
    # ------------------------------------------------------------------
    receitas: list[dict[str, Any]] = []
    body_receitas = _encontrar_painel(soup, "Receitas")
    if body_receitas:
        # Encontrar tabela cujo header contenha "Tipo de Receita"
        tabela_receitas: Tag | None = None
        for tabela_candidata in body_receitas.find_all("table"):
            if "Tipo de Receita" in tabela_candidata.get_text():
                tabela_receitas = tabela_candidata
                break

        if tabela_receitas:
            for row in tabela_receitas.find_all("tr"):
                celulas = row.find_all("td")
                if not celulas:
                    continue

                # Pular headers e footers
                classes_primeira = " ".join(celulas[0].get("class", []))
                if "headercell" in classes_primeira or "footercell" in classes_primeira:
                    continue

                celulas_dados = [
                    c for c in celulas
                    if "rich-table-cell" in " ".join(c.get("class", []))
                ]
                if len(celulas_dados) < 2:
                    continue

                tipo_receita = _limpar_texto(celulas_dados[0].get_text())
                valor_receita = _converter_valor(celulas_dados[1].get_text())

                if tipo_receita:
                    receitas.append({
                        "tipo_receita": tipo_receita,
                        "valor": valor_receita,
                    })

    resultado["receitas"] = receitas

    # ------------------------------------------------------------------
    # Painel "Natureza da Dívida / Origem"
    # ------------------------------------------------------------------
    natureza = ""
    referencias: list[dict[str, Any]] = []
    body_natureza = _encontrar_painel(soup, "Natureza")
    if body_natureza:
        # O título da natureza está no primeiro th da tabela
        tabela_natureza: Tag | None = body_natureza.find("table")
        if tabela_natureza:
            primeiro_th = tabela_natureza.find("th")
            if primeiro_th:
                natureza = _limpar_texto(primeiro_th.get_text())

            # Extrair linhas de dados (pular headers)
            linhas_dados = []
            for row in tabela_natureza.find_all("tr"):
                celulas = row.find_all("td")
                if not celulas:
                    continue

                classes_primeira = " ".join(celulas[0].get("class", []))
                if "headercell" in classes_primeira or "footercell" in classes_primeira:
                    continue

                celulas_dados = [
                    c for c in celulas
                    if "rich-table-cell" in " ".join(c.get("class", []))
                ]
                if celulas_dados:
                    linhas_dados.append(celulas_dados)

            for celulas_dados in linhas_dados:
                textos = [_limpar_texto(c.get_text()) for c in celulas_dados]
                ref: dict[str, Any] = {}

                if len(textos) >= 1:
                    ref["data"] = _converter_data(textos[0]) or textos[0]
                if len(textos) >= 2:
                    ref["valor"] = _converter_valor(textos[1])
                if len(textos) >= 3:
                    ref["data_inicio_juros"] = (
                        _converter_data(textos[2]) or textos[2]
                    )
                if len(textos) >= 4:
                    ref["data_inicio_correcao"] = (
                        _converter_data(textos[3]) or textos[3]
                    )

                if ref:
                    referencias.append(ref)

    resultado["natureza"] = natureza
    resultado["referencias"] = referencias

    if not resultado.get("cda"):
        logger.warning("Nenhum dado de CDA extraido do HTML de detalhe")
        return {}

    logger.info("Detalhe CDA %s parseado com sucesso", resultado.get("cda"))
    return resultado


def _resultado_vazio() -> dict[str, Any]:
    return {
        "encontrado": False,
        "devedor": {},
        "debitos": [],
        "resumo": {},
        "cartorio": {},
    }
