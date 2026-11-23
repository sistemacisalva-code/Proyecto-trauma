# 02. Dónde ajustar las reglas

Las solicitudes llegan normalmente del personal clínico (ver el manual [Calidad y veredicto](../clinico/03_calidad_y_veredicto.md), sección 6).

## Antes de cambiar cualquier regla

1. **Tenga la justificación por escrito:** quién lo pidió, qué valor y por qué (criterio clínico o literatura). Los límites nunca se fijan con el valor máximo que aparece en los datos.
2. **Cambie un solo archivo a la vez** y ejecute `python -m pytest -m unit`. Si una prueba falla por el cambio, actualícela solo si el nuevo comportamiento es el que se pidió.
3. **Vuelva a procesar:** transforme la fuente afectada, cárguela y revise la calidad ([Operar la aplicación](01_operar_la_aplicacion.md), sección 2). La carga detecta solas las atenciones que cambiaron.
4. **Deje registro** del cambio: fecha, solicitante, valor anterior y valor nuevo.

## 1. Rangos clínicos

Los valores vigentes de cada variable están en el manual [Catálogo de rangos y reglas](../clinico/04_catalogo_de_rangos_y_reglas.md).

| Qué ajustar | Archivo | Qué editar |
|---|---|---|
| Signos vitales y Glasgow | `etl/transform/common/signos_vitales.py` | `ESPECIFICACION_NUMERICA`: tipo, si es entero y `(mínimo, máximo)` |
| Duración de la pérdida de conciencia | El mismo archivo | `LIMITE_PERDIDA_CONCIENCIA_MIN` |
| AIS por región e ISS | `etl/transform/common/severidad.py` | `ESPECIFICACION_SEVERIDAD` |
| Líquidos | `etl/transform/common/liquidos.py` | `LIMITE_DURO_LITROS`, `LIMITE_BLANDO_LITROS` y `VOLUMEN_MINIMO_PLAUSIBLE_L` |
| Gases arteriales y laboratorio | `etl/transform/common/laboratorio.py` | `ESPECIFICACION_NUMERICA` y `RANGOS_PLAUSIBLES` |
| SCQ y altura de la caída | `etl/transform/common/mecanismo.py` | `ESPECIFICACION_NUMERICA` |
| Edad máxima | `etl/transform/common/demografia.py` | `EDAD_MAXIMA` |
| Duración máxima de un procedimiento | `etl/transform/common/procedimientos.py` | `LIMITE_DURACION_SEG` |
| Margen de la estancia | El mismo archivo | `MARGEN_ESTANCIA_HORAS` (hoy 0, por indicación del personal médico) |

**Ejemplo:** el equipo clínico pide subir el máximo de la frecuencia cardiaca de 300 a 320. En `signos_vitales.py`, la línea de `frecuencia_cardiaca` pasa de `(0, 300)` a `(0, 320)`.

La revisión de calidad de la bodega lee los mismos valores, así que el cambio se aplica en los dos lados sin editar nada más.

**Pasar un valor de borrarse a reportarse** (de límite duro a blando) no es un cambio de número, sino de tipo de regla: requiere un cambio de código y una prueba nueva. Pídalo como un desarrollo.

## 2. Etiquetas y textos

| Qué ajustar | Archivo |
|---|---|
| Etiquetas del Excel que se pasan a la escritura de REDCap (estado civil, seguro, caída, vehículo, muerte prevenible) | `etl/transform/excel/registro.py`, diccionarios `MAPEO_...` |
| Etiquetas de las hojas del Excel (parte del cuerpo en imágenes, pérdida de conciencia) | `etl/transform/excel/hojas.py`, diccionarios `MAPEO_...` |
| Nombres de las columnas de cada fuente | `config/renombres_columnas_excel.yaml` y `config/renombres_columnas_redcap.yaml` |

**Ejemplo (hipotético):** si el Excel trajera "Soltero" y REDCap "Soltero/a", se agregaría `"Soltero": "Soltero/a"` en `MAPEO_ESTADO_CIVIL`. Desde la siguiente transformación, el tablero mostraría una sola categoría y el reporte cuenta cuántas filas cambiaron.

## 3. Catálogos

| Catálogo | Archivo |
|---|---|
| Texto CIE-10 del Excel: errores ortográficos y equivalencias revisadas con las opciones de REDCap | `config/catalogos/cie10_excel.yaml` |
| Redacción única para los códigos que REDCap ofrece con dos redacciones del mismo diagnóstico | `config/catalogos/cie10_etiquetas_canonicas.yaml` |
| Clasificación del lugar del evento del Excel por palabras clave (el orden de las reglas es la prioridad) | `config/catalogos/lugar_del_evento.yaml` |
| Errores ortográficos evidentes en el texto de otras sustancias de abuso | `config/catalogos/sustancias_correcciones.yaml` |

Cada archivo explica su formato en los comentarios del inicio.

**Ejemplo:** un diagnóstico del Excel aparece como SIN CODIGO CIE-10 porque su texto no coincide con ninguna opción de REDCap. Después de revisarlo, se agrega la equivalencia (texto del Excel → opción de REDCap) en `cie10_excel.yaml`. En la siguiente transformación, esas atenciones quedan con el código.

## 4. Valores permitidos de las descripciones (regla de validez)

`config/valores_permitidos.yaml` define, para cada descripción (por ejemplo, el estado civil del paciente), la lista de valores aprobados. La revisión de calidad advierte cuando aparece un valor que no está en la lista.

- Si el archivo no existe, esa regla no se evalúa. Para crearlo, copie `config/valores_permitidos.example.yaml`.
- Escriba los valores entre comillas dobles: sin comillas, `No` se lee como falso y `10` como número, y la aplicación rechaza el archivo.
- "Sin dato" y "No aplica" no se escriben: se aceptan siempre.
- La lista **no se actualiza sola**, a propósito: si incluyera todo lo que llega, la regla nunca avisaría de nada. Un valor nuevo se agrega solo después de confirmar que es válido.
- El archivo no se sube al repositorio, porque sale de los valores reales.

## 5. Acción de una regla de calidad

`etl/quality/reporte.py`, diccionario `ACCIONES`. Las reglas que aparecen allí advierten o informan; las demás fallan.

**Ejemplo:** se decide que los días de UCI mayores que los de hospitalización no deben cambiar el veredicto. La regla `QR-CON-06` pasa de "Advierte" a "Informa" en `ACCIONES`.

Cambiar la acción cambia el veredicto. Hágalo solo con una decisión explícita y registrada.

## 6. Qué viaja de la fuente a la bodega

`config/contratos/completo.yaml` dice de qué columna de la fuente transformada sale cada columna de la bodega. Se edita cuando una fuente cambia el nombre de una variable o cuando se quiere llevar una variable nueva al tablero. Llevar una variable nueva suele requerir también un cambio en la estructura de la base; trátelo como un desarrollo, no como un ajuste.

## 7. Calendario

`etl/load/warehouse/calendario.py`: `FECHA_INICIO` (hoy, el 1 de enero de 2011) marca la fecha más antigua que acepta la bodega. Una atención con una fecha anterior va a cuarentena. Los festivos son los de Colombia, según la biblioteca `holidays`, cuya versión está fijada para que los festivos no cambien entre instalaciones.
