"""Capa de acceso a datos (Snowflake) para el tablero Balance Inventario MP/ME.

Conexion por llave privada .p8 (SF_PRIVATE_KEY_PATH), igual que el resto de
tableros del servidor de BI. El .env SIEMPRE se lee de la misma ruta fija
del usuario (no del cwd del proceso ni de un .env local del proyecto).

Fuentes:
  - Inventario: DB_TABLEAUDATASOURCE.CADENASUMINISTRO.TDS_VW_CDS_INVENTARIOMATERIALMMDIAACTUAL
  - Necesidad MRP: DB_EXCELENCIAYEFECTIVIDADORGANIZACIONAL.PUBLIC."EEO_RequerimientoMaterialMRP"
  - Entregas pendientes de OC: DB_EXCELENCIAYEFECTIVIDADORGANIZACIONAL.PUBLIC.EEO_PROVEEDORPENDIENTE
  - Maestra de materiales: DB_TABLEAUDATASOURCE.CADENASUMINISTRO.TDS_VW_CDS_MAESTRAMATERIALES
"""

from __future__ import annotations

import os

import pandas as pd
import snowflake.connector
import streamlit as st
from dotenv import load_dotenv

load_dotenv()


def conectar_snowflake():
    return snowflake.connector.connect(
        user=os.getenv("SF_USER"),
        account=os.getenv("SF_ACCOUNT"),
        private_key_file=os.getenv("SF_PRIVATE_KEY_PATH"),
        role=os.getenv("SF_ROLE"),
        warehouse=os.getenv("SF_WAREHOUSE"),
    )


def _query(sql: str) -> pd.DataFrame:
    conn = conectar_snowflake()
    try:
        cur = conn.cursor()
        cur.execute(sql)
        return cur.fetch_pandas_all()
    finally:
        conn.close()


