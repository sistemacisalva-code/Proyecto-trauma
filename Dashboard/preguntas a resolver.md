# Preguntas VS Variables 

Que preguntas se pueden responder con las variables que cuenta actualmente el modelo y que visual es posible para ver esto

---------------------------------------------------------------------
## 1. RELACIONES DEL MODELO 
---------------------------------------------------------------------

Grano: `FACT_TRAUMA` = 1 fila por atención.

**Dimensiones directas (1 -> N hacia la FACT)**

| Desde | Columna en FACT_TRAUMA | Atributos útiles |
|---|---|---|
| DIM_TIEMPO (rol admisión) | fecha_admision_id | fecha, anio, trimestre, mes, nombre_mes, dia, dia_semana, es_festivo |
| DIM_TIEMPO (rol hospitalización) | fecha_hospitalizacion_id | igual |
| DIM_TIEMPO (rol alta) | fecha_alta_id | igual |
| DIM_HORARIO | hora_alta_id | hora, minuto, intervalo |
| DIM_PACIENTE | paciente_id | quinquenio, quinquenio_orden, genero, estado_civil, nacionalidad, tipo_seguro, paciente_asegurado |
| DIM_EVENTO_TRAUMA | evento_id | consumo_alcohol, violencia, envenenamiento, lugar_evento |
| DIM_CAIDA | caida_id | caida, tipo_superficie |
| DIM_QUEMADURA | quemadura_id | quemadura, grado_quemadura |
| DIM_ACCIDENTE_TRANSITO | accidente_id | tipo_vehiculo, ocupante, tipo_colision, velocidad_colision |
| DIM_ARMAS | armas_id | lesion_arma_fuego, lesion_arma_blanca |
| DIM_DESENLACE | desenlace_id | disposicion_paciente, muerte_prevenible, donacion_organos, autopsia |
| DIM_CALIFICADOR_SIGNOS | calificador_signos_id | perdida_conciencia, avup, calificador_gcs, calificador_frecuencia_respiratoria |

**Medidas numéricas en la FACT:** iss, cabeza, cara, torax, abdomen, extremidades, externo,
gcs_ocular/verbal/motor, presion_sistolica/diastolica, frecuencia_cardiaca,
frecuencia_respiratoria, saturacion_o2, temperatura_c, pao2, paco2, dias_hospitalizacion,
uci_dias, sangre_l, altura_metros, scq, peso, altura.

**Puentes (FACT 1 -> N puente -> N 1 dimensión)**

| Puente | Dimensión | Qué aporta |
|---|---|---|
| BRIDGE_ATENCION_LESION | DIM_PARTE_CUERPO_LESION, DIM_MECANISMO_PRIMARIO, DIM_TIPO_LESION | región, mecanismo, naturaleza de cada lesión |
| BRIDGE_ATENCION_CIE_10 (rol) | DIM_CIE_10 | diagnóstico, comorbilidad, mecanismo_transito, otro_mecanismo |
| BRIDGE_ATENCION_COMPLICACION | DIM_CIE_10 (+ lugar_complicacion) | complicaciones |
| BRIDGE_ATENCION_SUSTANCIA | DIM_SUSTANCIA | sustancias de abuso |
| BRIDGE_ATENCION_PROCEDIMIENTO | DIM_PROCEDIMIENTO (+ fecha_inicio_id, hora_inicio_id, duracion_seg) | cirugías/procedimientos |
| BRIDGE_ATENCION_IMAGEN | DIM_IMAGEN | tipo de imagen y región (sin fecha) |

### Reglas para que las relaciones den respuestas correctas
1. **Contar pacientes siempre con `DISTINCTCOUNT(FACT_TRAUMA[fact_id])`.** Un paciente con
   varias lesiones/diagnósticos/procedimientos tiene varias filas en el puente.
2. **DIM_TIEMPO tiene 3 relaciones con la FACT** (admisión, hospitalización, alta) + 1 desde
   el puente de procedimientos (fecha_inicio_id). Dejar **activa solo admisión**; las demás
   inactivas, y usarlas con `USERELATIONSHIP` en la medida que las necesite.
