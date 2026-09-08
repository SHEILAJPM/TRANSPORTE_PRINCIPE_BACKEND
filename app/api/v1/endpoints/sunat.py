from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.enums import TipoDocumentoIdentidad
from app.models.usuario import Usuario
from app.schemas.cliente import ClienteResponse
from app.schemas.sunat import DniConsultaResponse, RucConsultaResponse
from app.services.sunat_service import ApiSunatError, ApiSunatService, obtener_o_crear_cliente

router = APIRouter(prefix="/sunat", tags=["SUNAT"])


async def get_apisunat_service() -> ApiSunatService:
    return ApiSunatService()


@router.get("/ruc/{ruc}", response_model=RucConsultaResponse)
async def consultar_ruc(ruc: str, apisunat: ApiSunatService = Depends(get_apisunat_service)):
    try:
        return await apisunat.consultar_ruc(ruc)
    except ApiSunatError as error:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error))
    finally:
        await apisunat.cerrar()


@router.get("/dni/{dni}", response_model=DniConsultaResponse)
async def consultar_dni(dni: str, apisunat: ApiSunatService = Depends(get_apisunat_service)):
    try:
        return await apisunat.consultar_dni(dni)
    except ApiSunatError as error:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error))
    finally:
        await apisunat.cerrar()


@router.post("/clientes/autocompletar/{tipo_documento}/{numero_documento}", response_model=ClienteResponse)
async def autocompletar_cliente(
    tipo_documento: TipoDocumentoIdentidad,
    numero_documento: str,
    db: AsyncSession = Depends(get_db),
    apisunat: ApiSunatService = Depends(get_apisunat_service),
    usuario_actual: Usuario = Depends(get_current_user),
):
    try:
        cliente = await obtener_o_crear_cliente(
            db=db,
            apisunat=apisunat,
            tipo_documento=tipo_documento,
            numero_documento=numero_documento,
            usuario_id=usuario_actual.id,
        )
        await db.commit()
        return cliente
    except ApiSunatError as error:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error))
    finally:
        await apisunat.cerrar()
