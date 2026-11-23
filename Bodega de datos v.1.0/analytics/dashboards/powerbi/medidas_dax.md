# Medidas DAX del reporte de Power BI (`trauma_completo`)

Estado: **propuesta para validación** (2026-11-04). Implementa los indicadores de [diseno_modulo_visualizacion.md](../../../docs/visualizacion/diseno_modulo_visualizacion.md) (secciones 4, 5 y 11). Se escribió a partir del DDL, de los dominios entregados por el autor del proyecto y de las pruebas de aceptación (`tests/acceptance_tests/`), sin consultar la bodega. Las reglas se alinearon con las de las pruebas TC-ACE para que el tablero y la prueba calculen lo mismo; las diferencias están en la sección 8.

## 1. Preparación del modelo

1. **Conexión.** Obtener datos > Base de datos PostgreSQL, modo Importar, credenciales del rol lector (`DB_READER_USER`). Las cuatro tablas con columnas excluidas (`fact_trauma`, `bridge_atencion_imagen`, `bridge_atencion_cie_10` y `bridge_atencion_complicacion`) se cargan con las consultas de [conexion_power_bi.sql](../../queries/conexion_power_bi.sql); las demás `dim_*` y `bridge_*`, desde el navegador.
2. **Nombres.** En Power Query, renombrar cada consulta con el nombre de la tabla sin el esquema (`fact_trauma`, `dim_tiempo`, etc.). Las fórmulas de este documento usan esos nombres.
3. **Relaciones.** Las de la sección 5 del diseño, todas de uno a muchos y con filtro en un solo sentido, salvo dos ajustes:
   - `fact_trauma[fecha_admision_id]` → `dim_tiempo[tiempo_id]` es la **activa**. Las de `fecha_alta_id` y `fecha_hospitalizacion_id` quedan **inactivas**.
   - `bridge_atencion_lesion[fact_id]` → `fact_trauma[fact_id]` con filtro **en ambos sentidos**. Es la única excepción: permite que el segmentador "Mecanismo" (`dim_mecanismo_primario`) filtre las atenciones.
4. **Tabla de medidas.** Introducir datos > tabla vacía llamada `Medidas`. Todas las medidas de la sección 5 van ahí, en carpetas de visualización con el nombre de cada subsección.
5. **Columnas y tabla calculadas.** Las de las secciones 3 y 4.

## 2. Convenciones

- **Atenciones, no filas.** Todo conteo usa `DISTINCTCOUNT(fact_id)`. En los puentes se cuenta `DISTINCTCOUNT(<puente>[fact_id])`, nunca `COUNTROWS`.
- **El vacío no es cero.** En DAX, `BLANK() < 9` es verdadero. Toda condición "menor que" lleva `NOT ISBLANK(...)`.
- **Textos.** En DAX la comparación de textos no distingue mayúsculas, pero sí acentos y espacios. Los dominios se escriben como los entregó el autor del proyecto.
- **Denominadores.** Cada porcentaje divide entre las atenciones con dato en esa variable, salvo que se indique otra cosa. `DIVIDE` devuelve vacío en lugar de dividir por cero.

## 3. Columnas calculadas

### `fact_trauma`

```dax
gcs_total =
IF (
    NOT ISBLANK ( fact_trauma[gcs_ocular] )
        && NOT ISBLANK ( fact_trauma[gcs_verbal] )
        && NOT ISBLANK ( fact_trauma[gcs_motor] ),
    fact_trauma[gcs_ocular] + fact_trauma[gcs_verbal] + fact_trauma[gcs_motor]
)
```

```dax
indice_choque =
IF (
    NOT ISBLANK ( fact_trauma[frecuencia_cardiaca] )
        && NOT ISBLANK ( fact_trauma[presion_sistolica] )
        && fact_trauma[presion_sistolica] > 0,
    DIVIDE ( fact_trauma[frecuencia_cardiaca], fact_trauma[presion_sistolica] )
)
```

