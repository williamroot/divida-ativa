from datetime import datetime

from pydantic import BaseModel


class ConsultaRequest(BaseModel):
    cnpj: str
    forcar: bool = False


class ConsultaLoteRequest(BaseModel):
    cnpjs: list[str]


class ConsultaResponse(BaseModel):
    id: int
    cnpj: str
    status: str  # pendente, concluido, erro
    resultado: dict | None = None
    criado_em: datetime


class LoteResponse(BaseModel):
    id: int
    status: str  # processando, concluido
    total: int
    concluidos: int
    criado_em: datetime


class LoteStatusResponse(LoteResponse):
    consultas: list[ConsultaResponse] = []
