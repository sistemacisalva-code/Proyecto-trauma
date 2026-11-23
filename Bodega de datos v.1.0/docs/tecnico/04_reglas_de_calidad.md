# 04. Reglas de calidad de la bodega

Catálogo de las reglas que revisa `python -m etl.quality --modelo completo` después de cada carga. Qué significa cada acción y cómo se decide el veredicto está en el manual [Calidad y veredicto](../clinico/03_calidad_y_veredicto.md). La misma lista, con ejemplos y sin detalles técnicos, está en el manual clínico [Reglas de calidad](../clinico/05_reglas_de_calidad.md).

Se evalúan **31 reglas**. El identificador `QR-EXA-06` (conteos, sumas y promedios iguales a los del staging) no se evalúa aparte: lo cubre `QR-EXA-04`, porque si cada celda coincide, también coinciden sus agregados.

La acción sale del diccionario `ACCIONES` de `etl/quality/reporte.py`: las reglas que no aparecen allí fallan.

| Regla | Dimensión | Qué revisa | Acción | Módulo |
|---|---|---|---|---|
| QR-INT-01 | Integridad | Ninguna fila apunta, por clave foránea, a una fila que no existe | Falla | `bodega.py` |
| QR-INT-02 | Integridad | Las claves del hecho hacia las dimensiones nunca están vacías (lo vacío usa el miembro 'Sin dato') | Falla | `bodega.py` |
| QR-INT-03 | Integridad | Los miembros por defecto ('Sin dato', 'No aplica') existen como máximo una vez en cada tabla | Falla | `bodega.py` |
| QR-INT-04 | Integridad | Toda atención del hecho tiene huella (la usa la carga incremental) | Falla | `bodega.py` |
| QR-DUP-01 | Unicidad | La llave de la atención no se repite y lleva el prefijo de su fuente (`EX-` o `RC-`) | Falla | `bodega.py` |
| QR-DUP-02 | Unicidad | Dimensiones, catálogos y puentes sin filas que repitan todas sus columnas | Falla | `bodega.py` |
| QR-EXA-01 | Exactitud | La bitácora cuadra en cada tabla: leídas = cargadas + otra toma + sin valor + duplicado + cuarentena | Falla | `bodega.py` |
| QR-EXA-02 | Exactitud | Atenciones del hecho = atenciones del staging menos las apartadas en cuarentena | Falla | `origen.py` |
| QR-EXA-03 | Exactitud | Las filas de cada puente en la bodega coinciden con las cargadas según la bitácora | Falla | `bodega.py` |
| QR-EXA-04 | Exactitud | El hecho y los atributos de sus dimensiones coinciden celda por celda con el staging de la carga | Falla | `origen.py` |
| QR-EXA-05 | Exactitud | Las filas de cada puente coinciden con el staging, atención por atención | Falla | `puentes.py` |
| QR-NUL-01 | Completitud | La llave del hecho nunca está vacía | Falla | `valores.py` |
| QR-NUL-02 | Completitud | Vacíos por columna del hecho y de los atributos de sus dimensiones | Informa | `valores.py` |
| QR-NUL-03 | Completitud | Atenciones sin ninguna fila en cada puente (por ejemplo, sin procedimientos) | Informa | `valores.py` |
| QR-NUL-04 | Completitud | La fecha de admisión (llegada del paciente) no está vacía | Advierte | `valores.py` |
| QR-DOM-01 | Validez | Glasgow dentro de su rango | Falla | `valores.py` |
| QR-DOM-02 | Validez | Las demás medidas del hecho dentro de su rango (los mismos rangos de la transformación) | Advierte | `valores.py` |
| QR-DOM-03 | Validez | Filas de diagnóstico con SIN CODIGO CIE-10 | Informa | `valores.py` |
| QR-DOM-04 | Validez | Atributos de texto dentro de la lista de valores aprobados (solo si existe `config/valores_permitidos.yaml`) | Advierte | `dominios.py` |
| QR-CON-01 | Consistencia | El alta no es anterior a la admisión | Advierte | `valores.py` |
| QR-CON-02 | Consistencia | La hospitalización no es anterior a la admisión, ni el alta anterior a la hospitalización | Advierte | `valores.py` |
| QR-CON-03 | Consistencia | Ninguna hora sin su fecha (alta e inicio de cada procedimiento) | Falla | `valores.py` |
| QR-CON-04 | Consistencia | Ninguna fecha posterior al día de la revisión | Advierte | `valores.py` |
| QR-CON-05 | Consistencia | La presión diastólica no es mayor que la sistólica | Advierte | `valores.py` |
| QR-CON-06 | Consistencia | Los días de UCI no superan los de hospitalización | Advierte | `valores.py` |
| QR-TIE-01 | Integridad (tiempo) | El horario tiene sus 1 440 minutos y el calendario empieza en la fecha de inicio, sin días faltantes | Falla | `valores.py` |
| QR-TRZ-01 | Trazabilidad | La última carga de cada fuente tiene en disco el reporte de la transformación de su staging | Falla | `bodega.py` |
| QR-TRZ-02 | Trazabilidad | Cada tabla de staging que usa el contrato aparece en la bitácora de la carga | Falla | `bodega.py` |
| QR-TRZ-03 | Trazabilidad | Lo que la bitácora cuenta en cuarentena está en disco | Falla | `bodega.py` |
| QR-SEG-01 | Seguridad | El usuario lector (el de Power BI) solo lee y no ve las columnas de texto clínico libre | Falla | `bodega.py` |
| QR-SEG-02 | Seguridad | Ninguna columna lleva un nombre que sugiera datos de identificación (documento, nombre…) | Falla | `bodega.py` |

Todos los módulos están en `etl/quality/`.

**Resumen por acción:** 20 fallan, 8 advierten y 3 informan.

**Por qué unas fallan y otras advierten:** falla lo que solo puede salir mal por un error de la aplicación o del modelo (claves huérfanas, descuadres con el staging, permisos). Advierte lo que viene de la fuente y la bodega no corrige a propósito (fechas en desorden, diastólica mayor que la sistólica, valores fuera de la lista aprobada). Informa lo que es descriptivo y no tiene un valor correcto (porcentaje de vacíos).

Las reglas `QR-EXA-02`, `04` y `05` comparan contra el staging de la misma corrida que se cargó. Si el staging se volvió a generar después de la carga, `QR-EXA-04` falla y no se hacen las comparaciones; la solución está en el manual [Problemas frecuentes](03_problemas_frecuentes.md).
