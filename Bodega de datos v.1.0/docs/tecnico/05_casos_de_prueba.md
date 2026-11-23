# 05. Casos de prueba

Resumen de las pruebas automáticas del proyecto: qué cubre cada grupo y cómo se ejecuta. Todas usan datos inventados; ninguna lee datos de pacientes. La explicación para el personal clínico, con la relación entre cada regla y sus casos, está en el manual [Casos de prueba](../clinico/06_casos_de_prueba.md).

## 1. Niveles y cantidad

Conteo al 2026-11-03: **738 pruebas**, todas en verde, con una cobertura de 96 % de las sentencias del paquete `etl`.

| Nivel | Marcador | Carpeta | Pruebas | Necesita base de datos |
|---|---|---|---|---|
| Unitarias | `unit` | `tests/etl_tests/` | 585 | No |
| Integración | `integration` | `tests/integration_tests/` | 84 | Sí |
| Calidad | `quality` | `tests/quality_tests/` | 54 | Sí |
| Aceptación | `acceptance` | `tests/acceptance_tests/` | 15 | Sí |

Una función de prueba con varios casos (parametrizada) cuenta como varias pruebas.

## 2. Grupos de casos

Cada caso tiene un identificador `TC-<grupo>-<número>`.

| Grupo | Qué valida | Casos | Ejemplos |
|---|---|---|---|
| `TC-EXT` Extracción | Lectura del Excel y de REDCap, extracción incremental, fábrica de extractores, que el extractor de REDCap no escriba en la fuente | 6 | El extractor falla con un archivo o una hoja inexistente; la extracción incremental sin cambios no escribe nada |
| `TC-TRF` Transformación | Cada regla del [catálogo de rangos y reglas](../clinico/04_catalogo_de_rangos_y_reglas.md): rangos duros y blandos, fechas, consistencia, etiquetas, CIE-10, seudonimización, duplicados y reportes | 42 | Un valor fuera del límite duro se borra y se cuenta; la seudonimización da el mismo código para el mismo documento |
| `TC-DDL` Esquema | Estructura de la base: tablas, claves sustitutas, unicidad, claves foráneas, permisos del usuario lector y esquema de control | 11 | Una fila hija con una clave inexistente se rechaza; el lector no puede modificar ni ver el texto libre |
| `TC-CAR` Carga | Carga en la bodega: idempotencia, cuarentena, balance de la bitácora, miembros por defecto, primera toma, puentes, carga incremental, calendario y candado | 30 | Cargar dos veces deja los mismos conteos; una fila con fecha fuera del calendario va a cuarentena |
| `TC-CAL` Calidad | Cada regla `QR-` del [catálogo de calidad](04_reglas_de_calidad.md) con un caso que cumple y uno con el defecto, y el reporte y el veredicto | 37 | Una clave huérfana hace fallar `QR-INT-01`; una regla que advierte deja el veredicto en "Aprobada con advertencias" |
| `TC-ACE` Aceptación | Indicadores de la bodega frente a un cálculo independiente en pandas sobre el mismo staging | 15 | Ver la sección 3 |

## 3. Indicadores de aceptación

| Caso | Indicador |
|---|---|
| TC-ACE-01 | Casos por mes de admisión y mecanismo |
| TC-ACE-02 | Porcentaje de casos por quinquenio de edad y género |
| TC-ACE-03 | Promedio de días de hospitalización y de UCI por mes de alta |
| TC-ACE-04 | Porcentaje de casos por disposición del paciente (incluida la muerte) |
| TC-ACE-05 | Diagnósticos CIE-10 más frecuentes |
| TC-ACE-06 | Casos por franja horaria de alta |
| TC-ACE-07 | Casos por rango de ISS (1–8, 9–15, 16–24 y 25 o más) |
| TC-ACE-08 | Pacientes críticos (Glasgow menor de 9, presión sistólica baja) |
| TC-ACE-09 | Mortalidad por rango de ISS y por mecanismo |
| TC-ACE-10 | Atenciones con UCI y con al menos un procedimiento |
| TC-ACE-11 | Atenciones por parte del cuerpo lesionada |
| TC-ACE-12 | Atenciones transfundidas y litros totales |
| TC-ACE-13 | Atenciones con al menos una imagen, por tipo |
| TC-ACE-14 | Prevalencia por sustancia de abuso |
| TC-ACE-15 | Promedio de días entre la admisión y el alta, por mes de admisión |

Tolerancia: 0 en conteos y 0,01 en promedios y porcentajes.

## 4. Cómo ejecutarlas

```bash
python -m pytest -m unit           # rápidas, sin base de datos (antes y después de cualquier cambio)
python -m pytest -m integration    # esquema y carga
python -m pytest -m quality        # reglas de calidad
python -m pytest -m acceptance     # indicadores
python -m pytest                   # todas
python -m pytest --cov=etl --cov-report=html   # con cobertura (queda en htmlcov/, que no se sube)
```

Las pruebas con base de datos necesitan la variable `DB_NAME_TEST` en `.env`, con un nombre terminado en `_test` y distinto de las bases de desarrollo y producción. Crean las tablas, las llenan con datos sintéticos y las borran al terminar. Si la variable falta o el nombre no termina en `_test`, se niegan a correr para no tocar una base real.

## 5. Al agregar o cambiar una prueba

- Ubíquela en la carpeta de su nivel, con el marcador que corresponda, y asígnele el identificador `TC-` de su grupo.
- Escriba el docstring en español con tres líneas: **Qué es** (tipo de prueba y componente), **Qué hace** (la acción) y **Esperado** (el resultado que la aprueba).
- Organice el cuerpo en tres bloques comentados: preparar (*Arrange*), ejecutar (*Act*) y comprobar (*Assert*).
- Use solo datos inventados, creados dentro de la prueba o en un *fixture*.
- Si cambió una regla, la prueba debe describir el comportamiento nuevo, no el anterior.

Los criterios con los que se acepta el prototipo (pruebas al 100 % en verde, cada regla con al menos dos pruebas, tolerancias) están en el manual [Calidad y veredicto](../clinico/03_calidad_y_veredicto.md), sección 5.