```dax
rango_iss =
SWITCH (
    TRUE (),
    ISBLANK ( fact_trauma[iss] ) || fact_trauma[iss] < 1, "Sin ISS",
    fact_trauma[iss] <= 8, "1–8",
    fact_trauma[iss] <= 15, "9–15",
    fact_trauma[iss] <= 24, "16–24",
    "25 o más"
)
```

```dax
rango_iss_orden =
SWITCH ( fact_trauma[rango_iss], "1–8", 1, "9–15", 2, "16–24", 3, "25 o más", 4, 5 )
```

Ordenar `rango_iss` por `rango_iss_orden` (Herramientas de columna > Ordenar por columna). Un ISS vacío o menor que 1 queda en "Sin ISS", igual que en TC-ACE-07.

```dax
dias_admision_alta =
VAR admision =
    LOOKUPVALUE ( dim_tiempo[fecha], dim_tiempo[tiempo_id], fact_trauma[fecha_admision_id] )
VAR alta =
    LOOKUPVALUE ( dim_tiempo[fecha], dim_tiempo[tiempo_id], fact_trauma[fecha_alta_id] )
RETURN
    IF ( NOT ISBLANK ( admision ) && NOT ISBLANK ( alta ), INT ( alta - admision ) )
```

Días enteros entre dos fechas, como TC-ACE-15. `LOOKUPVALUE` evita depender de la relación activa. Incluye las estancias negativas (alta anterior a la admisión), igual que la prueba; ver sección 8.

### `dim_desenlace`

```dax
grupo_destino =
VAR d = TRIM ( dim_desenlace[disposicion_paciente] )
RETURN
    SWITCH (
        TRUE (),
        ISBLANK ( d ) || d IN { "Sin dato", "Desconocido" }, "Sin información",
        d IN { "Fallece (Morgue)", "Murió antes de la llegada", "Murió en el Departamento de emergencias" }, "Fallecido",
        d = "Admitido a la UCI", "UCI",
        d = "Sala de Operaciones", "Quirófano",
        LEFT ( d, 9 ) = "Internado", "Hospitalización",
        d IN { "Domicilio", "Consulta externa" }, "Alta",
        LEFT ( d, 8 ) = "Referido" || LEFT ( d, 11 ) = "Transferido", "Traslado a otro hospital",
        "Otros"
    )
```

`TRIM` en DAX elimina los espacios de los extremos y deja un solo espacio entre palabras, así que `Fallece  (Morgue)` (dos espacios) y `Fallece (Morgue)` (uno) caen en el mismo grupo. "Otros" agrupa `Otros` y `Sale contra el consejo médico`.

### `dim_armas`

```dax
con_arma_fuego =
IF (
    NOT ISBLANK ( dim_armas[lesion_arma_fuego] )
        && NOT ( dim_armas[lesion_arma_fuego] IN { "No aplica", "Sin dato" } ),
    "Sí",
    "No"
)
```

```dax
con_arma_cortopunzante =
IF (
    NOT ISBLANK ( dim_armas[lesion_arma_blanca] )
        && NOT ( dim_armas[lesion_arma_blanca] IN { "No aplica", "Sin dato" } ),
    "Sí",
    "No"
)
```

Misma regla que TC-ACE-01 y TC-ACE-09 para el mecanismo de arma. Cada columna alimenta un botón del filtro rápido (segmentador en estilo de botón, con el valor "Sí").

### `dim_tiempo`

```dax
tipo_dia =
SWITCH (
    TRUE (),
    dim_tiempo[es_festivo] = "SI", "Festivos",
    WEEKDAY ( dim_tiempo[fecha], 2 ) >= 6, "Sábado y domingo",
    "Lunes a viernes"
)
```

```dax
dia_semana_orden = WEEKDAY ( dim_tiempo[fecha], 2 )
```

Ordenar `dia_semana` por `dia_semana_orden`. `tipo_dia` usa la fecha y no el texto de `dia_semana`, así no depende de cómo se escribió el nombre del día.

