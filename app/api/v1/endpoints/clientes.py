import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.cliente import Cliente
from app.models.usuario import Usuario
from app.schemas.cliente import ClienteResponse

router = APIRouter(prefix="/clientes", tags=["Clientes"])


@router.get("", response_model=list[ClienteResponse])
async def buscar_clientes(
    q: str | None = None,
    db: AsyncSession = Depends(get_db),
    usuario_actual: Usuario = Depends(get_current_user),
):
    """Búsqueda de clientes ya registrados localmente (por razón social o número de
    documento), para no volver a consultar apisunat.pe si el cliente ya existe."""
    stmt = select(Cliente).order_by(Cliente.razon_social).limit(50)
    if q:
        patron = f"%{q.strip()}%"
        stmt = select(Cliente).where(
            Cliente.razon_social.ilike(patron) | Cliente.numero_documento.ilike(patron)
        ).order_by(Cliente.razon_social).limit(50)
    return (await db.execute(stmt)).scalars().all()


@router.get("/{cliente_id}", response_model=ClienteResponse)
async def obtener_cliente(
    cliente_id: uuid.UUID, db: AsyncSession = Depends(get_db), usuario_actual: Usuario = Depends(get_current_user)
):
    cliente = await db.get(Cliente, cliente_id)
    if cliente is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cliente no encontrado")
    return cliente
