# 05. Reglas de calidad de la bodega

Lista completa de las revisiones que se hacen a la bodega después de cada actualización. Qué significa cada acción y cómo se decide el veredicto está en el manual [Calidad y veredicto](03_calidad_y_veredicto.md).

Cómo leer las tablas:

- **Falla:** el problema solo puede venir de un error de la aplicación. Si una regla falla, la actualización queda **Rechazada**.
- **Advierte:** el problema viene de la fuente (REDCap o el Excel). La actualización queda **Aprobada con advertencias** y los casos se envían para corregir en la fuente.
- **Informa:** es un dato descriptivo, no un error. No cambia el veredicto.
- Los ejemplos usan datos inventados.

Se aplican **31 reglas**: 20 fallan, 8 advierten y 3 informan. El identificador (`QR-...`) sirve para encontrar la regla en los reportes y en los casos de prueba ([Casos de prueba](06_casos_de_prueba.md)).

## 1. Integridad: ¿las piezas encajan?

| Regla | Qué revisa | Ejemplo de lo que detecta | Acción |
|---|---|---|---|
| QR-INT-01 | Cada diagnóstico, procedimiento, imagen o examen pertenece a una atención que existe | Un procedimiento que apunta a una atención que no está en la bodega | Falla |
| QR-INT-02 | Cada atención tiene todos sus datos descriptivos enlazados. Si un dato faltaba en la fuente, se enlaza con "Sin dato", nunca queda suelto | Una atención sin enlace al tipo de seguro | Falla |
| QR-INT-03 | Las opciones "Sin dato" y "No aplica" existen una sola vez en cada lista | "Sin dato" repetido dos veces en la lista de estados civiles | Falla |
| QR-INT-04 | Cada atención tiene su huella, el resumen que permite detectar si cambió en la siguiente actualización | Una atención sin huella, que no se actualizaría cuando cambie en REDCap | Falla |
| QR-TIE-01 | El calendario no tiene días faltantes y el reloj tiene los 1 440 minutos del día | Falta el 29 de febrero de 2016 en el calendario | Falla |

## 2. Unicidad: ¿hay repetidos?

| Regla | Qué revisa | Ejemplo de lo que detecta | Acción |
|---|---|---|---|
| QR-DUP-01 | Ninguna atención aparece dos veces, y su código empieza por el de su fuente (`EX-` para el Excel, `RC-` para REDCap) | La misma atención guardada dos veces | Falla |
| QR-DUP-02 | Ninguna lista ni relación tiene filas idénticas repetidas | El mismo diagnóstico dos veces, con el mismo rol, en la misma atención | Falla |

## 3. Exactitud: ¿la bodega dice lo mismo que la fuente transformada?

| Regla | Qué revisa | Ejemplo de lo que detecta | Acción |
|---|---|---|---|
| QR-EXA-01 | Las cuentas de cada actualización cuadran: filas leídas = cargadas + descartadas por un motivo conocido (otra toma, sin valor, repetida o apartada) | Se leyeron 100 tomas de laboratorio y solo se explican 98 | Falla |
| QR-EXA-02 | El número de atenciones de la bodega es igual al de la fuente transformada, menos las apartadas | La fuente tiene 500 atenciones, se apartaron 2 y la bodega tiene 497 | Falla |
| QR-EXA-03 | El número de diagnósticos, procedimientos, imágenes, etc. de la bodega coincide con lo que se registró como cargado | Se registraron 1 200 diagnósticos cargados y en la bodega hay 1 190 | Falla |
| QR-EXA-04 | Cada valor de cada atención coincide con el de la fuente transformada: Glasgow, ISS, signos vitales, fechas, seguro, etc. | La bodega dice ISS 25 y la fuente transformada dice 16 | Falla |
| QR-EXA-05 | Los diagnósticos, procedimientos, imágenes, lesiones, sustancias y complicaciones coinciden atención por atención con la fuente transformada | Una atención con 3 diagnósticos en la fuente y 2 en la bodega | Falla |

Que cada valor coincida (QR-EXA-04) asegura también que coincidan los conteos, las sumas y los promedios. Por eso esa comprobación no se hace por separado.

## 4. Completitud: ¿faltan datos?

