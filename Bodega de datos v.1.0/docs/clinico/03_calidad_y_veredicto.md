# 03. Calidad y veredicto

## 1. Qué se revisa

Después de cada carga, la aplicación revisa lo que quedó en la bodega con **31 reglas** (la lista completa, con un ejemplo de cada una, está en el manual [Reglas de calidad](05_reglas_de_calidad.md)). Cada regla cuenta cuántas filas revisó y cuántas no cumplen; la meta siempre es cero. Las reglas se agrupan según las dimensiones de calidad de la norma ISO/IEC 25012:

| Dimensión | Pregunta que responde | Ejemplo de regla |
|---|---|---|
| Integridad | ¿Las piezas encajan? | Ningún diagnóstico apunta a una atención inexistente |
| Unicidad | ¿Hay repetidos? | Ninguna atención aparece dos veces |
| Exactitud | ¿La bodega dice lo mismo que la fuente transformada? | Cada valor de la bodega coincide con el de la transformación |
| Completitud | ¿Faltan datos? | Cuántos vacíos tiene cada columna |
| Validez | ¿Los valores están en su dominio? | Glasgow entre 3 y 15; estado civil dentro de la lista aprobada |
| Consistencia | ¿Los datos se contradicen? | El alta no es anterior a la llegada |
| Trazabilidad | ¿Se puede reconstruir qué pasó? | Cada carga tiene su reporte y su cuarentena en disco |
| Seguridad | ¿Se protege la información? | El usuario del tablero no ve columnas reservadas |

## 2. Qué hace cada regla cuando no se cumple

| Acción | Significa | Ejemplos |
|---|---|---|
| **Falla** | El error es de la aplicación o del modelo. La carga no es confiable | Un diagnóstico sin su atención; una atención repetida; un valor de la bodega distinto del de la fuente transformada |
| **Advierte** | El problema viene de la fuente. La carga es utilizable, pero conviene corregir la fuente | Alta antes de la llegada; diastólica mayor que la sistólica; un valor fuera de la lista aprobada; fecha de llegada vacía |
| **Informa** | Es un dato descriptivo, no un error | Porcentaje de vacíos por columna; atenciones sin procedimientos; diagnósticos sin código CIE-10 |

## 3. El veredicto

| Veredicto | Cuándo | Qué hacer |
|---|---|---|
| **Aprobada** | Ninguna regla falla ni advierte | Usar los datos |
| **Aprobada con advertencias** | Alguna regla advierte y ninguna falla | Usar los datos y enviar al equipo de registro los casos a corregir en la fuente |
| **Rechazada** | Al menos una regla falla | No usar la actualización hasta que el personal técnico revise la causa |

El veredicto queda guardado con la fecha y los conteos, para poder consultar la historia de las cargas.

## 4. Ejemplos

| Situación (datos inventados) | Regla | Resultado |
|---|---|---|
| Una atención tiene fecha de alta anterior a la de llegada | Consistencia, advierte | Aprobada con advertencias. La atención se cuenta y se reporta para corregir en la fuente |
| El estado civil "Separado" aparece en la bodega pero no está en la lista aprobada | Validez, advierte | Aprobada con advertencias. Hay que decidir si se agrega a la lista o si es un error de captura |
| La columna de peso está vacía en muchas atenciones | Completitud, informa | No cambia el veredicto. Sirve para saber qué tan confiable es un promedio de peso |
| Tras una carga, una toma de laboratorio apunta a una atención que no está en la bodega | Integridad, falla | Rechazada. Es un error de la carga; el personal técnico debe revisarla |
| Un valor de la bodega no coincide con el de la transformación | Exactitud, falla | Rechazada. La carga construyó mal una fila |

## 5. Criterios de aceptación del prototipo

Además del veredicto de cada carga, se propone aceptar el prototipo con estos criterios, comprobados con datos sintéticos ([Casos de prueba](06_casos_de_prueba.md)). Las metas son una propuesta que se acuerda con el director del trabajo de grado:

| Criterio | Meta |
|---|---|
| Pruebas automáticas en verde | 100 % |
| Reglas de calidad con al menos dos pruebas (un caso que cumple y uno con el defecto) | 100 % |
| Diferencia entre un indicador del tablero y un cálculo independiente | 0 en conteos; 0,01 en promedios |
| Filas descuadradas entre fuente y bodega, referencias huérfanas y duplicados | 0 |
| Repetir una carga con los mismos datos | Mismos conteos y 0 errores |

## 6. Los reportes

| Reporte | Contenido | ¿Se puede compartir? |
|---|---|---|
| Reporte de calidad de la bodega | Conteos por regla y veredicto | Sí |
| Reporte de la transformación | Conteos de valores borrados, corregidos y apartados | Sí |
| Listado para corrección | Códigos de los registros a corregir en la fuente, con el campo y el motivo, sin valores | **No: es confidencial** |

Para pedir un ajuste de una regla (un rango, una etiqueta, un valor permitido), envíe al personal técnico qué regla, qué valor propone y su justificación clínica. El cambio se hace como se describe en el manual [Dónde ajustar las reglas](../tecnico/02_donde_ajustar_las_reglas.md).
