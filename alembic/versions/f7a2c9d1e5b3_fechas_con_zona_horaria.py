"""fechas con zona horaria

Revision ID: f7a2c9d1e5b3
Revises: e4f1b6c8a3d7
Create Date: 2026-11-02 10:00:00.000000

El frontend envía las fechas con zona horaria (ISO con "Z") y asyncpg no puede
guardarlas en columnas `timestamp` sin zona: Activar viaje, Iniciar/Finalizar viaje,
gastos, novedades, la conversión de cotizaciones y la subida del logo fallaban con
error 500. Se pasan a `timestamptz`; los valores existentes se ingresaron en hora
local, así que se interpretan como hora de Lima.
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'f7a2c9d1e5b3'
down_revision: Union[str, None] = 'e4f1b6c8a3d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COLUMNAS = [
    ("viajes", "fecha_salida_programada"),
    ("viajes", "fecha_salida_real"),
    ("viajes", "fecha_llegada_real"),
    ("gastos_viaje", "fecha"),
    ("gastos_viaje", "fecha_sincronizacion"),
    ("novedades_viaje", "fecha"),
    ("constancias_pesos_medidas", "fecha_verificacion"),
    ("cotizaciones", "convertida_en"),
    ("empresas", "logo_actualizado_en"),
]


def upgrade() -> None:
    for tabla, columna in COLUMNAS:
        op.execute(
            f"ALTER TABLE {tabla} ALTER COLUMN {columna} TYPE TIMESTAMP WITH TIME ZONE "
            f"USING {columna} AT TIME ZONE 'America/Lima'"
        )


def downgrade() -> None:
    for tabla, columna in COLUMNAS:
        op.execute(
            f"ALTER TABLE {tabla} ALTER COLUMN {columna} TYPE TIMESTAMP WITHOUT TIME ZONE "
            f"USING {columna} AT TIME ZONE 'America/Lima'"
        )
