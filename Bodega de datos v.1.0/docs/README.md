# Manuales de la bodega de datos de trauma

Estos manuales explican qué hace la bodega de datos, qué reglas se aplican a los datos y cómo se mantiene. Están escritos para dos públicos: el **personal clínico y administrativo**, que consulta los resultados y propone cambios en las reglas, y el **personal técnico**, que opera la aplicación y la mantiene.

## Organización

Los manuales están en dos carpetas, según quién los usa:

| Carpeta | Para quién | Requiere programación |
|---|---|---|
| [clinico/](clinico/) | Personal clínico y administrativo, que consulta los resultados y propone cambios en las reglas | No |
| [tecnico/](tecnico/) | Personal técnico, con acceso al equipo donde corre la aplicación, que la opera y la mantiene | Sí |

El personal técnico debe leer también los manuales clínicos: allí se explican las reglas que después ajusta.

## Por dónde empezar

| Si usted... | Lea |
|---|---|
| Quiere entender qué es la bodega y de dónde salen los datos | [clinico/01. Qué es la bodega](clinico/01_que_es_la_bodega.md) |
| Quiere saber qué pasa con un valor extremo, una celda vacía o un registro repetido | [clinico/02. Reglas de los datos](clinico/02_reglas_de_los_datos.md) |
| Quiere saber cómo se decide si una carga es confiable | [clinico/03. Calidad y veredicto](clinico/03_calidad_y_veredicto.md) |
| Busca el rango o la regla de una variable concreta | [clinico/04. Catálogo de rangos y reglas](clinico/04_catalogo_de_rangos_y_reglas.md) |
| Quiere ver todas las revisiones que se hacen a la bodega después de cada actualización | [clinico/05. Reglas de calidad](clinico/05_reglas_de_calidad.md) |
| Quiere saber cómo se comprobó que las reglas funcionan | [clinico/06. Casos de prueba](clinico/06_casos_de_prueba.md) |
| Debe actualizar los datos o revisar el resultado de una actualización | [tecnico/01. Operar la aplicación](tecnico/01_operar_la_aplicacion.md) |
| Debe cambiar un rango, una etiqueta, una lista o la acción de una regla | [tecnico/02. Dónde ajustar las reglas](tecnico/02_donde_ajustar_las_reglas.md) |
| Tiene un mensaje de error | [tecnico/03. Problemas frecuentes](tecnico/03_problemas_frecuentes.md) |
| Necesita saber en qué módulo se evalúa cada regla de calidad | [tecnico/04. Reglas de calidad](tecnico/04_reglas_de_calidad.md) |
| Va a correr o escribir pruebas | [tecnico/05. Casos de prueba](tecnico/05_casos_de_prueba.md) |
| Debe crear el tablero de Power BI, conectarlo a la bodega o actualizarlo | [tecnico/06. Tablero de Power BI](tecnico/06_tablero_power_bi.md) |

## Tres ideas que conviene tener presentes

1. **La bodega no corrige la historia clínica.** Lee las fuentes (el Excel histórico y REDCap), aplica reglas y guarda una copia para análisis. Si un dato está mal en la fuente, se corrige en la fuente y la próxima actualización lo trae corregido.
2. **Nada se cambia en silencio.** Cada valor que se borra, se corrige o se aparta queda contado en un reporte.
3. **Los datos de pacientes no salen del equipo autorizado.** Los reportes que se comparten tienen solo conteos. El documento de identidad se reemplaza por un código que no permite recuperarlo.

Las instrucciones de instalación y los comandos completos están en el [README del proyecto](../README.md).
