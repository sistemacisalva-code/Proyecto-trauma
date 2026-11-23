import os
from dotenv import load_dotenv
from pathlib import Path

# DB
DATABASE_YAML_PATH = "config/database.yaml"
DATABASE_DIR = Path("database")

load_dotenv()

admin_config = {
    'admin_user': os.getenv('DB_ADMIN_USER'),
    'admin_password': os.getenv('DB_ADMIN_PASSWORD'),
}

db_config = {
    'user_dev': os.getenv('DB_USER_DEV'),
    'password_dev': os.getenv('DB_PASSWORD'),
    'database_dev': os.getenv('DB_NAME_DEV'),

    'user_prod': os.getenv('DB_USER_PROD'),
    'password_prod': os.getenv('DB_PASSWORD_PROD'),
    'database_prod': os.getenv('DB_NAME_PROD'),
}

## Configuracion de extractores
# Excel fuente (carga historica) y carpeta destino en la capa raw. Son cosas distintas:
# el .xlsx NO debe vivir dentro de data/raw/.
EXCEL_SOURCE_PATH = "data/source_files/Base de datos Registro de TRauma 16 mar 24 (completa1).xlsx"
EXCEL_RAW_BASE_DIR = "data/raw/excel_trauma"
# Transformación del Excel (solo nombres, sin datos): renombres por hoja y división de registro_trauma en bloques
EXCEL_RENOMBRES_YAML_PATH = "config/renombres_columnas_excel.yaml"
EXCEL_MAPEO_YAML_PATH = "config/mapeo_columnas_excel.yaml"

EXCEL_SHEETS_CONFIG = {
    "hoja_principal": {
        "sheet_name": "Trauma Register",
        "dest" : "registro_trauma",
    },

    "hoja_colisiones": {
        "sheet_name": "Collision",
        "dest" : "colisiones",
    },

    "hoja_drogas": {
        "sheet_name": "Drug Abuse",
        "dest" : "abuso_sustancias",
    },

    "hoja_calificador_gcs": {
        "sheet_name": "Vital Sign GCS Qualifier",
        "dest" : "calificador_gcs",
    },

    "hoja_complicaciones_hospitalizacion": {
        "sheet_name": "Hospitalization Complication",
        "dest" : "complicaciones_hospitalizacion",
    },

    "hoja_cie10": {
        "sheet_name": "Trauma Register ICD10",
        "dest" : "codigos_cie10",
    },

    "hoja_tiempo_uci": {
        "sheet_name": "Intensive Care Unit",
        "dest" : "tiempo_uci",
    },

    "hoja_imagenes": {
        "sheet_name": "Imaging",
        "dest" : "imagenes",
    },

    "hoja_quemaduras": {
        "sheet_name": "Burn Injury",
        "dest" : "quemaduras",
    },

    "hoja_arma_fuego": {
        "sheet_name": "Firearm Injury",
        "dest" : "arma_fuego",
    },

    "hoja_arma_blanca": {
        "sheet_name": "Penetrating Injury",
        "dest" : "arma_blanca",
    },

    "hoja_envenenamiento": {
        "sheet_name": "Poisoning Injury",
        "dest" : "envenenamiento",
    },

    "hoja_violencia": {
        "sheet_name": "Violence Injury",
        "dest" : "violencia",
    },

    "hoja_tipo_violencia": {
        "sheet_name": "Physical Exam Body Part Injury",
        "dest" : "tipo_violencia",
    },

    "hoja_procedimientos": {
        "sheet_name": "Procedure",
        "dest" : "procedimientos",
    },

    "hoja_procedimientos_prehospitalarios": {
        "sheet_name": "Prehospital Procedure",
        "dest" : "procedimientos_prehospitalarios",
    },

    "hoja_signos_vitales": {
        "sheet_name" : "Vital Sign",
        "dest": "signos_vitales",
    },

    "hoja_laboratorio":{
        "sheet_name" : "Laboratory",
        "dest" : "laboratorio",
    }
}

# Salida de la transformación: staging (foto que se sobrescribe en cada corrida) y reportes de
# calidad (una carpeta por corrida, nunca se sobrescriben). Ambas bajo data/, fuera de git.
STAGING_BASE_DIR = "data/staging"
QUALITY_REPORTS_BASE_DIR = "data/quality_reports"

# Carga a la bodega: un contrato por modelo (versionado, solo nombres de columnas) y la cuarentena de las
# filas que no pueden entrar (una carpeta por corrida, bajo data/, fuera de git)
CONTRATOS_DIR = "config/contratos"
QUARANTINE_BASE_DIR = "data/quarantine"

# Listas de valores permitidos de los atributos de las dimensiones (QR-DOM-04): las define quien conoce el dominio
# clínico. Si el archivo no existe, la regla no se evalúa. Plantilla: valores_permitidos.example.yaml
VALORES_PERMITIDOS_YAML_PATH = "config/valores_permitidos.yaml"

# REDCap (solo lectura: el token debe ser de solo lectura en el proyecto REDCap)
REDCAP_RAW_BASE_DIR = "data/raw/REDCap"
# Clave del HMAC con que la transformación seudonimiza el documento de identidad (del .env)
PSEUDONYMIZATION_KEY = os.getenv("PSEUDONYMIZATION_KEY")
# Renombres semánticos de columnas (capa de transformación; solo nombres, sin datos)
REDCAP_RENOMBRES_YAML_PATH = "config/renombres_columnas_redcap.yaml"
REDCAP_API_URL = os.getenv("REDCAP_API_URL")
REDCAP_API_TOKEN = os.getenv("REDCAP_API_TOKEN")

# Una entrada lógica por extracción. Claves:
#   export_fields:      variables a exportar; None = todas (proyecto de una sola tabla longitudinal).
#   dest:               nombre fijo del Parquet; lo que distingue cada corrida es la
#                       partición load_date=<fecha y hora>, no el nombre del archivo.
#   expected_n_columns: control de deriva del esquema; None = sin control (primera corrida:
#                       leer "columnas observadas" del log y pegar ese número aquí). No usar
#                       el conteo del diccionario: checkbox, redcap_* y *_complete lo alteran.
# date_begin/date_end NO van aquí: se calculan en cada corrida (run_incremental_redcap, etl/pipeline.py).
REDCAP_EXPORT_CONFIG = {
    "registro_trauma_longitudinal": {
        "export_fields": None,
        "dest": "registro_trauma_redcap",
        "expected_n_columns": None,
    },
}