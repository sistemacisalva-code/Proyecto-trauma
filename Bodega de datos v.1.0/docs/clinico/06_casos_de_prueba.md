# 06. Casos de prueba: cómo se comprobó que la bodega funciona

Este manual explica cómo se verificó que las reglas de los manuales anteriores se aplican de verdad. Cómo se ejecutan las pruebas está en el manual técnico [Casos de prueba](../tecnico/05_casos_de_prueba.md).

## 1. Qué es un caso de prueba

Un caso de prueba es una comprobación automática con un resultado esperado. Por ejemplo: "si llega una frecuencia cardiaca de 350, la celda queda vacía y se cuenta como valor borrado". La aplicación prepara el dato, ejecuta la regla y compara el resultado con lo esperado. Si no coincide, la prueba falla.

**Todas las pruebas usan pacientes inventados.** Ninguna lee datos del hospital. Los datos inventados incluyen a propósito los errores que cada regla debe detectar: fechas invertidas, valores imposibles, diagnósticos repetidos.

Conteo al 2026-11-03: **738 pruebas, todas aprobadas.** Cada caso (`TC-...`) agrupa una o varias pruebas sobre el mismo tema.

| Grupo | Qué comprueba | Casos |
|---|---|---|
| `TC-EXT` Lectura de las fuentes | Que el Excel y REDCap se leen completos y que la aplicación nunca escribe en REDCap | 6 |
| `TC-TRF` Transformación | Que cada regla del [catálogo de rangos y reglas](04_catalogo_de_rangos_y_reglas.md) hace lo que dice | 42 |
| `TC-DDL` Estructura de la base | Que la base rechaza lo que no debe guardar (repetidos, piezas sueltas) y protege los textos libres | 11 |
| `TC-CAR` Carga | Que la bodega guarda exactamente lo que salió de la transformación | 30 |
| `TC-CAL` Calidad | Que cada regla de las [reglas de calidad](05_reglas_de_calidad.md) detecta su defecto | 37 |
| `TC-ACE` Aceptación | Que los indicadores de la bodega coinciden con un cálculo hecho por otro camino | 15 |

## 2. Reglas de la transformación (`TC-TRF`)

| Tema | Qué se comprobó | Casos |
|---|---|---|
| Límites duros y blandos | Un valor fuera del límite duro se borra y se cuenta, separado por extremo (por debajo o por encima). Uno fuera del límite blando se conserva y se reporta. Un decimal en una variable entera se trata según su regla | TC-TRF-04 |
| Signos vitales y Glasgow | Rangos de cada signo vital y de cada componente del Glasgow; valores en otra unidad o imposibles se borran; pérdida de conciencia de más de 24 h | TC-TRF-20, TC-TRF-25 |
| Severidad y líquidos | AIS por región de 0 a 5 (un 6 se borra); el ISS distinto de la suma de cuadrados se reporta; límites duros, blandos y de posible error de unidad en cristaloides, coloides y sangre | TC-TRF-20, TC-TRF-31 |
| Laboratorio | Rangos de los exámenes; tipo de sangre llevado a A+, O−, etc.; "NEG" en sangre en orina pasa a 0; relación hematocrito/hemoglobina | TC-TRF-21, TC-TRF-34 |
| Mecanismo de la lesión | Superficie quemada de 0 a 100 %; altura de la caída no negativa y sin tope | TC-TRF-28 |
| Edad y demografía | El quinquenio en los bordes de cada tramo (4 y 5 años, 84 y 85…); la edad exacta no llega a la bodega; el seguro vacío queda como "No especificado" | TC-TRF-18, TC-TRF-42 |
| Estancia, UCI e imágenes | Días negativos se borran (no se cambia el signo); días distintos de los calculados con las fechas se reportan | TC-TRF-19 |
| Fechas de procedimientos | Con el fin antes del inicio, se borra solo la fecha que cae fuera de la estancia; si no se sabe cuál está mal, se conservan y se reportan; la duración negativa queda vacía | TC-TRF-05, TC-TRF-22, TC-TRF-24 |
| Orden de las fechas | Llegada, admisión, alta y fechas de exámenes fuera de orden o fuera de la estancia se reportan; la admisión se compara por día | TC-TRF-16, TC-TRF-36 |
| Diagnósticos CIE-10 | Mayúsculas, puntos y espacios no impiden reconocer un código; un diagnóstico del Excel sin pareja queda como SIN CODIGO CIE-10 | TC-TRF-30, TC-TRF-32 |
| Sustancias de abuso | Errores de escritura corregidos (por ejemplo, BENZODIACEPINAS pasa a BENZODIAZEPINAS) | TC-TRF-29 |
| Municipio y departamento | Tildes y signos no impiden reconocerlos; el departamento se completa desde el municipio solo si la coincidencia es segura | TC-TRF-26, TC-TRF-27 |
| Lugar del evento | Se clasifica por palabras clave en las etiquetas de REDCap y respeta la prioridad (hospital antes que calle) | TC-TRF-33 |
| Etiquetas del Excel | Las siete listas del Excel escritas distinto que en REDCap se llevan a la escritura de REDCap y se cuentan | TC-TRF-41 |
| Atenciones repetidas | Dos atenciones del mismo paciente con la misma llegada dejan una sola, la más completa | TC-TRF-09, TC-TRF-37 |
| Privacidad | El documento se reemplaza por un código que es siempre el mismo para el mismo documento, distinto para documentos distintos y que no permite recuperarlo; los reportes no guardan valores | TC-TRF-09, TC-TRF-15 |
| Código de la atención | Cada atención lleva el prefijo de su fuente (`EX-` o `RC-`); los códigos repetidos o vacíos detienen el proceso | TC-TRF-14 |
| Nada se cambia en silencio | Cada valor borrado, corregido o apartado queda contado; una pérdida sin explicación detiene el proceso | TC-TRF-06, TC-TRF-07, TC-TRF-38 |
| Reportes | El reporte de la transformación resume los conteos; el listado para corrección abre con el aviso de confidencialidad y trae el registro, el campo y el motivo, sin valores | TC-TRF-39, TC-TRF-40 |
| Fuentes completas | Un REDCap inventado con sus 15 formularios y un Excel inventado con sus 18 hojas pasan por todas las reglas juntas | TC-TRF-10, TC-TRF-35 |

