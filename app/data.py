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
-- Inventario + Produccion + Entregas Pendientes de OC + Necesidad MRP (semana 0,1,2), una fila por Material + Centro.
-- Centros materia prima (material inicia por '13'): CPS1, CPS2, CPT2, CPB2, CPB1
-- Centros empaque (material inicia por '14'): CPS9, CPT9, CPB9, CPE9, CPK9, CPO9
-- Excluye los almacenes: 0003, 0004, 0005, 0006, 0017, 0018, 0038, 0039 (solo aplica a inventario normal, InventarioProduccion es el 85% de esos almacenes)
-- Semana 0 = semana actual (lunes a domingo), Semana 1 = siguiente semana, Semana 2 = la que sigue.
-- Entrega Pendiente: ordenes de compra no entregadas totalmente (IndicadorEntregaFinal = FALSE), sumando
-- todos los almacenes, discriminadas por el centro real (IdCentroFase2) de TDS_VW_CDS_ORDENCOMPRA.

WITH INV_BASE AS (
    SELECT
        "IdMaterial"                as IdMaterial,
        "Material"                  as Material,
        "IdCentroFase2"             as Centro,
        "UnidadMedidaBase"          as Unidad,
        "CantidadLibreUtilizacion"  as Libre,
        "CantidadControlCalidad"   as Calidad,
        "CantidadBloqueado"        as Bloqueado
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
RES_BASE AS (
    -- Reservado global sin excepcion de almacenes
    SELECT
        "IdMaterial"                as IdMaterial,
        "IdCentroFase2"             as Centro,
        "CantidadReservado"         as Reservado
    FROM DB_TABLEAUDATASOURCE.CADENASUMINISTRO.TDS_VW_CDS_INVENTARIOMATERIALMMDIAACTUAL
    WHERE (
            ("IdMaterial" LIKE '13%' AND "IdCentroFase2" IN ('CPS1','CPS2','CPT2','CPB2','CPB1'))
         OR ("IdMaterial" LIKE '14%' AND "IdCentroFase2" IN ('CPS9','CPT9','CPB9','CPE9','CPK9','CPO9'))
          )
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
    -- Entregas pendientes de ordenes de compra (no entregadas totalmente), sumando todos los almacenes,
    -- discriminadas por el centro real (IdCentroFase2)
    SELECT
        "IdMaterial"           as IdMaterial,
        "IdCentroFase2"        as Centro,
        ("CantidadOrdenCompra" - "CantidadEntregada") as Cantidad,
        "FechaEntregaPosicion" as FechaEntrega,
        DATEDIFF('WEEK', DATE_TRUNC('WEEK', CURRENT_DATE()), DATE_TRUNC('WEEK', "FechaEntregaPosicion")) as Semana
    FROM DB_TABLEAUDATASOURCE.CADENASUMINISTRO.TDS_VW_CDS_ORDENCOMPRA
    WHERE "IndicadorEntregaFinal" = FALSE
      AND "TipoMaterial" IN ('ZMPR','ZEMP')
      AND (
            ("IdMaterial" LIKE '13%' AND "IdCentroFase2" IN ('CPS1','CPS2','CPT2','CPB2','CPB1'))
         OR ("IdMaterial" LIKE '14%' AND "IdCentroFase2" IN ('CPS9','CPT9','CPB9','CPE9','CPK9','CPO9'))
          )
),
PO_AGG AS (
    SELECT
        IdMaterial, Centro,
        SUM(CASE WHEN Semana = 0 THEN Cantidad ELSE 0 END) as EntregaPendienteS0,
        MIN(CASE WHEN Semana = 0 THEN FechaEntrega END)    as FechaEntregaProgramadaS0,
        SUM(CASE WHEN Semana = 1 THEN Cantidad ELSE 0 END) as EntregaPendienteS1,
        MIN(CASE WHEN Semana = 1 THEN FechaEntrega END)    as FechaEntregaProgramadaS1,
        SUM(CASE WHEN Semana = 2 THEN Cantidad ELSE 0 END) as EntregaPendienteS2,
        MIN(CASE WHEN Semana = 2 THEN FechaEntrega END)    as FechaEntregaProgramadaS2
    FROM PO_BASE
    WHERE Semana IN (0, 1, 2)
    GROUP BY IdMaterial, Centro
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
MATERIALES_ALL AS (
    SELECT DISTINCT IdMaterial FROM INV_BASE
    UNION SELECT DISTINCT IdMaterial FROM PROD_BASE
    UNION SELECT DISTINCT IdMaterial FROM RES_BASE
    UNION SELECT DISTINCT IdMaterial FROM MRP_BASE
    UNION SELECT DISTINCT IdMaterial FROM PO_BASE
),
CENTROS_RAW AS (
    SELECT 'CPS1' as Centro UNION ALL SELECT 'CPS2' UNION ALL SELECT 'CPT2' UNION ALL SELECT 'CPB2' UNION ALL SELECT 'CPB1'
),
CENTROS_EMP AS (
    SELECT 'CPS9' as Centro UNION ALL SELECT 'CPT9' UNION ALL SELECT 'CPB9' UNION ALL SELECT 'CPE9' UNION ALL SELECT 'CPK9' UNION ALL SELECT 'CPO9'
),
MATERIAL_CENTRO AS (
    SELECT MA.IdMaterial, C.Centro FROM MATERIALES_ALL MA CROSS JOIN CENTROS_RAW C WHERE MA.IdMaterial LIKE '13%'
    UNION ALL
    SELECT MA.IdMaterial, C.Centro FROM MATERIALES_ALL MA CROSS JOIN CENTROS_EMP C WHERE MA.IdMaterial LIKE '14%'
),
INV_AGG AS (
    SELECT
        IdMaterial, Centro,
        MAX(Material)             as Material,
        SUM(Libre)                as InventarioLibreUtilizacion,
        SUM(Calidad)              as InventarioCalidad,
        SUM(Bloqueado)            as InventarioBloqueado
    FROM INV_BASE
    GROUP BY IdMaterial, Centro
),
PROD_AGG AS (
    SELECT
        IdMaterial, Centro,
        (SUM(Libre) + SUM(Calidad)) * 0.85 as InventarioProduccion
    FROM PROD_BASE
    GROUP BY IdMaterial, Centro
),
RES_AGG AS (
    SELECT
        IdMaterial, Centro,
        SUM(Reservado) as CantidadReservado
    FROM RES_BASE
    GROUP BY IdMaterial, Centro
),
MRP_AGG AS (
    SELECT
        IdMaterial, Centro,
        SUM(CASE WHEN Semana = 0 THEN Cantidad ELSE 0 END) as NecesidadSemana0,
        SUM(CASE WHEN Semana = 1 THEN Cantidad ELSE 0 END) as NecesidadSemana1,
        SUM(CASE WHEN Semana = 2 THEN Cantidad ELSE 0 END) as NecesidadSemana2
    FROM MRP_BASE
    WHERE Semana IN (0, 1, 2)
    GROUP BY IdMaterial, Centro
)
SELECT
    MC.IdMaterial                                             as IdMaterial,
    COALESCE(I.Material, MM."Material")                       as Material,
    MC.Centro                                                 as IdCentro,
    COALESCE(U.UnidadMedida, MM."UnidadMedidaBase")            as UnidadMedida,
    COALESCE(I.InventarioLibreUtilizacion, 0)                  as InventarioLibreUtilizacion,
    COALESCE(I.InventarioCalidad, 0)                           as InventarioCalidad,
    COALESCE(I.InventarioBloqueado, 0)                         as CantidadBloqueado,
    COALESCE(RES.CantidadReservado, 0)                         as CantidadReservado,
    COALESCE(P.InventarioProduccion, 0)                        as InventarioProduccion,
    COALESCE(PO.EntregaPendienteS0, 0)                         as "Entrega Pendiente S0",
    PO.FechaEntregaProgramadaS0                                as "Fecha Entrega Programada S0",
    COALESCE(PO.EntregaPendienteS1, 0)                         as "Entrega Pendiente S1",
    PO.FechaEntregaProgramadaS1                                as "Fecha Entrega Programada S1",
    COALESCE(PO.EntregaPendienteS2, 0)                         as "Entrega Pendiente S2",
    PO.FechaEntregaProgramadaS2                                as "Fecha Entrega Programada S2",
    COALESCE(R.NecesidadSemana0, 0)                            as NecesidadSemana0,
    COALESCE(R.NecesidadSemana1, 0)                            as NecesidadSemana1,
    COALESCE(R.NecesidadSemana2, 0)                            as NecesidadSemana2
FROM MATERIAL_CENTRO MC
LEFT JOIN INV_AGG I  ON MC.IdMaterial = I.IdMaterial  AND MC.Centro = I.Centro
LEFT JOIN PROD_AGG P ON MC.IdMaterial = P.IdMaterial  AND MC.Centro = P.Centro
LEFT JOIN RES_AGG RES ON MC.IdMaterial = RES.IdMaterial AND MC.Centro = RES.Centro
LEFT JOIN MRP_AGG R  ON MC.IdMaterial = R.IdMaterial  AND MC.Centro = R.Centro
LEFT JOIN PO_AGG PO  ON MC.IdMaterial = PO.IdMaterial AND MC.Centro = PO.Centro
LEFT JOIN UNIDAD_AGG U ON MC.IdMaterial = U.IdMaterial
LEFT JOIN DB_TABLEAUDATASOURCE.CADENASUMINISTRO.TDS_VW_CDS_MAESTRAMATERIALES MM ON MC.IdMaterial = MM."IdMaterial"
WHERE COALESCE(I.InventarioLibreUtilizacion, 0) != 0
   OR COALESCE(I.InventarioCalidad, 0) != 0
   OR COALESCE(I.InventarioBloqueado, 0) != 0
   OR COALESCE(RES.CantidadReservado, 0) != 0
   OR COALESCE(P.InventarioProduccion, 0) != 0
   OR COALESCE(PO.EntregaPendienteS0, 0) != 0
   OR COALESCE(PO.EntregaPendienteS1, 0) != 0
   OR COALESCE(PO.EntregaPendienteS2, 0) != 0
   OR COALESCE(R.NecesidadSemana0, 0) != 0
   OR COALESCE(R.NecesidadSemana1, 0) != 0
   OR COALESCE(R.NecesidadSemana2, 0) != 0
ORDER BY MC.IdMaterial, MC.Centro
"""


@st.cache_data(ttl=3600, show_spinner=False)
def cargar_inventario_necesidad() -> pd.DataFrame:
    """Columnas tal como las nombra la consulta (alias sin comillas -> MAYUSCULA
    por defecto de Snowflake; alias entre comillas, ej. "CPS1 Inv", conservan su forma)."""
    return _query(QUERY_INVENTARIO_NECESIDAD)