## 4. Tabla calculada `Mecanismos`

Las cinco familias de mecanismo viven en cuatro dimensiones, y un eje de gráfico solo admite una columna. Esta tabla, sin relaciones, da el eje de "Atenciones por mecanismo" y "Mortalidad por mecanismo".

```dax
Mecanismos =
DATATABLE (
    "mecanismo", STRING,
    "orden", INTEGER,
    {
        { "Caída", 1 },
        { "Quemadura", 2 },
        { "Tránsito: motocicleta", 3 },
        { "Tránsito: otro vehículo", 4 },
        { "Arma de fuego", 5 },
        { "Arma cortopunzante", 6 }
    }
)
```

Un mecanismo está presente con la misma regla de TC-ACE-01: el grupo no es la combinación `No aplica` (caída, quemadura y tránsito se juzgan por su primera columna) y, en las armas, la columna propia no es `No aplica` ni `Sin dato`. Una atención cuenta en cada mecanismo que tenga. Motocicleta y otro vehículo suman el total de tránsito de TC-ACE-01.

## 5. Medidas

### Volumen

```dax
Atenciones = DISTINCTCOUNT ( fact_trauma[fact_id] )
```

```dax
% de atenciones =
DIVIDE ( [Atenciones], CALCULATE ( [Atenciones], ALLSELECTED ( dim_paciente ) ) )
```

```dax
Promedio diario =
VAR primera = CALCULATE ( MIN ( dim_tiempo[fecha] ), fact_trauma )
VAR ultima = CALCULATE ( MAX ( dim_tiempo[fecha] ), fact_trauma )
VAR dias =
    COUNTROWS (
        FILTER ( VALUES ( dim_tiempo[fecha] ), dim_tiempo[fecha] >= primera && dim_tiempo[fecha] <= ultima )
    )
RETURN
    DIVIDE ( [Atenciones], dias )
```

Divide entre los días del calendario que van de la primera a la última admisión del periodo filtrado, incluidos los días sin atenciones. Con `tipo_dia` en el eje da el promedio por lunes a viernes, fin de semana y festivos.

```dax
Atenciones por mecanismo =
SWITCH (
    SELECTEDVALUE ( Mecanismos[mecanismo] ),
    "Caída",
        CALCULATE ( [Atenciones], dim_caida[caida] <> "No aplica", NOT ISBLANK ( dim_caida[caida] ) ),
    "Quemadura",
        CALCULATE ( [Atenciones], dim_quemadura[quemadura] <> "No aplica", NOT ISBLANK ( dim_quemadura[quemadura] ) ),
    "Tránsito: motocicleta",
        CALCULATE (
            [Atenciones],
            dim_accidente_transito[velocidad_colision] <> "No aplica",
            NOT ISBLANK ( dim_accidente_transito[velocidad_colision] ),
            dim_accidente_transito[tipo_vehiculo] = "Motocicleta"
        ),
    "Tránsito: otro vehículo",
        CALCULATE (
            [Atenciones],
            dim_accidente_transito[velocidad_colision] <> "No aplica",
            NOT ISBLANK ( dim_accidente_transito[velocidad_colision] ),
            dim_accidente_transito[tipo_vehiculo] <> "Motocicleta"
        ),
    "Arma de fuego", CALCULATE ( [Atenciones], dim_armas[con_arma_fuego] = "Sí" ),
    "Arma cortopunzante", CALCULATE ( [Atenciones], dim_armas[con_arma_cortopunzante] = "Sí" )
)
```

### Severidad

```dax
ISS promedio = AVERAGE ( fact_trauma[iss] )
```

```dax
Atenciones con ISS = CALCULATE ( [Atenciones], fact_trauma[iss] >= 1 )
```

```dax
% ISS ≥ 16 = DIVIDE ( CALCULATE ( [Atenciones], fact_trauma[iss] >= 16 ), [Atenciones con ISS] )
```

```dax
Atenciones con GCS = CALCULATE ( [Atenciones], NOT ISBLANK ( fact_trauma[gcs_total] ) )
```

