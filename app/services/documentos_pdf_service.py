import uuid

import segno

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chofer import Chofer
from app.models.cliente import Cliente
from app.models.comprobante import Factura, GuiaRemision
from app.models.cotizacion import Cotizacion
from app.models.empresa import Empresa
from app.models.enums import TipoDocumentoVenta
from app.models.flota import Carreta, Tracto
from app.models.pesos_medidas import ConstanciaPesosMedidas
from app.models.viaje import Viaje
from app.services.apisunat_facturacion_service import DatosIncompletosError
from app.services.guia_transportista_service import construir_datos
from app.services.pdf_service import renderizar_pdf
from app.utils.fechas import en_hora_peru
from app.utils.numero_letras import importe_en_letras


class DocumentoNoEncontradoError(Exception):
    pass


async def _empresa_contexto(db: AsyncSession, empresa_id: uuid.UUID) -> dict:
    empresa = await db.get(Empresa, empresa_id)
    if empresa is None:
        raise DocumentoNoEncontradoError("Empresa no encontrada")
    return {
        "razon_social": empresa.razon_social,
        "nombre_comercial": empresa.nombre_comercial,
        "ruc": empresa.ruc,
        "direccion_fiscal": empresa.direccion_fiscal,
        "telefono": empresa.telefono,
        "logo_url": empresa.logo_url,
    }


_NOMBRE_TIPO_DOCUMENTO = {"6": "RUC", "1": "DNI", "0": "-"}


def _cliente_contexto(cliente: Cliente) -> dict:
    return {
        "razon_social": cliente.razon_social,
        "tipo_documento": cliente.tipo_documento.value,
        "numero_documento": cliente.numero_documento,
        "direccion": cliente.direccion,
        "distrito": cliente.distrito,
        "provincia": cliente.provincia,
        "departamento": cliente.departamento,
    }


async def generar_pdf_cotizacion(db: AsyncSession, cotizacion_id: uuid.UUID) -> bytes:
    cotizacion = await db.get(Cotizacion, cotizacion_id)
    if cotizacion is None:
        raise DocumentoNoEncontradoError("Cotización no encontrada")
    cliente = await db.get(Cliente, cotizacion.cliente_id)

    contexto = {
        "empresa": await _empresa_contexto(db, cotizacion.empresa_id),
        "cliente": _cliente_contexto(cliente),
        "cotizacion": {
            "numero": cotizacion.numero,
            "fecha_emision": cotizacion.fecha_emision,
            "validez_dias": cotizacion.validez_dias,
            "descripcion_servicio": cotizacion.descripcion_servicio,
            "origen_direccion": cotizacion.origen_direccion,
            "origen_distrito": cotizacion.origen_distrito,
            "origen_provincia": cotizacion.origen_provincia,
            "origen_departamento": cotizacion.origen_departamento,
            "destino_direccion": cotizacion.destino_direccion,
            "destino_distrito": cotizacion.destino_distrito,
            "destino_provincia": cotizacion.destino_provincia,
            "destino_departamento": cotizacion.destino_departamento,
            "cantidad_camiones": cotizacion.cantidad_camiones,
            "peso_tm": float(cotizacion.peso_tm),
            "precio_base": float(cotizacion.precio_base),
            "porcentaje_igv": float(cotizacion.porcentaje_igv),
            "monto_igv": float(cotizacion.monto_igv),
            "precio_total": float(cotizacion.precio_total),
            "condiciones_comerciales": cotizacion.condiciones_comerciales,
        },
    }
    return renderizar_pdf("cotizacion.html", contexto)


_TITULO_COMPROBANTE = {
    TipoDocumentoVenta.FACTURA: ("FACTURA ELECTRÓNICA", "01"),
    TipoDocumentoVenta.BOLETA: ("BOLETA DE VENTA ELECTRÓNICA", "03"),
    TipoDocumentoVenta.NOTA_CREDITO: ("NOTA DE CRÉDITO ELECTRÓNICA", "07"),
}


