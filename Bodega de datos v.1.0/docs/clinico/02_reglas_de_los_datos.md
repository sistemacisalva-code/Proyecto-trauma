# 02. Reglas de los datos

Al final de cada sección se indica dónde se ajusta la regla (detalle en el manual [Dónde ajustar las reglas](../tecnico/02_donde_ajustar_las_reglas.md)).

Todas las reglas de este manual se aplican igual al Excel histórico y a REDCap, y cada vez que una regla cambia un dato, el cambio queda contado en el reporte de la transformación.

## 1. Qué puede pasar con un valor

| Tipo de regla | Qué hace | Cuándo se usa |
|---|---|---|
| **Límite duro** | Borra el valor (la celda queda vacía) y lo cuenta | El valor es imposible o es un error evidente de captura o de unidad |
| **Límite blando** | Conserva el valor y lo reporta | El valor es extremo pero posible |
| **Regla de consistencia** | Conserva los valores y reporta la atención | Dos datos se contradicen y no se sabe cuál está mal |
| **Corrección** | Cambia el valor según una regla escrita | Se sabe cuál es el valor correcto (por ejemplo, unificar una etiqueta) |
| **Detención** | Para la actualización con un mensaje | La fuente cambió de forma y seguir podría dañar los datos |

La idea que guía la elección: **si no se sabe cuál de dos valores está mal, se reporta; si se sabe y hay una regla escrita, se corrige o se borra; si la fuente cambió, se detiene.**

Los rangos incluyen sus extremos: un valor se acepta si es igual o mayor que el mínimo y igual o menor que el máximo.

## 2. Rangos clínicos principales

Esta sección resume los más consultados. La lista completa (laboratorio, gases arteriales, mecanismo, estancia, fechas y todas las reglas de consistencia) está en el manual [Catálogo de rangos y reglas](04_catalogo_de_rangos_y_reglas.md).

**Signos vitales (límite duro):**

| Medida | Mínimo | Máximo |
|---|---|---|
| Frecuencia cardiaca | 0 | 300 latidos/min |
| Presión sistólica | 0 | 300 mmHg |
| Presión diastólica | 0 | 200 mmHg |
| Frecuencia respiratoria | 0 | 100 respiraciones/min |
| Saturación de oxígeno | 0 | 100 % |
| Temperatura | 25 | 45 °C |
| Peso | 0,5 | 400 kg |
| Altura | 0,3 | 2,5 m |
| Glasgow total / ocular / verbal / motor | 3 / 1 / 1 / 1 | 15 / 4 / 5 / 6 |
| Duración de la pérdida de conciencia | 0 | 1 440 min (24 h) |

**Severidad (límite duro):** escala AIS por región de 0 a 5; ISS de 0 a 75.

**Líquidos (en litros):**

| Líquido | Límite duro (se borra) | Límite blando (se reporta) |
|---|---|---|
| Cristaloides | más de 30 L | más de 12,67 L |
| Coloides | más de 10 L | más de 1,5 L |
| Sangre | más de 10 L | más de 3 L |

Además, un volumen positivo menor que 0,05 L se reporta como posible error de unidad.

**Otros:** edad de 0 a 120 años (límite duro); días de hospitalización y de UCI desde 0, sin tope.

Dónde se ajusta: archivos de reglas comunes de la transformación ([Dónde ajustar las reglas](../tecnico/02_donde_ajustar_las_reglas.md), sección 1).

## 3. Ejemplos: ¿qué pasa si...?