```dax
% GCS < 9 =
DIVIDE (
    CALCULATE ( [Atenciones], fact_trauma[gcs_total] < 9, NOT ISBLANK ( fact_trauma[gcs_total] ) ),
    [Atenciones con GCS]
)
```

```dax
% PAS < 90 =
DIVIDE (
    CALCULATE ( [Atenciones], fact_trauma[presion_sistolica] < 90, NOT ISBLANK ( fact_trauma[presion_sistolica] ) ),
    CALCULATE ( [Atenciones], NOT ISBLANK ( fact_trauma[presion_sistolica] ) )
)
```

```dax
% índice de choque > 0,9 =
DIVIDE (
    CALCULATE ( [Atenciones], fact_trauma[indice_choque] > 0.9 ),
    CALCULATE ( [Atenciones], NOT ISBLANK ( fact_trauma[indice_choque] ) )
)
```

Signos vitales (promedio de la primera toma), una medida por fila de la tabla de la página 3:

```dax
PAS promedio = AVERAGE ( fact_trauma[presion_sistolica] )
PAD promedio = AVERAGE ( fact_trauma[presion_diastolica] )
FC promedio = AVERAGE ( fact_trauma[frecuencia_cardiaca] )
FR promedio = AVERAGE ( fact_trauma[frecuencia_respiratoria] )
Saturación promedio = AVERAGE ( fact_trauma[saturacion_o2] )
Temperatura promedio = AVERAGE ( fact_trauma[temperatura_c] )
GCS promedio = AVERAGE ( fact_trauma[gcs_total] )
```

AIS promedio por región, una medida por región:

```dax
AIS cabeza = AVERAGE ( fact_trauma[cabeza] )
AIS cara = AVERAGE ( fact_trauma[cara] )
AIS tórax = AVERAGE ( fact_trauma[torax] )
AIS abdomen = AVERAGE ( fact_trauma[abdomen] )
AIS extremidades = AVERAGE ( fact_trauma[extremidades] )
AIS externo = AVERAGE ( fact_trauma[externo] )
```

`AVERAGE` ignora los vacíos, así que cada promedio es sobre las atenciones con ese dato.

### Resultado

```dax
Fallecidos = CALCULATE ( [Atenciones], dim_desenlace[grupo_destino] = "Fallecido" )
```

```dax
Atenciones con destino conocido =
CALCULATE ( [Atenciones], dim_desenlace[grupo_destino] <> "Sin información" )
```

```dax
Mortalidad = DIVIDE ( [Fallecidos], [Atenciones con destino conocido] )
```

Con `rango_iss` en el eje da la mortalidad por rango de ISS; con `dim_mecanismo_primario[mecanismo_primario]` da la mortalidad por trauma contuso, penetrante y quemaduras; con `dim_desenlace[muerte_prevenible]` y la medida `Fallecidos` da las muertes según prevenibilidad.

```dax
Mortalidad por mecanismo =
SWITCH (
    SELECTEDVALUE ( Mecanismos[mecanismo] ),
    "Caída",
        CALCULATE ( [Mortalidad], dim_caida[caida] <> "No aplica", NOT ISBLANK ( dim_caida[caida] ) ),
    "Quemadura",
        CALCULATE ( [Mortalidad], dim_quemadura[quemadura] <> "No aplica", NOT ISBLANK ( dim_quemadura[quemadura] ) ),
    "Tránsito: motocicleta",
        CALCULATE (
            [Mortalidad],
            dim_accidente_transito[velocidad_colision] <> "No aplica",
            NOT ISBLANK ( dim_accidente_transito[velocidad_colision] ),
            dim_accidente_transito[tipo_vehiculo] = "Motocicleta"
        ),
    "Tránsito: otro vehículo",
        CALCULATE (
            [Mortalidad],
            dim_accidente_transito[velocidad_colision] <> "No aplica",
            NOT ISBLANK ( dim_accidente_transito[velocidad_colision] ),
            dim_accidente_transito[tipo_vehiculo] <> "Motocicleta"
        ),
    "Arma de fuego", CALCULATE ( [Mortalidad], dim_armas[con_arma_fuego] = "Sí" ),
    "Arma cortopunzante", CALCULATE ( [Mortalidad], dim_armas[con_arma_cortopunzante] = "Sí" )
)
```