async def contexto_factura(db: AsyncSession, factura_id: uuid.UUID) -> dict:
    """Representación impresa de Factura, Boleta o Nota de Crédito, con el receptor y
    los montos tal como se enviaron a SUNAT."""
    factura = await db.get(Factura, factura_id)
    if factura is None:
        raise DocumentoNoEncontradoError("Factura no encontrada")
    cliente = await db.get(Cliente, factura.cliente_id)
    empresa = await db.get(Empresa, factura.empresa_id)
    viaje = await db.get(Viaje, factura.viaje_id) if factura.viaje_id else None
    guia = await db.get(GuiaRemision, factura.guia_remision_id) if factura.guia_remision_id else None
    afectado = await db.get(Factura, factura.documento_afectado_id) if factura.documento_afectado_id else None

    datos_cliente = _cliente_contexto(cliente)
    codigo_receptor = factura.receptor_tipo_documento or {"RUC": "6", "DNI": "1"}[cliente.tipo_documento.value]
    if factura.receptor_numero_documento and factura.receptor_numero_documento != cliente.numero_documento:
        # Receptor distinto del cliente del viaje (p.ej. boleta a "CLIENTES VARIOS").
        datos_cliente = {
            "razon_social": factura.receptor_razon_social,
            "tipo_documento": _NOMBRE_TIPO_DOCUMENTO.get(codigo_receptor, "-"),
            "numero_documento": factura.receptor_numero_documento,
            "direccion": None,
        }

    titulo, codigo_tipo = _TITULO_COMPROBANTE[factura.tipo_documento]
    subtotal, igv, total = float(factura.subtotal), float(factura.igv), float(factura.total)
    qr = None
    if factura.hash_cpe and empresa is not None:
        # Formato SUNAT: RUC|TIPO|SERIE|NUMERO|IGV|TOTAL|FECHA|TIPO DOC ADQ|NUM DOC ADQ|HASH|
        qr = _qr_data_uri(
            f"{empresa.ruc}|{codigo_tipo}|{factura.serie}|{factura.numero}|{igv:.2f}|{total:.2f}|"
            f"{factura.fecha_emision:%Y-%m-%d}|{codigo_receptor}|{datos_cliente['numero_documento']}|{factura.hash_cpe}|"
        )

    return {
        "empresa": await _empresa_contexto(db, factura.empresa_id),
        "cliente": datos_cliente,
        "factura": {
            "serie": factura.serie,
            "numero": factura.numero,
            "fecha_emision": factura.fecha_emision,
            "moneda": factura.moneda,
            "forma_pago": "Contado",
            "subtotal": subtotal,
            "igv": igv,
            "porcentaje_igv": round(igv / subtotal * 100) if subtotal else 0,
            "total": total,
            "total_letras": importe_en_letras(total, factura.moneda),
            "estado_sunat": factura.estado_sunat.value,
            "hash": factura.hash_cpe,
            "qr": qr,
            "viaje_numero": viaje.numero if viaje else None,
            "descripcion_servicio": factura.descripcion or "Servicio de transporte de carga por carretera",
            "guia_remision": f"{guia.serie}-{guia.numero}" if guia else None,
            "documento_afectado": f"{afectado.serie}-{afectado.numero}" if afectado else None,
            "detraccion": (
                {
                    "porcentaje": float(factura.detraccion_porcentaje or 0),
                    "monto": float(factura.detraccion_monto),
                    "cuenta": factura.detraccion_cuenta,
                    "neto": total - float(factura.detraccion_monto),
                }
                if factura.detraccion_monto
                else None
            ),
            "titulo_documento": titulo,
        },
    }


async def generar_pdf_factura(db: AsyncSession, factura_id: uuid.UUID) -> bytes:
    return renderizar_pdf("factura.html", await contexto_factura(db, factura_id))


def _qr_data_uri(contenido: str) -> str:
    return segno.make(contenido, error="m").svg_data_uri(scale=3, border=1)


def _parte(parte) -> dict:
    return {
        "razon_social": parte.razon_social,
        "tipo_documento": _NOMBRE_TIPO_DOCUMENTO.get(parte.tipo_documento, parte.tipo_documento),
        "numero_documento": parte.numero_documento,
    }


