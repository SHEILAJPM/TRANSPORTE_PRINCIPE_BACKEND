"""Emisión de la Guía de Remisión Transportista (tipo 31).

Como SUNAT no tiene entorno beta para GRE, todo envío es real: el usuario siempre
revisa primero una vista previa, y el envío exige la huella de esa vista previa. Si
algún dato del viaje cambió entre la revisión y el envío, la huella no coincide y no
se envía nada.
"""

import asyncio
import io
import logging
import uuid
import zipfile
from dataclasses import dataclass, field
from decimal import Decimal

from lxml import etree
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.chofer import Chofer
from app.models.cliente import Cliente
from app.models.comprobante import GuiaRemision
from app.models.cotizacion import Cotizacion
from app.models.empresa import Empresa
from app.models.enums import EstadoSunat, TipoDocumentoIdentidad
from app.models.flota import Carreta, Tracto
from app.models.pesos_medidas import ConstanciaPesosMedidas
from app.models.viaje import Viaje
from app.services import gre_ubl_service as ubl
from app.services.apisunat_facturacion_service import DatosIncompletosError, emitir_guia_remision_transportista
from app.services import archivos_privados_service
from app.services.sunat_certificado_service import CertificadoSunatError, cargar_certificado
from app.services.sunat_firma_service import firmar_xml
from app.services.sunat_gre_api_service import (
    CODIGO_TICKET_CON_ERROR,
    CODIGO_TICKET_EN_PROCESO,
    CODIGO_TICKET_PROCESADO,
    ClienteSunatGre,
    RespuestaTicket,
    SunatGreError,
    credenciales_faltantes,
    empaquetar_zip,
)
from app.utils.fechas import ahora_peru
from app.utils.xml_seguro import XmlInvalidoError, parsear_xml

logger = logging.getLogger(__name__)

_CODIGO_TIPO_DOCUMENTO = {TipoDocumentoIdentidad.RUC: ubl.TIPO_DOC_RUC, TipoDocumentoIdentidad.DNI: ubl.TIPO_DOC_DNI}

_CONSULTAS_TICKET_TRAS_ENVIO = 3
_ESPERA_ENTRE_CONSULTAS_SEGUNDOS = 2

_NS_CBC = ubl.NS_CBC


class HuellaNoCoincideError(Exception):
    """Los datos de la guía cambiaron desde la vista previa que el usuario confirmó."""


class GuiaNoEmitibleError(Exception):
    """La guía ya fue aceptada o tiene un envío en proceso en SUNAT."""


@dataclass
class VistaPreviaGuia:
    datos: ubl.DatosGuiaTransportista
    huella: str
    proveedor: str
    errores: list[str] = field(default_factory=list)
    advertencias: list[str] = field(default_factory=list)
    xml: str | None = None


