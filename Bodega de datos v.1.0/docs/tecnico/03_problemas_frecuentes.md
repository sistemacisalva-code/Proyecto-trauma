# 03. Problemas frecuentes

Los mensajes aparecen en pantalla al ejecutar los comandos del manual [Operar la aplicación](01_operar_la_aplicacion.md).

## Transformación

| Mensaje (resumido) | Causa | Qué hacer |
|---|---|---|
| `... valores no enteros; el contrato exige enteros` | Un campo entero de la fuente trae decimales: la fuente cambió de formato | Revisar con el equipo de REDCap o del registro si cambió la variable. No cambiar la regla para "dejarlo pasar" |
| `... valores no se pudieron convertir` | Llegó texto en un campo numérico | Igual que el anterior: es un cambio en la fuente |
| `columnas a eliminar inexistentes` o `renombres sobre columnas inexistentes` | La fuente quitó o renombró una variable | Actualizar los renombres de columnas ([Dónde ajustar las reglas](02_donde_ajustar_las_reglas.md), sección 2) después de confirmar el cambio |

## Carga

| Mensaje (resumido) | Causa | Qué hacer |
|---|---|---|
| `No hay manifiesto en 'data/staging/...'` | No se ha transformado la fuente, o el staging es antiguo | Ejecutar la transformación de esa fuente y luego cargar |
| `El staging ... no coincide con su manifiesto` | El staging quedó incompleto (por ejemplo, una transformación interrumpida) | Volver a transformar |
| `El Excel ya se cargó en el modelo ...` | El histórico se carga una sola vez | Si su transformación cambió, cargar con `--force`; si no, no hace falta cargarlo |
| La actualización completa no empieza porque hay otra en curso | Ya hay una corrida activa | Esperar a que termine. Si no hay ninguna, revisar si quedó una sesión abierta en la base |

## Revisión de calidad

| Situación | Causa | Qué hacer |
|---|---|---|
| Falla `QR-TIE-01` (calendario incompleto) junto con muchas otras | Se revisó la calidad con la bodega vacía o recién creada | Cargar las dos fuentes y revisar la calidad de nuevo |
| `Sin config/valores_permitidos.yaml: no se evalúa QR-DOM-04` | No existe el archivo de valores permitidos | Es un aviso. Si quiere la regla, crear el archivo ([Dónde ajustar las reglas](02_donde_ajustar_las_reglas.md), sección 4) |
| Error al leer los valores permitidos, con un mensaje que pide comillas | Hay valores sin comillas dobles | Escribir cada valor como `"Sí"`, `"No"`, `"10"` |
| Error que nombra una dimensión o un atributo que no existe | Error de digitación en el archivo de valores permitidos | Corregir el nombre según la plantilla `.example.yaml` |
| Falla `QR-EXA-04` (la bodega no coincide con el staging) | El staging se volvió a generar después de cargar, o la carga construyó mal una fila | Volver a cargar la fuente. Si persiste, es un error de la aplicación |
| Falla `QR-TRZ-03` (cuarentena que no está en disco) | Se borró o movió la carpeta `data/quarantine/` | Restaurar la carpeta o volver a cargar la fuente |
| Advierte `QR-DOM-04` con un valor nuevo | Llegó un valor que no está en la lista aprobada | Confirmar con el personal clínico si es válido. Si lo es, agregarlo a la lista; si no, corregirlo en la fuente |

## Pruebas

| Situación | Causa | Qué hacer |
|---|---|---|
| Las pruebas con base de datos se niegan a correr | `DB_NAME_TEST` no está definido o su nombre no termina en `_test` | Definirlo en `.env` con un nombre propio, distinto de las bases de desarrollo y producción |
| Falla una prueba después de cambiar una regla | La prueba describía el comportamiento anterior | Actualizar la prueba solo si el comportamiento nuevo es el que se pidió |

## Tablero de Power BI

Los errores al generar o conectar el tablero están en el manual [Tablero de Power BI](06_tablero_power_bi.md), sección 8.

| Situación | Causa | Qué hacer |
|---|---|---|
| El tablero muestra datos viejos | No se actualizó después de la última carga | Abrirlo en Power BI Desktop y pulsar Actualizar |
| Error de permisos al actualizar | Se usaron credenciales distintas de las del usuario lector | Usar el usuario lector definido en `.env` (`DB_READER_USER`) |
| Una columna de texto libre no aparece | El usuario lector no tiene acceso a ella, por diseño | Es correcto. Solo la copia restringida del reporte la muestra |

Recuerde: un archivo de Power BI actualizado contiene datos de pacientes. No lo suba al repositorio ni lo envíe por canales abiertos.
