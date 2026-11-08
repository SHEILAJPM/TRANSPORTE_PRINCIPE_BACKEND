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
    ConsultaGuiaRemitenteRequest,
    ConexionResponse,
    DniConsultaResponse,
    GuiaRemitenteImportadaResponse,
    ParteGuia,
    PruebaConexionResponse,
    PuntoGuia,
    RucConsultaResponse,
)
from app.services.guia_remitente_pdf_service import es_pdf, leer_guia_remitente_pdf
from app.services.guia_remitente_service import (
    TAMANO_MAXIMO_BYTES,
    GuiaRemitenteInvalidaError,
    leer_guia_remitente,
    obtener_o_crear_cliente_remitente,
)
from app.services.sunat_certificado_service import CertificadoSunatError, cargar_certificado
from app.services.sunat_conexion_service import estado_conexiones, probar_conexion_gre
from app.services.sunat_gre_api_service import ClienteSunatGre, SunatGreError
from app.services.sunat_service import (
    ApiSunatDocumentoInvalidoError,
    ApiSunatError,
    ApiSunatNotFoundError,
    ApiSunatService,
    obtener_o_crear_cliente,
)
from app.utils.xml_seguro import XmlInvalidoError

router = APIRouter(prefix="/sunat", tags=["SUNAT"])


async def get_apisunat_service() -> ApiSunatService:
    return ApiSunatService()


def _error_consulta(error: ApiSunatError) -> HTTPException:
    if isinstance(error, ApiSunatDocumentoInvalidoError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))
    if isinstance(error, ApiSunatNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No se encontró ese documento en RENIEC/SUNAT")
    return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error))


# Cada consulta se cobra en Decolecta: solo usuarios que registran clientes o choferes.
_ROLES_CONSULTA = (RolUsuario.ADMIN, RolUsuario.OPERADOR)


@router.get("/ruc/{ruc}", response_model=RucConsultaResponse)
async def consultar_ruc(
    ruc: str,
    apisunat: ApiSunatService = Depends(get_apisunat_service),
    usuario_actual: Usuario = Depends(require_roles(*_ROLES_CONSULTA)),
):
    try:
        return await apisunat.consultar_ruc(ruc)
    except ApiSunatError as error:
        raise _error_consulta(error)
    finally:
        await apisunat.cerrar()


@router.get("/dni/{dni}", response_model=DniConsultaResponse)
async def consultar_dni(
    dni: str,
    apisunat: ApiSunatService = Depends(get_apisunat_service),
    usuario_actual: Usuario = Depends(require_roles(*_ROLES_CONSULTA)),
):
    """Nombres y apellidos por DNI (RENIEC vía Decolecta): autocompleta clientes y choferes."""
    try:
        return await apisunat.consultar_dni(dni)
    except ApiSunatError as error:
        raise _error_consulta(error)
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


async def _completar_nombre(apisunat: ApiSunatService, parte, advertencias: list[str]) -> None:
    """Nombre del destinatario por su RUC/DNI; si la consulta falla se pide a mano."""
    try:
        if parte.tipo_documento == "6":
            parte.razon_social = (await apisunat.consultar_ruc(parte.numero_documento)).razon_social
        else:
            parte.razon_social = (await apisunat.consultar_dni(parte.numero_documento)).nombre_completo
    except ApiSunatError:
        advertencias.append(f"No se pudo consultar el nombre del destinatario ({parte.numero_documento}): escríbelo a mano.")


def _respuesta_importada(leida, cliente) -> GuiaRemitenteImportadaResponse:
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


@router.post("/guia-remitente/consultar", response_model=GuiaRemitenteImportadaResponse)
async def consultar_guia_remitente(
    body: ConsultaGuiaRemitenteRequest,
    db: AsyncSession = Depends(get_db),
    usuario_actual: Usuario = Depends(require_roles(RolUsuario.ADMIN, RolUsuario.OPERADOR)),
):
    """Trae de SUNAT la guía de remitente del cliente con solo su RUC, serie y número
    (la empresa debe figurar en ella como transportista) y devuelve el viaje prellenado
    igual que al subir el XML. Solo consulta; no envía nada a SUNAT."""
    empresa = await db.get(Empresa, usuario_actual.empresa_id)
    try:
        sunat = ClienteSunatGre()
    except SunatGreError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error))
    try:
        xml = await sunat.descargar_comprobante(body.ruc, "09", body.serie.upper(), body.numero)
    except SunatGreError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    finally:
        await sunat.cerrar()
    try:
        leida = leer_guia_remitente(xml, ruc_transportista=empresa.ruc if empresa else "")
        cliente = await obtener_o_crear_cliente_remitente(db, leida.remitente)
        await db.commit()
    except (GuiaRemitenteInvalidaError, XmlInvalidoError) as error:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error))
    return _respuesta_importada(leida, cliente)


