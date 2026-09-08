from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.correlativo import Correlativo


async def siguiente_numero(db: AsyncSession, tipo: str, serie: str | None = None) -> int:
    """Incrementa y devuelve el contador atómico para `tipo` (+ `serie` opcional).

    Bloquea la fila del contador (SELECT ... FOR UPDATE) para que dos requests
    concurrentes nunca reciban el mismo número; debe llamarse dentro de la misma
    transacción que persiste el documento numerado.
    """
    stmt = select(Correlativo).where(Correlativo.tipo == tipo, Correlativo.serie == serie).with_for_update()
    contador = (await db.execute(stmt)).scalar_one_or_none()

    if contador is None:
        contador = Correlativo(tipo=tipo, serie=serie, ultimo_numero=0)
        db.add(contador)
        await db.flush()

    contador.ultimo_numero += 1
    await db.flush()
    return contador.ultimo_numero


async def generar_correlativo(db: AsyncSession, tipo: str, prefijo: str, ancho: int = 6) -> str:
    """Correlativo con prefijo legible para documentos internos: 'COT-000123'."""
    numero = await siguiente_numero(db, tipo=tipo)
    return f"{prefijo}-{numero:0{ancho}d}"


async def generar_numero_serie_sunat(db: AsyncSession, tipo: str, serie: str, ancho: int = 8) -> str:
    """Correlativo numérico puro (sin prefijo) para el campo `numero` de
    comprobantes electrónicos (Guía de Remisión / Factura), donde la serie va aparte.
    """
    numero = await siguiente_numero(db, tipo=tipo, serie=serie)
    return f"{numero:0{ancho}d}"
