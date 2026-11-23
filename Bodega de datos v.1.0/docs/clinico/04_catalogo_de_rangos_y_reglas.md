# 04. Catálogo de rangos y reglas

Lista completa de los rangos y de las reglas que la transformación aplica a cada variable. La explicación de cada tipo de regla, con ejemplos, está en el manual [Reglas de los datos](02_reglas_de_los_datos.md). Dónde se cambia cada valor está en el manual [Dónde ajustar las reglas](../tecnico/02_donde_ajustar_las_reglas.md).

Cómo leer las tablas:

- **Duro:** un valor fuera del rango se borra (la celda queda vacía) y se cuenta.
- **Blando:** un valor fuera del rango se conserva y se reporta.
- **Informativo:** solo se reporta; no cambia nada.
- Los rangos incluyen sus extremos.
- **Entero** significa que la variable no admite decimales: si llegan, la actualización se detiene (salvo donde se indica).
- La columna "Variable" da el nombre que usa la aplicación, para que el personal técnico la ubique.

Los rangos son propuestas que el equipo clínico debe validar. Mientras tanto, son los que la aplicación usa.

## 1. Signos vitales y Glasgow

| Medida | Variable | Unidad | Mínimo | Máximo | Tipo | Entero |
|---|---|---|---|---|---|---|
| Frecuencia cardiaca | `frecuencia_cardiaca` | latidos/min | 0 | 300 | Duro | Sí |
| Presión sistólica | `presion_arterial_sistolica` | mmHg | 0 | 300 | Duro | Sí |
| Presión diastólica | `presion_arterial_diastolica` | mmHg | 0 | 200 | Duro | Sí |
| Frecuencia respiratoria | `frecuencia_respiratoria` | respiraciones/min | 0 | 100 | Duro | Sí, pero un decimal se borra en lugar de detener |
| Saturación de oxígeno | `saturacion_de_oxigeno` | % | 0 | 100 | Duro | No |
| Temperatura | `temperatura` | °C | 25 | 45 | Duro | No |
| Peso | `peso` | kg | 0,5 | 400 | Duro | No |
| Altura | `altura` | m | 0,3 | 2,5 | Duro | No |
| Glasgow total | `gcs_total` | puntos | 3 | 15 | Duro | Sí |
| Glasgow ocular | `gcs_ocular` | puntos | 1 | 4 | Duro | Sí |
| Glasgow verbal | `gcs_verbal` | puntos | 1 | 5 | Duro | Sí |
| Glasgow motor | `gcs_motora` | puntos | 1 | 6 | Duro | Sí |
| Duración de la pérdida de conciencia | `duracion_de_la_perdida_de_conciencia` | minutos | 0 | 1 440 (24 h) | Duro | No (llega como HH:MM:SS) |

## 2. Severidad

| Medida | Variable | Mínimo | Máximo | Tipo | Entero |
|---|---|---|---|---|---|
| AIS por región (cabeza, cara, tórax, abdomen, extremidades, externo) | `cabeza`, `cara`, `torax`, `abdomen`, `extremidades`, `externo` | 0 | 5 | Duro | Sí |
| ISS | `iss` | 0 | 75 | Duro | Sí |

El AIS 6 (lesión no sobreviviente) hoy se borra. Si el registro lo usa, el máximo debe pasar a 6.

## 3. Líquidos

| Líquido | Variable | Unidad | Duro (se borra) | Blando (se reporta) | Posible error de unidad (se reporta) |
|---|---|---|---|---|---|
| Cristaloides | `cristaloides` | L | más de 30 | más de 12,67 | mayor que 0 y menor que 0,05 |
| Coloides | `coloides` | L | más de 10 | más de 1,5 | mayor que 0 y menor que 0,05 |
| Sangre | `sangre` | L | más de 10 | más de 3 | mayor que 0 y menor que 0,05 |

## 4. Laboratorio y gases arteriales

| Examen | Variable | Unidad | Mínimo | Máximo | Tipo |
|---|---|---|---|---|---|
| Glóbulos blancos | `globulos_blancos` | ×10³/µL o /mm³ (sin confirmar) | Sin rango | Sin rango | Informativo: se reporta si cae fuera de 0,1–200 (×10³/µL) **y** de 100–200 000 (/mm³), y cuántos valores parecen de cada unidad |
| Hematocrito | `hematocrito` | % | 5 | 75 | Duro |
| Hemoglobina | `hemoglobina` | g/dL | 1 | 25 | Duro |
| Plaquetas | `plaquetas` | ×10³/µL | 5 | 1 500 | Duro |
| Sodio | `na` | mEq/L | 90 | 190 | Duro |
| Potasio | `k` | mEq/L | 1 | 12 | Duro |
| Cloro | `cl` | mEq/L | 60 | 150 | Duro |
| Bicarbonato | `hco3` | mEq/L | 2 | 60 | Duro |
| BUN | `bun` | mg/dL | 1 | 300 | Duro |
| Creatinina | `creatinina` | mg/dL | 0,1 | 25 | Duro |
| Glucosa | `glucosa` | mg/dL | 10 | 1 000 | Duro |
| TP | `tp` | segundos | 5 | 300 | Duro |
| TPT | `tpt` | segundos | 10 | 300 | Duro |
| INR | `inr` | sin unidad | 0,5 | 20 | Duro |
| PaO2 | `pao2` | mmHg | 10 | 700 | Duro |
| PaCO2 | `paco2` | mmHg | 5 | 200 | Duro |
| pH | `ph` | sin unidad | 6,5 | 8,0 | Duro |
| Exceso de base | `be` | mEq/L | −40 | 40 | Duro |
| Déficit de base | `deficit_de_base` | mEq/L | −40 | 40 | Duro (convención de signo sin confirmar) |
| Lactato | `lactato` | mmol/L | 0,1 | 30 | Duro |
| Sangre en orina | `sangre_en_orina` | eritrocitos/µL (supuesta) | 0 | 250 | Duro, entero. "NEG" o "NEGATIVO" pasa a 0. Se reporta un valor fuera de la escala de la tira (0, 10, 25, 50, 150, 250) |