3. **Para filtrar la FACT desde un atributo de puente** (p. ej. segmentar por mecanismo o
   por CIE-10), la relación puente -> FACT debe filtrar hacia la FACT (filtro cruzado en
   ambos sentidos en esa relación, o medida con `CROSSFILTER`).
4. **DIM_CIE_10 se usa en dos puentes** (CIE_10 y COMPLICACION): duplicarla como
   `DIM_CIE_10_COMPLICACION` para que no se mezclen diagnósticos con complicaciones.
5. **"Sin dato" y "No aplica"** son valores reales en las dimensiones: excluirlos del
   denominador de los porcentajes y mostrar su % como indicador de calidad.
6. **Medidas base sugeridas:**
   - `Pacientes = DISTINCTCOUNT(FACT_TRAUMA[fact_id])`
   - `Fallecidos = CALCULATE([Pacientes], DIM_DESENLACE[disposicion_paciente] = "<valor de fallecido>")`
   - `Mortalidad % = DIVIDE([Fallecidos], [Pacientes])`
7. **Rangos y flags calculados en la FACT:** `rango_iss`, `gcs_total = ocular+verbal+motor`,
   `shock_index = frecuencia_cardiaca / presion_sistolica`, `rts`, `es_transfundido = sangre_l>0`,
   `es_uci = uci_dias>0`.

---------------------------------------------------------------------
## 2. ACTIVIDAD ASISTENCIAL
---------------------------------------------------------------------

**¿Cuántos pacientes de trauma hay hoy / 7 días / mes / año?**
- Relación: `DIM_TIEMPO` (admisión) -> `FACT_TRAUMA`.
- Cálculo: `Pacientes` filtrado por `DIM_TIEMPO[fecha]` (hoy, últimos 7 días, mes, año).
- Gráfico: **tarjetas KPI** con variación vs periodo anterior (`DATEADD`/`SAMEPERIODLASTYEAR`).

**¿Cuánto aumentó el trauma respecto al año pasado? ¿Tendencia de 12 meses?**
- Relación: `DIM_TIEMPO` -> `FACT_TRAUMA`.
- Cálculo: `Pacientes` por mes; comparar con `SAMEPERIODLASTYEAR`; % cambio.
- Gráfico: **línea de 12 meses** con la serie del año anterior superpuesta (o pequeños múltiplos por año).

**¿Qué días concentran mayor volumen?**
- Relación: `DIM_TIEMPO[dia_semana]`, `DIM_TIEMPO[es_festivo]` -> FACT.
- Cálculo: promedio de pacientes por día = `Pacientes / días distintos` en cada día de la semana (no sumar, normalizar por número de días).
- Gráfico: **barras por día de semana** (orden lunes-domingo) y **mapa de calor** semana × día; barras comparando festivo vs no festivo.

**Promedio diario / tendencia semanal**
- Cálculo: `DIVIDE([Pacientes], DISTINCTCOUNT(DIM_TIEMPO[fecha]))`.
- Gráfico: tarjeta + sparkline; línea semanal con media móvil.

*(Hora pico, por turno, últimas 24 h y última hora no se pueden responder: la FACT guarda solo la fecha de admisión, sin hora.)*

---------------------------------------------------------------------
## 3. SEVERIDAD
---------------------------------------------------------------------

**ISS promedio y % ISS > 15**
- Relación: solo `FACT_TRAUMA.iss`; filtros por `DIM_TIEMPO`.
- Cálculo: `AVERAGE(iss)`; `DIVIDE(CALCULATE([Pacientes], iss > 15), [Pacientes])`.
- Gráfico: **tarjetas** + **histograma de ISS**.

**Distribución por rango ISS (1–8, 9–15, 16–24, >25)**
- Cálculo: columna calculada `rango_iss` en la FACT.
- Gráfico: **barras apiladas al 100 % por año** (cómo cambia la severidad).

