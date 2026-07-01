# Validación de cédulas contra el padrón

Cruza `personas.cedula` + `personas.nombre` contra fuentes públicas del
padrón venezolano (dateas.com, armandodata.com, cedula.com.ve) para
detectar nombres asociados a una cédula que no coinciden con lo
reportado por el scraper. No borra ni oculta nada automáticamente —
solo marca cada registro para que el equipo lo revise.

## Por qué fonético y no solo texto exacto

Los reportes ciudadanos traen errores de transcripción, acentos
distintos, apellidos en otro orden, o apodos. Un match textual exacto
marcaría como "inválidos" muchísimos registros legítimos. Por eso se
usa el mismo principio que proyectos de matching post-desastre (IOM/PDNA
Haití): reducir el nombre a un código fonético que agrupa sonidos
equivalentes en español (`b`/`v`, `s`/`z`/`c`, `y`/`ll`, vocales sin
acento, letras repetidas) y comparar por esa vía además de por texto
exacto y por reordenamiento de tokens.

## Piezas

| Archivo | Qué hace |
|---|---|
| `alembic/versions/0005_add_cedula_validation_columns.py` | Agrega columnas `cedula_validacion`, `cedula_nombre_oficial`, `cedula_similitud` a `personas`. |
| `scripts/fonetica_es.py` | Normalización y comparación fonética de nombres en español. Sin dependencias externas. |
| `scripts/scrape_target_cedulas.py` | Consulta el padrón **solo** para las cédulas que ya existen en `personas` (no todo el rango V-1..30M). Guarda en `panitascraper/spiders/datos/personas.db` (SQLite). |
| `scripts/validate_cedulas.py` | Cruza `personas` contra ese SQLite y actualiza las columnas de validación. |

## Por qué scraping dirigido y no el padrón completo

`scraper_dateas.py`, `scraper_armando.py` y `scraper_cedula_ve.py` (en
`panitascraper/spiders/`) están diseñados para recorrer todo el rango
V-1 a V-30,000,000 — a ~1s por consulta eso son meses de scraping
continuo. No tiene sentido construir el padrón completo solo para
validar los pocos miles de cédulas que tenemos. `scrape_target_cedulas.py`
reutiliza la misma lógica de consulta (de `buscar_cedula.py`) pero solo
para las cédulas que ya están en nuestra base, y escribe al mismo
esquema SQLite — así que si en el futuro se decide correr el scraping
completo, ambos conviven sin conflicto (mismo `PRIMARY KEY cedula`).

## Valores de `cedula_validacion`

- `exacta` — nombre idéntico tras normalizar (mayúsculas, sin acentos).
- `exacta_reordenada` — mismas palabras, distinto orden (ej. apellido antes que nombre).
- `fonetica` — no coincide letra por letra pero sí fonéticamente (score ≥ 0.82) — candidato a variante de transcripción, no necesariamente error.
- `no_coincide` — score bajo — revisar manualmente, puede ser error de digitación, nombre de casada, cédula incorrecta, o coincidencia legítima que el algoritmo no captó.
- `sin_registro` — la cédula no está en el padrón local todavía (falta correr `scrape_target_cedulas.py` para esa cédula, o el padrón no tiene ese registro).

`cedula_similitud` guarda el score 0.0–1.0 usado para decidir la categoría, útil para ajustar el umbral (`0.82` en `fonetica_es.comparar`) si se ve mucho falso positivo/negativo.

## Cómo correrlo

```powershell
# 1. Aplicar migración (una sola vez)
.venv\Scripts\Activate.ps1
docker compose up -d db
$env:DATABASE_URL="postgresql://panitas:panitas@localhost:5433/panitasmap"
alembic upgrade head

# 2. Probar con pocas cédulas
python scripts/scrape_target_cedulas.py --limit 20

# 3. Correr contra todas las cédulas (usa --resume para no repetir)
python scripts/scrape_target_cedulas.py --resume

# 4. Validar y marcar en Postgres
python scripts/validate_cedulas.py
```

### En producción (VM)

```bash
# 1. Copiar los archivos nuevos a la VM
scp scripts/import_csv_manual.py scripts/la_guaira_raw.txt \
    scripts/fonetica_es.py scripts/scrape_target_cedulas.py scripts/validate_cedulas.py \
    ubuntu@<IP_VM>:~/panitascraper/scripts/
scp alembic/versions/0004_add_missing_persona_columns.py \
    alembic/versions/0005_add_cedula_validation_columns.py \
    ubuntu@<IP_VM>:~/panitascraper/alembic/versions/

# 2. En la VM: aplicar migraciones
ssh ubuntu@<IP_VM>
cd ~/panitascraper
source .venv/bin/activate
export DATABASE_URL=postgresql://panitas:panitas@localhost:5432/panitasmap  # ajustar host/puerto real
alembic upgrade head

# 3. Scraping dirigido — en producción hay miles de cédulas (no 18 como en el
#    test local), a 1.2s cada una puede tardar horas. Correr en background:
nohup python scripts/scrape_target_cedulas.py --resume > scrape.log 2>&1 &

# 4. Validar (una vez termine el paso 3)
python scripts/validate_cedulas.py
```

## Qué base de datos se toca

- **Se modifica**: `panitasmap-db-1` (la base de producción de la web), tabla `personas`. Solo se agregan/actualizan las 3 columnas nuevas (`cedula_validacion`, `cedula_nombre_oficial`, `cedula_similitud`). **No se toca `nombre`, `cedula`, `tipo_reporte` ni ninguna otra columna existente, y no se borra ni una fila.**
- **Se crea aparte**: `panitascraper/spiders/datos/personas.db` (SQLite nuevo, en la VM) — es el padrón de referencia descargado de dateas.com/armandodata.com. No lo usa la web, solo lo usan estos scripts.
- **No se toca**: `panitascraper-db-1` (la base del scraper original) ni MinIO.

## Cómo se ve esto reflejado en el sitio web

**Por ahora, en nada.** El plan que se acordó (ver historial de decisión) fue "solo marcar para revisión", no ocultar ni filtrar nada del sitio público. Las columnas nuevas quedan en la base de datos pero:

- El backend (`app/routers/personas.py`, `app/schemas/persona.py`) no las expone en la API todavía.
- El frontend no las lee ni las muestra.
- Los filtros de estado (`ingresado`/`dado_de_alta`/`fallecido`/`desaparecido`) siguen funcionando exactamente igual que antes.

Es decir: esto es puramente un proceso de auditoría interna por ahora. Si más adelante se quiere que el equipo revise los `no_coincide` desde una pantalla (en vez de SQL directo), o que el sitio muestre un aviso tipo "cédula no verificada" en el detalle de la persona, eso requiere un cambio adicional en el backend/frontend que no se ha hecho — avísame si lo quieres y lo diseñamos.

## Revisar resultados en SQL

```sql
SELECT cedula_validacion, COUNT(*) FROM personas GROUP BY cedula_validacion;

-- Ver los casos dudosos
SELECT nombre, cedula, cedula_nombre_oficial, cedula_similitud
FROM personas
WHERE cedula_validacion = 'no_coincide'
ORDER BY cedula_similitud DESC;
```