Los demás casos `TC-TRF` comprueban la mecánica interna: lectura de archivos, nombres de columnas y división en bloques.

## 3. Reglas de calidad (`TC-CAL`)

Cada regla se probó con una bodega inventada que la cumple y otra con el defecto que debe detectar.

| Regla | Qué detecta | Casos |
|---|---|---|
| QR-INT-01 | Filas que apuntan a una atención inexistente | TC-CAL-01 |
| QR-INT-02 | Atenciones con un dato descriptivo sin enlazar | TC-CAL-02 |
| QR-INT-03 | "Sin dato" o "No aplica" repetidos | TC-CAL-25 |
| QR-INT-04 | Atenciones sin huella | TC-CAL-29 |
| QR-DUP-01 | Atenciones repetidas o con el prefijo equivocado | TC-CAL-03 |
| QR-DUP-02 | Filas idénticas repetidas | TC-CAL-04 |
| QR-EXA-01 | Cuentas de la actualización que no cuadran | TC-CAL-05 |
| QR-EXA-02 | Número de atenciones distinto del de la fuente | TC-CAL-34 |
| QR-EXA-03 | Diagnósticos, procedimientos, etc. en número distinto del registrado | TC-CAL-06 |
| QR-EXA-04 | Un valor distinto del de la fuente transformada | TC-CAL-21 a 24, TC-CAL-31, TC-CAL-32 |
| QR-EXA-05 | Diagnósticos, procedimientos, etc. distintos en una atención | TC-CAL-27, TC-CAL-28 |
| QR-NUL-01 y 04 | Atención sin código; fecha de llegada vacía | TC-CAL-15 |
| QR-NUL-02 | Porcentaje de vacíos | TC-CAL-16 |
| QR-NUL-03 | Atenciones sin filas de un tipo | TC-CAL-26 |
| QR-DOM-01 y 02 | Glasgow y demás medidas fuera de rango | TC-CAL-17 |
| QR-DOM-03 | Diagnósticos SIN CODIGO CIE-10 | TC-CAL-18 |
| QR-DOM-04 | Textos fuera de la lista aprobada | TC-CAL-35 a 37 |
| QR-CON-01 a 06 | Fechas en desorden, hora sin fecha, fecha futura, diastólica mayor que la sistólica, más días de UCI que de hospitalización | TC-CAL-19 |
| QR-TIE-01 | Días faltantes en el calendario | TC-CAL-20 |
| QR-TRZ-01 | Actualización sin reporte de transformación | TC-CAL-12 |
| QR-TRZ-02 | Tabla que no aparece en el registro | TC-CAL-13 |
| QR-TRZ-03 | Atenciones apartadas que no están guardadas | TC-CAL-33 |
| QR-SEG-01 | Usuario del tablero que puede leer textos libres o modificar datos | TC-CAL-10 |
| QR-SEG-02 | Columnas con nombres de identificación | TC-CAL-11 |
| Veredicto | Una regla que falla da "Rechazada"; una que advierte, "Aprobada con advertencias"; el reporte se guarda | TC-CAL-07 a 09, TC-CAL-14, TC-CAL-30 |

