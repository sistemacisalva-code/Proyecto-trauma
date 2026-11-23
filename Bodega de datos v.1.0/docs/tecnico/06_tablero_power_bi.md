# 06. Tablero de Power BI: crearlo y conectarlo

Cómo generar el proyecto del tablero, conectarlo a la bodega y mantenerlo actualizado. Los indicadores de cada página se describen en la sección 6.

## 1. Cómo funciona

El tablero no se guarda en el repositorio. Un script lo **genera sin datos**: tablas, relaciones, medidas y páginas. Los datos llegan cuando usted lo abre en Power BI Desktop, escribe las credenciales y pulsa Actualizar.

Después de actualizar, el archivo **contiene datos de la bodega**. Por eso:

- se genera siempre en una carpeta **fuera** del proyecto (el script se niega a escribir dentro);
- no se sube a GitHub, ni se envía por correo o por canales abiertos;
- las credenciales se escriben solo en Power BI y nunca quedan en el archivo del proyecto.

## 2. Antes de empezar

| Requisito | Detalle |
|---|---|
| Power BI Desktop | En Windows, con el formato de proyecto `.pbip`. Si su versión lo pide, active en *Archivo > Opciones y configuración > Opciones > Características en versión preliminar* el guardado como proyecto de Power BI y el formato TMDL |
| Bodega cargada | Al menos una carga exitosa y una revisión de calidad ([Operar la aplicación](01_operar_la_aplicacion.md)) |
| Usuario lector | Creado con los permisos de la base (`database/schema/04_permissions.sql`). Su usuario y contraseña están en el `.env` del equipo (`DB_READER_USER` y `DB_READER_PASSWORD`, o las variables `_PROD` en producción) |
| Acceso de red | El equipo con Power BI debe llegar al servidor de PostgreSQL y a su puerto |

El usuario lector solo puede leer, y no ve las columnas de texto clínico libre ni la llave de negocio de la atención. Es el único usuario que debe usar el tablero estándar.

## 3. Generar el proyecto

Desde la carpeta del proyecto, con el entorno virtual activo:

```bash
python analytics/dashboards/powerbi/generar_pbip.py "C:\Tableros\trauma" --sin-control
```

| Opción | Cuándo usarla |
|---|---|
| (ninguna) | Tablero estándar con la página "Cargas de la bodega". Requiere que el lector tenga permiso de lectura sobre `etl_control.carga` y `etl_control.calidad` |
| `--sin-control` | **Hoy es la opción a usar:** ese permiso todavía no está aplicado en la base. Genera el tablero sin la página de cargas |
| `--variante admin` | Copia restringida con el texto libre (sección 7) |

Al terminar, el script muestra la carpeta, la variante y cuántas páginas y visuales generó. En la carpeta quedan:

```
C:\Tableros\trauma\
├── Trauma.pbip              el archivo que se abre
├── Trauma.SemanticModel\    tablas, relaciones, medidas y parámetros de conexión
└── Trauma.Report\           páginas y visuales
```

Si vuelve a generar el proyecto en la misma carpeta, se reemplaza la definición, pero hay que volver a actualizar los datos.

## 4. Conectar el tablero a la bodega

### Paso 1. Abrir el proyecto
Abra `Trauma.pbip` con doble clic o desde *Archivo > Abrir*. Las páginas aparecen vacías o con errores: todavía no hay conexión.

### Paso 2. Indicar el servidor y la base
1. *Inicio > Transformar datos > Editar parámetros*.
2. **Servidor:** el equipo y el puerto de PostgreSQL, en la forma `equipo:puerto`, por ejemplo `localhost:5432`. Son los valores de `DB_HOST` y `DB_PORT` del `.env` (o `DB_HOST_PROD` y `DB_PORT_PROD`).
3. **BaseDatos:** el nombre de la base. Es `DB_NAME_PROD` en producción o `DB_NAME_DEV` en desarrollo. **Nunca** la base de pruebas, que termina en `_test` y solo tiene datos inventados.
4. Acepte. Power BI pedirá aplicar los cambios: hágalo después de escribir las credenciales (paso 3).

### Paso 3. Escribir las credenciales
1. *Archivo > Opciones y configuración > Configuración de origen de datos*.
2. Seleccione el origen de PostgreSQL con el servidor y la base del paso 2 y pulse *Editar permisos*.
3. En *Credenciales > Editar*, elija **Base de datos** y escriba el usuario y la contraseña **del lector**.
4. Deje marcada la opción de cifrar la conexión si el servidor tiene SSL configurado. Si el servidor no lo admite, Power BI mostrará un aviso y ofrecerá conectar sin cifrar. Aceptarlo solo es razonable si la base está en el mismo equipo o en una red interna del hospital.
5. **Nivel de privacidad:** *Organizativo*.

### Paso 4. Aprobar las consultas
Algunas tablas (la tabla de hechos, los diagnósticos, las complicaciones, las imágenes y, si existe la página de cargas, la bitácora) se leen con una consulta SQL que pide solo las columnas que el lector puede ver. Power BI pide aprobar cada una la primera vez: **apruébelas**. Las mismas consultas están, para revisión, en `analytics/queries/conexion_power_bi.sql`.

### Paso 5. Actualizar
*Inicio > Actualizar*. La primera vez puede tardar unos minutos. Al terminar, las páginas muestran los datos.