**AIS por región**
- Relación: FACT (`cabeza, cara, torax, abdomen, extremidades, externo`).
- Cálculo: % de pacientes con AIS ≥ 3 por región (despivotar las 6 columnas).
- Gráfico: **barras horizontales** ordenadas (o radar si son pocas categorías).

**GCS < 9**
- Relación: FACT + `DIM_CALIFICADOR_SIGNOS[calificador_gcs]`.
- Cálculo: `gcs_total = gcs_ocular + gcs_verbal + gcs_motor`; excluir/segmentar los calificados (intubado, sedado) para no inflar el indicador.
- Gráfico: tarjeta % GCS<9 + **histograma de GCS total**.

**PAS < 90 / Shock Index > 0.9 (pacientes en shock)**
- Relación: FACT (primera toma de vitales).
- Cálculo: `presion_sistolica < 90`; `shock_index = frecuencia_cardiaca / presion_sistolica > 0.9`.
- Gráfico: tarjetas + **dispersión PAS × FC** con línea de Shock Index 0.9.

**RTS**
- Cálculo: codificar GCS, PAS y FR en 0–4 y ponderar; guardar `rts` en la FACT.
- Gráfico: histograma, y **línea por año** de RTS promedio.

**Severidad por mecanismo**
- Relación: `DIM_MECANISMO_PRIMARIO` -> `BRIDGE_ATENCION_LESION` -> FACT.
- Cálculo: ISS por atención (cada atención una vez; el mecanismo está copiado a cada lesión).
- Gráfico: **boxplot de ISS por mecanismo**.

---------------------------------------------------------------------
## 4. MECANISMO DEL TRAUMA
---------------------------------------------------------------------

**¿Mecanismo más frecuente? Top 10 mecanismos**
- Relación: `DIM_MECANISMO_PRIMARIO` -> `BRIDGE_ATENCION_LESION` -> FACT.
- Cálculo: `Pacientes` (DISTINCT) por mecanismo, Top N.
- Gráfico: **barras horizontales ordenadas** (Top 10).

**Tendencias mensuales por mecanismo**
- Relación: lo anterior + `DIM_TIEMPO`.
- Gráfico: **áreas apiladas** o líneas (top 5 + "Otros").

**¿Qué % corresponde a motociclistas?**
- Relación: `DIM_ACCIDENTE_TRANSITO` -> FACT.
- Cálculo: `% = pacientes con tipo_vehiculo = moto / pacientes con accidente de tránsito` (excluir "No aplica").
- Gráfico: **tarjeta**; apoyo con **barras apiladas** de `ocupante` (conductor / pasajero / peatón) por `tipo_vehiculo`.

**Cerrado vs penetrante / ¿% trauma penetrante?**
- Relación: `DIM_TIPO_LESION` -> `BRIDGE_ATENCION_LESION` -> FACT; refuerzo con `DIM_ARMAS`.
- Cálculo: clasificar `tipo_lesion` (y arma de fuego/blanca) en penetrante/cerrado con una tabla de mapeo; contar pacientes distintos.
- Gráfico: **barras al 100 % por año**, tarjeta con %.

**Intención (accidental / violencia / autolesión)**
- Relación: `DIM_EVENTO_TRAUMA[violencia]`; autolesión desde `BRIDGE_ATENCION_CIE_10` con `rol = 'otro_mecanismo'` (códigos X60–X84).
- Gráfico: **barras apiladas** por año.

**Caídas, quemaduras, armas**
- `DIM_CAIDA` (+ `altura_metros`), `DIM_QUEMADURA` (+ `scq`), `DIM_ARMAS` -> FACT.
- Gráficos: barras por tipo/grado; **histograma de altura**; **dispersión SCQ × ISS**.

**Alcohol y sustancias**
- Relación: `DIM_EVENTO_TRAUMA[consumo_alcohol]`; `DIM_SUSTANCIA` -> `BRIDGE_ATENCION_SUSTANCIA` -> FACT.
- Gráfico: **barras de % con alcohol por mecanismo**; **mapa de calor** sustancia × mecanismo.

