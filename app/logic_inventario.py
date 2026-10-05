"""Logica de negocio del Cuadro 1 (Inventario y Necesidad) y del Cuadro 2
(Nivelaciones y Ventas Internas).

Transforma el resultado ancho de QUERY_INVENTARIO_NECESIDAD (app/data.py)
-- una fila por material, columnas repetidas por centro y por semana --
en las vistas de ambos cuadros.

Snowflake devuelve los alias sin comillas en MAYUSCULA (IdMaterial ->
IDMATERIAL) y los alias entre comillas tal cual se escribieron, con
espacios ("CPS1 Inv", "Entrega Pendiente NS0", ...).
"""

import pandas as pd
import streamlit as st

CENTROS_MP = ["CPS1", "CPS2", "CPT2", "CPB2", "CPB1"]
CENTROS_ME = ["CPS9", "CPT9", "CPB9", "CPE9", "CPK9", "CPO9"]


def clasificar_traslado(origen: str, destino: str) -> str:
    """Mismo ultimo digito de IdCentro = misma razon social = Nivelacion.
    Digito distinto = razones sociales distintas = Venta Interna."""
    return "Nivelacion" if origen[-1] == destino[-1] else "Venta Interna"


def calcular_traslados_semana(estado: dict[str, dict], centros_ordenados: list[str]) -> list[dict]:
    """
    estado: {IdCentro: {"inv_total":, "inv_libre_calidad":, "necesidad":}}
            para UNA semana y UN material.
    centros_ordenados: lista de IdCentro en un orden fijo (para desempatar).

    Reglas:
    - superavit(c) = inv_total(c) - necesidad(c).
    - Un centro solo puede ser ORIGEN si superavit(c) > 0; lo maximo que
      puede enviar es min(superavit(c), inv_libre_calidad(c)) -- nunca se
      usa inventario de produccion para traslados, y nunca se deja al
      origen en deficit.
    - Los origenes se usan en orden de MAYOR superavit primero; un mismo
      origen puede repartirse entre varios destinos.
    - Los destinos (superavit(c) < 0) se atienden en orden de MENOR
      deficit primero, para maximizar cuantos centros quedan cubiertos.
    """
    superavit = {c: estado[c]["inv_total"] - estado[c]["necesidad"] for c in centros_ordenados}

    origenes = [c for c in centros_ordenados if superavit[c] > 0]
    origenes.sort(key=lambda c: (-superavit[c], centros_ordenados.index(c)))
    capacidad_restante = {c: min(superavit[c], estado[c]["inv_libre_calidad"]) for c in origenes}
    capacidad_restante = {c: cap for c, cap in capacidad_restante.items() if cap > 0}
    origenes = [c for c in origenes if c in capacidad_restante]

    destinos = [c for c in centros_ordenados if superavit[c] < 0]
    destinos.sort(key=lambda c: (-superavit[c], centros_ordenados.index(c)))  # -superavit = deficit, ascendente

    traslados = []
    for destino in destinos:
        falta = -superavit[destino]
        for origen in origenes:
            if falta <= 0:
                break
            disponible = capacidad_restante.get(origen, 0)
            if disponible <= 0:
                continue
            enviar = min(falta, disponible)
            if enviar <= 0:
                continue
            traslados.append({"Origen": origen, "Destino": destino, "Cantidad": enviar})
            capacidad_restante[origen] -= enviar
            falta -= enviar

    return traslados