async def _construir_datos(db: AsyncSession, guia: GuiaRemision) -> tuple[ubl.DatosGuiaTransportista, list[str]]:
    viaje = await db.get(Viaje, guia.viaje_id)
    if viaje is None:
        raise DatosIncompletosError("El viaje asociado a esta guía no existe")
    tracto = await db.get(Tracto, viaje.tracto_id)
    carreta = await db.get(Carreta, viaje.carreta_id) if viaje.carreta_id else None
    chofer = await db.get(Chofer, viaje.chofer_id)
    cliente = await db.get(Cliente, viaje.cliente_id)
    empresa = await db.get(Empresa, guia.empresa_id)
    if tracto is None or chofer is None or cliente is None or empresa is None:
        raise DatosIncompletosError("Faltan datos del tracto, chofer, cliente o empresa para emitir la guía")

    advertencias: list[str] = []

    constancia = (
        await db.execute(select(ConstanciaPesosMedidas).where(ConstanciaPesosMedidas.guia_remision_id == guia.id))
    ).scalar_one_or_none()
    generador_carga = await db.get(Cliente, constancia.generador_carga_cliente_id) if constancia else None
    remitente = generador_carga or cliente

    if guia.destinatario_numero_documento and guia.destinatario_tipo_documento and guia.destinatario_razon_social:
        destinatario = ubl.Parte(
            guia.destinatario_tipo_documento, guia.destinatario_numero_documento, guia.destinatario_razon_social
        )
    else:
        destinatario = ubl.Parte(_CODIGO_TIPO_DOCUMENTO[cliente.tipo_documento], cliente.numero_documento, cliente.razon_social)
        advertencias.append("No se registró destinatario: se usará al cliente del viaje como destinatario")

    hoy = ahora_peru().date()
    fecha_inicio = viaje.fecha_salida_programada.date()
    if fecha_inicio < hoy:
        advertencias.append(
            f"La salida programada ({fecha_inicio:%d/%m/%Y}) ya pasó: se declarará hoy como inicio del traslado"
        )
        fecha_inicio = hoy

    if guia.bienes:
        bienes = tuple(
            ubl.Bien(
                descripcion=b["descripcion"],
                cantidad=Decimal(str(b.get("cantidad") or 1)),
                unidad=b.get("unidad") or "NIU",
                codigo=b.get("codigo"),
            )
            for b in guia.bienes
        )
    elif guia.remitente_guia_serie:
        bienes = ()  # los bienes ya constan en la guía de remitente referenciada
    else:
        cotizacion = await db.get(Cotizacion, viaje.cotizacion_id) if viaje.cotizacion_id else None
        descripcion = cotizacion.descripcion_servicio if cotizacion else f"Carga general — {viaje.peso_tm} TM"
        bienes = (ubl.Bien(descripcion=descripcion, cantidad=Decimal(1), unidad="NIU"),)

    documentos = ()
    if guia.remitente_guia_serie and guia.remitente_guia_numero and guia.remitente_guia_ruc_emisor:
        documentos = (
            ubl.DocumentoRelacionado(
                "09", guia.remitente_guia_serie, guia.remitente_guia_numero, guia.remitente_guia_ruc_emisor
            ),
        )

    datos = ubl.DatosGuiaTransportista(
        serie=guia.serie,
        numero=guia.numero,
        transportista=ubl.Parte(ubl.TIPO_DOC_RUC, empresa.ruc, empresa.razon_social),
        registro_mtc=empresa.numero_registro_mtc,
        remitente=ubl.Parte(_CODIGO_TIPO_DOCUMENTO[remitente.tipo_documento], remitente.numero_documento, remitente.razon_social),
        destinatario=destinatario,
        partida=ubl.Direccion(viaje.origen_ubigeo or "", viaje.origen_direccion),
        llegada=ubl.Direccion(viaje.destino_ubigeo or "", viaje.destino_direccion),
        fecha_inicio_traslado=fecha_inicio,
        peso_bruto_kg=Decimal(str(guia.peso_bruto_total_kg)),
        vehiculo_principal=ubl.Vehiculo(ubl.normalizar_placa(tracto.placa), tracto.tarjeta_unica_circulacion),
        vehiculos_secundarios=(
            (ubl.Vehiculo(ubl.normalizar_placa(carreta.placa), carreta.tarjeta_unica_circulacion),) if carreta else ()
        ),
        conductor=ubl.Conductor(chofer.dni, chofer.nombres, chofer.apellidos, chofer.licencia_numero.upper()),
        bienes=bienes,
        documentos_relacionados=documentos,
    )
    return datos, advertencias


def _verificar_estado_emitible(guia: GuiaRemision) -> None:
    if guia.estado_sunat == EstadoSunat.ACEPTADO:
        raise GuiaNoEmitibleError("La guía ya fue aceptada por SUNAT")
    if guia.estado_sunat == EstadoSunat.PENDIENTE and guia.sunat_ticket:
        raise GuiaNoEmitibleError(
            f"La guía ya fue enviada a SUNAT (ticket {guia.sunat_ticket}) y está en proceso: consulte el estado, no la reenvíe"
        )