*(Uso de casco/cinturón no está en el modelo.)*

---------------------------------------------------------------------
## 5. LESIONES
---------------------------------------------------------------------

**Región anatómica**
- Relación: `DIM_PARTE_CUERPO_LESION` -> `BRIDGE_ATENCION_LESION` -> FACT.
- Cálculo: la parte del cuerpo trae lateralidad; agrupar en una columna calculada de región (cráneo, cara, tórax, abdomen, pelvis, columna, extremidades). `Pacientes` DISTINCT.
- Gráfico: **barras horizontales** o **silueta corporal con mapa de calor**.

**Top 20 lesiones / diagnósticos principales**
- Relación: `DIM_CIE_10` -> `BRIDGE_ATENCION_CIE_10` (filtrar `rol = 'diagnostico'`) -> FACT.
- Cálculo: `Pacientes` por código; agrupar por capítulo CIE-10 para el nivel superior.
- Gráfico: **barras horizontales Top 20** + **treemap** por capítulo.

**Parte del cuerpo × tipo de lesión**
- Relación: ambas dimensiones viven en la misma fila de `BRIDGE_ATENCION_LESION`.
- Gráfico: **matriz con mapa de calor**.

**Trauma craneoencefálico**
- Relación: `BRIDGE_ATENCION_CIE_10` (rol diagnóstico, código S06) o `FACT.cabeza ≥ 2`.
- Gráfico: tarjeta + barras por rango de GCS.

---------------------------------------------------------------------
## 6. FLUJO HOSPITALARIO
---------------------------------------------------------------------

**Destino del paciente**
- Relación: `DIM_DESENLACE[disposicion_paciente]` -> FACT.
- Gráfico: **barras apiladas por año** o **Sankey** (atención -> destino).

**¿Cuántos pacientes de trauma hay hospitalizados?**
- Relación: FACT (`fecha_hospitalizacion_id` con valor y alta sin fecha).
- Cálculo: atenciones con hospitalización y sin `fecha_alta_id` real (definir cómo la carga marca "sin alta").
- Gráfico: **tarjeta**.

**Estancia**
- Relación: FACT (`dias_hospitalizacion`).
- Cálculo: **mediana y P90**, no solo el promedio.
- Gráfico: **histograma** con líneas de mediana y P90.

**Tiempo en urgencias**
- Relación: `DIM_TIEMPO` (hospitalización) − `DIM_TIEMPO` (admisión) vía `USERELATIONSHIP`.
- Cálculo: días entre admisión y paso a hospitalización.
- Gráfico: **barras por rangos** (0, 1, 2, 3+ días).

---------------------------------------------------------------------
## 7. CIRUGÍA
---------------------------------------------------------------------

**Número de cirugías / cirugías hoy**
- Relación: `DIM_PROCEDIMIENTO` -> `BRIDGE_ATENCION_PROCEDIMIENTO` -> FACT; fecha por `fecha_inicio_id` -> `DIM_TIEMPO`.
- Cálculo: tabla de mapeo `procedimiento -> categoría (cirugía / no cirugía / tipo)`; contar procedimientos o atenciones distintas.
- Gráfico: **tarjeta** (hoy) + **barras por mes**.

**¿Cuántos pacientes recibieron laparotomía?**
- Cálculo: filtrar `DIM_PROCEDIMIENTO[procedimientos]` por texto (laparotomía); `Pacientes` DISTINCT.
- Gráfico: tarjeta + línea anual.

**Duración de cirugías**
- Relación: `BRIDGE_ATENCION_PROCEDIMIENTO[duracion_seg]`.
- Cálculo: segundos/60; mediana por tipo (excluir vacíos y reportar su %).
- Gráfico: **boxplot por tipo de procedimiento**.

**Horario de las cirugías**
- Relación: `hora_inicio_id` -> `DIM_HORARIO`.
- Gráfico: **mapa de calor día de semana × hora**.

