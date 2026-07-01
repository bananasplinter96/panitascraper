"""add cedula validation columns

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-01
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "personas",
        sa.Column("cedula_validacion", sa.String(30), nullable=True),
        # 'exacta' | 'exacta_reordenada' | 'fonetica' | 'no_coincide' | 'sin_registro'
    )
    op.add_column(
        "personas",
        sa.Column("cedula_nombre_oficial", sa.String(512), nullable=True),
        # nombre tal como aparece en el padrón (dateas/armando/cedula.com.ve)
    )
    op.add_column(
        "personas",
        sa.Column("cedula_similitud", sa.Float(), nullable=True),
        # score 0.0-1.0 de similitud tras normalizar/fonetizar
    )
    op.create_index("ix_personas_cedula_validacion", "personas", ["cedula_validacion"])


def downgrade() -> None:
    op.drop_index("ix_personas_cedula_validacion", table_name="personas")
    op.drop_column("personas", "cedula_similitud")
    op.drop_column("personas", "cedula_nombre_oficial")
    op.drop_column("personas", "cedula_validacion")
