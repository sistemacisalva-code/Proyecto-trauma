"""Constantes compartidas por las pruebas del DDL (TC-DDL). Casos: docs/tecnico/05_casos_de_prueba.md."""
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]

# SQLSTATE de PostgreSQL
UNIQUE = "23505"
FOREIGN_KEY = "23503"
NOT_NULL = "23502"
CHECK_VIOLATION = "23514"
GENERATED_ALWAYS = "428C9"
PERMISO_DENEGADO = "42501"

BRIDGES = {
    "bridge_atencion_cie_10",
    "bridge_atencion_complicacion",
    "bridge_atencion_imagen",
    "bridge_atencion_lesion",
    "bridge_atencion_procedimiento",
    "bridge_atencion_sustancia",
}
# Puentes cuya PK es una clave sustituta (GENERATED ALWAYS) en lugar de la combinacion de sus FK: los dos de
# codigos CIE-10, porque texto_origen admite NULL y va en su UNIQUE (2026-10-27)
PUENTES_CON_CLAVE_SUSTITUTA = {"bridge_atencion_cie_10", "bridge_atencion_complicacion"}
COMPLETO = BRIDGES | {
    "dim_accidente_transito", "dim_armas", "dim_caida", "dim_calificador_signos", "dim_cie_10",
    "dim_desenlace",
    "dim_evento_trauma", "dim_horario", "dim_imagen",
    "dim_mecanismo_primario", "dim_paciente", "dim_parte_cuerpo_lesion",
    "dim_procedimiento", "dim_sustancia",
    "dim_quemadura", "dim_tiempo", "dim_tipo_lesion", "fact_trauma",
}
MINI = {
    "dwh_dim_calendario", "dwh_dim_hechos", "dwh_dim_horario", "dwh_dim_municipio",
    "dwh_dim_perfildem", "dwh_dim_subdimtrauma", "dwh_dim_trauma",
}

# Dimensiones cuya restriccion UNIQUE NULLS NOT DISTINCT cubre todos sus atributos
DIMENSIONES_SIN_CLAVE_NATURAL = [
    "trauma_completo.dim_paciente",
    "trauma_completo.dim_evento_trauma",
    "trauma_completo.dim_caida",
    "trauma_completo.dim_quemadura",
    "trauma_completo.dim_accidente_transito",
    "trauma_completo.dim_armas",
    "trauma_completo.dim_imagen",
    "trauma_completo.dim_desenlace",
    "trauma_completo.dim_calificador_signos",
    "trauma_mini.dwh_dim_perfildem",
    "trauma_mini.dwh_dim_trauma",
]
