import uuid

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
from app.services.pdf_service import renderizar_pdf


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


async def generar_pdf_factura(db: AsyncSession, factura_id: uuid.UUID) -> bytes:
    factura = await db.get(Factura, factura_id)
    if factura is None:
        raise DocumentoNoEncontradoError("Factura no encontrada")
    cliente = await db.get(Cliente, factura.cliente_id)
    viaje = await db.get(Viaje, factura.viaje_id) if factura.viaje_id else None
    guia = await db.get(GuiaRemision, factura.guia_remision_id) if factura.guia_remision_id else None

    datos_cliente = _cliente_contexto(cliente)
    if factura.receptor_numero_documento and factura.receptor_numero_documento != cliente.numero_documento:
        # Receptor distinto del cliente del viaje (p.ej. boleta a "CLIENTES VARIOS").
        datos_cliente = {
            "razon_social": factura.receptor_razon_social,
            "tipo_documento": _NOMBRE_TIPO_DOCUMENTO.get(factura.receptor_tipo_documento or "", "-"),
            "numero_documento": factura.receptor_numero_documento,
            "direccion": None,
        }

    contexto = {
        "empresa": await _empresa_contexto(db, factura.empresa_id),
        "cliente": datos_cliente,
        "factura": {
            "serie": factura.serie,
            "numero": factura.numero,
            "fecha_emision": factura.fecha_emision,
            "moneda": factura.moneda,
            "subtotal": float(factura.subtotal),
            "igv": float(factura.igv),
            "total": float(factura.total),
            "estado_sunat": factura.estado_sunat.value,
            "viaje_numero": viaje.numero if viaje else None,
            "descripcion_servicio": factura.descripcion or "Servicio de transporte de carga por carretera",
            "guia_remision": f"{guia.serie}-{guia.numero}" if guia else None,
            "detraccion": (
                {
                    "porcentaje": float(factura.detraccion_porcentaje or 0),
                    "monto": float(factura.detraccion_monto),
                    "cuenta": factura.detraccion_cuenta,
                    "neto": float(factura.total) - float(factura.detraccion_monto),
                }
                if factura.detraccion_monto
                else None
            ),
            "titulo_documento": (
                "FACTURA ELECTRÓNICA" if factura.tipo_documento == TipoDocumentoVenta.FACTURA else "BOLETA DE VENTA ELECTRÓNICA"
            ),
        },
    }
    return renderizar_pdf("factura.html", contexto)


async def generar_pdf_guia_remision(db: AsyncSession, guia_remision_id: uuid.UUID) -> bytes:
    guia = await db.get(GuiaRemision, guia_remision_id)
    if guia is None:
        raise DocumentoNoEncontradoError("Guía de remisión no encontrada")
    cliente = await db.get(Cliente, guia.cliente_id)
    viaje = await db.get(Viaje, guia.viaje_id)
    tracto = await db.get(Tracto, viaje.tracto_id) if viaje else None
    carreta = await db.get(Carreta, viaje.carreta_id) if viaje and viaje.carreta_id else None
    chofer = await db.get(Chofer, viaje.chofer_id) if viaje else None

    contexto = {
        "empresa": await _empresa_contexto(db, guia.empresa_id),
        "cliente": _cliente_contexto(cliente),
        "guia": {
            "serie": guia.serie,
            "numero": guia.numero,
            "fecha_emision": guia.fecha_emision,
            "motivo_traslado": guia.motivo_traslado,
            "modalidad_transporte": guia.modalidad_transporte,
            "peso_bruto_total_kg": float(guia.peso_bruto_total_kg),
            "numero_bultos": guia.numero_bultos,
            "estado_sunat": guia.estado_sunat.value,
        },
        "viaje": {
            "numero": viaje.numero if viaje else None,
            "origen": f"{viaje.origen_direccion}, {viaje.origen_distrito}, {viaje.origen_provincia}" if viaje else None,
            "destino": f"{viaje.destino_direccion}, {viaje.destino_distrito}, {viaje.destino_provincia}" if viaje else None,
            "fecha_salida_programada": viaje.fecha_salida_programada if viaje else None,
        },
        "tracto": {"placa": tracto.placa, "marca": tracto.marca} if tracto else None,
        "carreta": {"placa": carreta.placa, "tipo_carreta": carreta.tipo_carreta.value} if carreta else None,
        "chofer": {
            "nombres": chofer.nombres,
            "apellidos": chofer.apellidos,
            "licencia_numero": chofer.licencia_numero,
            "licencia_categoria": chofer.licencia_categoria,
        }
        if chofer
        else None,
    }
    return renderizar_pdf("guia_remision.html", contexto)


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
            "fecha_verificacion": constancia.fecha_verificacion,
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
