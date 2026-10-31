"""comprobante al finalizar viaje

Revision ID: c5e8f3a1b2d4
Revises: b7c41e2a9d10
Create Date: 2026-10-31 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c5e8f3a1b2d4'
down_revision: Union[str, None] = 'b7c41e2a9d10'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('facturas', sa.Column('precio_incluye_igv', sa.Boolean(), nullable=True))
    op.add_column('facturas', sa.Column('receptor_tipo_documento', sa.String(length=1), nullable=True))
    op.add_column('facturas', sa.Column('receptor_numero_documento', sa.String(length=15), nullable=True))
    op.add_column('facturas', sa.Column('receptor_razon_social', sa.String(length=255), nullable=True))
    op.add_column('facturas', sa.Column('descripcion', sa.Text(), nullable=True))
    op.add_column('facturas', sa.Column('enviado_en', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('facturas', 'enviado_en')
    op.drop_column('facturas', 'descripcion')
    op.drop_column('facturas', 'receptor_razon_social')
    op.drop_column('facturas', 'receptor_numero_documento')
    op.drop_column('facturas', 'receptor_tipo_documento')
    op.drop_column('facturas', 'precio_incluye_igv')
