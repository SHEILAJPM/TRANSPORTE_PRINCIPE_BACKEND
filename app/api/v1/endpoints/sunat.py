from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_roles
from app.core.database import get_db
from app.models.empresa import Empresa
from app.models.enums import RolUsuario, TipoDocumentoIdentidad
from app.models.usuario import Usuario
from app.schemas.cliente import ClienteResponse
from app.schemas.comprobante import BienGuia
from app.schemas.sunat import (
    CertificadoEstadoResponse,
    DniConsultaResponse,
    GuiaRemitenteImportadaResponse,
    ParteGuia,
    PuntoGuia,
    RucConsultaResponse,
)
from app.services.guia_remitente_service import (
    TAMANO_MAXIMO_BYTES,
    GuiaRemitenteInvalidaError,
    leer_guia_remitente,
    obtener_o_crear_cliente_remitente,
)
from app.services.sunat_certificado_service import CertificadoSunatError, cargar_certificado
from app.services.sunat_service import ApiSunatError, ApiSunatService, obtener_o_crear_cliente
from app.utils.xml_seguro import XmlInvalidoError

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


@router.post("/guia-remitente/importar", response_model=GuiaRemitenteImportadaResponse)
async def importar_guia_remitente(
    archivo: UploadFile = File(..., description="XML de la Guía de Remisión Remitente (tipo 09) del cliente"),
    db: AsyncSession = Depends(get_db),
    usuario_actual: Usuario = Depends(require_roles(RolUsuario.ADMIN, RolUsuario.OPERADOR)),
):
    """Lee la guía de remitente que entregó el cliente y devuelve los datos del viaje
    ya llenos (cliente, destinatario, ruta, peso, bienes y la referencia a su guía).
    No crea el viaje: solo falta elegir tracto y chofer y llamar a /viajes/activar.
    Si el remitente no estaba registrado como cliente, se registra."""
    contenido = await archivo.read(TAMANO_MAXIMO_BYTES + 1)
    empresa = await db.get(Empresa, usuario_actual.empresa_id)
    try:
        leida = leer_guia_remitente(contenido, ruc_transportista=empresa.ruc if empresa else "")
        cliente = await obtener_o_crear_cliente_remitente(db, leida.remitente)
        await db.commit()
    except (GuiaRemitenteInvalidaError, XmlInvalidoError) as error:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error))

    return GuiaRemitenteImportadaResponse(
        cliente=ClienteResponse.model_validate(cliente),
        remitente_guia_ruc_emisor=leida.remitente.numero_documento,
        remitente_guia_serie=leida.serie,
        remitente_guia_numero=leida.numero,
        fecha_emision_guia=leida.fecha_emision,
        destinatario=ParteGuia(**vars(leida.destinatario)) if leida.destinatario else None,
        origen=PuntoGuia(**vars(leida.partida)),
        destino=PuntoGuia(**vars(leida.llegada)),
        peso_tm=float(leida.peso_bruto_kg / 1000) if leida.peso_bruto_kg is not None else None,
        numero_bultos=leida.numero_bultos,
        fecha_inicio_traslado=leida.fecha_inicio_traslado,
        motivo_traslado=(
            f"{leida.motivo_codigo} - {leida.motivo_descripcion}" if leida.motivo_codigo else leida.motivo_descripcion
        ),
        bienes=[
            BienGuia(descripcion=b.descripcion, cantidad=float(b.cantidad), unidad=b.unidad, codigo=b.codigo)
            for b in leida.bienes
        ],
        advertencias=leida.advertencias,
    )


@router.get("/certificado/estado", response_model=CertificadoEstadoResponse)
async def estado_certificado(usuario_actual: Usuario = Depends(require_roles(RolUsuario.ADMIN))):
    """Verifica que el certificado .p12 esté configurado, abra con su contraseña y
    no esté vencido. Siempre responde 200: el resultado va en `listo_para_firmar`."""
    try:
        certificado = cargar_certificado()
    except CertificadoSunatError as error:
        return CertificadoEstadoResponse(listo_para_firmar=False, mensaje=str(error))

    return CertificadoEstadoResponse(
        listo_para_firmar=True,
        mensaje="Certificado digital listo para firmar",
        titular=certificado.titular,
        vence_en=certificado.vence_en,
        dias_para_vencer=(certificado.vence_en - datetime.now(timezone.utc)).days,
    )
