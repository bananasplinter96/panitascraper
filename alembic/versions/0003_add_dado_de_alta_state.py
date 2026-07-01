"""add dado_de_alta state and clean bad data

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-30
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Reclasificar registros que estaban mezclados en "ingresado" pero son altas/localizados
    op.execute("""
        UPDATE personas
        SET tipo_reporte = 'dado_de_alta'
        WHERE tipo_reporte = 'ingresado'
          AND (
            estado ILIKE '%alta%'
            OR estado ILIKE '%egresado%'
            OR estado ILIKE '%localizado%'
            OR estado ILIKE '%encontrado%'
            OR estado ILIKE '%aparecido%'
            OR estado ILIKE '%reunited%'
            OR estado ILIKE '%discharged%'
          )
    """)

    # Limpiar nombres que son solo números o caracteres no alfabéticos
    op.execute("""
        UPDATE personas
        SET nombre = NULL
        WHERE nombre ~ '^\\d+$'
           OR nombre ~ '^[-/\\\\_.,:;\\s]+$'
           OR LENGTH(TRIM(nombre)) < 2
    """)

    # Limpiar cédulas con formato inválido
    op.execute("""
        UPDATE personas
        SET cedula = NULL
        WHERE cedula !~ '^\\d{6,9}$'
    """)

    # Eliminar filas completamente sin identificación
    op.execute("""
        DELETE FROM personas
        WHERE (nombre IS NULL OR TRIM(nombre) = '')
          AND (cedula IS NULL OR TRIM(cedula) = '')
    """)


def downgrade() -> None:
    # Revertir dado_de_alta a ingresado (no se puede recuperar datos borrados)
    op.execute("""
        UPDATE personas SET tipo_reporte = 'ingresado'
        WHERE tipo_reporte = 'dado_de_alta'
    """)