## 4. Carga y estructura (`TC-CAR` y `TC-DDL`)

| Qué se comprobó | Casos |
|---|---|
| Repetir una actualización con los mismos datos deja los mismos conteos | TC-CAR-01, TC-CAR-20 |
| Si una atención cambia en REDCap, la siguiente actualización la reemplaza completa; las que no cambian no se tocan | TC-CAR-21 a 23 |
| Entre varias tomas de signos vitales o de laboratorio, se guarda la primera con datos | TC-CAR-19 |
| Si la carga falla a mitad de camino, la bodega queda como estaba (no queda a medias) | TC-CAR-31 |
| Las atenciones apartadas quedan guardadas y registradas | TC-CAR-29, TC-DDL-11 |
| La base rechaza atenciones repetidas y filas que apuntan a una atención inexistente | TC-DDL-04, TC-DDL-05 |
| El usuario del tablero solo lee y no ve los textos clínicos libres ni el registro de las actualizaciones | TC-DDL-07, TC-DDL-10 |

## 5. Indicadores de aceptación (`TC-ACE`)

Cada indicador se calculó dos veces sobre los mismos datos inventados: una con la bodega (como lo hace el tablero) y otra por un camino independiente, directamente desde la fuente transformada. Los dos resultados deben coincidir exactamente en los conteos y con una diferencia máxima de 0,01 en promedios y porcentajes.

| Caso | Indicador |
|---|---|
| TC-ACE-01 | Casos por mes de admisión y mecanismo (caída, quemadura, tránsito, arma de fuego, arma blanca). Una atención cuenta en cada mecanismo que tenga |
| TC-ACE-02 | Porcentaje de casos por quinquenio de edad y género |
| TC-ACE-03 | Promedio de días de hospitalización y de UCI por mes de alta |
| TC-ACE-04 | Porcentaje de casos por disposición del paciente, incluida la muerte |
| TC-ACE-05 | Diagnósticos CIE-10 más frecuentes |
| TC-ACE-06 | Casos por franja horaria de alta |
| TC-ACE-07 | Casos por rango de ISS (1–8, 9–15, 16–24 y 25 o más) |
| TC-ACE-08 | Pacientes críticos: Glasgow menor de 9 (suma de ocular, verbal y motor), presión sistólica menor de 90 e índice de choque mayor de 0,9 |
| TC-ACE-09 | Mortalidad por rango de ISS y por mecanismo |
| TC-ACE-10 | Atenciones con UCI y atenciones con al menos un procedimiento |
| TC-ACE-11 | Atenciones por parte del cuerpo lesionada |
| TC-ACE-12 | Atenciones transfundidas y litros totales |
| TC-ACE-13 | Atenciones con al menos una imagen, por tipo |
| TC-ACE-14 | Prevalencia por sustancia de abuso |
| TC-ACE-15 | Promedio de días entre la admisión y el alta, por mes de admisión |

## 6. Lo que las pruebas no cubren

- **Que los rangos sean clínicamente correctos.** Las pruebas comprueban que la aplicación aplica el rango escrito, no que el rango sea el adecuado. Los rangos son propuestas que el equipo clínico debe validar ([Catálogo de rangos y reglas](04_catalogo_de_rangos_y_reglas.md)).
- **Las unidades sin confirmar.** Glóbulos blancos, sangre en orina y la convención de signo del déficit de base dependen de que el laboratorio confirme la unidad.
- **Los datos reales.** Las pruebas usan datos inventados. Con los datos del hospital, la calidad se revisa en cada actualización con las [reglas de calidad](05_reglas_de_calidad.md).