@router.post("/guia-remitente/importar", response_model=GuiaRemitenteImportadaResponse)
async def importar_guia_remitente(
    archivo: UploadFile = File(..., description="XML o PDF de la Guía de Remisión Remitente (tipo 09) del cliente"),
    db: AsyncSession = Depends(get_db),
    apisunat: ApiSunatService = Depends(get_apisunat_service),
    usuario_actual: Usuario = Depends(require_roles(RolUsuario.ADMIN, RolUsuario.OPERADOR)),
):
    """Lee la guía de remitente que entregó el cliente (XML o PDF) y devuelve los datos
    del viaje ya llenos (cliente, destinatario, ruta, peso, bienes y la referencia a su
    guía). No crea el viaje: solo falta elegir tracto y chofer y llamar a /viajes/activar.
    Si el remitente no estaba registrado como cliente, se registra. Del PDF se toman los
    números de documento y los nombres se consultan en RENIEC/SUNAT."""
    contenido = await archivo.read(TAMANO_MAXIMO_BYTES + 1)
    if len(contenido) > TAMANO_MAXIMO_BYTES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="El archivo es demasiado grande (máx. 2 MB)")
    empresa = await db.get(Empresa, usuario_actual.empresa_id)
    ruc_empresa = empresa.ruc if empresa else ""
    try:
        if es_pdf(contenido):
            leida = leer_guia_remitente_pdf(contenido, ruc_transportista=ruc_empresa)
            cliente = await obtener_o_crear_cliente(
                db=db, apisunat=apisunat, tipo_documento=TipoDocumentoIdentidad.RUC,
                numero_documento=leida.remitente.numero_documento, usuario_id=usuario_actual.id,
            )
            if leida.destinatario is not None:
                await _completar_nombre(apisunat, leida.destinatario, leida.advertencias)
        else:
            leida = leer_guia_remitente(contenido, ruc_transportista=ruc_empresa)
            cliente = await obtener_o_crear_cliente_remitente(db, leida.remitente)
        await db.commit()
    except (GuiaRemitenteInvalidaError, XmlInvalidoError) as error:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error))
    except ApiSunatError as error:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Se leyó el PDF, pero no se pudo consultar el RUC del remitente: {error}",
        )
    finally:
        await apisunat.cerrar()

    return _respuesta_importada(leida, cliente)


@router.get("/certificado/estado", response_model=CertificadoEstadoResponse)
async def estado_certificado(
    db: AsyncSession = Depends(get_db), usuario_actual: Usuario = Depends(require_roles(RolUsuario.ADMIN))
):
    """Verifica que el certificado .p12 esté configurado, abra con su contraseña y no
    esté vencido, y lista el estado de cada conexión (certificado, credenciales de API
    para guías, usuario/clave SOL y facturas). Siempre responde 200; no contacta a SUNAT."""
    conexiones = [
        ConexionResponse(**vars(c)) for c in estado_conexiones(await db.get(Empresa, usuario_actual.empresa_id))
    ]
    try:
        certificado = cargar_certificado()
    except CertificadoSunatError as error:
        return CertificadoEstadoResponse(listo_para_firmar=False, mensaje=str(error), conexiones=conexiones)

    return CertificadoEstadoResponse(
        listo_para_firmar=True,
        mensaje="Certificado digital listo para firmar",
        titular=certificado.titular,
        vence_en=certificado.vence_en,
        dias_para_vencer=(certificado.vence_en - datetime.now(timezone.utc)).days,
        conexiones=conexiones,
    )


@router.post("/conexion/probar", response_model=PruebaConexionResponse)
async def probar_conexion(
    db: AsyncSession = Depends(get_db), usuario_actual: Usuario = Depends(require_roles(RolUsuario.ADMIN))
):
    """"Probar conexión con SUNAT": pide un token con el client ID/secret y el usuario/
    clave SOL configurados. NO firma ni envía ningún documento."""
    empresa = await db.get(Empresa, usuario_actual.empresa_id)
    ok, mensaje = await probar_conexion_gre(empresa)
    return PruebaConexionResponse(
        ok=ok, mensaje=mensaje, conexiones=[ConexionResponse(**vars(c)) for c in estado_conexiones(empresa)]
    )