@st.cache_data(show_spinner=False)
def simular_semanas(df_largo: pd.DataFrame, grupo: str, modo: str) -> dict:
    """
    Devuelve, por material, el estado (inv_total, inv_libre_calidad,
    necesidad) de cada IdCentro fisico en las semanas 0, 1 y 2.

    df_largo viene en formato largo (una fila por Material+Centro, ver
    QUERY_INVENTARIO_NECESIDAD en data.py): IDMATERIAL, MATERIAL, IDCENTRO,
    UNIDADMEDIDA, INVENTARIOLIBREUTILIZACION, INVENTARIOCALIDAD,
    CANTIDADBLOQUEADO, INVENTARIOPRODUCCION, NECESIDADSEMANA0/1/2,
    "Entrega Pendiente S0/1/2", "Fecha Entrega Programada S0/1/2" (ya
    discriminadas por centro).

    inv_total(semana0) = Libre + Calidad + Produccion.
    inv_libre_calidad(semana0) = Libre + Calidad (nunca incluye Produccion,
    que solo sirve para cubrir la necesidad del propio centro, nunca para
    traslados). CantidadBloqueado es puramente informativo: no participa
    en inv_total/inv_libre_calidad ni en la cascada o los traslados.

    modo="actual": cascada independiente por semana (igual que hoy en el
    Cuadro 1), sin corregir ningun deficit ni sumar entregas pendientes.
    modo="simulado":
    - Antes de calcular los traslados de la semana 0, suma la Entrega
      Pendiente S0 de cada centro a su inv_total/inv_libre_calidad (ya que
      ahora viene discriminada por centro real): esas ordenes llegan esta
      semana, asi que un centro que las recibe ya cuenta con ese inventario
      para decidir si necesita o puede dar un traslado. Las semanas 1 y 2
      no suman entrega pendiente (solo aplica a la semana actual).
    - Al final de cada semana, aplica los traslados que sugeriria
      calcular_traslados_semana para esa semana (resta al origen, suma al
      destino, tanto en inv_total como en inv_libre_calidad) antes de pasar
      a la semana siguiente.

    Estructura del resultado:
        {IdMaterial: {"Material":, "UnidadMedida":,
                      "estado": {IdCentro: {0: {...}, 1: {...}, 2: {...}}},
                      "bloqueado": {IdCentro: cantidad},
                      "entrega_pendiente": {IdCentro: {0: {"cantidad":, "fecha":}, 1: {...}, 2: {...}}}}}
    """
    centros = CENTROS_MP if grupo == "MP" else CENTROS_ME
    prefijo = "13" if grupo == "MP" else "14"
    df_grupo = df_largo[df_largo["IDMATERIAL"].str.startswith(prefijo)]

    resultado = {}
    for id_mat, filas_material in df_grupo.groupby("IDMATERIAL"):
        filas_centro = {fila["IDCENTRO"]: fila for _, fila in filas_material.iterrows()}
        estado_centro: dict[str, dict[int, dict]] = {c: {} for c in centros}
        bloqueado_centro: dict[str, float] = {}
        entrega_centro: dict[str, dict[int, dict]] = {c: {} for c in centros}

        for centro in centros:
            fila = filas_centro.get(centro)
            libre = (fila.get("INVENTARIOLIBREUTILIZACION", 0) or 0) if fila is not None else 0
            calidad = (fila.get("INVENTARIOCALIDAD", 0) or 0) if fila is not None else 0
            produccion = (fila.get("INVENTARIOPRODUCCION", 0) or 0) if fila is not None else 0
            bloqueado_centro[centro] = (fila.get("CANTIDADBLOQUEADO", 0) or 0) if fila is not None else 0
            inv_libre_calidad = libre + calidad

            estado_centro[centro][0] = {
                "inv_total": inv_libre_calidad + produccion,
                "inv_libre_calidad": inv_libre_calidad,
                "necesidad": (fila.get("NECESIDADSEMANA0", 0) or 0) if fila is not None else 0,
            }
            estado_centro[centro][1] = {"necesidad": (fila.get("NECESIDADSEMANA1", 0) or 0) if fila is not None else 0}
            estado_centro[centro][2] = {"necesidad": (fila.get("NECESIDADSEMANA2", 0) or 0) if fila is not None else 0}

            for s in (0, 1, 2):
                entrega_centro[centro][s] = {
                    "cantidad": (fila.get(f"Entrega Pendiente S{s}", 0) or 0) if fila is not None else 0,
                    "fecha": (fila.get(f"Fecha Entrega Programada S{s}")) if fila is not None else None,
                }

        if modo == "simulado":
            for centro in centros:
                cantidad_s0 = entrega_centro[centro][0]["cantidad"]
                estado_centro[centro][0]["inv_total"] += cantidad_s0
                estado_centro[centro][0]["inv_libre_calidad"] += cantidad_s0

        for semana in (0, 1):
            for centro in centros:
                actual = estado_centro[centro][semana]
                estado_centro[centro][semana + 1]["inv_total"] = actual["inv_total"] - actual["necesidad"]
                estado_centro[centro][semana + 1]["inv_libre_calidad"] = (
                    actual["inv_libre_calidad"] - actual["necesidad"]
                )

            if modo == "simulado":
                estado_semana = {c: estado_centro[c][semana] for c in centros}
                traslados = calcular_traslados_semana(estado_semana, centros)
                for t in traslados:
                    origen, destino, cantidad = t["Origen"], t["Destino"], t["Cantidad"]
                    estado_centro[origen][semana + 1]["inv_total"] -= cantidad
                    estado_centro[origen][semana + 1]["inv_libre_calidad"] -= cantidad
                    estado_centro[destino][semana + 1]["inv_total"] += cantidad
                    estado_centro[destino][semana + 1]["inv_libre_calidad"] += cantidad

        primera = filas_material.iloc[0]
        resultado[id_mat] = {
            "Material": primera["MATERIAL"],
            "UnidadMedida": primera["UNIDADMEDIDA"],
            "estado": estado_centro,
            "bloqueado": bloqueado_centro,
            "entrega_pendiente": entrega_centro,
        }

    return resultado