async def vista_previa(db: AsyncSession, guia: GuiaRemision) -> VistaPreviaGuia:
    datos, advertencias = await _construir_datos(db, guia)
    validacion = ubl.validar(datos)
    vista = VistaPreviaGuia(
        datos=datos,
        huella=datos.huella(),
        proveedor=settings.GRE_PROVEEDOR,
        errores=validacion.errores,
        advertencias=advertencias + validacion.advertencias,
    )

    try:
        _verificar_estado_emitible(guia)
    except GuiaNoEmitibleError as error:
        vista.errores.insert(0, str(error))

    if settings.GRE_PROVEEDOR == "sunat_directo":
        try:
            cargar_certificado()
        except CertificadoSunatError as error:
            vista.errores.append(str(error))
        faltantes = credenciales_faltantes()
        if faltantes:
            vista.errores.append("Faltan credenciales de la API de GRE de SUNAT: " + ", ".join(faltantes))
        # XML sin firmar, solo para revisión: el que se envía se genera y firma al confirmar.
        raiz = ubl.construir_xml(datos, ahora_peru())
        vista.xml = etree.tostring(raiz, pretty_print=True, encoding="unicode")

    return vista


def _leer_cdr(cdr_zip: bytes) -> tuple[str | None, str | None, str | None]:
    """Devuelve (código de respuesta, descripción + observaciones, enlace de consulta)."""
    try:
        with zipfile.ZipFile(io.BytesIO(cdr_zip)) as zip_:
            nombre = next(n for n in zip_.namelist() if n.lower().endswith(".xml"))
            raiz = parsear_xml(zip_.read(nombre))
    except (zipfile.BadZipFile, StopIteration, XmlInvalidoError):
        return None, "SUNAT devolvió un CDR que no se pudo leer", None

    codigo = raiz.findtext(f".//{{{_NS_CBC}}}ResponseCode")
    descripcion = raiz.findtext(f".//{{{_NS_CBC}}}Description")
    notas = [n.text for n in raiz.iter(f"{{{_NS_CBC}}}Note") if n.text]
    enlace = next(
        (t.text for t in raiz.iter(f"{{{_NS_CBC}}}DocumentDescription") if t.text and t.text.startswith("http")), None
    )
    mensaje = " | ".join(filter(None, [descripcion, *notas]))
    return codigo, mensaje or None, enlace


async def _aplicar_respuesta_ticket(db: AsyncSession, guia: GuiaRemision, respuesta: RespuestaTicket) -> None:
    if respuesta.codigo == CODIGO_TICKET_EN_PROCESO:
        guia.estado_sunat = EstadoSunat.PENDIENTE
        guia.mensaje_sunat = f"SUNAT está procesando la guía (ticket {guia.sunat_ticket})"
        return

    if respuesta.cdr_zip:
        guia.cdr_clave = await archivos_privados_service.guardar(
            db, f"sunat/gre/{guia.serie}-{guia.numero}/R-{guia.serie}-{guia.numero}.zip", respuesta.cdr_zip, "application/zip"
        )
        codigo_cdr, mensaje_cdr, enlace = _leer_cdr(respuesta.cdr_zip)
        guia.sunat_codigo_respuesta = codigo_cdr
        guia.mensaje_sunat = (mensaje_cdr or "")[:500] or None
        if enlace:
            guia.pdf_url = enlace[:500]

    if respuesta.codigo == CODIGO_TICKET_PROCESADO:
        guia.estado_sunat = EstadoSunat.ACEPTADO
        guia.mensaje_sunat = guia.mensaje_sunat or "Guía aceptada por SUNAT"
    elif respuesta.codigo == CODIGO_TICKET_CON_ERROR:
        guia.estado_sunat = EstadoSunat.RECHAZADO
        if not respuesta.cdr_zip:
            guia.sunat_codigo_respuesta = respuesta.error_codigo
            guia.mensaje_sunat = f"{respuesta.error_codigo or ''} {respuesta.error_mensaje or 'SUNAT rechazó la guía'}".strip()[:500]
    else:
        guia.mensaje_sunat = f"Respuesta desconocida de SUNAT para el ticket {guia.sunat_ticket}: {respuesta.codigo!r}"


