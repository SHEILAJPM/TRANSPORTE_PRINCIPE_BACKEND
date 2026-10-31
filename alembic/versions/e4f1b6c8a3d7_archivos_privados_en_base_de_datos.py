"""archivos privados en base de datos

Revision ID: e4f1b6c8a3d7
Revises: d2a9c7e4f6b1
Create Date: 2026-11-01 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'e4f1b6c8a3d7'
down_revision: Union[str, None] = 'd2a9c7e4f6b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'archivos_privados',
        sa.Column('clave', sa.String(length=300), nullable=False),
        sa.Column('contenido', sa.LargeBinary(), nullable=False),
        sa.Column('content_type', sa.String(length=100), nullable=False),
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('creado_en', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('actualizado_en', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_archivos_privados_clave'), 'archivos_privados', ['clave'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_archivos_privados_clave'), table_name='archivos_privados')
    op.drop_table('archivos_privados')
