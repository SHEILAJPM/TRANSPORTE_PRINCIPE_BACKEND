"""gre transportista sunat directo

Revision ID: b7c41e2a9d10
Revises: 12bf60ce79e4
Create Date: 2026-10-31 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'b7c41e2a9d10'
down_revision: Union[str, None] = '12bf60ce79e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('guias_remision', sa.Column('destinatario_tipo_documento', sa.String(length=1), nullable=True))
    op.add_column('guias_remision', sa.Column('destinatario_numero_documento', sa.String(length=15), nullable=True))
    op.add_column('guias_remision', sa.Column('destinatario_razon_social', sa.String(length=250), nullable=True))
    op.add_column('guias_remision', sa.Column('bienes', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('guias_remision', sa.Column('sunat_ticket', sa.String(length=60), nullable=True))
    op.add_column('guias_remision', sa.Column('sunat_codigo_respuesta', sa.String(length=10), nullable=True))
    op.add_column('guias_remision', sa.Column('enviado_sunat_en', sa.DateTime(timezone=True), nullable=True))
    op.add_column('guias_remision', sa.Column('xml_clave', sa.String(length=300), nullable=True))
    op.add_column('guias_remision', sa.Column('cdr_clave', sa.String(length=300), nullable=True))


def downgrade() -> None:
    op.drop_column('guias_remision', 'cdr_clave')
    op.drop_column('guias_remision', 'xml_clave')
    op.drop_column('guias_remision', 'enviado_sunat_en')
    op.drop_column('guias_remision', 'sunat_codigo_respuesta')
    op.drop_column('guias_remision', 'sunat_ticket')
    op.drop_column('guias_remision', 'bienes')
    op.drop_column('guias_remision', 'destinatario_razon_social')
    op.drop_column('guias_remision', 'destinatario_numero_documento')
    op.drop_column('guias_remision', 'destinatario_tipo_documento')
