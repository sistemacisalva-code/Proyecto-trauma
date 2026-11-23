# 01. Qué es la bodega

## En pocas palabras

La bodega de datos reúne en un solo lugar las atenciones del registro de trauma, que hoy están en dos fuentes:

| Fuente | Qué trae | Cómo se identifica cada atención |
|---|---|---|
| Excel histórico | Atenciones registradas antes de REDCap | Código que empieza por `EX-` |
| REDCap | Atenciones registradas en la plataforma actual | Código que empieza por `RC-` |

Con los datos ya unificados, el tablero de Power BI responde preguntas como cuántas atenciones hubo por mes, qué mecanismos de lesión son más frecuentes o cuánto duró la estancia hospitalaria.

## Qué hace y qué no hace

| Hace | No hace |
|---|---|
| Lee las dos fuentes sin modificarlas | No registra atenciones nuevas |
| Aplica las mismas reglas a las dos fuentes | No corrige la historia clínica ni REDCap |
| Unifica las etiquetas (por ejemplo, "Si" del Excel pasa a "Sí", como en REDCap) | No inventa valores que no están en la fuente |
| Cuenta cada valor que borra o corrige | No reemplaza el juicio clínico |
| Revisa la calidad de lo cargado y emite un veredicto | No publica datos de pacientes |

## Cómo viajan los datos

```text
Excel histórico ┐
                ├─► 1. Extracción ─► 2. Transformación ─► 3. Carga ─► 4. Revisión de calidad ─► Tablero
REDCap ─────────┘     (copia fiel)     (reglas)            (bodega)    (veredicto)               (Power BI)
```

1. **Extracción:** se copia la información de la fuente tal como está. REDCap se lee con permiso de solo lectura.
2. **Transformación:** se aplican las reglas del manual [Reglas de los datos](02_reglas_de_los_datos.md): rangos clínicos, fechas coherentes, etiquetas unificadas, códigos CIE-10 y seudonimización del documento.
3. **Carga:** los datos pasan a la bodega. Solo se escriben las atenciones nuevas o las que cambiaron desde la última vez.
4. **Revisión de calidad:** se comprueba lo que quedó en la bodega con 31 reglas y se emite un veredicto ([Calidad y veredicto](03_calidad_y_veredicto.md)).

## Cómo está organizada la información

Cada atención es una fila central, con sus medidas: signos vitales de la primera toma, gases arteriales, severidad (ISS y escala por región), días de hospitalización y de UCI, y volumen de sangre. Alrededor están las descripciones que permiten filtrar y agrupar:

- **El paciente:** grupo de edad (quinquenio), género, estado civil, nacionalidad y seguro.
- **El evento:** lugar, consumo de alcohol, violencia y envenenamiento.
- **El mecanismo:** caída, quemadura, accidente de tránsito y armas.
- **El desenlace:** destino del paciente, muerte prevenible, donación de órganos y autopsia.
- **El tiempo:** fecha (con día de la semana y festivos de Colombia) y hora.
- **Las listas de cada atención:** lesiones, imágenes, diagnósticos CIE-10, comorbilidades, complicaciones, sustancias y procedimientos.

## Dos valores especiales: "Sin dato" y "No aplica"

Cuando la fuente no trae un valor, la bodega no deja el espacio en blanco en las descripciones; usa una de estas dos etiquetas:

| Etiqueta | Significa | Ejemplo |
|---|---|---|
| **Sin dato** | El dato existía pero no se registró | La atención no tiene estado civil |
| **No aplica** | Lo que se describe no ocurrió | La atención no fue por una caída: el tipo de superficie es "No aplica" |

Así, en el tablero se distingue "no sabemos" de "no pasó". En las medidas numéricas (peso, presión) el valor ausente queda vacío y no cuenta en los promedios.

## Privacidad

- El nombre, el documento y otros identificadores directos se eliminan en la transformación y nunca llegan a la bodega.
- El documento se reemplaza por un código seudonimizado, que sirve para reconocer atenciones repetidas sin revelar quién es el paciente.
- El tablero se conecta con un usuario de solo lectura que no ve el texto libre ni los registros apartados.
- Los reportes que se comparten tienen solo conteos. El listado de registros para corregir en la fuente es confidencial y no sale del equipo autorizado.