### Recursos y estancia

```dax
Atenciones con UCI = CALCULATE ( [Atenciones], fact_trauma[uci_dias] > 0 )
```

```dax
% con UCI =
DIVIDE ( [Atenciones con UCI], CALCULATE ( [Atenciones], NOT ISBLANK ( fact_trauma[uci_dias] ) ) )
```

```dax
Atenciones con procedimiento = DISTINCTCOUNT ( bridge_atencion_procedimiento[fact_id] )
```

```dax
% con procedimiento = DIVIDE ( [Atenciones con procedimiento], [Atenciones] )
```

```dax
Atenciones con imagen = DISTINCTCOUNT ( bridge_atencion_imagen[fact_id] )
```

```dax
% con imagen = DIVIDE ( [Atenciones con imagen], [Atenciones] )
```

```dax
Transfundidos = CALCULATE ( [Atenciones], fact_trauma[sangre_l] > 0 )
```

```dax
% transfundidos =
DIVIDE ( [Transfundidos], CALCULATE ( [Atenciones], NOT ISBLANK ( fact_trauma[sangre_l] ) ) )
```

```dax
Litros de sangre = SUM ( fact_trauma[sangre_l] )
```

```dax
Días de hospitalización (promedio) = AVERAGE ( fact_trauma[dias_hospitalizacion] )
```

```dax
Días de UCI (promedio) = AVERAGE ( fact_trauma[uci_dias] )
```

```dax
Días de hospitalización por mes de alta =
CALCULATE ( [Días de hospitalización (promedio)], USERELATIONSHIP ( fact_trauma[fecha_alta_id], dim_tiempo[tiempo_id] ) )
```

```dax
Días de UCI por mes de alta =
CALCULATE ( [Días de UCI (promedio)], USERELATIONSHIP ( fact_trauma[fecha_alta_id], dim_tiempo[tiempo_id] ) )
```

```dax
Estancia admisión–alta (promedio) = AVERAGE ( fact_trauma[dias_admision_alta] )
```

`Días de UCI (promedio)` incluye los ceros, igual que TC-ACE-03. Las versiones "por mes de alta" cambian la fecha del eje a la de alta.

### Diagnósticos, lesiones y contexto

Con el catálogo correspondiente en el eje (o en una tabla de top N), cada medida cuenta atenciones distintas:

```dax
Atenciones con diagnóstico =
CALCULATE ( DISTINCTCOUNT ( bridge_atencion_cie_10[fact_id] ), bridge_atencion_cie_10[rol] = "diagnostico" )
```

```dax
Atenciones con comorbilidad =
CALCULATE ( DISTINCTCOUNT ( bridge_atencion_cie_10[fact_id] ), bridge_atencion_cie_10[rol] = "comorbilidad" )
```

```dax
Atenciones con complicación = DISTINCTCOUNT ( bridge_atencion_complicacion[fact_id] )
```

```dax
Atenciones con lesión = DISTINCTCOUNT ( bridge_atencion_lesion[fact_id] )
```

```dax
Atenciones con sustancia = DISTINCTCOUNT ( bridge_atencion_sustancia[fact_id] )
```

```dax
% violencia =
DIVIDE (
    CALCULATE (
        [Atenciones],
        dim_evento_trauma[violencia] IN { "Abuso físico", "Abuso psicológico", "Abuso sexual", "Sospecha de violencia" }
    ),
    [Atenciones]
)
```

```dax
% autolesión = DIVIDE ( CALCULATE ( [Atenciones], dim_evento_trauma[violencia] = "Intento de suicidio" ), [Atenciones] )
```