### Paso 6. Comprobar que quedó bien conectado
- La tarjeta de atenciones de la página "Demografía", sin filtros, debe coincidir con el número de atenciones de la bodega: es la suma de las atenciones de las dos fuentes en la última carga.
- Ningún visual debe mostrar un error ni una "X" gris.
- Con la página de cargas, el último veredicto debe ser el mismo del reporte de calidad más reciente.

### Paso 7. Guardar
*Archivo > Guardar*. El proyecto queda en la carpeta de la sección 3, ya con datos.

## 5. Mantenerlo actualizado

- **Después de cada carga:** abra el proyecto y pulse *Actualizar*. El tablero no se actualiza solo.
- **Si el veredicto de la carga fue "Rechazada":** no actualice el tablero hasta que la causa esté resuelta ([Operar la aplicación](01_operar_la_aplicacion.md), sección 5).
- **Si cambió la contraseña del lector:** repita el paso 3.
- **Si se aplicó el permiso de `etl_control`:** vuelva a generar el proyecto sin `--sin-control`, en otra carpeta, y conéctelo de nuevo.

## 6. Páginas del tablero

| Página | Qué muestra | Variante |
|---|---|---|
| Demografía | Total de atenciones, hombres, mujeres, quinquenio más frecuente y promedio diario; pirámide poblacional; atenciones por tipo de seguro, estado civil y nacionalidad | Todas |
| Atención | Tarjetas de resumen: atenciones, ISS promedio, % ISS ≥ 16, % GCS < 9, % PAS < 90, % índice de choque > 0,9, mortalidad, % con UCI, % con procedimiento, % con imagen y % transfundidos. Tipo de trauma: atenciones por mes de admisión, por mecanismo y contexto del evento (violencia, alcohol, sustancias, autolesión). Demanda: atenciones por día de la semana, promedio diario por tipo de día y cobertura de los filtros (qué porcentaje de atenciones tiene dato de mecanismo, armas y alcohol) | Todas |
| Severidad y resultado | Atenciones por rango de ISS, AIS promedio por región y signos vitales de la primera toma (incluido el Glasgow); destino del paciente, mortalidad por rango de ISS y por mecanismo, y muertes según prevenibilidad; procedimientos más frecuentes, imágenes por tipo, sangre transfundida por mes y estancia promedio | Todas |
| Diagnósticos y lesiones | Diagnósticos CIE-10, comorbilidades y complicaciones más frecuentes; lesiones por parte del cuerpo; detalle por atención (una fila por diagnóstico) | Todas (la variante `admin` agrega el motivo de consulta al detalle) |
| Cargas de la bodega | Última carga exitosa, veredicto de calidad, reglas que cumplen, advierten y fallan, y balance de cada carga (solo conteos) | Sin `--sin-control` |
| Textos libres (administración) | Motivo de consulta, otras sustancias, detalles de hospitalización, descripción de imágenes y texto original de diagnósticos y complicaciones | Solo `admin` |

Los segmentadores de la parte superior filtran las páginas 1 a 4: arma de fuego, arma cortopunzante, año, mes, tipo de día, festivo, género, quinquenio, mecanismo, rango de ISS y seguro. La página de cargas no responde a ellos.

Todas las cifras cuentan **atenciones distintas**, no filas. Una atención con tres diagnósticos cuenta una vez en el total de atenciones.

## 7. Copia restringida (variante de administración)

```bash
python analytics/dashboards/powerbi/generar_pbip.py "C:\Tableros\trauma_admin" --variante admin
```

- Agrega la página de textos libres y las columnas que el lector no ve.
- Se conecta igual que el estándar (sección 4), pero con un usuario que pueda leer todas las columnas. Hoy es el usuario administrador (`DB_ADMIN_USER`); el plan es reemplazarlo por un usuario propio de solo lectura con acceso completo.
- Contiene texto clínico libre: guárdela en una carpeta distinta, de acceso restringido, y no la comparta con los usuarios del tablero estándar.

## 8. Problemas al conectar

| Mensaje o situación | Causa | Qué hacer |
|---|---|---|
| `La salida debe quedar FUERA del repositorio` | Se dio una carpeta dentro del proyecto | Use una carpeta fuera, por ejemplo `C:\Tableros\trauma` |
| `permission denied for schema etl_control` o error en las tablas `carga` y `calidad` | El lector no tiene permiso sobre la bitácora | Genere el proyecto con `--sin-control` (sección 3) |
| `permission denied for table ...` en otra tabla | Se conectó con un usuario sin permisos, o la base no tiene aplicados los permisos del lector | Revise que sea el usuario lector y que la base tenga aplicado `04_permissions.sql` |
| `password authentication failed` | Usuario o contraseña equivocados | Repita el paso 3 con los valores del `.env` |
| No se puede conectar con el servidor o se agota el tiempo | Servidor, puerto o red | Revise el parámetro Servidor (paso 2) y que el equipo llegue al servidor |
| Aviso de cifrado o de certificado SSL | El servidor no tiene SSL configurado | Vea el paso 3, punto 4 |
| Una página aparece en blanco después de actualizar | La bodega está vacía o la carga no terminó | Revise que la última carga sea exitosa y vuelva a actualizar |
| Las cifras no coinciden con el reporte de calidad | El tablero no se actualizó después de la última carga | Pulse *Actualizar* |

Otros problemas del tablero se describen en [Problemas frecuentes](03_problemas_frecuentes.md), sección "Tablero de Power BI".

**Estado:** el proyecto generado está pendiente de validarse de punta a punta en Power BI Desktop. Si un visual muestra un error después de conectar, anote la página, el visual y el mensaje, y repórtelo al responsable del proyecto.