@st.cache_data(show_spinner=False)
def construir_filas_inventario_necesidad(
    df_largo: pd.DataFrame, grupo: str, semana: int,
    idcentro_filtro: tuple[str, ...] | None = None, modo: str = "actual",
) -> list[dict]:
    """
    grupo: "MP" o "ME"
    semana: 0, 1 o 2
    idcentro_filtro: si se indica, solo se devuelven filas de esos IdCentro
        (tupla de codigos reales, ej. ("CPS1", "CPT2")).
    modo: "actual" o "simulado" (ver simular_semanas)
    """
    centros = CENTROS_MP if grupo == "MP" else CENTROS_ME

    estados = simular_semanas(df_largo, grupo, modo)
    resaltar_entrega = modo == "simulado" and semana == 0

    filas = []
    for id_mat, info in estados.items():
        estado_centro = info["estado"]
        bloqueado_centro = info["bloqueado"]
        entrega_centro = info["entrega_pendiente"]

        for centro in centros:
            if idcentro_filtro is not None and centro not in idcentro_filtro:
                continue

            datos_semana = estado_centro[centro][semana]
            inv = datos_semana["inv_total"]
            nec = datos_semana["necesidad"]

            if inv == 0 and nec == 0:
                continue

            entrega = entrega_centro[centro][semana]

            filas.append({
                "IdMaterial": id_mat,
                "Material": info["Material"],
                "UnidadMedida": info["UnidadMedida"],
                "IdCentro": centro,
                "Inventario": inv,
                "Necesidad": nec,
                "Bloqueado": bloqueado_centro.get(centro, 0),
                "EntregaPendiente": entrega["cantidad"],
                "FechaEntrega": entrega["fecha"],
                "ResaltarEntrega": resaltar_entrega,
            })

    filas.sort(key=lambda f: (f["IdMaterial"], centros.index(f["IdCentro"])))
    return filas


