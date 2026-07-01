"""create personas table

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-30
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "personas",
        sa.Column("id", sa.String(), nullable=False),
        # Identificación
        sa.Column("nombre", sa.String(512), nullable=True),
        sa.Column("cedula", sa.String(20), nullable=True),
        sa.Column("edad", sa.String(10), nullable=True),
        # Situación
        sa.Column("tipo_reporte", sa.String(30), nullable=True),   # ingresado | desaparecido | fallecido
        sa.Column("condicion", sa.String(255), nullable=True),     # descripción libre del estado clínico
        sa.Column("estado", sa.String(255), nullable=True),        # texto del estado según la fuente
        # Ubicación
        sa.Column("hospital", sa.String(512), nullable=True),
        sa.Column("ciudad", sa.String(255), nullable=True),
        # Contacto y fuente
        sa.Column("notas", sa.Text, nullable=True),
        sa.Column("spider_name", sa.String(100), nullable=True),   # spider de origen
        sa.Column("fuente_url", sa.String(2048), nullable=True),   # URL fuente
        # Timestamps
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
    )

    # Índices para búsqueda y dedup
    op.create_index("ix_personas_cedula",  "personas", ["cedula"])
    op.create_index("ix_personas_nombre",  "personas", ["nombre"])
    op.create_index("ix_personas_hospital", "personas", ["hospital"])
    op.create_index("ix_personas_tipo_reporte", "personas", ["tipo_reporte"])


def downgrade() -> None:
    op.drop_table("personas")