Otras variables del laboratorio:

- **Tipo de sangre:** se lleva a la forma A+, A−, B+, B−, AB+, AB−, O+ u O−. Lo que no se puede interpretar se borra y se cuenta.
- **Toxicología** (anfetaminas, barbitúricos, benzodiacepinas, cocaína, opiáceos y otros): los resultados pasan a positivo o negativo. Hoy no se cargan en la bodega.
- **Excel, plaquetas con la unidad 10E12L:** se suponen cuentas por µL y se dividen entre 1 000. Se reportan las que tienen esa unidad y un valor que no parece una cuenta.

## 5. Mecanismo, demografía, estancia y UCI

| Medida | Variable | Mínimo | Máximo | Tipo |
|---|---|---|---|---|
| Superficie corporal quemada (SCQ) | `scq` | 0 | 100 % | Duro |
| Altura de la caída | `altura_en_metros` | 0 | Sin tope | Duro (solo el mínimo) |
| Edad | `edad` | 0 | 120 años | Duro, entero |
| Días de hospitalización | `dias_de_hospitalizacion` | 0 | Sin tope | Duro (solo el mínimo), entero |
| Días de UCI | `dias_usados_uci` | 0 | Sin tope | Duro (solo el mínimo), entero |
| Duración de un procedimiento | `duracion_procedimiento_seg` | — | 24 h | Informativo: más de 24 h o exactamente 0 s se reporta |

La edad exacta no llega a la bodega: se convierte en el quinquenio (0-4, 5-9, …, 85 o más) y después se elimina.

## 6. Fechas

| Regla | Fuente | Qué pasa |
|---|---|---|
| Fecha fuera del 1 de enero de 2011 al 31 de diciembre de 2022 | Excel | La celda se borra y se cuenta, por extremo (antes o después) |
| Fecha posterior al día de la extracción | REDCap | Se reporta |
| Fecha de una atención antes del 1 de enero de 2011 o después del 31 de diciembre del año siguiente al actual | Ambas, en la carga | La atención va a cuarentena (`fecha_fuera_de_calendario`) |
| Fecha de un procedimiento, de signos vitales, de laboratorio o del ventilador fuera de la estancia (de la llegada al alta, sin margen) | Ambas | Se reporta. En los procedimientos con el fin anterior al inicio, si una de las dos fechas está dentro de la estancia y la otra fuera, la de fuera se borra |
| Fin del procedimiento anterior al inicio, sin forma de saber cuál fecha está mal | Ambas | Se conservan y se reporta para revisión manual. La duración queda vacía |

## 7. Reglas de consistencia (se conservan los valores y se reporta)

| Regla | Fuente |
|---|---|
| Alta anterior a la admisión | Ambas |
| Llegada del paciente, admisión y alta fuera de orden | REDCap |
| Evento posterior a la llegada del paciente | Excel |
| Llegada del médico anterior a la del paciente (además, cuántas por más de 1 h, de 24 h y de 7 días) | Excel |
| Disposición anterior a la llegada del paciente | Excel |
| Días de hospitalización distintos de los calculados con las fechas | Ambas |
| Días de UCI distintos de los días completos calculados con las fechas del ventilador | REDCap |
| Ventilador con solo una de las dos fechas, o con el término antes del inicio | Ambas |
| Presión diastólica mayor que la sistólica | Ambas |
| Glasgow total distinto de ocular + verbal + motor | Ambas |
| ISS distinto de la suma de los cuadrados de las tres regiones más graves | Ambas |
| Hematocrito dividido entre hemoglobina fuera de 2,5 a 3,5 | Ambas |
| Mismo examen repetido en la misma toma (decisión pendiente; se conservan los dos) | Excel |
| Edad en meses de 60 o más (equivale a 5 años o más) | Excel |
| Minutos en sala de emergencias mayores que 59 | Excel |
| Municipio y departamento que no concuerdan con el catálogo | Excel |
| Otras drogas con varias sustancias en una celda | Ambas |

## 8. Textos y catálogos

| Regla | Qué pasa |
|---|---|
| Etiquetas del Excel escritas distinto que en REDCap | Se corrigen a la escritura de REDCap y se cuentan ([Reglas de los datos](02_reglas_de_los_datos.md), sección 4) |
| Diagnóstico del Excel sin pareja en el catálogo CIE-10 de REDCap | Queda como SIN CODIGO CIE-10; el texto se conserva en mayúsculas |
| Lugar del evento del Excel | Se borran números, teléfonos y nomenclatura de dirección, y se clasifica en las 12 etiquetas de REDCap por palabras clave. Sin palabra clave, queda la etiqueta por defecto y se reporta. El texto original se descarta |
| Errores ortográficos en otras sustancias de abuso | Se corrigen según el catálogo de correcciones |
| Departamento vacío con un municipio conocido | Se completa desde el municipio, solo si la coincidencia es segura |