```dax
% consumo de alcohol =
DIVIDE (
    CALCULATE ( [Atenciones], dim_evento_trauma[consumo_alcohol] = "Si" ),
    CALCULATE ( [Atenciones], dim_evento_trauma[consumo_alcohol] IN { "Si", "No" } )
)
```

```dax
Cobertura consumo de alcohol =
DIVIDE ( CALCULATE ( [Atenciones], dim_evento_trauma[consumo_alcohol] IN { "Si", "No" } ), [Atenciones] )
```

Dominio de `consumo_alcohol` (2026-11-04): `Si`, `No`, `No especificado`, `No disponible` y `Sin dato`. `Si` va **sin tilde**, como está en la bodega; DAX distingue acentos. El denominador son las atenciones con `Si` o `No`: las tres categorías sin información no entran, y la medida de cobertura muestra qué parte de las atenciones las tiene.

```dax
% trauma penetrante =
DIVIDE (
    CALCULATE ( [Atenciones con lesión], dim_mecanismo_primario[mecanismo_primario] = "Penetrante" ),
    CALCULATE ( [Atenciones con lesión], dim_mecanismo_primario[mecanismo_primario] <> "Sin dato" )
)
```

### Cobertura

Se muestran junto a los filtros de mecanismo y de arma, para que se vea qué parte de las atenciones puede clasificarse.

```dax
Cobertura del mecanismo primario =
DIVIDE ( CALCULATE ( [Atenciones con lesión], dim_mecanismo_primario[mecanismo_primario] <> "Sin dato" ), [Atenciones] )
```

```dax
Cobertura arma de fuego =
DIVIDE ( CALCULATE ( [Atenciones], dim_armas[lesion_arma_fuego] <> "Sin dato" ), [Atenciones] )
```

```dax
Cobertura arma cortopunzante =
DIVIDE ( CALCULATE ( [Atenciones], dim_armas[lesion_arma_blanca] <> "Sin dato" ), [Atenciones] )
```

### Demografía

```dax
Pirámide =
IF ( SELECTEDVALUE ( dim_paciente[genero] ) = "Masculino", - [% de atenciones], [% de atenciones] )
```

Gráfico de barras horizontales apiladas con `quinquenio` en el eje (ordenado por `quinquenio_orden`) y `genero` en la leyenda. Formato de la medida `0.0 %;0.0 %` para que el lado negativo se muestre sin signo. Los hombres (`genero` = `Masculino`, confirmado el 2026-11-04) van a la izquierda.

### Cargas de la bodega (página 5)

Requieren aplicar [propuesta_cambios_ddl_lector_control.md](../../../docs/modelo/propuesta_cambios_ddl_lector_control.md) y cargar `carga` y `calidad` con las consultas de la sección 5 de `conexion_power_bi.sql`. La página no responde a los segmentadores (Formato > Editar interacciones).

```dax
Última carga exitosa =
CALCULATE ( MAX ( carga[ejecutado_en] ), carga[exitosa] = TRUE (), carga[modelo] = "completo" )
```

```dax
Último veredicto =
VAR ultima = CALCULATE ( MAX ( calidad[ejecutado_en] ), calidad[modelo] = "completo" )
RETURN
    CALCULATE ( SELECTEDVALUE ( calidad[veredicto] ), calidad[ejecutado_en] = ultima, calidad[modelo] = "completo" )
```

```dax
Reglas que cumplen (última) =
VAR ultima = CALCULATE ( MAX ( calidad[ejecutado_en] ), calidad[modelo] = "completo" )
RETURN
    CALCULATE ( SUM ( calidad[reglas_cumplen] ), calidad[ejecutado_en] = ultima, calidad[modelo] = "completo" )
```

`Reglas que advierten (última)` y `Reglas que fallan (última)` siguen el mismo patrón con `reglas_advierten` y `reglas_fallan`. Las tablas de reconciliación y de atenciones por carga usan las columnas de `carga` directamente.

