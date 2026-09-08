from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_roles
from app.core.database import get_db
from app.models.empresa import Empresa
from app.models.enums import RolUsuario
from app.models.usuario import Usuario
from app.schemas.empresa import EmpresaResponse, EmpresaUpdateRequest
from app.services.storage_service import StorageService

router = APIRouter(prefix="/empresa", tags=["Empresa"])

CONTENT_TYPES_LOGO_PERMITIDOS = {"image/png", "image/jpeg", "image/webp", "image/svg+xml"}


async def _obtener_empresa_actual(db: AsyncSession, usuario_actual: Usuario) -> Empresa:
    empresa = await db.get(Empresa, usuario_actual.empresa_id)
    if empresa is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Empresa no encontrada")
    return empresa


@router.get("", response_model=EmpresaResponse)
async def obtener_empresa(db: AsyncSession = Depends(get_db), usuario_actual: Usuario = Depends(get_current_user)):
    return await _obtener_empresa_actual(db, usuario_actual)


@router.patch("", response_model=EmpresaResponse)
async def actualizar_empresa(
    body: EmpresaUpdateRequest,
    db: AsyncSession = Depends(get_db),
    usuario_actual: Usuario = Depends(require_roles(RolUsuario.ADMIN)),
):
    empresa = await _obtener_empresa_actual(db, usuario_actual)
    for campo, valor in body.model_dump(exclude_unset=True).items():
        setattr(empresa, campo, valor)
    await db.commit()
    await db.refresh(empresa)
    return empresa


@router.post("/logo", response_model=EmpresaResponse)
async def actualizar_logo(
    archivo: UploadFile,
    db: AsyncSession = Depends(get_db),
    usuario_actual: Usuario = Depends(require_roles(RolUsuario.ADMIN)),
):
    """Sube/reemplaza el logotipo corporativo que aparecerá en cotizaciones, facturas,
    guías de remisión y constancias de pesos y medidas en PDF."""
    if archivo.content_type not in CONTENT_TYPES_LOGO_PERMITIDOS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Formato de imagen no soportado (use PNG, JPG, WEBP o SVG)",
        )

    empresa = await _obtener_empresa_actual(db, usuario_actual)
    storage = StorageService()
    empresa.logo_url = await storage.guardar_logo_empresa(empresa.id, archivo)
    empresa.logo_actualizado_en = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(empresa)
    return empresa