| Situación (datos inventados) | Resultado | Por qué |
|---|---|---|
| Temperatura de 25 °C | Se conserva | Está en el extremo del rango, y los extremos se aceptan |
| Temperatura de 98,6 | Se borra y se cuenta | Está fuera del límite duro; casi seguro se digitó en °F |
| Frecuencia cardiaca de 301 | Se borra y se cuenta | Supera el máximo de 300 |
| Sangre: 4 L | Se conserva y se reporta | Supera el límite blando (3 L) pero no el duro (10 L): es extremo, no imposible |
| Sangre: 12 L | Se borra y se cuenta | Supera el límite duro de 10 L |
| Coloides: 0,0005 L | Se conserva y se reporta | Puede ser 0,5 L digitado con un error de unidad; no se corrige porque no hay certeza |
| Diastólica de 120 con sistólica de 90 | Se conservan las dos y se reporta la atención | Una de las dos está mal, pero no se sabe cuál |
| Glasgow total de 14 con componentes 4 + 5 + 6 | Se conservan y se reporta | La suma da 15; no se sabe si el error está en el total o en un componente |
| ISS distinto de la suma de los cuadrados de las tres regiones más graves | Se conservan y se reporta | Mismo motivo: contradicción sin forma de saber cuál dato falla |
| Frecuencia respiratoria de 18,5 | Se borra y se cuenta | Una frecuencia respiratoria con decimales no es medible; se trata como error de captura |
| Otro número entero (por ejemplo, frecuencia cardiaca) llega con decimales | La actualización se detiene | Indica que la fuente cambió de formato; hay que revisarla antes de seguir |
| Edad de 130 años | Se borra y se cuenta | Supera el máximo de 120 |
| Duración de un procedimiento de 0 segundos | Se conserva y se reporta | Puede ser un registro incompleto, pero no es imposible |
| Fecha de un procedimiento fuera de la estancia (antes de la llegada o después del alta) | Se conserva y se reporta | La estancia no tiene margen de tolerancia, por indicación del personal médico |
| Procedimiento con el fin antes del inicio, y una de las dos fechas fuera de la estancia | La fecha que está fuera se borra y se cuenta | La otra fecha, dentro de la estancia, es la evidencia de cuál está mal. Si las dos están dentro o las dos fuera, se conservan y se reporta para revisión manual |
| Fecha de alta anterior a la fecha de llegada | Se conservan y se reporta | No se sabe cuál de las dos fechas es la errónea |

## 4. Etiquetas unificadas entre fuentes

El Excel y REDCap escriben algunas respuestas de forma distinta. Para que el tablero no muestre dos categorías para la misma respuesta, el Excel adopta la escritura de REDCap:

| En el Excel | Queda como |
|---|---|
| Si | Sí |
| Viudo | Viudo/a |
| Union Libre | Unión libre |
| Camión o trailer | Camión o tráiler |

Hay una excepción en sentido contrario: en REDCap, el tipo de seguro vacío pasa a "No especificado", que es la etiqueta del Excel. Cada cambio se cuenta en el reporte.

Dónde se ajusta: mapeos de etiquetas del Excel ([Dónde ajustar las reglas](../tecnico/02_donde_ajustar_las_reglas.md), sección 2).

## 5. Cuándo se borra una celda y cuándo una fila completa

**Se borra una celda** (el resto de la atención se conserva) cuando:
- el valor supera un límite duro (sección 2);
- un número que debe ser entero trae decimales en un campo donde la regla lo permite (frecuencia respiratoria);
- el fin de un procedimiento es anterior a su inicio y una de las dos fechas cae fuera de la estancia (se borra la de fuera);
- una fecha del Excel cae antes del 1 de enero de 2011 o después del 31 de diciembre de 2022.

**Se aparta una atención completa** cuando:

| Caso | Qué pasa | Dónde queda |
|---|---|---|
| Dos registros con el mismo documento (seudonimizado) y la misma fecha y hora de llegada | Son la misma llegada capturada dos veces. Se conserva el registro con más información y el otro sale con todas sus filas | Contado en el reporte de la transformación |
| La fecha de llegada (u otra fecha de la atención) está antes del 1 de enero de 2011 o después del 31 de diciembre del año siguiente | La atención no entra a la bodega | Cuarentena, con el motivo `fecha_fuera_de_calendario` |
| Una fila de una lista (por ejemplo, una toma de signos vitales) pertenece a una atención que no existe | La fila no entra a la bodega | Cuarentena, con el motivo `fila_sin_atencion` |
| Un registro de REDCap no tiene datos del instrumento | Se descarta | Contado en el reporte de la transformación |

La **cuarentena** es una carpeta del equipo autorizado donde quedan las filas que no pudieron entrar, con la regla que incumplieron. Nada se pierde: se puede revisar, corregir en la fuente y volver a cargar.

**No se borra, pero no se usa:**
- **Varias tomas de signos vitales o de laboratorio:** la bodega guarda la primera toma con algún valor, en orden de fecha y hora. Las demás quedan contadas como "otra toma".
- **Diagnósticos repetidos:** si una atención tiene dos veces el mismo código CIE-10 en el mismo rol, queda una sola fila.
- **Columnas de identificación directa** (nombre, documento): se eliminan en la transformación; queda constancia de cuántas filas tenían valor.

## 6. Códigos CIE-10

Los diagnósticos se llevan al código CIE-10 correspondiente. Si un texto del Excel no se puede asociar a un código, la bodega lo marca como **SIN CODIGO CIE-10** y guarda el texto original para revisarlo. Ese caso no se considera un error de la carga: la revisión de calidad solo lo informa.

Dónde se ajusta: catálogos CIE-10 ([Dónde ajustar las reglas](../tecnico/02_donde_ajustar_las_reglas.md), sección 3).
