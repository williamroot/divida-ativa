"""Aplicação principal FastAPI para consulta de dívida ativa PGE-SP."""

import asyncio
import json
import logging
import re

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.database import (
    adicionar_consulta_lote,
    atualizar_consulta,
    atualizar_lote,
    buscar_cache,
    criar_consulta,
    criar_lote,
    init_db,
    listar_consultas_recentes,
    obter_consulta,
    obter_lote,
)
from app.models import ConsultaLoteRequest, ConsultaRequest
from app.parser import parsear_detalhe_cda, parsear_detalhes, parsear_resultado
from app.scraper import (
    ScraperError,
    consultar_cnpj,
    consultar_detalhe_cda,
    consultar_detalhes,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Consulta Dívida Ativa PGE-SP")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

DELAY_ENTRE_CONSULTAS = 1.5


@app.on_event("startup")
async def startup():
    await init_db()
    logger.info("Banco de dados inicializado")


# ---------------------------------------------------------------------------
# Páginas HTML
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def pagina_inicial(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# ---------------------------------------------------------------------------
# API - Consulta individual
# ---------------------------------------------------------------------------

def _contexto_resultado(request: Request, resultado: dict) -> dict:
    """Monta o contexto do template a partir do resultado parseado."""
    return {
        "request": request,
        "devedor": resultado.get("devedor", {}),
        "debitos": resultado.get("debitos", []),
        "resumo": resultado.get("resumo", {}),
        "cartorio": resultado.get("cartorio", {}),
        "cdas": resultado.get("cdas", []),
        "resultado_json": json.dumps(resultado, ensure_ascii=False),
    }


@app.post("/api/consulta", response_class=HTMLResponse)
async def api_consulta(request: Request, body: ConsultaRequest):
    cnpj = _limpar_cnpj(body.cnpj)
    if len(cnpj) != 14:
        raise HTTPException(status_code=400, detail="CNPJ inválido. Deve ter 14 dígitos.")

    if not body.forcar:
        cache = await buscar_cache(cnpj)
        if cache:
            logger.info("Cache encontrado para CNPJ %s", cnpj)
            return templates.TemplateResponse(
                "resultado.html", _contexto_resultado(request, cache["resultado"])
            )

    consulta_id = await criar_consulta(cnpj)

    try:
        html_resposta = await consultar_cnpj(cnpj)
        resultado = parsear_resultado(html_resposta)

        # Buscar detalhes de cada tipo de débito e cada CDA
        if resultado.get("encontrado") and resultado.get("debitos"):
            todas_cdas = []
            for i in range(len(resultado["debitos"])):
                try:
                    html_detalhe = await consultar_detalhes(html_resposta, i)
                    cdas = parsear_detalhes(html_detalhe)

                    # Buscar detalhes sequencialmente (mesmo IP da sessão)
                    html_atual = html_detalhe
                    for j, cda in enumerate(cdas):
                        try:
                            html_cda = await consultar_detalhe_cda(html_atual, j)
                            detalhe = parsear_detalhe_cda(html_cda)
                            if detalhe:
                                cda["detalhe"] = detalhe
                                html_atual = html_cda
                        except Exception:
                            logger.warning("Erro detalhe CDA %d do tipo %d", j, i)

                    todas_cdas.extend(cdas)
                except Exception:
                    logger.exception("Erro ao buscar detalhes do tipo %d", i)
            resultado["cdas"] = todas_cdas

        resultado_json = json.dumps(resultado, ensure_ascii=False)
        await atualizar_consulta(consulta_id, "concluido", resultado_json)
    except ScraperError as exc:
        await atualizar_consulta(consulta_id, "erro")
        raise HTTPException(status_code=502, detail=str(exc))
    except Exception:
        await atualizar_consulta(consulta_id, "erro")
        logger.exception("Erro inesperado na consulta CNPJ %s", cnpj)
        raise HTTPException(status_code=500, detail="Erro interno ao processar consulta.")

    return templates.TemplateResponse(
        "resultado.html", _contexto_resultado(request, resultado)
    )


# ---------------------------------------------------------------------------
# API - Consulta em lote
# ---------------------------------------------------------------------------

@app.post("/api/consulta/lote")
async def api_consulta_lote(body: ConsultaLoteRequest, background_tasks: BackgroundTasks):
    cnpjs = [_limpar_cnpj(c) for c in body.cnpjs]
    cnpjs = [c for c in cnpjs if len(c) == 14]

    if not cnpjs:
        raise HTTPException(status_code=400, detail="Nenhum CNPJ válido informado.")

    lote_id = await criar_lote(len(cnpjs))
    background_tasks.add_task(_processar_lote, lote_id, cnpjs)

    return {"id": lote_id, "total": len(cnpjs), "status": "processando"}


@app.get("/api/consulta/lote/{lote_id}/status")
async def api_status_lote(lote_id: int):
    lote = await obter_lote(lote_id)
    if not lote:
        raise HTTPException(status_code=404, detail="Lote não encontrado.")

    resultados = []
    for consulta in lote.get("consultas", []):
        resultado = consulta.get("resultado") or {}
        devedor = resultado.get("devedor", {})
        debitos = resultado.get("debitos", [])
        resumo = resultado.get("resumo", {})
        encontrado = resultado.get("encontrado", False)

        cnpj_raw = consulta["cnpj"]
        cnpj_fmt = _formatar_cnpj(cnpj_raw)

        item = {
            "cnpj": cnpj_fmt,
            "nome": devedor.get("nome", ""),
            "encontrado": encontrado,
            "status": consulta["status"],
        }

        if encontrado and debitos:
            item["total_debitos"] = resumo.get("total_debitos", 0)
            item["valor_total"] = resumo.get("valor_total", 0)
            item["tipos"] = [
                {
                    "tipo": d.get("tipo", ""),
                    "quantidade": d.get("quantidade", 0),
                    "origem": d.get("origem", ""),
                    "valor_total": d.get("valor_total", 0),
                }
                for d in debitos
            ]
        else:
            item["total_debitos"] = 0
            item["valor_total"] = 0
            item["tipos"] = []

        resultados.append(item)

    return {
        "id": lote["id"],
        "status": lote["status"],
        "total": lote["total"],
        "processados": lote["concluidos"],
        "resultados": resultados,
    }


# ---------------------------------------------------------------------------
# API - Consulta por ID e histórico
# ---------------------------------------------------------------------------

@app.get("/api/consulta/{consulta_id}")
async def api_obter_consulta(consulta_id: int):
    consulta = await obter_consulta(consulta_id)
    if not consulta:
        raise HTTPException(status_code=404, detail="Consulta não encontrada.")
    return consulta


@app.get("/api/consultas/recentes")
async def api_consultas_recentes():
    consultas = await listar_consultas_recentes(20)
    return [
        {
            "cnpj": c["cnpj"],
            "status": c["status"],
            "data": c["criado_em"],
        }
        for c in consultas
    ]


# ---------------------------------------------------------------------------
# Processamento em lote (background)
# ---------------------------------------------------------------------------

async def _processar_lote(lote_id: int, cnpjs: list[str]):
    """Processa consultas em lote sequencialmente com delay entre cada uma."""
    concluidos = 0

    for cnpj in cnpjs:
        consulta_id = await criar_consulta(cnpj)
        await adicionar_consulta_lote(lote_id, consulta_id)

        try:
            cache = await buscar_cache(cnpj)
            if cache:
                resultado_json = json.dumps(cache["resultado"], ensure_ascii=False)
                await atualizar_consulta(consulta_id, "concluido", resultado_json)
            else:
                html_resposta = await consultar_cnpj(cnpj)
                resultado = parsear_resultado(html_resposta)
                resultado_json = json.dumps(resultado, ensure_ascii=False)
                await atualizar_consulta(consulta_id, "concluido", resultado_json)
        except Exception:
            logger.exception("Erro ao consultar CNPJ %s no lote %d", cnpj, lote_id)
            await atualizar_consulta(consulta_id, "erro")

        concluidos += 1
        await atualizar_lote(lote_id, concluidos)

        if cnpj != cnpjs[-1]:
            await asyncio.sleep(DELAY_ENTRE_CONSULTAS)

    await atualizar_lote(lote_id, concluidos, "concluido")
    logger.info("Lote %d concluído: %d/%d consultas", lote_id, concluidos, len(cnpjs))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _limpar_cnpj(cnpj: str) -> str:
    """Remove caracteres não numéricos do CNPJ."""
    return re.sub(r"\D", "", cnpj)


def _formatar_cnpj(cnpj: str) -> str:
    """Formata CNPJ como 00.000.000/0000-00."""
    c = _limpar_cnpj(cnpj)
    if len(c) != 14:
        return cnpj
    return f"{c[:2]}.{c[2:5]}.{c[5:8]}/{c[8:12]}-{c[12:14]}"
