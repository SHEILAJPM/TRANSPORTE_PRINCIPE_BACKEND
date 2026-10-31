"""detraccion factura y cuenta de detracciones de la empresa

Revision ID: d2a9c7e4f6b1
Revises: c5e8f3a1b2d4
Create Date: 2026-10-31 17:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd2a9c7e4f6b1'
down_revision: Union[str, None] = 'c5e8f3a1b2d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('facturas', sa.Column('detraccion_porcentaje', sa.Numeric(precision=5, scale=2), nullable=True))
    op.add_column('facturas', sa.Column('detraccion_monto', sa.Numeric(precision=12, scale=2), nullable=True))
    op.add_column('facturas', sa.Column('detraccion_cuenta', sa.String(length=20), nullable=True))
    op.add_column('empresas', sa.Column('cuenta_detracciones', sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column('empresas', 'cuenta_detracciones')
    op.drop_column('facturas', 'detraccion_cuenta')
    op.drop_column('facturas', 'detraccion_monto')
    op.drop_column('facturas', 'detraccion_porcentaje')
