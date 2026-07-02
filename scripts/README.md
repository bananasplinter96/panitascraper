# Pipeline de depuración de datos de `personas`

Índice maestro de todo lo construido para importar, validar y limpiar la
tabla `personas` (la base de datos real detrás de panitasmap.org,
`panitasmap-db-1`). Cada script documenta su propio propósito en su
docstring — esto es el mapa de cómo encajan entre sí y en qué orden
correrlos.

## Regla de seguridad general

**Todo lo que es "reporte" es de solo lectura.** No modifica la base de
datos, solo imprime hallazgos. Los que sí modifican datos lo indican
explícitamente y casi todos requieren `--apply` (por defecto corren en
modo reporte/dry-run). Nada borra filas de producción sin que un humano
lo decida explícitamente después de ver un reporte.

## 1. Esquema y estados

| Archivo | Qué hace |
|---|---|
| `alembic/versions/0002_create_personas_table.py` | Crea la tabla `personas` (columnas base). |
| `alembic/versions/0003_add_dado_de_alta_state.py` | Agrega el estado `dado_de_alta` (antes mezclado con `ingresado`) y limpia nombres basura conocidos. |
| `alembic/versions/0004_add_missing_persona_columns.py` | Agrega columnas que ya existían en producción pero no en el esquema local (sexo, foto_url, cama_sala, etc.) — para que ambos entornos coincidan. |
| `alembic/versions/0005_add_cedula_validation_columns.py` | Agrega `cedula_validacion`, `cedula_nombre_oficial`, `cedula_similitud`. |
| `panitascraper/pipelines/transform.py` (función `puede_actualizar_estado`) | **Matriz de transición de estado** — bloquea downgrades inválidos: `fallecido` nunca se toca, nunca se regresa a `desaparecido` desde `ingresado`/`dado_de_alta`. Se aplica en el pipeline general de todos los spiders Y en `import_csv_manual.py`. |

Los 4 estados válidos de `tipo_reporte`: `ingresado` | `dado_de_alta` | `fallecido` | `desaparecido`.

## 2. Importación manual de datos (CSV/PDF)

| Archivo | Qué hace |
|---|---|
| `scripts/import_csv_manual.py` | Importa listas de sobrevivientes/ingresados transcritas de PDFs (ej. La Guaira, Hospital Ciudad Caribia). Dedup por id→cédula→nombre+hospital→nombre solo, respetando la matriz de estado. **Modifica la base de datos.** |
| `scripts/la_guaira_raw.txt` | Datos crudos parseados del PDF "Lista Unificada de Sobrevivientes La Guaira". |
| `scripts/preview_import_conflicts.py` | Vista previa de solo lectura — muestra qué del import ya existe en producción con otro estado, ANTES de correr el import real. Correr siempre primero. |

## 3. Validación de cédula contra padrón externo

Ver también `scripts/README_validacion_cedulas.md` (detalle específico de este subsistema).

| Archivo | Qué hace |
|---|---|
| `scripts/fonetica_es.py` | Motor de comparación fonética en español (normalización, códigos fonéticos, `comparar()`). Lo usan casi todos los demás scripts. |
| `scripts/scrape_target_cedulas.py` | Consulta el padrón (dateas.com → armandodata.com → cedula.com.ve) SOLO para las cédulas que ya existen en `personas` (no el rango completo V-1..30M). Guarda en `panitascraper/spiders/datos/personas.db` (SQLite). Normaliza cualquier formato de cédula (V-, puntos, guiones) antes de consultar. |
| `scripts/validate_cedulas.py` | Cruza `personas` contra ese SQLite y marca `cedula_validacion`. **Modifica la base de datos** (solo esas 3 columnas, nunca borra ni cambia otros campos). |

## 4. Reportes de calidad de datos (solo lectura)

| Archivo | Qué verifica |
|---|---|
| `scripts/data_quality_report.py` | Enfocado en `nombre` y duplicados: consonantes seguidas, registros sin contexto, variantes de hospital, duplicados fonéticos (bloqueo de 2 niveles, cobertura completa), dígitos embebidos, nombres muy largos, placeholders genéricos, nombre = hospital/ciudad. |
| `scripts/field_integrity_report.py` | El resto de las columnas: edad inválida, sexo inválido, cédulas sospechosas (repetidas/secuenciales), misma cédula con nombres distintos, teléfonos inválidos, foto_url reutilizada, `tipo_reporte` vs `estado` inconsistente, encoding roto, filas 100% duplicadas. |
| `scripts/verify_block_coverage.py` | Diagnóstico del propio sistema de bloqueo fonético — mide cuánta cobertura real tiene el análisis de duplicados. |

## 5. Reparación de corrupción específica (semi-automática)

| Archivo | Qué hace |
|---|---|
| `scripts/fix_multipart_corruption.py` | Repara filas donde `nombre` quedó con el cuerpo crudo de un request `multipart/form-data` (bug de la API externa `encuentralos.tecnosoft.dev`). Extrae los campos reales si el blob los tiene. Modo reporte por defecto, `--apply` para aplicar. |
| `scripts/fix_name_variants.py` | Clasifica nombres con `/` en 3 grupos: `variantes_ocr` (se repara automático con `--apply`), `notas_administrativas` y `mensaje_multiple` (nunca se tocan, requieren revisión manual). |

## Orden recomendado de ejecución

```bash
# 0. Migraciones (una sola vez por entorno)
alembic upgrade head

# 1. Vista previa + import manual (si hay CSVs pendientes)
python scripts/preview_import_conflicts.py
python scripts/import_csv_manual.py

# 2. Reportes de calidad — solo lectura, correr cuantas veces se quiera
python scripts/data_quality_report.py
python scripts/field_integrity_report.py
python scripts/verify_block_coverage.py    # si hay dudas de cobertura

# 3. Reparaciones puntuales (revisar reporte antes de --apply)
python scripts/fix_multipart_corruption.py            # reporte
python scripts/fix_multipart_corruption.py --apply     # aplicar recuperables
python scripts/fix_name_variants.py                    # reporte
python scripts/fix_name_variants.py --apply            # aplicar variantes_ocr

# 4. Validación de cédula contra padrón externo (tarda horas — usar screen/nohup)
python scripts/scrape_target_cedulas.py --resume
python scripts/validate_cedulas.py
```

## Cómo correr esto — local vs producción

**Local** (`docker-compose.yml`, DB en `localhost:5433`):
```powershell
.venv\Scripts\Activate.ps1
docker compose up -d db
$env:DATABASE_URL="postgresql://<user>:<pass>@localhost:5433/panitasmap"
python scripts/<script>.py
```

**Producción** (VM, `panitasmap-db-1` publica el puerto 5432 en el host):
```bash
ssh ubuntu@<IP_VM>
cd ~/mapa-web/panitascraper
git pull origin main
export DATABASE_URL=postgresql://panitas:<password_real>@localhost:5432/panitasmap
uv run python scripts/<script>.py
```

La contraseña real de producción está en `docker exec panitasmap-db-1 env | grep POSTGRES_PASSWORD` (no la memorices/hardcodees en ningún script — todos estos scripts requieren `DATABASE_URL` explícito, fallan si no está seteado).

Para procesos largos (scraping de cédulas, reportes sobre 200k+ filas), usar `screen`:
```bash
screen -S nombre_sesion
# ... correr el comando ...
# Ctrl+A luego D para salir sin matar el proceso
screen -r nombre_sesion   # volver a verlo
```