QUERY_INVENTARIO_NECESIDAD = """
-- Consolidado de Inventario + Necesidad MRP (semana 0, 1 y 2) + Entregas Pendientes de OC por material y centro.
-- Centros materia prima (material inicia por '13'): CPS1, CPS2, CPT2, CPB2, CPB1
-- Centros empaque (material inicia por '14'): CPS9, CPT9, CPB9, CPE9, CPK9, CPO9
-- Excluye los almacenes: 0003, 0004, 0005, 0006, 0017, 0018, 0038, 0039 (solo aplica a inventario normal)
-- Semana 0 = semana actual (lunes a domingo), Semana 1 = siguiente semana, Semana 2 = la que sigue.

WITH INV_BASE AS (
    SELECT
        "IdMaterial"                as IdMaterial,
        "Material"                  as Material,
        "IdCentroFase2"             as Centro,
        "UnidadMedidaBase"          as Unidad,
        "CantidadLibreUtilizacion"  as Libre,
        "CantidadControlCalidad"   as Calidad
    FROM DB_TABLEAUDATASOURCE.CADENASUMINISTRO.TDS_VW_CDS_INVENTARIOMATERIALMMDIAACTUAL
    WHERE (
            ("IdMaterial" LIKE '13%' AND "IdCentroFase2" IN ('CPS1','CPS2','CPT2','CPB2','CPB1'))
         OR ("IdMaterial" LIKE '14%' AND "IdCentroFase2" IN ('CPS9','CPT9','CPB9','CPE9','CPK9','CPO9'))
          )
      AND ("IdAlmacen" IS NULL OR "IdAlmacen" NOT IN ('0003','0004','0005','0006','0017','0018','0038','0039'))
),
PROD_BASE AS (
    -- Inventario en los almacenes de excepcion (0003,0004,0005,0006,0017,0018,0038,0039)
    SELECT
        "IdMaterial"                as IdMaterial,
        "IdCentroFase2"             as Centro,
        "CantidadLibreUtilizacion"  as Libre,
        "CantidadControlCalidad"   as Calidad
    FROM DB_TABLEAUDATASOURCE.CADENASUMINISTRO.TDS_VW_CDS_INVENTARIOMATERIALMMDIAACTUAL
    WHERE (
            ("IdMaterial" LIKE '13%' AND "IdCentroFase2" IN ('CPS1','CPS2','CPT2','CPB2','CPB1'))
         OR ("IdMaterial" LIKE '14%' AND "IdCentroFase2" IN ('CPS9','CPT9','CPB9','CPE9','CPK9','CPO9'))
          )
      AND "IdAlmacen" IN ('0003','0004','0005','0006','0017','0018','0038','0039')
),
PROD_AGG AS (
    -- Solo se cuenta el 85% del inventario de esos almacenes de excepcion, desglosado por centro
    -- (los campos _Prod se usan unicamente para sumarlos al Inv de cada centro, no se exponen como columnas nuevas)
    SELECT
        IdMaterial,
        (SUM(Libre) + SUM(Calidad)) * 0.85 as INVENTARIOPRODUCCION,
        SUM(CASE WHEN Centro = 'CPS1' THEN (Libre + Calidad) * 0.85 ELSE 0 END) as CPS1_Prod,
        SUM(CASE WHEN Centro = 'CPS2' THEN (Libre + Calidad) * 0.85 ELSE 0 END) as CPS2_Prod,
        SUM(CASE WHEN Centro = 'CPT2' THEN (Libre + Calidad) * 0.85 ELSE 0 END) as CPT2_Prod,
        SUM(CASE WHEN Centro = 'CPB2' THEN (Libre + Calidad) * 0.85 ELSE 0 END) as CPB2_Prod,
        SUM(CASE WHEN Centro = 'CPB1' THEN (Libre + Calidad) * 0.85 ELSE 0 END) as CPB1_Prod,
        SUM(CASE WHEN Centro = 'CPS9' THEN (Libre + Calidad) * 0.85 ELSE 0 END) as CPS9_Prod,
        SUM(CASE WHEN Centro = 'CPT9' THEN (Libre + Calidad) * 0.85 ELSE 0 END) as CPT9_Prod,
        SUM(CASE WHEN Centro = 'CPB9' THEN (Libre + Calidad) * 0.85 ELSE 0 END) as CPB9_Prod,
        SUM(CASE WHEN Centro = 'CPE9' THEN (Libre + Calidad) * 0.85 ELSE 0 END) as CPE9_Prod,
        SUM(CASE WHEN Centro = 'CPK9' THEN (Libre + Calidad) * 0.85 ELSE 0 END) as CPK9_Prod,
        SUM(CASE WHEN Centro = 'CPO9' THEN (Libre + Calidad) * 0.85 ELSE 0 END) as CPO9_Prod
    FROM PROD_BASE
    GROUP BY IdMaterial
),
MRP_BASE AS (
    SELECT
        "MRP_IdMaterial"     as IdMaterial,
        "MRP_ID_CENTRO_CF2"  as Centro,
        "MRP_UnidadMedidaBase" as Unidad,
        "MRP_CantidadNecesaria" as Cantidad,
        DATEDIFF('WEEK', DATE_TRUNC('WEEK', CURRENT_DATE()), DATE_TRUNC('WEEK', "MRP_FechaNecesidad")) as Semana
    FROM DB_EXCELENCIAYEFECTIVIDADORGANIZACIONAL.PUBLIC."EEO_RequerimientoMaterialMRP"
    WHERE "MRP_Estado" = 'Activo'
      AND "MRP_TipoMaterial" IN ('ZMPR','ZEMP')
      AND (
            ("MRP_IdMaterial" LIKE '13%' AND "MRP_ID_CENTRO_CF2" IN ('CPS1','CPS2','CPT2','CPB2','CPB1'))
         OR ("MRP_IdMaterial" LIKE '14%' AND "MRP_ID_CENTRO_CF2" IN ('CPS9','CPT9','CPB9','CPE9','CPK9','CPO9'))
          )
),
PO_BASE AS (
    -- Entregas pendientes de ordenes de compra activas, clasificadas por semana de entrega solicitada
    SELECT
        PEN_IDMATERIAL as IdMaterial,
        -PEN_CANTIDADPENDIENTE as Cantidad,
        PEN_FECHAENTREGASOLICITADA as FechaEntrega,
        DATEDIFF('WEEK', DATE_TRUNC('WEEK', CURRENT_DATE()), DATE_TRUNC('WEEK', PEN_FECHAENTREGASOLICITADA)) as Semana
    FROM DB_EXCELENCIAYEFECTIVIDADORGANIZACIONAL.PUBLIC.EEO_PROVEEDORPENDIENTE
    WHERE PEN_ESTADOORDEN = 'Pendiente'
      AND PEN_TIPO_MATERIAL IN ('ZMPR','ZEMP')
      AND (PEN_IDMATERIAL LIKE '13%' OR PEN_IDMATERIAL LIKE '14%')
),
PO_AGG AS (
    SELECT
        IdMaterial,
        SUM(CASE WHEN Semana = 0 THEN Cantidad ELSE 0 END) as EntregaPendienteNS0,
        MIN(CASE WHEN Semana = 0 THEN FechaEntrega END)    as FechaEntregaProgramadaNS0,
        SUM(CASE WHEN Semana = 1 THEN Cantidad ELSE 0 END) as EntregaPendienteNS1,
        MIN(CASE WHEN Semana = 1 THEN FechaEntrega END)    as FechaEntregaProgramadaNS1,
        SUM(CASE WHEN Semana = 2 THEN Cantidad ELSE 0 END) as EntregaPendienteNS2,
        MIN(CASE WHEN Semana = 2 THEN FechaEntrega END)    as FechaEntregaProgramadaNS2
    FROM PO_BASE
    WHERE Semana IN (0, 1, 2)
    GROUP BY IdMaterial
),
UNIDAD_BASE AS (
    SELECT IdMaterial, Unidad FROM INV_BASE WHERE Unidad IS NOT NULL
    UNION
    SELECT IdMaterial, Unidad FROM MRP_BASE WHERE Unidad IS NOT NULL
),
UNIDAD_AGG AS (
    SELECT
        IdMaterial,
        LISTAGG(DISTINCT Unidad, ', ') as UnidadMedida
    FROM UNIDAD_BASE
    GROUP BY IdMaterial
),
INV_AGG AS (
    SELECT
        IdMaterial,
        MAX(Material) as Material,
        SUM(Libre)                as InventarioLibreUtilizacion,
        SUM(Calidad)               as InventarioCalidad,
        SUM(CASE WHEN Centro = 'CPS1' THEN Libre + Calidad ELSE 0 END) as CPS1_Inv,
        SUM(CASE WHEN Centro = 'CPS2' THEN Libre + Calidad ELSE 0 END) as CPS2_Inv,
        SUM(CASE WHEN Centro = 'CPT2' THEN Libre + Calidad ELSE 0 END) as CPT2_Inv,
        SUM(CASE WHEN Centro = 'CPB2' THEN Libre + Calidad ELSE 0 END) as CPB2_Inv,
        SUM(CASE WHEN Centro = 'CPB1' THEN Libre + Calidad ELSE 0 END) as CPB1_Inv,
        SUM(CASE WHEN Centro = 'CPS9' THEN Libre + Calidad ELSE 0 END) as CPS9_Inv,
        SUM(CASE WHEN Centro = 'CPT9' THEN Libre + Calidad ELSE 0 END) as CPT9_Inv,
        SUM(CASE WHEN Centro = 'CPB9' THEN Libre + Calidad ELSE 0 END) as CPB9_Inv,
        SUM(CASE WHEN Centro = 'CPE9' THEN Libre + Calidad ELSE 0 END) as CPE9_Inv,
        SUM(CASE WHEN Centro = 'CPK9' THEN Libre + Calidad ELSE 0 END) as CPK9_Inv,
        SUM(CASE WHEN Centro = 'CPO9' THEN Libre + Calidad ELSE 0 END) as CPO9_Inv
    FROM INV_BASE
    GROUP BY IdMaterial
),
MRP_AGG AS (
    SELECT
        IdMaterial,
        SUM(CASE WHEN Centro = 'CPS1' AND Semana = 0 THEN Cantidad ELSE 0 END) as CPS1_NS0,
        SUM(CASE WHEN Centro = 'CPS1' AND Semana = 1 THEN Cantidad ELSE 0 END) as CPS1_NS1,
        SUM(CASE WHEN Centro = 'CPS1' AND Semana = 2 THEN Cantidad ELSE 0 END) as CPS1_NS2,
        SUM(CASE WHEN Centro = 'CPS2' AND Semana = 0 THEN Cantidad ELSE 0 END) as CPS2_NS0,
        SUM(CASE WHEN Centro = 'CPS2' AND Semana = 1 THEN Cantidad ELSE 0 END) as CPS2_NS1,
        SUM(CASE WHEN Centro = 'CPS2' AND Semana = 2 THEN Cantidad ELSE 0 END) as CPS2_NS2,
        SUM(CASE WHEN Centro = 'CPT2' AND Semana = 0 THEN Cantidad ELSE 0 END) as CPT2_NS0,
        SUM(CASE WHEN Centro = 'CPT2' AND Semana = 1 THEN Cantidad ELSE 0 END) as CPT2_NS1,
        SUM(CASE WHEN Centro = 'CPT2' AND Semana = 2 THEN Cantidad ELSE 0 END) as CPT2_NS2,
        SUM(CASE WHEN Centro = 'CPB2' AND Semana = 0 THEN Cantidad ELSE 0 END) as CPB2_NS0,
        SUM(CASE WHEN Centro = 'CPB2' AND Semana = 1 THEN Cantidad ELSE 0 END) as CPB2_NS1,
        SUM(CASE WHEN Centro = 'CPB2' AND Semana = 2 THEN Cantidad ELSE 0 END) as CPB2_NS2,
        SUM(CASE WHEN Centro = 'CPB1' AND Semana = 0 THEN Cantidad ELSE 0 END) as CPB1_NS0,
        SUM(CASE WHEN Centro = 'CPB1' AND Semana = 1 THEN Cantidad ELSE 0 END) as CPB1_NS1,
        SUM(CASE WHEN Centro = 'CPB1' AND Semana = 2 THEN Cantidad ELSE 0 END) as CPB1_NS2,
        SUM(CASE WHEN Centro = 'CPS9' AND Semana = 0 THEN Cantidad ELSE 0 END) as CPS9_NS0,
        SUM(CASE WHEN Centro = 'CPS9' AND Semana = 1 THEN Cantidad ELSE 0 END) as CPS9_NS1,
        SUM(CASE WHEN Centro = 'CPS9' AND Semana = 2 THEN Cantidad ELSE 0 END) as CPS9_NS2,
        SUM(CASE WHEN Centro = 'CPT9' AND Semana = 0 THEN Cantidad ELSE 0 END) as CPT9_NS0,
        SUM(CASE WHEN Centro = 'CPT9' AND Semana = 1 THEN Cantidad ELSE 0 END) as CPT9_NS1,
        SUM(CASE WHEN Centro = 'CPT9' AND Semana = 2 THEN Cantidad ELSE 0 END) as CPT9_NS2,
        SUM(CASE WHEN Centro = 'CPB9' AND Semana = 0 THEN Cantidad ELSE 0 END) as CPB9_NS0,
        SUM(CASE WHEN Centro = 'CPB9' AND Semana = 1 THEN Cantidad ELSE 0 END) as CPB9_NS1,
        SUM(CASE WHEN Centro = 'CPB9' AND Semana = 2 THEN Cantidad ELSE 0 END) as CPB9_NS2,
        SUM(CASE WHEN Centro = 'CPE9' AND Semana = 0 THEN Cantidad ELSE 0 END) as CPE9_NS0,
        SUM(CASE WHEN Centro = 'CPE9' AND Semana = 1 THEN Cantidad ELSE 0 END) as CPE9_NS1,
        SUM(CASE WHEN Centro = 'CPE9' AND Semana = 2 THEN Cantidad ELSE 0 END) as CPE9_NS2,
        SUM(CASE WHEN Centro = 'CPK9' AND Semana = 0 THEN Cantidad ELSE 0 END) as CPK9_NS0,
        SUM(CASE WHEN Centro = 'CPK9' AND Semana = 1 THEN Cantidad ELSE 0 END) as CPK9_NS1,
        SUM(CASE WHEN Centro = 'CPK9' AND Semana = 2 THEN Cantidad ELSE 0 END) as CPK9_NS2,
        SUM(CASE WHEN Centro = 'CPO9' AND Semana = 0 THEN Cantidad ELSE 0 END) as CPO9_NS0,
        SUM(CASE WHEN Centro = 'CPO9' AND Semana = 1 THEN Cantidad ELSE 0 END) as CPO9_NS1,
        SUM(CASE WHEN Centro = 'CPO9' AND Semana = 2 THEN Cantidad ELSE 0 END) as CPO9_NS2
    FROM MRP_BASE
    WHERE Semana IN (0, 1, 2)
    GROUP BY IdMaterial
)
SELECT
    COALESCE(I.IdMaterial, M.IdMaterial, P.IdMaterial, PO.IdMaterial)  as IdMaterial,
    COALESCE(I.Material, MM."Material")                                as Material,
    COALESCE(U.UnidadMedida, MM."UnidadMedidaBase")                     as UnidadMedida,
    COALESCE(I.InventarioLibreUtilizacion, 0)                           as InventarioLibreUtilizacion,
    COALESCE(I.InventarioCalidad, 0)                                    as InventarioCalidad,
    COALESCE(P.INVENTARIOPRODUCCION, 0)                                 as INVENTARIOPRODUCCION,
    COALESCE(PO.EntregaPendienteNS0, 0) as "Entrega Pendiente NS0", PO.FechaEntregaProgramadaNS0 as "Fecha Entrega Programada NS0",
    COALESCE(PO.EntregaPendienteNS1, 0) as "Entrega Pendiente NS1", PO.FechaEntregaProgramadaNS1 as "Fecha Entrega Programada NS1",
    COALESCE(PO.EntregaPendienteNS2, 0) as "Entrega Pendiente NS2", PO.FechaEntregaProgramadaNS2 as "Fecha Entrega Programada NS2",
    COALESCE(I.CPS1_Inv, 0) + COALESCE(P.CPS1_Prod, 0) as "CPS1 Inv", COALESCE(P.CPS1_Prod, 0) as "CPS1 Prod", COALESCE(M.CPS1_NS0, 0) as "CPS1 NS0", COALESCE(M.CPS1_NS1, 0) as "CPS1 NS1", COALESCE(M.CPS1_NS2, 0) as "CPS1 NS2",
    COALESCE(I.CPS2_Inv, 0) + COALESCE(P.CPS2_Prod, 0) as "CPS2 Inv", COALESCE(P.CPS2_Prod, 0) as "CPS2 Prod", COALESCE(M.CPS2_NS0, 0) as "CPS2 NS0", COALESCE(M.CPS2_NS1, 0) as "CPS2 NS1", COALESCE(M.CPS2_NS2, 0) as "CPS2 NS2",
    COALESCE(I.CPT2_Inv, 0) + COALESCE(P.CPT2_Prod, 0) as "CPT2 Inv", COALESCE(P.CPT2_Prod, 0) as "CPT2 Prod", COALESCE(M.CPT2_NS0, 0) as "CPT2 NS0", COALESCE(M.CPT2_NS1, 0) as "CPT2 NS1", COALESCE(M.CPT2_NS2, 0) as "CPT2 NS2",
    COALESCE(I.CPB2_Inv, 0) + COALESCE(P.CPB2_Prod, 0) as "CPB2 Inv", COALESCE(P.CPB2_Prod, 0) as "CPB2 Prod", COALESCE(M.CPB2_NS0, 0) as "CPB2 NS0", COALESCE(M.CPB2_NS1, 0) as "CPB2 NS1", COALESCE(M.CPB2_NS2, 0) as "CPB2 NS2",
    COALESCE(I.CPB1_Inv, 0) + COALESCE(P.CPB1_Prod, 0) as "CPB1 Inv", COALESCE(P.CPB1_Prod, 0) as "CPB1 Prod", COALESCE(M.CPB1_NS0, 0) as "CPB1 NS0", COALESCE(M.CPB1_NS1, 0) as "CPB1 NS1", COALESCE(M.CPB1_NS2, 0) as "CPB1 NS2",
    COALESCE(I.CPS9_Inv, 0) + COALESCE(P.CPS9_Prod, 0) as "CPS9 Inv", COALESCE(P.CPS9_Prod, 0) as "CPS9 Prod", COALESCE(M.CPS9_NS0, 0) as "CPS9 NS0", COALESCE(M.CPS9_NS1, 0) as "CPS9 NS1", COALESCE(M.CPS9_NS2, 0) as "CPS9 NS2",
    COALESCE(I.CPT9_Inv, 0) + COALESCE(P.CPT9_Prod, 0) as "CPT9 Inv", COALESCE(P.CPT9_Prod, 0) as "CPT9 Prod", COALESCE(M.CPT9_NS0, 0) as "CPT9 NS0", COALESCE(M.CPT9_NS1, 0) as "CPT9 NS1", COALESCE(M.CPT9_NS2, 0) as "CPT9 NS2",
    COALESCE(I.CPB9_Inv, 0) + COALESCE(P.CPB9_Prod, 0) as "CPB9 Inv", COALESCE(P.CPB9_Prod, 0) as "CPB9 Prod", COALESCE(M.CPB9_NS0, 0) as "CPB9 NS0", COALESCE(M.CPB9_NS1, 0) as "CPB9 NS1", COALESCE(M.CPB9_NS2, 0) as "CPB9 NS2",
    COALESCE(I.CPE9_Inv, 0) + COALESCE(P.CPE9_Prod, 0) as "CPE9 Inv", COALESCE(P.CPE9_Prod, 0) as "CPE9 Prod", COALESCE(M.CPE9_NS0, 0) as "CPE9 NS0", COALESCE(M.CPE9_NS1, 0) as "CPE9 NS1", COALESCE(M.CPE9_NS2, 0) as "CPE9 NS2",
    COALESCE(I.CPK9_Inv, 0) + COALESCE(P.CPK9_Prod, 0) as "CPK9 Inv", COALESCE(P.CPK9_Prod, 0) as "CPK9 Prod", COALESCE(M.CPK9_NS0, 0) as "CPK9 NS0", COALESCE(M.CPK9_NS1, 0) as "CPK9 NS1", COALESCE(M.CPK9_NS2, 0) as "CPK9 NS2",
    COALESCE(I.CPO9_Inv, 0) + COALESCE(P.CPO9_Prod, 0) as "CPO9 Inv", COALESCE(P.CPO9_Prod, 0) as "CPO9 Prod", COALESCE(M.CPO9_NS0, 0) as "CPO9 NS0", COALESCE(M.CPO9_NS1, 0) as "CPO9 NS1", COALESCE(M.CPO9_NS2, 0) as "CPO9 NS2"
FROM INV_AGG I
FULL OUTER JOIN MRP_AGG M
    ON I.IdMaterial = M.IdMaterial
FULL OUTER JOIN PROD_AGG P
    ON COALESCE(I.IdMaterial, M.IdMaterial) = P.IdMaterial
FULL OUTER JOIN PO_AGG PO
    ON COALESCE(I.IdMaterial, M.IdMaterial, P.IdMaterial) = PO.IdMaterial
LEFT JOIN UNIDAD_AGG U
    ON COALESCE(I.IdMaterial, M.IdMaterial, P.IdMaterial, PO.IdMaterial) = U.IdMaterial
LEFT JOIN DB_TABLEAUDATASOURCE.CADENASUMINISTRO.TDS_VW_CDS_MAESTRAMATERIALES MM
    ON COALESCE(I.IdMaterial, M.IdMaterial, P.IdMaterial, PO.IdMaterial) = MM."IdMaterial"
ORDER BY IdMaterial
"""


@st.cache_data(ttl=3600, show_spinner=False)
def cargar_inventario_necesidad() -> pd.DataFrame:
    """Columnas tal como las nombra la consulta (alias sin comillas -> MAYUSCULA
    por defecto de Snowflake; alias entre comillas, ej. "CPS1 Inv", conservan su forma)."""
    return _query(QUERY_INVENTARIO_NECESIDAD)
