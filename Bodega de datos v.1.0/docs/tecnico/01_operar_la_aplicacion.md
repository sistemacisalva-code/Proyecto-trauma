# 01. Operar la aplicación

Supone la aplicación instalada y el archivo `.env` configurado (ver el [README del proyecto](../../README.md), secciones 5 y 6).

Todos los comandos se ejecutan desde la carpeta del proyecto, con el entorno virtual activo:

```powershell
.\venv\Scripts\Activate.ps1
```

## 1. Actualización normal (lo habitual)

```bash
python -m etl.pipeline --mode=all
```

Hace en orden: extracción de REDCap (y del Excel, si nunca se ha cargado), transformación, carga y revisión de calidad. Si ya hay una actualización en curso, la segunda se niega a empezar.

| Opción | Cuándo usarla |
|---|---|
| `--sin-extraccion` | No hay conexión con REDCap y se quiere reprocesar lo que ya se extrajo |
| `--sin-excel` | Se quiere dejar el Excel histórico fuera de esta corrida |

**Al terminar, revise:**
1. El final del mensaje en pantalla: dice el veredicto y, si algo falla o advierte, qué regla es y cuántas filas afecta.
2. El código de salida: `0` si la carga se aceptó; `2` si el veredicto es "Rechazada". Un programador de tareas puede usarlo para avisar.

## 2. Pasos sueltos

Útiles cuando se cambió una regla y no hace falta repetir todo.

| Paso | Comando | Nota |
|---|---|---|
| Extraer el Excel | `python -m etl.pipeline --mode=excel-registro-antiguo` | Una sola vez; `--force` lo repite |
| Extraer REDCap | `python -m etl.pipeline --mode=redcap` | Solo trae lo modificado desde la última extracción exitosa |
| Transformar | `python -m etl.pipeline --mode=transform-excel` o `--mode=transform-redcap` | Reemplaza el staging de esa fuente |
| Cargar | `python -m etl.pipeline --mode=load --modelo completo --fuente excel` (o `redcap`) | Solo escribe las atenciones que cambiaron |
| Revisar la calidad | `python -m etl.quality --modelo completo` | No modifica la bodega; solo escribe el reporte y el veredicto |

**El orden importa:** transformar, después cargar y, al final, revisar la calidad. Si se revisa la calidad sin haber cargado, varias reglas fallan porque la bodega está vacía.

Opciones de la carga:
- `--full-refresh`: reescribe todas las atenciones de la fuente, no solo las que cambiaron. Úsela si sospecha que la bodega quedó desalineada.
- `--force`: solo para el Excel. El histórico se carga una vez; `--force` lo vuelve a cargar si su transformación cambió.

## 3. Dónde quedan los resultados

Todo queda dentro de `data/`, que no se sube al repositorio:

| Carpeta | Contenido | ¿Se comparte? |
|---|---|---|
| `data/quality_reports/<fuente>/run_id=.../` | Reporte de la transformación: `reporte.md` con conteos | Sí, `reporte.md` |
| La misma carpeta, `para_correccion.md` y `.csv` | Códigos de los registros a corregir en la fuente, con campo y motivo | **No: confidencial** |
| `data/quality_reports/warehouse/completo/carga_id=.../` | Reporte de calidad de la bodega: `reporte.md` y CSV por sección | Sí |
| `data/quarantine/completo/<fuente>/run_id=.../` | Filas que no entraron a la bodega, con la regla que incumplieron | **No** |
| `data/staging/<fuente>/` | Datos transformados listos para cargar | **No** |

En la base de datos, el esquema `etl_control` guarda la historia:
- `etl_control.extraccion`: cada extracción.
- `etl_control.carga` y `etl_control.carga_detalle`: cada carga y su balance por tabla (leídas, cargadas, otra toma, sin valor, duplicadas y en cuarentena).
- `etl_control.calidad`: cada veredicto con sus conteos.

## 4. Después de una carga "Aprobada con advertencias"

1. Abra el reporte de calidad de la bodega y busque las reglas que advierten.
2. Abra `para_correccion.md` de la transformación: lista los registros que el equipo de registro debe corregir en la fuente.
3. Envíe ese listado por el canal autorizado. No lo adjunte en correos abiertos ni lo suba a repositorios.
4. Cuando la fuente esté corregida, la siguiente actualización trae los datos nuevos y la carga los reemplaza.

## 5. Después de una carga "Rechazada"

Una regla que falla indica un error de la aplicación o del modelo, no de la fuente.

1. Lea en el mensaje final qué regla falla.
2. No use esa actualización en el tablero.
3. Busque la regla en el manual [Problemas frecuentes](03_problemas_frecuentes.md). Si no está, revise los últimos cambios de reglas o de configuración.
4. Corregida la causa, vuelva a cargar la fuente (con `--full-refresh` si hace falta) y revise de nuevo la calidad.

## 6. Pruebas antes de cambiar algo

Antes y después de modificar una regla o un archivo de configuración, ejecute las pruebas rápidas:

```bash
python -m pytest -m unit
```

Las pruebas usan solo datos inventados. Las que requieren base de datos crean y borran una base propia, cuyo nombre debe terminar en `_test`.
