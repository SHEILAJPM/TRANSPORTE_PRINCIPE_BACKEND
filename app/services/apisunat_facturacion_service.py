import uuid
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.config import settings
from app.models.chofer import Chofer
from app.models.cliente import Cliente
from app.models.comprobante import Factura, GuiaRemision
from app.models.cotizacion import Cotizacion
from app.models.empresa import Empresa
from app.models.enums import EstadoSunat, TipoDocumentoIdentidad, TipoDocumentoVenta
from app.models.flota import Carreta, Tracto
from app.models.pesos_medidas import ConstanciaPesosMedidas
from app.models.viaje import Viaje
from app.utils.correlativos import generar_numero_serie_sunat
from app.utils.fechas import ahora_peru

_CODIGO_TIPO_DOCUMENTO = {
    TipoDocumentoIdentidad.DNI: "1",
    TipoDocumentoIdentidad.RUC: "6",
}


class ApiSunatFacturacionError(Exception):
    """Error de red/conexión con apisunat.pe (no un rechazo de SUNAT en sí)."""


class DatosIncompletosError(Exception):
    """Falta un dato propio (chofer, tracto, generador de carga, etc.) antes de poder emitir."""


class ComprobanteNoAceptadoError(Exception):
    """No se puede anular un comprobante que SUNAT todavía no aceptó (o que ya fue anulado)."""


class AnulacionNoSoportadaError(Exception):
    """apisunat.pe no admite anular este tipo de documento por esta vía (p.ej. Guía de Remisión)."""


# Plazos (días desde la emisión) dentro de los cuales apisunat.pe admite anular una
# Factura/Boleta directamente; pasado ese plazo, SUNAT exige una Nota de Crédito.
_PLAZO_ANULACION_DIRECTA_DIAS = {
    TipoDocumentoVenta.FACTURA: 3,
    TipoDocumentoVenta.BOLETA: 5,
}