@st.cache_data(show_spinner=False)
def construir_filas_traslados(
    df_largo: pd.DataFrame, grupo: str, semana: int, modo: str,
    origen_filtro: str | None = None, destino_filtro: str | None = None,
    clasificacion_filtro: str | None = None,
) -> list[dict]:
    """Traslados sugeridos (Nivelacion / Venta Interna) para la semana y
    modo (actual/simulado) indicados, con filtros opcionales de Origen,
    Destino y Clasificacion (todos por IdCentro/nombre real)."""
    centros = CENTROS_MP if grupo == "MP" else CENTROS_ME
    estados = simular_semanas(df_largo, grupo, modo)

    filas = []
    for id_mat, info in estados.items():
        estado_semana = {c: info["estado"][c][semana] for c in centros}
        for t in calcular_traslados_semana(estado_semana, centros):
            origen, destino, cantidad = t["Origen"], t["Destino"], t["Cantidad"]
            clasificacion = clasificar_traslado(origen, destino)

            if origen_filtro is not None and origen != origen_filtro:
                continue
            if destino_filtro is not None and destino != destino_filtro:
                continue
            if clasificacion_filtro is not None and clasificacion != clasificacion_filtro:
                continue

            filas.append({
                "IdMaterial": id_mat,
                "Material": info["Material"],
                "UnidadMedida": info["UnidadMedida"],
                "Cantidad": cantidad,
                "Origen": origen,
                "Destino": destino,
                "Clasificacion": clasificacion,
            })

    filas.sort(key=lambda f: (f["IdMaterial"], f["Origen"]))
    return filas


def construir_filas_combinadas(
    df_largo: pd.DataFrame, grupo: str, semana: int, modo: str,
    idcentro_filtro: tuple[str, ...] | None = None,
    centro_destino_filtro: tuple[str, ...] | None = None, clasificacion_filtro: str | None = None,
) -> list[dict]:
    """
    Combina Inventario y Necesidad con las Nivelaciones/Ventas Internas
    sugeridas en una sola vista: cada fila de `construir_filas_inventario_necesidad`
    (un IdCentro real) se expande en una sub-fila por cada traslado donde ese
    IdCentro participa como ORIGEN (el que despacha), agregando
    CentroNivelar/CantidadNivelar/ClasificacionNivelar. Un IdCentro que solo
    participa como destino (recibe) no muestra nada en esas 3 columnas, ya
    que el traslado ya se ve en la fila de su origen. Si no participa como
    origen en ningun traslado, queda una sola fila con esos 3 campos en None
    (a menos que haya un filtro de centro_destino/clasificacion activo, en
    cuyo caso esa fila sin coincidencia se oculta).

    grupo: "MP", "ME" o "AMBOS" (combina ambos grupos en una sola lista).
    idcentro_filtro: tupla de codigos reales de IdCentro a incluir (None = todos).
    centro_destino_filtro: tupla de IdCentro; filtra las sub-filas de
    nivelacion cuyo CentroNivelar este en esa tupla (None = todos).
    """
    if grupo == "AMBOS":
        return [
            *construir_filas_combinadas(
                df_largo, "MP", semana, modo, idcentro_filtro, centro_destino_filtro, clasificacion_filtro,
            ),
            *construir_filas_combinadas(
                df_largo, "ME", semana, modo, idcentro_filtro, centro_destino_filtro, clasificacion_filtro,
            ),
        ]

    filas_inv = construir_filas_inventario_necesidad(
        df_largo, grupo=grupo, semana=semana, idcentro_filtro=idcentro_filtro, modo=modo,
    )
    filas_tras = construir_filas_traslados(df_largo, grupo=grupo, semana=semana, modo=modo)

    nivelaciones: dict[tuple[str, str], list[dict]] = {}
    for t in filas_tras:
        nivelaciones.setdefault((t["IdMaterial"], t["Origen"]), []).append({
            "CentroNivelar": t["Destino"],
            "CantidadNivelar": t["Cantidad"],
            "ClasificacionNivelar": t["Clasificacion"],
        })

    hay_filtro_nivelacion = centro_destino_filtro is not None or clasificacion_filtro is not None

    filas = []
    for fila in filas_inv:
        matches = nivelaciones.get((fila["IdMaterial"], fila["IdCentro"]), [])
        if centro_destino_filtro is not None:
            matches = [m for m in matches if m["CentroNivelar"] in centro_destino_filtro]
        if clasificacion_filtro is not None:
            matches = [m for m in matches if m["ClasificacionNivelar"] == clasificacion_filtro]

        if not matches:
            if hay_filtro_nivelacion:
                continue
            filas.append({**fila, "CentroNivelar": None, "CantidadNivelar": None, "ClasificacionNivelar": None})
        else:
            for match in matches:
                filas.append({**fila, **match})

    return filas