async def contexto_guia_remision(db: AsyncSession, guia_remision_id: uuid.UUID) -> dict:
    """Representación impresa de la Guía de Remisión Transportista. Los datos salen de
    `construir_datos`, la misma función que arma el XML enviado a SUNAT, para que el
    papel y el documento electrónico nunca difieran."""
    guia = await db.get(GuiaRemision, guia_remision_id)
    if guia is None:
        raise DocumentoNoEncontradoError("Guía de remisión no encontrada")
    viaje = await db.get(Viaje, guia.viaje_id)
    chofer = await db.get(Chofer, viaje.chofer_id) if viaje else None
    try:
        datos, _ = await construir_datos(db, guia)
    except DatosIncompletosError as error:
        raise DocumentoNoEncontradoError(str(error)) from error

    enlace_sunat = guia.pdf_url if guia.pdf_url and guia.pdf_url.startswith("http") else None
    return {
        "empresa": await _empresa_contexto(db, guia.empresa_id),
        "guia": {
            "serie": guia.serie,
            "numero": guia.numero,
            "fecha_emision": guia.fecha_emision,
            "hora_emision": en_hora_peru(guia.enviado_sunat_en).strftime("%H:%M:%S") if guia.enviado_sunat_en else None,
            "fecha_inicio_traslado": datos.fecha_inicio_traslado,
            "registro_mtc": datos.registro_mtc,
            "peso_bruto_kg": float(datos.peso_bruto_kg),
            "numero_bultos": guia.numero_bultos,
            "motivo_traslado": guia.motivo_traslado,
            "estado_sunat": guia.estado_sunat.value,
            "hash": guia.hash_cpe,
            "enlace_sunat": enlace_sunat,
            "qr": _qr_data_uri(enlace_sunat) if enlace_sunat else None,
        },
        "remitente": _parte(datos.remitente),
        "destinatario": _parte(datos.destinatario),
        "partida": {
            "direccion": datos.partida.direccion,
            "ubigeo": datos.partida.ubigeo,
            "lugar": f"{viaje.origen_distrito}, {viaje.origen_provincia}, {viaje.origen_departamento}" if viaje else "",
        },
        "llegada": {
            "direccion": datos.llegada.direccion,
            "ubigeo": datos.llegada.ubigeo,
            "lugar": f"{viaje.destino_distrito}, {viaje.destino_provincia}, {viaje.destino_departamento}" if viaje else "",
        },
        "vehiculos": [
            {"rol": "Principal (tracto)", "placa": v.placa, "tuc": v.tarjeta_unica_circulacion}
            for v in [datos.vehiculo_principal]
        ]
        + [
            {"rol": "Secundario (carreta)", "placa": v.placa, "tuc": v.tarjeta_unica_circulacion}
            for v in datos.vehiculos_secundarios
        ],
        "conductor": {
            "nombre": f"{datos.conductor.nombres} {datos.conductor.apellidos}",
            "dni": datos.conductor.dni,
            "licencia": datos.conductor.licencia,
            "categoria": chofer.licencia_categoria if chofer else None,
        },
        "bienes": [
            {"descripcion": b.descripcion, "cantidad": float(b.cantidad), "unidad": b.unidad, "codigo": b.codigo}
            for b in datos.bienes
        ],
        "documentos_relacionados": [
            {"tipo": "Guía de remisión remitente", "numero": f"{d.serie}-{d.numero}", "ruc_emisor": d.ruc_emisor}
            for d in datos.documentos_relacionados
        ],
        "viaje_numero": viaje.numero if viaje else None,
    }


async def generar_pdf_guia_remision(db: AsyncSession, guia_remision_id: uuid.UUID) -> bytes:
    return renderizar_pdf("guia_remision.html", await contexto_guia_remision(db, guia_remision_id))


async def generar_pdf_constancia_pesos_medidas(db: AsyncSession, constancia_id: uuid.UUID) -> bytes:
    constancia = await db.get(ConstanciaPesosMedidas, constancia_id)
    if constancia is None:
        raise DocumentoNoEncontradoError("Constancia de pesos y medidas no encontrada")

    guia = await db.get(GuiaRemision, constancia.guia_remision_id)
    tracto = await db.get(Tracto, constancia.tracto_id)
    carreta = await db.get(Carreta, constancia.carreta_id) if constancia.carreta_id else None
    chofer = await db.get(Chofer, constancia.chofer_id)
    generador_carga = await db.get(Cliente, constancia.generador_carga_cliente_id)

    contexto = {
        "empresa": await _empresa_contexto(db, constancia.empresa_id),
        "constancia": {
            "numero": constancia.numero,
            "tipo_control": constancia.tipo_control,
            "lugar_verificacion": constancia.lugar_verificacion,
            "fecha_verificacion": en_hora_peru(constancia.fecha_verificacion),
            "peso_bruto_kg": float(constancia.peso_bruto_kg),
            "tara_kg": float(constancia.tara_kg),
            "peso_neto_kg": float(constancia.peso_neto_kg),
            "precinto_seguridad": constancia.precinto_seguridad,
            "numero_licencia_chofer": constancia.numero_licencia_chofer,
            "largo_m": float(constancia.largo_m),
            "ancho_m": float(constancia.ancho_m),
            "alto_m": float(constancia.alto_m),
            "configuracion_vehicular": constancia.configuracion_vehicular,
            "peso_bruto_max_kg": float(constancia.peso_bruto_max_kg),
            "observaciones": constancia.observaciones,
        },
        "guia_remision": {"serie": guia.serie, "numero": guia.numero} if guia else None,
        "tracto_placa": tracto.placa if tracto else None,
        "carreta_placa": carreta.placa if carreta else None,
        "chofer_nombre_completo": f"{chofer.nombres} {chofer.apellidos}" if chofer else None,
        "generador_carga": generador_carga.razon_social if generador_carga else None,
    }
    return renderizar_pdf("constancia_pesos_medidas.html", contexto)
