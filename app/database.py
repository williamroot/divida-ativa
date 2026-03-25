import json
import os
from datetime import datetime, timedelta, timezone

import aiosqlite

DATABASE_PATH = os.getenv("DATABASE_PATH", "data/divida.db")


async def init_db() -> None:
    """Create tables and indexes if they don't exist."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS consultas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cnpj TEXT NOT NULL,
                resultado_json TEXT,
                status TEXT NOT NULL DEFAULT 'pendente',
                criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS lotes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                status TEXT NOT NULL DEFAULT 'processando',
                total INTEGER NOT NULL,
                concluidos INTEGER NOT NULL DEFAULT 0,
                criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS lote_consultas (
                lote_id INTEGER NOT NULL,
                consulta_id INTEGER NOT NULL,
                FOREIGN KEY (lote_id) REFERENCES lotes (id),
                FOREIGN KEY (consulta_id) REFERENCES consultas (id)
            )
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_consultas_cnpj ON consultas (cnpj)
        """)
        await db.commit()


async def criar_consulta(cnpj: str) -> int:
    """Insert a new consulta and return its id."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO consultas (cnpj) VALUES (?)",
            (cnpj,),
        )
        await db.commit()
        return cursor.lastrowid


async def atualizar_consulta(
    consulta_id: int,
    status: str,
    resultado_json: str | None = None,
) -> None:
    """Update a consulta's status and optionally its resultado_json."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "UPDATE consultas SET status = ?, resultado_json = ? WHERE id = ?",
            (status, resultado_json, consulta_id),
        )
        await db.commit()


async def obter_consulta(consulta_id: int) -> dict | None:
    """Get a single consulta by id."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM consultas WHERE id = ?",
            (consulta_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return _row_to_consulta(row)


async def buscar_cache(cnpj: str) -> dict | None:
    """Find a consulta for this CNPJ completed in the last 24 hours."""
    limite = datetime.now(timezone.utc) - timedelta(hours=24)
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT * FROM consultas
            WHERE cnpj = ? AND status = 'concluido' AND criado_em >= ?
            ORDER BY criado_em DESC
            LIMIT 1
            """,
            (cnpj, limite.isoformat()),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return _row_to_consulta(row)


async def criar_lote(total: int) -> int:
    """Insert a new lote and return its id."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO lotes (total) VALUES (?)",
            (total,),
        )
        await db.commit()
        return cursor.lastrowid


async def adicionar_consulta_lote(lote_id: int, consulta_id: int) -> None:
    """Link a consulta to a lote."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute(
            "INSERT INTO lote_consultas (lote_id, consulta_id) VALUES (?, ?)",
            (lote_id, consulta_id),
        )
        await db.commit()


async def atualizar_lote(
    lote_id: int,
    concluidos: int,
    status: str | None = None,
) -> None:
    """Update lote progress and optionally its status."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        if status is not None:
            await db.execute(
                "UPDATE lotes SET concluidos = ?, status = ? WHERE id = ?",
                (concluidos, status, lote_id),
            )
        else:
            await db.execute(
                "UPDATE lotes SET concluidos = ? WHERE id = ?",
                (concluidos, lote_id),
            )
        await db.commit()


async def obter_lote(lote_id: int) -> dict | None:
    """Get a lote with its associated consultas."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM lotes WHERE id = ?",
            (lote_id,),
        )
        lote_row = await cursor.fetchone()
        if lote_row is None:
            return None

        lote = dict(lote_row)

        cursor = await db.execute(
            """
            SELECT c.* FROM consultas c
            INNER JOIN lote_consultas lc ON lc.consulta_id = c.id
            WHERE lc.lote_id = ?
            ORDER BY c.id
            """,
            (lote_id,),
        )
        rows = await cursor.fetchall()
        lote["consultas"] = [_row_to_consulta(row) for row in rows]
        return lote


async def listar_consultas_recentes(limit: int = 20) -> list[dict]:
    """List recent consultas ordered by creation date descending."""
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM consultas ORDER BY criado_em DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [_row_to_consulta(row) for row in rows]


def _row_to_consulta(row: aiosqlite.Row) -> dict:
    """Convert a database row to a consulta dict, parsing resultado_json."""
    consulta = dict(row)
    resultado_json = consulta.pop("resultado_json", None)
    consulta["resultado"] = json.loads(resultado_json) if resultado_json else None
    return consulta
