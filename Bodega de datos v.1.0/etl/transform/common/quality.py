"""Reporte de calidad y trazabilidad de una corrida de transformación (conteos y nombres; las llaves de las filas
solo en `detalle_filas` y `atenciones_descartadas`)."""
from dataclasses import dataclass, field

import pandas as pd

CARDINALIDAD_MAXIMA = 30  # tope para listar los valores únicos de una columna categórica
# Columnas que identifican el registro durante la transformación: la de REDCap, la del Excel y la ya canónica
COLUMNAS_LLAVE = ("record_id", "traumaregisterrecordid", "trauma_register_id")


@dataclass
class ReporteCalidad:
    """Acumula la trazabilidad y los hallazgos de calidad de una corrida de transformación.

    Se crea una instancia por corrida y se pasa como parámetro a las funciones de transformación,
    de modo que no existe estado compartido entre corridas ni entre pruebas.
    """
    auditoria: dict = field(default_factory=dict)
    reglas: dict = field(default_factory=dict)
    correcciones: dict = field(default_factory=dict)
    renombres: dict = field(default_factory=dict)
    exclusiones: dict = field(default_factory=dict)
    perfiles: list = field(default_factory=list)
    duplicados: list = field(default_factory=list)
    resumen_duplicados: list = field(default_factory=list)
    consolidacion: list = field(default_factory=list)
    resumen_bloques: list = field(default_factory=list)
    descartes: list = field(default_factory=list)
    balance_filas: list = field(default_factory=list)
    atenciones_descartadas: list = field(default_factory=list)
    detalle_filas: list = field(default_factory=list)

    # --- Auditoría de conservación -------------------------------------------------
    def registrar_auditoria(self, bloque: str, col: str, original: pd.Series, resultado: pd.Series,
                            no_convertibles: int = 0, fuera_de_rango: int = 0,
                            bajo_minimo: int = 0, sobre_maximo: int = 0) -> None:
        """Regla: no_nulos_antes == no_nulos_despues + no_convertibles + fuera_de_rango.

        bajo_minimo y sobre_maximo desglosan fuera_de_rango según el extremo del dominio que se violó: sirven
        para distinguir un error de unidad (todos por encima, p. ej. mililitros en una columna de litros) de
        uno de captura. Son opcionales; si se informan, deben sumar fuera_de_rango.
        """
        # Sin setdefault: en un reporte nuevo, auditar dos veces la misma columna es un error de lógica
        if (bloque, col) in self.auditoria:
            raise ValueError(f"{bloque}.{col}: la variable ya fue auditada en esta corrida")
        if (bajo_minimo or sobre_maximo) and bajo_minimo + sobre_maximo != fuera_de_rango:
            raise ValueError(f"{bloque}.{col}: bajo_minimo + sobre_maximo ({bajo_minimo + sobre_maximo}) "
                             f"debe ser igual a fuera_de_rango ({fuera_de_rango})")
        antes, despues = int(original.notna().sum()), int(resultado.notna().sum())
        diferencia = antes - despues - no_convertibles - fuera_de_rango
        self.auditoria[(bloque, col)] = {
            "bloque": bloque, "columna": col,
            "tipo_antes": str(original.dtype), "tipo_despues": str(resultado.dtype),
            "filas": len(resultado), "no_nulos_antes": antes, "no_nulos_despues": despues,
            "no_convertibles": no_convertibles, "fuera_de_rango": fuera_de_rango,
            "bajo_minimo": bajo_minimo, "sobre_maximo": sobre_maximo,
            "diferencia_sin_explicar": diferencia, "conserva": diferencia == 0,
        }

    def verificar_auditoria(self) -> pd.DataFrame:
        """Devuelve la tabla de auditoría; detiene la ejecución si alguna variable perdió datos sin explicación."""
        tabla = self.tabla("auditoria")
        if tabla.empty:
            return tabla
        perdidas = tabla.loc[~tabla["conserva"], "columna"].tolist()
        if perdidas:
            raise ValueError(f"Variables con diferencia sin explicar: {perdidas}")
        return tabla

    # --- Reglas, correcciones y renombres ------------------------------------------
    def reportar_regla(self, bloque: str, regla: str, evaluables: pd.Series, incumplen: pd.Series,
                       llaves: pd.Series | None = None, campos: list[str] | None = None) -> None:
        """Cuenta cuántas filas violan una regla de consistencia entre variables, sin modificar datos.

        Cuándo usarla: cuando dos o más valores pueden contradecirse y no se sabe cuál es el erróneo
        (p. ej. presión diastólica > sistólica, alta anterior a la admisión). También para límites
        blandos: valores extremos pero posibles que se conservan y solo se reportan.

        evaluables: filas donde la regla puede aplicarse (las que tienen todos los datos necesarios).
        incumplen: filas que la violan; solo cuentan las que además son evaluables.
        llaves: llave del registro de cada fila (por ejemplo `df["record_id"]`), con el mismo índice que `evaluables`.
            Si se da, las llaves de las filas que incumplen quedan en `detalle_filas` para que el equipo pueda
            localizarlas y corregirlas en la fuente. Nunca se guardan valores, solo la llave y cuántas filas del
            registro incumplen.
        campos: los campos que la regla compara o revisa, para que quien corrige sepa dónde mirar (por ejemplo,
            ["fecha_de_admision", "fecha_y_hora_de_alta"]). Un campo de otro instrumento se escribe "instrumento.campo".
        """
        marcadas = evaluables & incumplen.fillna(False)
        self.reglas[(bloque, regla)] = {
            "bloque": bloque, "regla": regla,
            "filas_evaluables": int(evaluables.sum()),
            "filas_que_incumplen": int(marcadas.sum()),
        }
        self.detallar(bloque, regla, "incumple", None, llaves, marcadas, campos)

    def registrar_correccion(self, bloque: str, col: str, regla: str, filas_afectadas: int, accion: str,
                             llaves: pd.Series | None = None, afectadas: pd.Series | None = None,
                             campos: list[str] | None = None) -> None:
        """Deja constancia de valores que una regla documentada INVALIDÓ o MODIFICÓ después de la conversión.

        Cuándo usarla: cada vez que el transformer cambia un valor ya convertido (p. ej. una fecha de
        procedimiento invalidada por quedar fuera de la estancia). No es para pérdidas por conversión
        o dominio: esas ya las cuenta la auditoría. Llamarla ANTES de modificar, con el conteo de
        partida, y sin guardar los valores afectados.

        llaves y afectadas: si se dan los dos (la llave de cada fila y la máscara de las filas modificadas, con el
        mismo índice), las llaves de las filas modificadas quedan en `detalle_filas` con el tipo "corregida".
        """
        self.correcciones[(bloque, col, regla)] = {
            "bloque": bloque, "columna": col, "regla": regla,
            "accion": accion, "filas_afectadas": filas_afectadas,
        }
        if afectadas is not None:
            self.detallar(bloque, regla, "corregida", col, llaves, afectadas.fillna(False), campos)

    @staticmethod
    def llaves(df: pd.DataFrame) -> pd.Series | None:
        """La llave del registro de cada fila de `df` (primera columna de COLUMNAS_LLAVE que tenga), o None."""
        return next((df[c] for c in COLUMNAS_LLAVE if c in df.columns), None)

    def detallar(self, bloque: str, regla: str, tipo: str, columna: str | None, llaves: pd.Series | None,
                 marcadas: pd.Series, campos: list[str] | None = None) -> None:
        """Guarda la llave de las filas marcadas (una fila por llave, con cuántas filas suyas se marcaron).

        Sin llaves no hace nada. Las llaves deben corresponder a las mismas filas que la máscara (mismo índice, o
        al menos sus etiquetas): un desalineo asignaría llaves equivocadas, que es peor que no darlas, así que
        se detiene.
        """
        if llaves is None:
            return
        if not llaves.index.equals(marcadas.index):
            if not (llaves.index.is_unique and marcadas.index.isin(llaves.index).all()):
                raise ValueError(f"Las llaves de '{regla}' no están alineadas con las filas evaluadas (distinto índice)")
            llaves = llaves.reindex(marcadas.index)
        # Campos que la regla revisa: los dados o, si no se dieron, la columna afectada
        texto_campos = "; ".join(campos) if campos else (columna or "")
        conteo = llaves[marcadas.astype(bool)].dropna().value_counts(sort=False)
        for llave, filas in conteo.items():
            self.detalle_filas.append({"bloque": bloque, "regla": regla, "tipo": tipo, "columna": columna,
                                       "campos": texto_campos, "llave": llave, "filas": int(filas)})

    def registrar_exclusion(self, bloque: str, col: str, filas_con_valor: int, motivo: str) -> None:
        """Deja constancia de una columna eliminada completa (solo su nombre y cuántas filas tenían valor).

        Cuándo usarla: al quitar una columna que no llega al staging (minimización, identificador directo,
        columna vacía, dato que se toma de otra hoja). `eliminar_columnas` la llama por cada columna; no suele
        invocarse directamente. Excluir dos veces la misma columna del mismo bloque es un error de lógica.
        """
        if (bloque, col) in self.exclusiones:
            raise ValueError(f"{bloque}.{col}: la columna ya fue excluida en esta corrida")
        self.exclusiones[(bloque, col)] = {
            "bloque": bloque, "columna": col, "filas_con_valor": filas_con_valor, "motivo": motivo,
        }

    def registrar_balance(self, origen: str, filas_entrada: int, tabla: str, filas_salida: int) -> None:
        """Filas que entraron de una hoja de origen y filas que salieron en cada tabla derivada de ella (solo conteos).

        Cuándo usarla: en fuentes donde una hoja se divide en varias tablas o cambia de grano (Excel histórico). Las
        diferencias deben quedar explicadas en `correcciones` (filas eliminadas o agrupadas) o en la propia división.
        """
        self.balance_filas.append({"origen": origen, "filas_entrada": int(filas_entrada), "tabla": tabla,
                                   "filas_salida": int(filas_salida)})

    def registrar_renombre(self, bloque: str, original: str, nuevo: str, motivo: str) -> None:
        """Registra el cambio de nombre de UNA columna (solo nombres, sin datos).

        Cuándo usarla: al renombrar una columna de un bloque (p. ej. `descripcion` ->
        `descripcion_imagen` para alinearla con el modelo). `renombrar_columnas` la llama por cada
        entrada del mapa; no suele invocarse directamente.
        """
        self.renombres[(bloque, original)] = {
            "bloque": bloque, "columna_original": original, "columna_nueva": nuevo, "motivo": motivo,
        }

    def registrar_equivalencia(self, equivalencia: dict[str, str], bloque: str = "global") -> None:
        """Registra de una sola vez los renombres globales: nombre original de REDCap -> nombre final.

        Cuándo usarla: una vez, después de `normalizar_columnas` y `aplicar_renombres` (YAML), con la
        equivalencia que devuelve esta última. Solo registra las columnas cuyo nombre cambió.
        """
        for original, final in equivalencia.items():
            if original != final:
                self.registrar_renombre(bloque, original, final,
                                        "normalizacion estructural y renombres semanticos (YAML)")

    def registrar_consolidacion(self, resumen: dict) -> None:
        """Guarda el resumen de conteos de `consolidar_particiones`.

        Cuándo usarla: una vez por corrida, justo después de consolidar las particiones y antes de
        transformar, para que quede constancia de cuántas filas se reemplazaron.
        """
        self.consolidacion.append(resumen)

    def registrar_resumen_bloques(self, filas: list[dict]) -> None:
        """Guarda el resumen por instrumento (filas, record_id, máximo de filas por registro, si es repetible).

        Cuándo usarla: una vez por corrida, justo después de dividir en bloques y ANTES de eliminar las
        columnas de sistema, porque `repetible` se calcula con `redcap_repeat_instance`.
        """
        self.resumen_bloques.extend(filas)

    def registrar_descartes(self, filas: list[dict]) -> None:
        """Guarda cuántas filas descartó la división en bloques por no tener datos del instrumento,
        por instrumento y por valor de su marcador `*_complete` (solo conteos).

        Cuándo usarla: una vez por corrida, junto con `registrar_resumen_bloques`, con el mismo
        DataFrame que se dividió. Permite comprobar que filas del bloque + descartadas = filas de origen.
        """
        self.descartes.extend(filas)

    def registrar_atenciones_descartadas(self, filas: list[dict]) -> None:
        """Guarda qué atenciones salieron del staging por ser duplicados de otra (solo llaves de registro y conteos).

        Cuándo usarla: una vez por corrida, desde `retirar_atenciones_duplicadas`, con una fila por atención retirada:
        su llave, la de la atención que se conservó y cuánto se sabía de cada una. Las filas que salieron de cada
        tabla quedan en `balance_filas` con el motivo como origen.
        """
        self.atenciones_descartadas.extend(filas)

    # --- Perfilado antes / después --------------------------------------------------
    def perfilar(self, df: pd.DataFrame, bloque: str, etapa: str, categoricas: tuple[str, ...] = ()) -> None:
        """Una fila por columna: tipo, filas, nulos y distintos.

        Los valores únicos se listan solo si la columna se declaró categórica y tiene a lo sumo
        CARDINALIDAD_MAXIMA distintos; en cualquier otro caso queda únicamente el conteo.
        """
        if etapa not in ("antes", "despues"):
            raise ValueError("etapa debe ser 'antes' o 'despues'")
        for col in df.columns:
            n_unicos = int(df[col].nunique(dropna=True))
            listar = col in categoricas and n_unicos <= CARDINALIDAD_MAXIMA
            self.perfiles.append({
                "bloque": bloque, "etapa": etapa, "columna": col, "tipo": str(df[col].dtype),
                "n_filas": len(df), "n_nulos": int(df[col].isna().sum()), "n_unicos": n_unicos,
                "valores_unicos": sorted(df[col].dropna().astype(str).unique().tolist()) if listar else None,
            })

    # --- Duplicados: solo se marcan, no se eliminan ---------------------------------
    def marcar_duplicados(self, df: pd.DataFrame, bloque: str, nivel: str, columnas: list[str],
                          id_col: str = "record_id", ignorar_nulos: bool = True) -> None:
        """Registra qué filas repiten la combinación `columnas`.

        Guarda solo id_col y un número de grupo, nunca los valores de la clave (que pueden incluir el
        documento seudonimizado). ignorar_nulos=False para claves con nulos estructurales, como la
        instancia de un instrumento repetible.
        """
        faltantes = [c for c in dict.fromkeys([id_col, *columnas]) if c not in df.columns]
        if faltantes:
            raise KeyError(f"Columnas ausentes: {faltantes}")

        evaluables = df.dropna(subset=columnas) if ignorar_nulos else df
        marcadas = evaluables.duplicated(subset=columnas, keep=False)
        filas = evaluables.loc[marcadas]
        if len(filas):
            grupo = filas.groupby(columnas, dropna=False, sort=False).ngroup()
            self.duplicados.append(pd.DataFrame({
                "bloque": bloque, "nivel": nivel, id_col: filas[id_col],
                "grupo": grupo, "n_en_grupo": grupo.map(grupo.value_counts()),
            }))
            combinaciones = int(grupo.nunique())
        else:
            combinaciones = 0

        self.resumen_duplicados.append({
            "bloque": bloque, "nivel": nivel, "columnas": list(columnas),
            "filas_totales": len(df), "filas_evaluables": len(evaluables),
            "filas_involucradas": int(marcadas.sum()), "combinaciones_repetidas": combinaciones,
            "es_unica": not marcadas.any(),
        })

    # --- Salida ---------------------------------------------------------------------
    def tabla(self, nombre: str) -> pd.DataFrame:
        """nombre: auditoria | reglas | correcciones | renombres | exclusiones | perfiles | duplicados |
        resumen_duplicados | consolidacion | resumen_bloques | descartes | balance_filas | atenciones_descartadas |
        detalle_filas."""
        datos = getattr(self, nombre)
        if nombre == "duplicados":
            return pd.concat(datos, ignore_index=True) if datos else pd.DataFrame()
        return pd.DataFrame(list(datos.values()) if isinstance(datos, dict) else datos)