## 6. Correspondencia con las pruebas de aceptación

| Prueba | Medida o columna del tablero |
|---|---|
| TC-ACE-01 | `Atenciones por mecanismo` con año y mes de admisión |
| TC-ACE-02 | `% de atenciones` por `quinquenio` y `genero` |
| TC-ACE-03 | `Días de hospitalización por mes de alta` y `Días de UCI por mes de alta` |
| TC-ACE-04 | `Atenciones` por `disposicion_paciente` (etiqueta original, antes de agrupar) |
| TC-ACE-05 | `Atenciones con diagnóstico` por `dim_cie_10[cie_10]` |
| TC-ACE-06 | Franja horaria de alta: no se muestra en el tablero |
| TC-ACE-07 | `Atenciones` por `rango_iss` |
| TC-ACE-08 | `% GCS < 9`, `% PAS < 90` y `% índice de choque > 0,9` (sus numeradores) |
| TC-ACE-09 | `Mortalidad` por `rango_iss` y `Mortalidad por mecanismo` (ver sección 8) |
| TC-ACE-10 | `Atenciones con UCI` y `Atenciones con procedimiento` |
| TC-ACE-11 | `Atenciones con lesión` por `dim_parte_cuerpo_lesion[parte_cuerpo]` |
| TC-ACE-12 | `Transfundidos` y `Litros de sangre` |
| TC-ACE-13 | `Atenciones con imagen` por `dim_imagen[tipo_imagen]` |
| TC-ACE-14 | `Atenciones con sustancia` por `dim_sustancia[sustancia]` |
| TC-ACE-15 | `Estancia admisión–alta (promedio)` por año y mes de admisión |

## 7. Validación manual en Power BI

Para cada fila de la sección 6, comparar el valor del visual con la consulta SQL de la prueba correspondiente, ejecutada con el rol lector sobre la misma bodega. La diferencia debe estar dentro de las tolerancias de D-11. Se registra en la guía de uso con fecha, filtros aplicados y resultado; no se copian valores de pacientes.

## 8. Diferencias con las pruebas y pendientes

**Decisión del autor del proyecto (2026-11-04):** las diferencias 1 a 3 se mantienen como están. Quedan documentadas aquí como limitaciones conocidas y no se cambian ni el tablero ni las pruebas.

1. **`Fallece (Morgue)`.** El dominio entregado trae dos espacios (`Fallece  (Morgue)`); TC-ACE-09 siembra uno. `grupo_destino` usa `TRIM` y funciona con ambas formas. Falta confirmar cuál es el valor real; si es el de dos espacios, la consulta SQL de TC-ACE-09 contaría 0 muertes con esa etiqueta sobre la bodega real.
2. **Denominador de la mortalidad.** El tablero excluye `Sin dato` y `Desconocido`; TC-ACE-09 excluye solo `Sin dato`. Hoy la prueba pasa porque no siembra `Desconocido`, pero las dos definiciones difieren. Recomendación: excluir también `Desconocido` en TC-ACE-09 y sembrarlo.
3. **Estancias negativas.** `dias_admision_alta` incluye las altas anteriores a la admisión (QR-CON-01, que advierte) porque TC-ACE-15 también las incluye. Si se decide excluirlas, el cambio va en las dos partes a la vez: en la columna, la condición `alta >= admision`, y en la prueba, el filtro equivalente.
4. **Valores por confirmar.** Si `dim_sustancia` incluye un valor del tipo "ninguna" que no deba contar; y el texto exacto de `modelo` en `etl_control` (se asumió `completo`).
5. **Significado del vacío.** `% con UCI` y `% transfundidos` dividen entre las atenciones con dato. Si el vacío significa "no tuvo", el denominador debe ser `[Atenciones]`.
6. **ISS no entero.** `rango_iss` asigna un ISS decimal (por ejemplo 8,5) al rango siguiente, mientras que la consulta de TC-ACE-07 lo deja en "sin ISS". Con ISS entero, que es lo esperado, no hay diferencia.