| Regla | Qué revisa | Ejemplo de lo que detecta | Acción |
|---|---|---|---|
| QR-NUL-01 | Toda atención tiene su código | Una atención sin código | Falla |
| QR-NUL-02 | Porcentaje de vacíos de cada dato | El peso está vacío en el 40 % de las atenciones | Informa |
| QR-NUL-03 | Cuántas atenciones no tienen ninguna fila de cada tipo | 120 atenciones sin procedimientos | Informa |
| QR-NUL-04 | La fecha de admisión (llegada del paciente) no está vacía | Una atención sin fecha de llegada, que no se puede ubicar en el tiempo | Advierte |

## 5. Validez: ¿los valores están en su dominio?

| Regla | Qué revisa | Ejemplo de lo que detecta | Acción |
|---|---|---|---|
| QR-DOM-01 | Glasgow ocular de 1 a 4, verbal de 1 a 5 y motor de 1 a 6 | Glasgow verbal de 7 | Falla |
| QR-DOM-02 | Las demás medidas dentro de los rangos del [catálogo](04_catalogo_de_rangos_y_reglas.md): signos vitales, AIS, ISS, quemadura, altura de la caída, PaO2, PaCO2, sangre transfundida y días de estancia y de UCI | Frecuencia cardiaca de 350 | Advierte |
| QR-DOM-03 | Diagnósticos que quedaron como SIN CODIGO CIE-10 | 15 diagnósticos del Excel sin pareja en el catálogo CIE-10 | Informa |
| QR-DOM-04 | Los textos están dentro de la lista de valores aprobados (estado civil, seguro, nacionalidad…). Solo se revisa si la lista aprobada existe | Estado civil "Separado" cuando la lista no lo incluye | Advierte |

El Glasgow falla porque la transformación ya borra los valores fuera de rango: si aparece uno en la bodega, es un error de la aplicación. Las demás medidas solo advierten porque sus rangos todavía son propuestas.

## 6. Consistencia: ¿los datos se contradicen?

| Regla | Qué revisa | Ejemplo de lo que detecta | Acción |
|---|---|---|---|
| QR-CON-01 | El alta no es anterior a la admisión | Alta el 3 de marzo y admisión el 5 de marzo | Advierte |
| QR-CON-02 | La hospitalización no es anterior a la admisión, ni el alta anterior a la hospitalización | Hospitalización antes de la llegada a urgencias | Advierte |
| QR-CON-03 | Ninguna hora sin su fecha (alta e inicio de cada procedimiento) | Hora de alta 14:30 sin fecha de alta | Falla |
| QR-CON-04 | Ninguna fecha posterior al día de la revisión | Una admisión con fecha del año próximo | Advierte |
| QR-CON-05 | La presión diastólica no es mayor que la sistólica | 80/120 (probablemente invertida al digitar) | Advierte |
| QR-CON-06 | Los días de UCI no superan los de hospitalización | 12 días de UCI en una hospitalización de 5 días | Advierte |

## 7. Trazabilidad: ¿se puede reconstruir qué pasó?

| Regla | Qué revisa | Ejemplo de lo que detecta | Acción |
|---|---|---|---|
| QR-TRZ-01 | La última actualización de cada fuente tiene guardado el reporte de su transformación | No se puede consultar qué valores se borraron en la última actualización de REDCap | Falla |
| QR-TRZ-02 | Cada tabla de la fuente transformada aparece en el registro de la actualización | La tabla de imágenes no figura en el registro | Falla |
| QR-TRZ-03 | Las atenciones apartadas (cuarentena) están guardadas para revisarlas | El registro dice 2 atenciones apartadas, pero no están guardadas | Falla |

## 8. Seguridad: ¿se protege la información?

| Regla | Qué revisa | Ejemplo de lo que detecta | Acción |
|---|---|---|---|
| QR-SEG-01 | El usuario del tablero (Power BI) solo puede leer y no ve los textos clínicos libres (detalles de hospitalización, descripción de imágenes y texto original de diagnósticos y complicaciones) | El usuario del tablero puede leer la descripción de las imágenes | Falla |
| QR-SEG-02 | Ningún dato de la bodega tiene un nombre que sugiera identificación del paciente (documento, nombre, teléfono, dirección) | Una columna llamada "documento" | Falla |

## 9. Por qué unas fallan y otras advierten

La regla general es: **falla** lo que solo puede salir mal por un error de la aplicación o del modelo, y **advierte** lo que viene de la fuente y la bodega no corrige a propósito. La bodega no cambia la historia clínica: si una fecha está mal en REDCap, se corrige en REDCap y la próxima actualización la trae corregida.

Para pedir que una regla pase de advertir a fallar, o al revés, o que se agregue un valor a una lista aprobada, envíe al personal técnico la regla, el cambio y su justificación clínica.
