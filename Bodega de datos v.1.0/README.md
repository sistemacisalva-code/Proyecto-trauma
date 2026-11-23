# TG_CDW — Bodega de Datos (OLAP) para el Área de Trauma

Prototipo de bodega de datos dimensional para apoyar la toma de decisiones clínicas y administrativas en el servicio de trauma de un hospital de alta complejidad de Cali, Colombia.

> **Naturaleza del sistema:** analítico (OLAP), no transaccional. No registra atenciones; consolida información histórica para su análisis en Power BI.

---

## Tabla de contenido

1. [Aviso de privacidad y confidencialidad](#1-aviso-de-privacidad-y-confidencialidad)
2. [Arquitectura](#2-arquitectura)
3. [Stack tecnológico](#3-stack-tecnológico)
4. [Estructura del repositorio](#4-estructura-del-repositorio)
5. [Requisitos previos](#5-requisitos-previos)
6. [Instalación y configuración](#6-instalación-y-configuración)
7. [Comandos de uso](#7-comandos-de-uso)
8. [Pruebas](#8-pruebas)
9. [Modelo dimensional](#9-modelo-dimensional)
10. [Calidad de datos](#10-calidad-de-datos)
11. [Visualización en Power BI](#11-visualización-en-power-bi)
12. [Estado del proyecto](#12-estado-del-proyecto)
13. [Flujo de trabajo con Git](#13-flujo-de-trabajo-con-git)

---

## 1. Aviso de privacidad y confidencialidad

| Elemento | Regla |
|---|---|
| Datos clínicos reales (historias clínicas, nombres, documentos de identidad) | **Nunca** se versionan ni se usan en pruebas. La carpeta `data/` está excluida en `.gitignore`. |
| Archivos de origen (Excel del registro y exportaciones de REDCap) | Permanecen únicamente en el equipo autorizado, en `data/source_files/` (ignorada por Git). |
| Documento de identidad | La transformación lo seudonimiza con un HMAC cuya clave (`PSEUDONYMIZATION_KEY`) vive solo en el `.env` local. La bodega no guarda el documento original. |
| Credenciales de base de datos | Se definen en un archivo `.env` local, **ignorado por Git**. Solo se versiona la plantilla `.env.example`, con marcadores vacíos. |
| Tokens de la API de REDCap | No se almacenan en el repositorio. |
| Listas de valores permitidos | `config/valores_permitidos.yaml` sale de los valores del staging real y está en `.gitignore`; solo se versiona la plantilla `config/valores_permitidos.example.yaml`. |
| Reportes de Power BI | Un `.pbix` o un proyecto `.pbip` actualizado guarda los datos importados: **nunca** se versionan (`.gitignore` los excluye). |
| Reportes de calidad y cuarentena | Contienen solo conteos o filas apartadas; quedan en `data/` (ignorada por Git). El rol lector de Power BI no tiene acceso a la cuarentena. |
| Pruebas automatizadas | Utilizan exclusivamente esquemas estructurales y datos **sintéticos** generados artificialmente. |
| Nombre de la institución | No se menciona; el proyecto se refiere a "un hospital de alta complejidad de Cali". |

**Antes de cada commit** verifique que no se incluyan archivos `.env`, `.xlsx`, `.parquet`, `.csv` con datos reales, `.pbix`/`.pbip` ni capturas que muestren información de pacientes.

---

## 2. Arquitectura

Arquitectura por capas:

```text
Fuente de datos ──► Extracción ──► Transformación ──► Carga ──────────► Data Warehouse ──► Power BI
(Excel histórico,    (raw:           (staging:          (contrato por     (PostgreSQL,        (rol lector,
 REDCap)              Parquet)        Parquet +          modelo,           esquema estrella,   solo lectura)
                                      manifiesto)        incremental)      etl_control)
                                                              │
                                                              └──► Calidad (31 reglas QR-*, veredicto)
```

- **Extracción:** patrón *Strategy* + *Factory* (`BaseExtractor`, `ExcelExtractor`, `REDCapExtractor`, `ExtractorFactory`). Cada hoja del Excel histórico y cada extracción de REDCap se persiste en Parquet en `data/raw/`, particionada por fecha (y hora, en REDCap) de carga.
- **REDCap (solo lectura):** `REDCapExtractor` usa PyCap y solo invoca operaciones de exportación (`export_records`). El control definitivo es el token, que debe configurarse en REDCap con permiso de solo lectura (API Export únicamente).
- **Transformación:** un transformador por fuente (`etl/transform/excel/` y `etl/transform/redcap/`) con reglas comunes (`etl/transform/common/`): renombres semánticos, tipos, rangos clínicos, cronología de la estancia, mapeo a CIE-10, etiquetas unificadas entre las dos fuentes y seudonimización. Cada regla invalida, corrige, reporta o detiene, y toda corrección queda contada en el reporte de la transformación. El resultado es un **staging** en Parquet por fuente (`data/staging/<fuente>/`) con un `manifiesto.json` que identifica la corrida (`run_id`) y las filas de cada tabla.
- **Carga:** guiada por un **contrato** por modelo (`config/contratos/completo.yaml`) que declara de qué tabla y columna del staging sale cada columna de la bodega. La carga es incremental: calcula una huella (SHA-256) por atención y solo escribe las que cambiaron (`--full-refresh` las reescribe todas). Las filas que no pueden entrar se apartan a **cuarentena** (`data/quarantine/`) con la regla que incumplieron. Toda la carga de una fuente ocurre en una sola transacción.
- **Control del ETL:** el esquema `etl_control` registra las extracciones, las cargas (con su balance por tabla) y los veredictos de calidad. La carga histórica de Excel usa una guardia de idempotencia (de una sola vez); la extracción de REDCap usa la última corrida exitosa como ventana incremental.
- **Calidad:** después de cargar, se verifica la bodega con 31 reglas (sección 10) y se emite un veredicto.
- **Data Warehouse:** PostgreSQL, esquema `trauma_completo` en estrella (sección 9).
- **Seguridad:** separación de roles — un rol de aplicación (dueño de los objetos, ejecuta el ETL) y un rol lector de solo lectura para Power BI.

---

## 3. Stack tecnológico

| Componente | Uso | Versión validada |
|---|---|---|
| Python 3 | Lenguaje del ETL | — |
| pandas | Transformación | 3.0.5 |
| pyarrow | Parquet (raw y staging) | 25.0.1 |
| python-calamine, openpyxl | Lectura del Excel | 0.8.2, 3.1.5 |
| PyCap, requests | Extracción de solo lectura desde la API de REDCap | 2.7.0, 2.34.2 |
| SQLAlchemy, psycopg2-binary | Acceso a PostgreSQL | 2.0.52, 2.9.13 |
| PyYAML, pyyaml-env-tag, python-dotenv | Configuración por entorno y contratos | 6.0.3, 1.1, 1.2.3 |
| holidays | Festivos de Colombia en `dim_tiempo` | 0.57 (fijada) |
| pytest, pytest-cov | Pruebas y cobertura | 9.1.1, 7.1.0 |
| PostgreSQL | Data Warehouse | 17.4 |
| Power BI Desktop | Visualización | — |
| Git, Markdown | Control de versiones y documentación | — |

La columna "Versión validada" indica con qué versiones pasó la suite completa de pruebas. `requirements.txt` declara versiones mínimas; para reproducir el entorno exacto, instale las versiones de esta tabla.

---

## 4. Estructura del repositorio

```text
TG_CDW/
├── main.py                       # Bootstrap: roles, base de datos, DDL y permisos
├── config/
│   ├── database.yaml             # Configuración por entorno (usa variables ${...})
│   ├── settings.py               # Rutas, hojas del Excel y carga del .env
│   ├── contratos/                # Contrato de carga del modelo (staging -> bodega)
│   ├── catalogos/                # Catálogos de apoyo a la transformación (CIE-10, lugar del evento, sustancias)
│   ├── renombres_columnas_*.yaml # Renombres semánticos de columnas por fuente
│   └── valores_permitidos.example.yaml  # Plantilla de las listas de QR-DOM-04
├── database/
│   ├── schema/                   # DDL numerado: roles/BD, control ETL, tablas, índices, permisos
│   └── seeds/                    # Datos semilla (catálogo CIE-10)
├── etl/
│   ├── extract/                  # Extractores (Excel, REDCap) y fábrica
│   ├── transform/                # Transformadores por fuente (excel/, redcap/) y reglas comunes (common/)
│   ├── load/                     # Escritura de Parquet y staging
│   │   └── warehouse/            # Carga a la bodega: contrato, resolución, calendario, cuarentena
│   ├── quality/                  # Reglas de calidad de la bodega cargada y reporte
│   └── pipeline.py               # Punto de entrada del ETL (--mode)
├── tests/
│   ├── etl_tests/                # Unitarias (sin base de datos)
│   ├── integration_tests/        # Requieren PostgreSQL (DDL, carga, permisos, control ETL)
│   ├── quality_tests/            # Reglas de calidad sobre una bodega sintética
│   ├── acceptance_tests/         # Indicadores de la bodega frente a un cálculo independiente
│   └── fixtures/                 # Generador de staging sintético
├── analytics/
│   ├── dashboards/powerbi/       # Generador del proyecto de Power BI y medidas DAX
│   └── queries/                  # Consultas de conexión de Power BI y conteos por dominio
├── data/                         # (ignorada por Git) source_files/, raw/, staging/, quarantine/, quality_reports/
├── .env.example                  # Plantilla de variables de entorno
├── pytest.ini                    # Configuración y marcadores de pytest
└── requirements.txt
```

---

## 5. Requisitos previos

- Python 3.10 o superior.
- PostgreSQL instalado y en ejecución (validado con la 17.4).
- Un rol de PostgreSQL con permisos `CREATEDB` y `CREATEROLE` (solo para el bootstrap).
- Power BI Desktop (solo para la visualización).
- Git.

---

## 6. Instalación y configuración

**Windows (PowerShell):**

```powershell
git clone <URL-DEL-REPOSITORIO>
cd TG_CDW

python -m venv venv
.\venv\Scripts\Activate.ps1

pip install -r requirements.txt

Copy-Item .env.example .env
```

**Linux / macOS:**

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Luego edite el archivo `.env` local y complete las variables. Descripción de cada grupo (los valores **no** se documentan aquí):

| Variable | Descripción |
|---|---|
| `DB_ADMIN_USER`, `DB_ADMIN_PASSWORD` | Administrador de PostgreSQL, solo para el bootstrap |
| `APP_ENV` | `development` o `production` |
| `DB_HOST`, `DB_PORT`, `DB_NAME_DEV`, `DB_USER_DEV`, `DB_PASSWORD` | Conexión de la aplicación en desarrollo |
| `DB_READER_USER`, `DB_READER_PASSWORD` | Rol lector de solo lectura (Power BI) |
| `*_PROD` | Equivalentes para producción |
| `DB_NAME_TEST` | Base de pruebas; debe terminar en `_test` |
| `REDCAP_API_URL`, `REDCAP_API_TOKEN` | API de REDCap. El token debe configurarse en REDCap con permiso de **solo lectura** (API Export únicamente, sin Import/Update ni Delete) |
| `PSEUDONYMIZATION_KEY` | Clave del HMAC con que la transformación seudonimiza el documento de identidad. Si cambia, cambian los seudónimos: consérvela fuera del repositorio |

> Evite los caracteres `@ : /` en las contraseñas: `main.py` arma la URL de conexión sin codificarla.

Coloque el Excel histórico (obtenido por los canales autorizados) en `data/source_files/`. La ruta esperada está en `EXCEL_SOURCE_PATH` de [config/settings.py](config/settings.py).

Las variables a exportar de REDCap se configuran en `REDCAP_EXPORT_CONFIG` de [config/settings.py](config/settings.py).

### Listas de valores permitidos (opcional)

La regla QR-DOM-04 compara cada atributo categórico de las dimensiones con una lista aprobada. Para activarla, copie la plantilla y complete las listas con quien conozca el dominio clínico:

```powershell
Copy-Item config/valores_permitidos.example.yaml config/valores_permitidos.yaml
```

Si el archivo no existe, la regla no se evalúa y el log lo indica. Los valores deben ir entre comillas dobles (YAML lee `No` sin comillas como booleano).

---

## 7. Comandos de uso

Ejecute todos los comandos desde la raíz del proyecto con el entorno virtual activo.

### 7.1 Inicializar la bodega de datos

Crea roles, la base de datos del entorno activo, el esquema de control del ETL, el modelo dimensional (tablas e índices) y los permisos del rol lector. Es idempotente.

```bash
python main.py
```

### 7.2 ETL completo

Ejecuta en orden la extracción, la transformación y la carga de las dos fuentes, y al final el reporte de calidad. Un candado impide dos ejecuciones simultáneas.

```bash
python -m etl.pipeline --mode=all
```

| Opción | Efecto |
|---|---|
| `--sin-excel` | No incluye el Excel histórico aunque esté pendiente |
| `--sin-extraccion` | No extrae; usa la capa raw que ya hay en disco (por ejemplo, sin red) |

Termina con código de salida **2** si el veredicto de calidad es "Rechazada", para que un programador de tareas lo detecte.

### 7.3 Pasos individuales

**Extracción histórica desde Excel** (de una sola vez; `--force` la repite de forma deliberada):

```bash
python -m etl.pipeline --mode=excel-registro-antiguo
```

**Extracción desde REDCap** (solo lectura, incremental desde la última corrida exitosa):

```bash
python -m etl.pipeline --mode=redcap
```

> Antes del primer uso: fijar `expected_n_columns` en `REDCAP_EXPORT_CONFIG` con el número de columnas observado en la primera corrida, y confirmar en REDCap que el token tiene permiso de solo lectura.

**Transformación hacia staging** (reemplaza el staging de la fuente y escribe el reporte de la transformación):

```bash
python -m etl.pipeline --mode=transform-excel
python -m etl.pipeline --mode=transform-redcap
```

**Carga a la bodega** (exige modelo y fuente):

```bash
python -m etl.pipeline --mode=load --modelo completo --fuente excel
python -m etl.pipeline --mode=load --modelo completo --fuente redcap
```

| Opción | Efecto |
|---|---|
| `--full-refresh` | Reescribe todas las atenciones de la fuente, no solo las que cambiaron |
| `--force` | Solo para el Excel: el histórico se carga una vez por modelo; `--force` lo vuelve a cargar si cambió su staging |

**Reporte de calidad de la bodega cargada:**

```bash
python -m etl.quality --modelo completo
```

Escribe el reporte (Markdown y CSV, solo conteos) en `data/quality_reports/` y registra el veredicto en `etl_control.calidad`. Termina con código 2 si el veredicto es "Rechazada".

### 7.4 Ayuda del pipeline

```bash
python -m etl.pipeline --help
```

### 7.5 Cambiar de entorno

```powershell
# PowerShell
$env:APP_ENV = "production"
```

```bash
# Bash
export APP_ENV=production
```

### 7.6 Comandos útiles de PostgreSQL (opcional)

```bash
# Listar esquemas de la bodega
psql -h <HOST> -U <USUARIO> -d <BASE_DE_DATOS> -c "\dn"

# Ver las extracciones, las cargas y los veredictos de calidad
psql -h <HOST> -U <USUARIO> -d <BASE_DE_DATOS> -c "SELECT * FROM etl_control.extraccion;"
psql -h <HOST> -U <USUARIO> -d <BASE_DE_DATOS> -c "SELECT * FROM etl_control.carga ORDER BY id DESC;"
psql -h <HOST> -U <USUARIO> -d <BASE_DE_DATOS> -c "SELECT * FROM etl_control.calidad ORDER BY id DESC;"
```

---

## 8. Pruebas

La suite tiene 738 pruebas, todas en verde en la última corrida completa. Se clasifican con marcadores de pytest (definidos en [pytest.ini](pytest.ini)):

| Marcador | Carpeta | Requiere PostgreSQL | Pruebas | Descripción |
|---|---|:-:|:-:|---|
| `unit` | `tests/etl_tests/` | No | 585 | Extractores, transformadores, contrato, resolución de la carga, reglas de calidad y pipeline (con dobles) |
| `integration` | `tests/integration_tests/` | Sí | 84 | DDL, claves, integridad referencial, carga incremental, atomicidad, control ETL y permisos |
| `quality` | `tests/quality_tests/` | Sí | 54 | Cada regla de calidad cumple sobre la bodega sintética y detecta el defecto inyectado |
| `acceptance` | `tests/acceptance_tests/` | Sí | 15 | Indicadores de la bodega frente a un cálculo independiente en pandas sobre el staging sintético |

Los marcadores se asignan automáticamente según la carpeta de la prueba. Cada prueba documenta qué es, qué hace y qué se espera, y sigue el patrón Arrange / Act / Assert.

**Ejecutar todas las pruebas:**

```bash
python -m pytest
```

**Solo las unitarias (rápidas, sin base de datos):**

```bash
python -m pytest -m unit
```

**Solo las que requieren PostgreSQL:**

```bash
python -m pytest tests/integration_tests tests/quality_tests tests/acceptance_tests
```

**Salida detallada / un archivo / una prueba concreta:**

```bash
python -m pytest -v
python -m pytest tests/etl_tests/test_pipeline_excel.py
python -m pytest tests/etl_tests/test_pipeline_excel.py::<nombre_de_la_prueba>
python -m pytest -k "excel"
```

**Detenerse en el primer fallo y mostrar la salida impresa:**

```bash
python -m pytest -x -s
```

**Listar las pruebas sin ejecutarlas:**

```bash
python -m pytest --collect-only -q
```

**Cobertura del código del ETL** (el informe HTML queda en `htmlcov/`, ignorada por Git):

```bash
python -m pytest --cov=etl --cov-report=term-missing --cov-report=html
```

### Precauciones con las pruebas que usan PostgreSQL

- Requieren `DB_NAME_TEST` definido en `.env`.
- **Crean y eliminan** esa base de datos en cada corrida. Por seguridad, el nombre debe terminar en `_test` y ser distinto de las bases de desarrollo y producción; de lo contrario, las pruebas abortan.
- Usan únicamente datos sintéticos o estructura; nunca datos reales.

---

## 9. Modelo dimensional

Esquema en estrella (`trauma_completo`) con claves sustitutas, dimensiones independientes y una tabla de hechos central con una fila por atención.

| Elemento | Tablas |
|---|---|
| Hecho | `fact_trauma`: medidas de la primera toma de signos vitales, gases arteriales, severidad (ISS y regiones), estancia y recursos |
| Dimensiones | Paciente, evento de trauma, caída, quemadura, accidente de tránsito, armas, desenlace, calificador de signos vitales e imagen |
| Tiempo | `dim_tiempo` (calendario con festivos de Colombia) y `dim_horario` (hora y minuto), generadas por la carga |
| Catálogos | CIE-10, parte del cuerpo, tipo de lesión, mecanismo primario, sustancia y procedimiento |
| Puentes (muchos a muchos) | Lesiones, imágenes, CIE-10 (diagnóstico, comorbilidad y mecanismos), complicaciones, sustancias y procedimientos |
| Control | `etl_control`: extracciones, cargas con su balance por tabla y veredictos de calidad |

Cuando el staging viene vacío, las dimensiones apuntan a miembros por defecto: `Sin dato` (no se registró) o `No aplica` (el mecanismo no ocurrió). El DDL está en `database/schema/` y el mapeo desde el staging, en [config/contratos/completo.yaml](config/contratos/completo.yaml).

---

## 10. Calidad de datos

La calidad se controla en dos momentos:

1. **En la transformación:** se evalúan y cuentan duplicados, nulos, inconsistencias de formato, tipos de datos y dominios clínicos (rangos, cronología de la estancia y CIE-10). Cada corrección queda en el reporte de la transformación.
2. **Sobre la bodega cargada:** 31 reglas `QR-<dimensión>-<n>`, organizadas según las dimensiones de calidad de ISO/IEC 25012 (con la unicidad de DAMA): integridad referencial, duplicados, exactitud contra el staging y la bitácora, completitud, validez de dominios, consistencia entre columnas, trazabilidad, seguridad y continuidad del calendario.

Cada regla tiene una acción:

| Acción | Significado | Efecto en el veredicto |
|---|---|---|
| Falla | Error de la carga o del modelo | "Rechazada" |
| Advierte | Defecto que viene de la fuente | "Aprobada con advertencias" |
| Informa | Dato descriptivo (por ejemplo, vacíos por columna) | Ninguno |

El reporte se escribe en `data/quality_reports/` (solo conteos, nunca valores) y su veredicto queda en `etl_control.calidad`.

---

## 11. Visualización en Power BI

Power BI se conecta a la bodega con el **rol lector** (solo lectura), en modo Importar.

- [analytics/queries/conexion_power_bi.sql](analytics/queries/conexion_power_bi.sql): una consulta por tabla, sin texto libre, sin la llave de negocio y sin las rutas de `etl_control`.
- [analytics/queries/conexion_power_bi_admin.sql](analytics/queries/conexion_power_bi_admin.sql): variante con el texto libre, solo para la copia del reporte de usuarios autorizados.
- [analytics/dashboards/powerbi/medidas_dax.md](analytics/dashboards/powerbi/medidas_dax.md): preparación del modelo y medidas DAX.

El proyecto de Power BI (PBIP) se genera sin datos, siempre en una carpeta **fuera del repositorio**:

```bash
python analytics/dashboards/powerbi/generar_pbip.py <carpeta_fuera_del_repositorio>
python analytics/dashboards/powerbi/generar_pbip.py <carpeta> --variante admin   # incluye el texto libre
python analytics/dashboards/powerbi/generar_pbip.py <carpeta> --sin-control      # sin la página de cargas
```

Luego se abre el `.pbip` en Power BI Desktop, se indican el servidor y la base en los parámetros, se escriben las credenciales del rol lector y se actualiza. Desde ese momento el proyecto contiene datos: no se copia al repositorio.

---

## 12. Estado del proyecto

| Componente | Estado |
|---|---|
| Bootstrap de roles, base de datos, DDL y permisos | Completo |
| Modelo dimensional `trauma_completo` | Completo y probado |
| Control del ETL e idempotencia | Completo |
| Extracción histórica desde Excel (capa raw) | Completo |
| Extracción desde REDCap (capa raw), incremental y de solo lectura | Completo |
| Transformación de las dos fuentes hacia staging | Completo |
| Carga incremental a la bodega con contrato, cuarentena y bitácora | Completo |
| Calidad de la bodega cargada (31 reglas y veredicto) | Completo; línea base "Aprobada con advertencias" (advertencias que vienen de la fuente) |
| Pruebas unitarias, de integración, de calidad y de aceptación | 738 pruebas en verde |
| Tablero de Power BI | En desarrollo: generador del proyecto, consultas y medidas listos; falta validar el tablero en Power BI Desktop |

---

## 13. Flujo de trabajo con Git

- Ramas: `main` (estable), `develop` (integración) y ramas `feature/*` por funcionalidad.
- Commits con prefijo convencional: `feat`, `test`, `docs`, `fix`, `refactor`, `chore`.
- Todo cambio es revisado por el autor antes de integrarse (*human-in-the-loop*).

```bash
git checkout develop
git checkout -b feature/<nombre-de-la-funcionalidad>
git add <archivos>
git commit -m "feat(etl): descripción breve"
```
