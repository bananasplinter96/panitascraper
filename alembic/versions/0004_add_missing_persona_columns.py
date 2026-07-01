"""add missing persona columns to match production schema

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-01
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("personas", sa.Column("sexo", sa.String(), nullable=True, server_default=""))
    op.add_column("personas", sa.Column("foto_url", sa.String(), nullable=True))
    op.add_column("personas", sa.Column("cama_sala", sa.String(), nullable=True))
    op.add_column("personas", sa.Column("contacto_familiar", sa.String(), nullable=True))
    op.add_column("personas", sa.Column("ubicacion_cuerpo", sa.String(), nullable=True))
    op.add_column("personas", sa.Column("confirmacion_tipo", sa.String(), nullable=True))
    op.add_column("personas", sa.Column("confirmacion_detalle", sa.Text(), nullable=True))
    op.add_column("personas", sa.Column("ultimo_lugar", sa.String(), nullable=True))
    op.add_column("personas", sa.Column("ultimo_contacto", sa.String(), nullable=True))
    op.add_column("personas", sa.Column("descripcion_fisica", sa.Text(), nullable=True))
    op.add_column("personas", sa.Column("telefono_familiar", sa.String(), nullable=True))
    op.add_column("personas", sa.Column("reportero_nombre", sa.String(), nullable=True))
    op.add_column("personas", sa.Column("reportero_telefono", sa.String(), nullable=True))
    op.add_column("personas", sa.Column("merge_count", sa.Integer(), nullable=True, server_default="1"))
    op.add_column("personas", sa.Column("dedup_phase", sa.Integer(), nullable=True, server_default="0"))


def downgrade() -> None:
    op.drop_column("personas", "dedup_phase")
    op.drop_column("personas", "merge_count")
    op.drop_column("personas", "reportero_telefono")
    op.drop_column("personas", "reportero_nombre")
    op.drop_column("personas", "telefono_familiar")
    op.drop_column("personas", "descripcion_fisica")
    op.drop_column("personas", "ultimo_contacto")
    op.drop_column("personas", "ultimo_lugar")
    op.drop_column("personas", "confirmacion_detalle")
    op.drop_column("personas", "confirmacion_tipo")
    op.drop_column("personas", "ubicacion_cuerpo")
    op.drop_column("personas", "contacto_familiar")
    op.drop_column("personas", "cama_sala")
    op.drop_column("personas", "foto_url")
    op.drop_column("personas", "sexo")
