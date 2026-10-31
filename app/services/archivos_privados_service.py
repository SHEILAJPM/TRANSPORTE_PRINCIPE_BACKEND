from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.archivo_privado import ArchivoPrivado


class ArchivoPrivadoNoEncontradoError(Exception):
    """El archivo privado solicitado no existe."""


async def guardar(db: AsyncSession, clave: str, contenido: bytes, content_type: str) -> str:
    """Guarda (o reemplaza, p.ej. al reenviar una guía rechazada) un archivo privado.
    Devuelve la clave con la que luego se lee mediante `leer`."""
    archivo = (await db.execute(select(ArchivoPrivado).where(ArchivoPrivado.clave == clave))).scalar_one_or_none()
    if archivo is None:
        db.add(ArchivoPrivado(clave=clave, contenido=contenido, content_type=content_type))
    else:
        archivo.contenido = contenido
        archivo.content_type = content_type
    await db.flush()
    return clave


async def leer(db: AsyncSession, clave: str) -> bytes:
    archivo = (await db.execute(select(ArchivoPrivado).where(ArchivoPrivado.clave == clave))).scalar_one_or_none()
    if archivo is None:
        raise ArchivoPrivadoNoEncontradoError(clave)
    return archivo.contenido