async def emitir(db: AsyncSession, guia_remision_id: uuid.UUID, huella_confirmada: str) -> GuiaRemision:
    """Envía la guía que el usuario revisó en la vista previa. Bloquea la fila para
    que un doble clic no la envíe dos veces."""
    guia = await db.get(GuiaRemision, guia_remision_id, with_for_update=True)
    if guia is None:
        raise DatosIncompletosError("Guía de remisión no encontrada")
    _verificar_estado_emitible(guia)

    datos, _ = await _construir_datos(db, guia)
    if datos.huella() != huella_confirmada:
        raise HuellaNoCoincideError(
            "Los datos de la guía cambiaron desde que los revisó. Vuelva a abrir la vista previa antes de emitir."
        )
    validacion = ubl.validar(datos)
    if validacion.errores:
        raise DatosIncompletosError("; ".join(validacion.errores))

    if settings.GRE_PROVEEDOR == "apisunat":
        return await emitir_guia_remision_transportista(db, guia.id)

    certificado = cargar_certificado()
    cliente_api = ClienteSunatGre()  # valida credenciales antes de firmar
    try:
        emitido_en = ahora_peru()
        raiz = ubl.construir_xml(datos, emitido_en)
        firmado = await asyncio.to_thread(firmar_xml, raiz, certificado, ubl.ID_FIRMA)

        guia.xml_clave = await archivos_privados_service.guardar(
            db, f"sunat/gre/{guia.serie}-{guia.numero}/{datos.nombre_archivo}.xml", firmado.contenido, "application/xml"
        )
        ticket = await cliente_api.enviar(datos.nombre_archivo, empaquetar_zip(datos.nombre_archivo, firmado.contenido))

        # Desde aquí el documento ya está en SUNAT: nada de lo que sigue debe propagar
        # una excepción que haga rollback y pierda el ticket.
        guia.sunat_ticket = ticket
        guia.enviado_sunat_en = emitido_en
        guia.fecha_emision = emitido_en.date()
        guia.hash_cpe = firmado.digest
        guia.estado_sunat = EstadoSunat.PENDIENTE
        guia.sunat_codigo_respuesta = None
        guia.mensaje_sunat = f"Enviada a SUNAT (ticket {ticket})"
        await db.flush()

        for _ in range(_CONSULTAS_TICKET_TRAS_ENVIO):
            await asyncio.sleep(_ESPERA_ENTRE_CONSULTAS_SEGUNDOS)
            try:
                respuesta = await cliente_api.consultar_ticket(ticket)
                await _aplicar_respuesta_ticket(db, guia, respuesta)
            except Exception:
                # Queda PENDIENTE con su ticket guardado; el usuario consulta el estado luego.
                logger.exception("No se pudo obtener la respuesta del ticket %s de SUNAT", ticket)
                break
            if respuesta.codigo != CODIGO_TICKET_EN_PROCESO:
                break
    finally:
        await cliente_api.cerrar()

    await db.flush()
    return guia


async def consultar_ticket(db: AsyncSession, guia_remision_id: uuid.UUID) -> GuiaRemision:
    guia = await db.get(GuiaRemision, guia_remision_id, with_for_update=True)
    if guia is None:
        raise DatosIncompletosError("Guía de remisión no encontrada")
    if not guia.sunat_ticket:
        raise GuiaNoEmitibleError("Esta guía todavía no fue enviada a SUNAT")
    if guia.estado_sunat != EstadoSunat.PENDIENTE:
        return guia

    cliente_api = ClienteSunatGre()
    try:
        respuesta = await cliente_api.consultar_ticket(guia.sunat_ticket)
    finally:
        await cliente_api.cerrar()
    await _aplicar_respuesta_ticket(db, guia, respuesta)
    await db.flush()
    return guia