**Tiempo a cirugía**
- Cálculo: `fecha_inicio` del procedimiento − `fecha_admision` (días).
- Gráfico: **histograma** 0 d / 1 d / 2+ d, mediana y P90.

**Reintervención / control de daños**
- Cálculo: más de una cirugía del mismo tipo por `fact_id` en una ventana de días; control de daños por texto del procedimiento.
- Gráfico: barras por año.

---------------------------------------------------------------------
## 8. MORTALIDAD
---------------------------------------------------------------------

**¿Cuál fue la mortalidad este mes? Mortalidad global**
- Relación: `DIM_DESENLACE` -> FACT; `DIM_TIEMPO` (admisión o alta).
- Cálculo: `Mortalidad %`.
- Gráfico: **tarjeta** + **gráfico de control** mensual (límites 3σ), porque con pocos casos la línea simple fluctúa.

**Mortalidad por ISS / ¿cuántos con ISS>25 sobrevivieron?**
- Relación: FACT (`rango_iss`) + `DIM_DESENLACE`.
- Gráfico: **barras de % por rango ISS** con N visible; tarjeta para ISS>25.

**Mortalidad por mecanismo / por trauma penetrante / en TCE**
- Relación: mecanismo (`BRIDGE_LESION`), tipo de lesión o `DIM_ARMAS`, o CIE-10 S06 — todos × `DIM_DESENLACE`.
- Gráfico: **barras ordenadas con N**; tarjetas para penetrante y TCE.

**Muertes potencialmente evitables**
- Relación: `DIM_DESENLACE[muerte_prevenible]`, `autopsia`, `donacion_organos`.
- Gráfico: **tarjeta + barras por año**.

**Momento de la muerte**
- Relación: `fecha_alta_id` (rol alta) + `hora_alta_id` -> `DIM_HORARIO`; días desde admisión.
- Gráfico: **histograma por día de estancia** y **mapa de calor** hora de egreso.

**Mortalidad ajustada (TRISS)**
- Cálculo: modelo con ISS, RTS, tipo de lesión y quinquenio; mortalidad observada vs esperada.
- Gráfico: **funnel plot** por año.

---------------------------------------------------------------------
## 9. RECURSOS
---------------------------------------------------------------------

**¿Cuántos pacientes requirieron transfusión (masiva)?**
- Relación: FACT (`sangre_l`).
- Cálculo: transfundido = `sangre_l > 0`; masiva con umbral de litros definido por el comité (el modelo no trae GR/plasma/plaquetas ni protocolo).
- Gráfico: tarjeta + **histograma de litros** + línea mensual.

**Pacientes en UCI / días UCI**
- Relación: FACT (`uci_dias`).
- Gráfico: **barras por mes** y **boxplot de días**.

---------------------------------------------------------------------
## 10. CALIDAD
---------------------------------------------------------------------

**Complicaciones**
- Relación: `DIM_CIE_10_COMPLICACION` -> `BRIDGE_ATENCION_COMPLICACION` -> FACT; `lugar_complicacion`.
- Cálculo: % de pacientes con ≥1 complicación; Top 10 por código.
- Gráfico: **barras Top 10** + **línea anual del %**.

**Eventos adversos (aproximación)**
- Cálculo: subconjunto de complicaciones + `muerte_prevenible`.
- Gráfico: línea de tasa.

**Calidad del dato**
- Cálculo: % "Sin dato" por columna; % de procedimientos sin duración; % CIE-10 "SIN CODIGO CIE-10".
- Gráfico: **barras de completitud**.

---------------------------------------------------------------------
## 11. EPIDEMIOLOGÍA
---------------------------------------------------------------------

**Pirámide poblacional**
- Relación: `DIM_PACIENTE` -> FACT.
- Cálculo: `Pacientes` por `quinquenio` y `genero`; ordenar por `quinquenio_orden`.
- Gráfico: **pirámide** (barras divergentes hombre/mujer).

