import enum


class RolUsuario(str, enum.Enum):
    ADMIN = "ADMIN"
    OPERADOR = "OPERADOR"
    CONTABILIDAD = "CONTABILIDAD"
    CHOFER = "CHOFER"


class TipoDocumentoIdentidad(str, enum.Enum):
    RUC = "RUC"
    DNI = "DNI"


class EstadoCotizacion(str, enum.Enum):
    BORRADOR = "BORRADOR"
    ENVIADA = "ENVIADA"
    APROBADA = "APROBADA"
    RECHAZADA = "RECHAZADA"
    CONVERTIDA = "CONVERTIDA"
    VENCIDA = "VENCIDA"


class ModalidadViaje(str, enum.Enum):
    CON_RUC = "CON_RUC"
    SIN_RUC = "SIN_RUC"


class EstadoViaje(str, enum.Enum):
    PROGRAMADO = "PROGRAMADO"
    EN_RUTA = "EN_RUTA"
    FINALIZADO = "FINALIZADO"
    LIQUIDADO = "LIQUIDADO"
    CANCELADO = "CANCELADO"


class EstadoVehiculo(str, enum.Enum):
    OPERATIVO = "OPERATIVO"
    EN_MANTENIMIENTO = "EN_MANTENIMIENTO"
    INHABILITADO = "INHABILITADO"


class TipoCarreta(str, enum.Enum):
    SEMIRREMOLQUE = "SEMIRREMOLQUE"
    REMOLQUE = "REMOLQUE"


class TipoGastoViaje(str, enum.Enum):
    COMBUSTIBLE = "COMBUSTIBLE"
    PEAJE = "PEAJE"
    VIATICO = "VIATICO"
    ADELANTO = "ADELANTO"
    OTRO = "OTRO"


class TipoMantenimiento(str, enum.Enum):
    PREVENTIVO = "PREVENTIVO"
    CORRECTIVO = "CORRECTIVO"


class TipoDocumentoVenta(str, enum.Enum):
    FACTURA = "FACTURA"
    BOLETA = "BOLETA"
    NOTA_CREDITO = "NOTA_CREDITO"


class EstadoSunat(str, enum.Enum):
    PENDIENTE = "PENDIENTE"
    ACEPTADO = "ACEPTADO"
    RECHAZADO = "RECHAZADO"
    ANULADO = "ANULADO"


class EstadoLiquidacion(str, enum.Enum):
    PENDIENTE = "PENDIENTE"
    PAGADO = "PAGADO"


class CategoriaGastoGeneral(str, enum.Enum):
    """Egresos de la empresa que no están atados a un viaje ni a mantenimiento de flota."""

    ALQUILER = "ALQUILER"
    SEGUROS = "SEGUROS"
    SUELDOS_ADMINISTRATIVOS = "SUELDOS_ADMINISTRATIVOS"
    SERVICIOS = "SERVICIOS"
    IMPUESTOS_Y_TASAS = "IMPUESTOS_Y_TASAS"
    OTRO = "OTRO"
