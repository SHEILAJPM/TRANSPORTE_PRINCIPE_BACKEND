from app.models.archivo_privado import ArchivoPrivado
from app.models.base import Base
from app.models.chofer import Chofer
from app.models.cliente import Cliente
from app.models.comprobante import Factura, GuiaRemision
from app.models.correlativo import Correlativo
from app.models.cotizacion import Cotizacion
from app.models.empresa import Empresa
from app.models.flota import Carreta, Tracto
from app.models.gasto_general import GastoGeneral
from app.models.gasto_viaje import GastoViaje
from app.models.liquidacion import LiquidacionChofer
from app.models.mantenimiento import MantenimientoVehiculo
from app.models.novedad_viaje import NovedadViaje
from app.models.pesos_medidas import ConstanciaPesosMedidas
from app.models.sunat_log import ConsultaSunatLog
from app.models.usuario import Usuario
from app.models.viaje import Viaje

__all__ = [
    "Base",
    "Empresa",
    "Usuario",
    "Cliente",
    "Chofer",
    "Tracto",
    "Carreta",
    "MantenimientoVehiculo",
    "Cotizacion",
    "Viaje",
    "GuiaRemision",
    "Factura",
    "Correlativo",
    "ConstanciaPesosMedidas",
    "GastoViaje",
    "GastoGeneral",
    "NovedadViaje",
    "LiquidacionChofer",
    "ConsultaSunatLog",
    "ArchivoPrivado",
]