**Sexo, tipo de seguro, nacionalidad**
- `DIM_PACIENTE` -> FACT. Gráfico: **barras**.

**Edad × mecanismo**
- Relación: `DIM_PACIENTE` + `DIM_MECANISMO_PRIMARIO` (vía puente). Gráfico: **mapa de calor**.

**Lugar del evento**
- `DIM_EVENTO_TRAUMA[lugar_evento]`. Gráfico: **barras**.

---------------------------------------------------------------------
## 12. DASHBOARD PRINCIPAL (tarjetas)
---------------------------------------------------------------------

| Tarjeta | Cálculo | Gráfico |
|---|---|---|
| Trauma hoy | `Pacientes` con fecha_admision = hoy | KPI |
| Trauma hospitalizados | atenciones con hospitalización y sin alta | KPI |
| Trauma en UCI | hospitalizados con `uci_dias > 0` | KPI |
| ISS promedio | `AVERAGE(iss)` | KPI |
| ISS > 15 (%) | ver sección 3 | KPI |
| GCS < 9 | ver sección 3 | KPI |
| Shock | Shock Index > 0.9 | KPI |
| Mortalidad | `Mortalidad %` | KPI + control chart |
| Cirugías hoy | procedimientos con `fecha_inicio_id` = hoy | KPI |

Cada tarjeta con **sparkline de 12 meses** y color de alerta solo cuando se pasa un umbral.

---------------------------------------------------------------------
## 13. FILTROS GLOBALES (segmentadores) y su relación
---------------------------------------------------------------------

| Filtro | Tabla / columna | Nota |
|---|---|---|
| Fecha, Año, Mes, Semana | DIM_TIEMPO (admisión activa) | |
| Sexo | DIM_PACIENTE[genero] | |
| Edad | DIM_PACIENTE[quinquenio] (orden por quinquenio_orden) | grupos de 5 años |
| EPS / seguro | DIM_PACIENTE[tipo_seguro], paciente_asegurado | |
| Mecanismo | DIM_MECANISMO_PRIMARIO | requiere filtro puente -> FACT |
| Tipo de trauma | DIM_TIPO_LESION | requiere filtro puente -> FACT |
| ISS | rango_iss (columna calculada) | |
| Alcohol / sustancia | DIM_EVENTO_TRAUMA / DIM_SUSTANCIA | |
| Diagnóstico | DIM_CIE_10 (rol diagnóstico) | |
| Procedimiento | DIM_PROCEDIMIENTO | |

---------------------------------------------------------------------
## 14. PREGUNTAS QUE EL MODELO NO PUEDE RESPONDER HOY
---------------------------------------------------------------------

| Pregunta | Qué falta |
|---|---|
| Hora pico, distribución por hora, por turno, última hora, últimas 24 h | hora de admisión (solo hay fecha) |
| Municipios, mapa, incidencia | ciudad/departamento |
| Esperando TAC / cirugía / cama UCI, ocupación | solicitudes con hora, camas |
| Tiempo a TAC | `BRIDGE_ATENCION_IMAGEN` no tiene fecha |
| Código Trauma, ATLS | no existen |
| Casco / cinturón | no existen |
| Ventilación mecánica | no existe |
| Reingresos, pacientes únicos | no hay identificador de paciente |
| Lugar de la muerte, especialidad quirúrgica | no existen |
| Sala de Situación en tiempo real | ubicación y vitales actuales no existen |

---------------------------------------------------------------------
## 15. PÁGINAS SUGERIDAS EN POWER BI
---------------------------------------------------------------------

1. **Ejecutivo**: tarjetas de la sección 12 + línea de 12 meses.
2. **Operativo**: hospitalizados, estancia, UCI, cirugías, días de mayor demanda.
3. **Epidemiológico**: pirámide, mecanismo, tendencia, alcohol/sustancias, lugar.
4. **Calidad**: mortalidad (control chart, por ISS, por mecanismo), complicaciones, completitud.
5. **Investigación**: matriz libre con todos los segmentadores y CIE-10/procedimientos.
