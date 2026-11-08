"""deposito de detraccion

Revision ID: a8d3e1f9c2b6
Revises: f7a2c9d1e5b3
Create Date: 2026-11-08 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'a8d3e1f9c2b6'
down_revision: Union[str, None] = 'f7a2c9d1e5b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

depositante = postgresql.ENUM('CLIENTE', 'EMPRESA', name='depositante_detraccion')


def upgrade() -> None:
    depositante.create(op.get_bind(), checkfirst=True)
    op.add_column('facturas', sa.Column('detraccion_depositada_por', depositante, nullable=True))
    op.add_column('facturas', sa.Column('detraccion_fecha_deposito', sa.Date(), nullable=True))
    op.add_column('facturas', sa.Column('detraccion_constancia', sa.String(length=30), nullable=True))
    op.add_column('facturas', sa.Column('detraccion_monto_depositado', sa.Numeric(precision=12, scale=2), nullable=True))


def downgrade() -> None:
    op.drop_column('facturas', 'detraccion_monto_depositado')
    op.drop_column('facturas', 'detraccion_constancia')
    op.drop_column('facturas', 'detraccion_fecha_deposito')
    op.drop_column('facturas', 'detraccion_depositada_por')
    depositante.drop(op.get_bind(), checkfirst=True)