class _ClienteApiSunatFacturacion:
    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=settings.APISUNAT_BASE_URL,
            headers={
                "Authorization": f"Bearer {settings.APISUNAT_TOKEN}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            timeout=settings.APISUNAT_TIMEOUT_SECONDS,
        )

    async def cerrar(self) -> None:
        await self._client.aclose()

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, max=4),
        retry=retry_if_exception_type(httpx.TransportError),
    )
    async def emitir(self, ruta: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST a `ruta` (/api/v3/dispatches para guías, /api/v3/documents para
        facturas/boletas/notas). Devuelve el JSON de respuesta tal cual (tanto en
        éxito como en rechazo de validación: apisunat.pe siempre responde 200/422 con
        un cuerpo JSON {success, message, payload?} en vez de un error HTTP genérico).
        """
        try:
            response = await self._client.post(ruta, json=payload)
        except httpx.TransportError as error:
            raise ApiSunatFacturacionError(f"No se pudo conectar con apisunat.pe: {error}") from error

        if response.status_code == 401:
            raise ApiSunatFacturacionError("Token de apisunat.pe inválido o vencido")
        if response.status_code == 429:
            raise ApiSunatFacturacionError("Límite de solicitudes a apisunat.pe excedido, intente en un minuto")

        try:
            return response.json()
        except ValueError as error:
            raise ApiSunatFacturacionError(f"Respuesta inesperada de apisunat.pe (HTTP {response.status_code})") from error


async def _descripcion_servicio(db: AsyncSession, viaje: Viaje | None, por_defecto: str) -> str:
    cotizacion = await db.get(Cotizacion, viaje.cotizacion_id) if viaje is not None and viaje.cotizacion_id else None
    return cotizacion.descripcion_servicio if cotizacion is not None else por_defecto


async def _construir_items(db: AsyncSession, viaje: Viaje) -> list[dict[str, Any]]:
    descripcion = await _descripcion_servicio(db, viaje, f"Transporte de carga general — {viaje.peso_tm} TM")
    return [
        {
            "codigo": "CARGA",
            "descripcion": descripcion[:250],
            "cantidad": "1",
            "unidad_de_medida": "NIU",
        }
    ]


async def construir_payload_guia_remision_transportista(
    db: AsyncSession, guia: GuiaRemision
) -> dict[str, Any]:
    viaje = await db.get(Viaje, guia.viaje_id)
    if viaje is None:
        raise DatosIncompletosError("El viaje asociado a esta guía no existe")

    tracto = await db.get(Tracto, viaje.tracto_id)
    carreta = await db.get(Carreta, viaje.carreta_id) if viaje.carreta_id else None
    chofer = await db.get(Chofer, viaje.chofer_id)
    cliente = await db.get(Cliente, viaje.cliente_id)
    empresa = await db.get(Empresa, guia.empresa_id)

    if tracto is None or chofer is None or cliente is None or empresa is None:
        raise DatosIncompletosError("Faltan datos del camión, chofer, cliente o empresa para emitir la guía")

    generador_carga: Cliente | None = None
    constancia_stmt = select(ConstanciaPesosMedidas).where(ConstanciaPesosMedidas.guia_remision_id == guia.id)
    constancia = (await db.execute(constancia_stmt)).scalar_one_or_none()
    if constancia is not None:
        generador_carga = await db.get(Cliente, constancia.generador_carga_cliente_id)

    remitente = generador_carga or cliente

    if not viaje.origen_ubigeo or not viaje.destino_ubigeo:
        raise DatosIncompletosError(
            "El viaje no tiene registrado el código UBIGEO de origen y/o destino, requerido por SUNAT"
        )

    # SUNAT exige que fecha_de_emision sea el día real de la presentación (hoy), no la
    # fecha en que se generó el registro interno (que puede ser una salida programada
    # a futuro, o un envío tardío de un viaje ya activado hace días).
    ahora = ahora_peru()
    fecha_emision = ahora.date().isoformat()
    hora_emision = ahora.strftime("%H:%M:%S")

    vehiculos = [
        {
            "vehiculo": "principal",
            "numero_de_placa": tracto.placa,
            "tarjeta_unica_de_cirulacion": tracto.tarjeta_unica_circulacion or "",
        }
    ]
    if carreta is not None:
        vehiculos.append(
            {
                "vehiculo": "secundario",
                "numero_de_placa": carreta.placa,
                "tarjeta_unica_de_cirulacion": carreta.tarjeta_unica_circulacion or "",
            }
        )

    payload: dict[str, Any] = {
        "documento": "guia_remision_transportista",
        "serie": guia.serie,
        "numero": guia.numero,
        "fecha_de_emision": fecha_emision,
        "hora_de_emision": hora_emision,
        "fecha_inicio_de_traslado": fecha_emision,
        "peso_bruto_total": str(guia.peso_bruto_total_kg),
        "peso_bruto_unidad_de_medida": "KGM",
        "numero_de_bultos": guia.numero_bultos or 1,
        "numero_de_registro_mtc": empresa.numero_registro_mtc or "",
        "observaciones": "",
        "punto_de_partida_ubigeo": viaje.origen_ubigeo,
        "punto_de_partida_direccion": viaje.origen_direccion,
        "punto_de_llegada_ubigeo": viaje.destino_ubigeo,
        "punto_de_llegada_direccion": viaje.destino_direccion,
        "destinatario": (
            {
                "tipo_de_documento": guia.destinatario_tipo_documento,
                "numero_de_documento": guia.destinatario_numero_documento,
                "denominacion": guia.destinatario_razon_social,
                "direccion": viaje.destino_direccion,
            }
            if guia.destinatario_numero_documento and guia.destinatario_tipo_documento and guia.destinatario_razon_social
            else {
                "tipo_de_documento": _CODIGO_TIPO_DOCUMENTO[cliente.tipo_documento],
                "numero_de_documento": cliente.numero_documento,
                "denominacion": cliente.razon_social,
                "direccion": cliente.direccion or viaje.destino_direccion,
            }
        ),
        "remitente": {
            "tipo_de_documento": _CODIGO_TIPO_DOCUMENTO[remitente.tipo_documento],
            "numero_de_documento": remitente.numero_documento,
            "denominacion": remitente.razon_social,
        },
        "conductores": [
            {
                "conductor": "principal",
                "tipo_de_documento": "1",
                "numero_de_documento": chofer.dni,
                "nombres": chofer.nombres,
                "apellidos": chofer.apellidos,
                "numero_licencia_conducir": chofer.licencia_numero,
            }
        ],
        "vehiculos": vehiculos,
        "items": (
            [
                {
                    "codigo": b.get("codigo") or "CARGA",
                    "descripcion": b["descripcion"][:250],
                    "cantidad": str(b.get("cantidad") or 1),
                    "unidad_de_medida": b.get("unidad") or "NIU",
                }
                for b in guia.bienes
            ]
            if guia.bienes
            else await _construir_items(db, viaje)
        ),
    }

    # Si el cliente ya generó su propia Guía de Remisión Remitente en SUNAT, se
    # referencia aquí (caso frecuente: ~50% de los clientes con RUC la emiten antes
    # del viaje). Confirmado aceptado por SUNAT vía prueba directa contra el sandbox.
    if guia.remitente_guia_serie and guia.remitente_guia_numero and guia.remitente_guia_ruc_emisor:
        payload["documentos_relacionados"] = [
            {
                "documento": "guia_remision_remitente",
                "serie": guia.remitente_guia_serie,
                "numero": guia.remitente_guia_numero,
                "ruc_emisor": guia.remitente_guia_ruc_emisor,
            }
        ]

    return payload


async def emitir_guia_remision_transportista(db: AsyncSession, guia_remision_id: uuid.UUID) -> GuiaRemision:
    """Envía la Guía de Remisión Transportista a SUNAT vía apisunat.pe (POST
    /api/v3/dispatches) y persiste el resultado (estado, hash, XML, CDR, PDF oficial)
    en la propia Guía de Remisión."""
    guia = await db.get(GuiaRemision, guia_remision_id)
    if guia is None:
        raise DatosIncompletosError("Guía de remisión no encontrada")

    payload = await construir_payload_guia_remision_transportista(db, guia)

    cliente_api = _ClienteApiSunatFacturacion()
    try:
        resultado = await cliente_api.emitir("/api/v3/dispatches", payload)
    finally:
        await cliente_api.cerrar()

    guia.mensaje_sunat = resultado.get("message")

    if resultado.get("success"):
        datos = resultado.get("payload") or {}
        estado_texto = str(datos.get("estado", "")).upper()
        guia.estado_sunat = EstadoSunat.ACEPTADO if estado_texto == "ACEPTADO" else EstadoSunat.PENDIENTE
        guia.hash_cpe = datos.get("hash")
        guia.xml_url = datos.get("xml")
        guia.cdr_url = datos.get("cdr") or None
        pdf = datos.get("pdf") or {}
        guia.pdf_url = pdf.get("a4")
        # Refleja la fecha real de presentación a SUNAT (payload["fecha_de_emision"]),
        # que puede diferir de la fecha con la que se creó el registro interno.
        guia.fecha_emision = ahora_peru().date()
    else:
        guia.estado_sunat = EstadoSunat.RECHAZADO

    await db.flush()
    return guia


def _receptor(factura: Factura, cliente: Cliente) -> dict[str, str]:
    """Receptor tal como se confirmó al emitir (puede ser "CLIENTES VARIOS" en una
    boleta sin documento); los comprobantes antiguos sin snapshot usan el cliente."""
    if factura.receptor_numero_documento and factura.receptor_tipo_documento and factura.receptor_razon_social:
        return {
            "cliente_tipo_de_documento": factura.receptor_tipo_documento,
            "cliente_numero_de_documento": factura.receptor_numero_documento,
            "cliente_denominacion": factura.receptor_razon_social,
            "cliente_direccion": (
                (cliente.direccion or "") if factura.receptor_numero_documento == cliente.numero_documento else ""
            ),
        }
    return {
        "cliente_tipo_de_documento": _CODIGO_TIPO_DOCUMENTO[cliente.tipo_documento],
        "cliente_numero_de_documento": cliente.numero_documento,
        "cliente_denominacion": cliente.razon_social,
        "cliente_direccion": cliente.direccion or "",
    }


async def construir_payload_factura(db: AsyncSession, factura: Factura) -> dict[str, Any]:
    cliente = await db.get(Cliente, factura.cliente_id)
    if cliente is None:
        raise DatosIncompletosError("El cliente de esta factura no existe")

    viaje = await db.get(Viaje, factura.viaje_id) if factura.viaje_id else None
    descripcion = factura.descripcion or await _descripcion_servicio(
        db, viaje, "Servicio de transporte de carga por carretera"
    )

    fecha_emision = ahora_peru().date().isoformat()
    subtotal = float(factura.subtotal)
    igv = float(factura.igv)
    total = float(factura.total)
    # "10" = Gravado - Operación Onerosa; "20" = Exonerado (catálogo 07 SUNAT). Nuestro
    # sistema solo distingue "con IGV" (18%) de "sin IGV" (0%) en la cotización, así
    # que una factura sin IGV se trata como exonerada por defecto.
    afecto = igv > 0
    porcentaje_igv = round((igv / subtotal) * 100, 2) if afecto and subtotal else 0.0

    documento = "factura" if factura.tipo_documento == TipoDocumentoVenta.FACTURA else "boleta"

    return {
        "documento": documento,
        "serie": factura.serie,
        "numero": factura.numero,
        "fecha_de_emision": fecha_emision,
        "fecha_de_vencimiento": fecha_emision,
        "moneda": factura.moneda,
        "tipo_operacion": "0101",
        **_receptor(factura, cliente),
        "gravadas": f"{subtotal:.2f}" if afecto else "0.00",
        "exoneradas": "0.00" if afecto else f"{subtotal:.2f}",
        "igv": f"{igv:.2f}",
        "total": f"{total:.2f}",
        "items": [
            {
                "codigo": "SERV001",
                "descripcion": descripcion[:250],
                "cantidad": "1",
                "unidad_de_medida": "ZZ",
                "valor_unitario": f"{subtotal:.2f}",
                "precio_unitario": f"{total:.2f}",
                "tipo_de_afectacion_igv": "10" if afecto else "20",
                "codigo_tipo_afectacion_igv": "10" if afecto else "20",
                "porcentaje_igv": f"{porcentaje_igv:.2f}",
                "nombre_tributo": "IGV",
            }
        ],
    }


async def emitir_factura(db: AsyncSession, factura_id: uuid.UUID) -> Factura:
    """Envía la Factura o Boleta a SUNAT vía apisunat.pe (POST /api/v3/documents) y
    persiste el resultado (estado, hash, XML, CDR) en el propio registro."""
    factura = await db.get(Factura, factura_id)
    if factura is None:
        raise DatosIncompletosError("Factura no encontrada")

    payload = await construir_payload_factura(db, factura)
    factura.enviado_en = factura.enviado_en or ahora_peru()

    cliente_api = _ClienteApiSunatFacturacion()
    try:
        resultado = await cliente_api.emitir("/api/v3/documents", payload)
    finally:
        await cliente_api.cerrar()

    factura.mensaje_sunat = resultado.get("message")

    if resultado.get("success"):
        datos = resultado.get("payload") or {}
        estado_texto = str(datos.get("estado", "")).upper()
        factura.estado_sunat = EstadoSunat.ACEPTADO if estado_texto == "ACEPTADO" else EstadoSunat.PENDIENTE
        factura.hash_cpe = datos.get("hash")
        factura.xml_url = datos.get("xml")
        factura.cdr_url = datos.get("cdr") or None
        pdf = datos.get("pdf") or {}
        factura.pdf_url = pdf.get("a4")
        factura.fecha_emision = ahora_peru().date()
    else:
        factura.estado_sunat = EstadoSunat.RECHAZADO

    await db.flush()
    return factura


def _construir_payload_comunicacion_baja(factura: Factura, motivo: str) -> dict[str, Any]:
    return {
        "documento": "comunicacion_baja",
        "motivo": motivo,
        "documento_afectado": {"documento": "factura", "serie": factura.serie, "numero": factura.numero},
    }


def _construir_payload_resumen_diario_anular(factura: Factura) -> dict[str, Any]:
    return {
        "documento": "resumen_diario",
        "documentos_afectados": [
            {"accion_resumen": "anular", "documento": "boleta", "serie": factura.serie, "numero": factura.numero}
        ],
    }


async def _construir_payload_nota_credito(
    db: AsyncSession, factura: Factura, cliente: Cliente, serie_nota: str, numero_nota: str, motivo: str
) -> dict[str, Any]:
    viaje = await db.get(Viaje, factura.viaje_id) if factura.viaje_id else None
    descripcion = factura.descripcion or await _descripcion_servicio(
        db, viaje, "Servicio de transporte de carga por carretera"
    )
    subtotal = float(factura.subtotal)
    igv = float(factura.igv)
    total = float(factura.total)
    afecto = igv > 0
    porcentaje_igv = round((igv / subtotal) * 100, 2) if afecto and subtotal else 0.0
    documento_afectado = "factura" if factura.tipo_documento == TipoDocumentoVenta.FACTURA else "boleta"

    return {
        "documento": "nota_credito",
        "serie": serie_nota,
        "numero": numero_nota,
        "fecha_de_emision": ahora_peru().date().isoformat(),
        "moneda": factura.moneda,
        **_receptor(factura, cliente),
        "nota_credito_codigo_tipo": "01",  # Catálogo 09 SUNAT: "01" = Anulación de la operación
        "nota_credito_motivo": motivo,
        "documento_afectado": {"documento": documento_afectado, "serie": factura.serie, "numero": factura.numero},
        "items": [
            {
                "unidad_de_medida": "ZZ",
                "descripcion": descripcion[:250],
                "cantidad": "1",
                "valor_unitario": f"{subtotal:.2f}",
                "porcentaje_igv": f"{porcentaje_igv:.2f}",
                "codigo_tipo_afectacion_igv": "10" if afecto else "20",
                "nombre_tributo": "IGV",
            }
        ],
        "total": f"{total:.2f}",
    }


async def anular_comprobante(db: AsyncSession, factura_id: uuid.UUID, motivo: str | None = None) -> Factura:
    """Anula una Factura o Boleta ya aceptada por SUNAT.

    Usa la vía directa (comunicación de baja para Factura, resumen diario para
    Boleta) mientras esté dentro del plazo que admite apisunat.pe; pasado ese
    plazo, emite una Nota de Crédito de anulación total referenciando el
    documento original — es la única vía que SUNAT permite después del plazo.
    Una Guía de Remisión no puede anularse por esta API (SUNAT la rechaza).
    """
    factura = await db.get(Factura, factura_id)
    if factura is None:
        raise DatosIncompletosError("Comprobante no encontrado")
    if factura.tipo_documento == TipoDocumentoVenta.NOTA_CREDITO:
        raise AnulacionNoSoportadaError("Una Nota de Crédito no puede anularse")
    if factura.estado_sunat != EstadoSunat.ACEPTADO:
        raise ComprobanteNoAceptadoError("Solo se puede anular un comprobante que ya fue aceptado por SUNAT")

    motivo_final = motivo or "ANULACION DE OPERACION"
    dias_desde_emision = (ahora_peru().date() - factura.fecha_emision).days
    plazo_directo = _PLAZO_ANULACION_DIRECTA_DIAS[factura.tipo_documento]

    cliente_api = _ClienteApiSunatFacturacion()
    try:
        if dias_desde_emision <= plazo_directo:
            ruta = "/api/v3/voided" if factura.tipo_documento == TipoDocumentoVenta.FACTURA else "/api/v3/daily-summary"
            payload = (
                _construir_payload_comunicacion_baja(factura, motivo_final)
                if factura.tipo_documento == TipoDocumentoVenta.FACTURA
                else _construir_payload_resumen_diario_anular(factura)
            )
            resultado = await cliente_api.emitir(ruta, payload)
            factura.mensaje_sunat = resultado.get("message")
            if resultado.get("success"):
                factura.estado_sunat = EstadoSunat.ANULADO
            await db.flush()
            return factura

        # Fuera de plazo: solo Nota de Crédito. Genera un nuevo comprobante propio.
        cliente = await db.get(Cliente, factura.cliente_id)
        if cliente is None:
            raise DatosIncompletosError("El cliente de este comprobante no existe")
        serie_nota = "FC01" if factura.tipo_documento == TipoDocumentoVenta.FACTURA else "BC01"
        numero_nota = await generar_numero_serie_sunat(db, tipo="NOTA_CREDITO", serie=serie_nota)
        payload = await _construir_payload_nota_credito(db, factura, cliente, serie_nota, numero_nota, motivo_final)
        resultado = await cliente_api.emitir("/api/v3/documents", payload)
    finally:
        await cliente_api.cerrar()

    nota_credito = Factura(
        empresa_id=factura.empresa_id,
        viaje_id=factura.viaje_id,
        cotizacion_id=factura.cotizacion_id,
        cliente_id=factura.cliente_id,
        documento_afectado_id=factura.id,
        tipo_documento=TipoDocumentoVenta.NOTA_CREDITO,
        serie=serie_nota,
        numero=numero_nota,
        fecha_emision=ahora_peru().date(),
        moneda=factura.moneda,
        subtotal=factura.subtotal,
        igv=factura.igv,
        total=factura.total,
        precio_incluye_igv=factura.precio_incluye_igv,
        receptor_tipo_documento=factura.receptor_tipo_documento,
        receptor_numero_documento=factura.receptor_numero_documento,
        receptor_razon_social=factura.receptor_razon_social,
        descripcion=factura.descripcion,
        estado_sunat=EstadoSunat.PENDIENTE,
        mensaje_sunat=resultado.get("message"),
    )

    if resultado.get("success"):
        datos = resultado.get("payload") or {}
        estado_texto = str(datos.get("estado", "")).upper()
        nota_credito.estado_sunat = EstadoSunat.ACEPTADO if estado_texto == "ACEPTADO" else EstadoSunat.PENDIENTE
        nota_credito.hash_cpe = datos.get("hash")
        nota_credito.xml_url = datos.get("xml")
        nota_credito.cdr_url = datos.get("cdr") or None
        pdf = datos.get("pdf") or {}
        nota_credito.pdf_url = pdf.get("a4")
        factura.estado_sunat = EstadoSunat.ANULADO
    else:
        nota_credito.estado_sunat = EstadoSunat.RECHAZADO

    db.add(nota_credito)
    await db.flush()
    return factura
