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

LUGAR_FISICO_POR_LETRA = {
    "S": "Super",
    "T": "Trululu",
    "B": "Bianchi",
    "E": "Oka Loka",
    "O": "Oka Loka",
    "K": "Centro robotizado",
}

RAZON_SOCIAL_POR_DIGITO = {
    "1": "Super",
    "2": "Trululu",
    "3": "Comercializadora",
    "9": "Comercializadora",
}

# Orden fijo en el que deben aparecer los grupos de centro, sin importar
# si se clasifico por lugar fisico o por razon social.
ORDEN_CENTROS = ["Super", "Trululu", "Bianchi", "Oka Loka", "Centro robotizado", "Comercializadora"]


def clasificar_lugar_fisico(id_centro: str) -> str:
    letra = id_centro[2].upper()
    return LUGAR_FISICO_POR_LETRA.get(letra, "Otro")


def clasificar_razon_social(id_centro: str) -> str:
    digito = id_centro[-1]
    return RAZON_SOCIAL_POR_DIGITO.get(digito, "Otro")


def clasificar_traslado(origen: str, destino: str) -> str:
    """Mismo ultimo digito de IdCentro = misma razon social = Nivelacion.
    Digito distinto = razones sociales distintas = Venta Interna."""
    return "Nivelacion" if origen[-1] == destino[-1] else "Venta Interna"


def _indice_orden(nombre_centro: str) -> int:
    try:
        return ORDEN_CENTROS.index(nombre_centro)
    except ValueError:
        return len(ORDEN_CENTROS)


def centros_disponibles(grupo: str, orden: str) -> list[str]:
    """Nombres de centro (ya clasificados) que puede tener este grupo,
    en el orden fijo Super/Trululu/Bianchi/Oka Loka/Centro robotizado/Comercializadora."""
    centros = CENTROS_MP if grupo == "MP" else CENTROS_ME
    clasificar = clasificar_lugar_fisico if orden == "fisico" else clasificar_razon_social
    nombres = {clasificar(c) for c in centros}
    return sorted(nombres, key=_indice_orden)


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
def simular_semanas(df_ancho: pd.DataFrame, grupo: str, modo: str) -> dict:
    """
    Devuelve, por material, el estado (inv_total, inv_libre_calidad,
    necesidad) de cada IdCentro fisico en las semanas 0, 1 y 2.

    modo="actual": cascada independiente por semana (igual que hoy en el
    Cuadro 1), sin corregir ningun deficit.
    modo="simulado": aplica, al final de cada semana, los traslados que
    sugeriria calcular_traslados_semana para esa semana (resta al origen,
    suma al destino, tanto en inv_total como en inv_libre_calidad) antes
    de pasar a la semana siguiente.

    Estructura del resultado:
        {IdMaterial: {"Material":, "UnidadMedida":,
                      "estado": {IdCentro: {0: {...}, 1: {...}, 2: {...}}}}}
    """
    centros = CENTROS_MP if grupo == "MP" else CENTROS_ME
    prefijo = "13" if grupo == "MP" else "14"
    df_grupo = df_ancho[df_ancho["IDMATERIAL"].str.startswith(prefijo)]

    resultado = {}
    for _, material in df_grupo.iterrows():
        id_mat = material["IDMATERIAL"]
        estado_centro: dict[str, dict[int, dict]] = {c: {} for c in centros}

        for centro in centros:
            inv = material.get(f"{centro} Inv", 0) or 0
            prod = material.get(f"{centro} Prod", 0) or 0
            estado_centro[centro][0] = {
                "inv_total": inv,
                "inv_libre_calidad": inv - prod,
                "necesidad": material.get(f"{centro} NS0", 0) or 0,
            }
            estado_centro[centro][1] = {"necesidad": material.get(f"{centro} NS1", 0) or 0}
            estado_centro[centro][2] = {"necesidad": material.get(f"{centro} NS2", 0) or 0}

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

        resultado[id_mat] = {
            "Material": material["MATERIAL"],
            "UnidadMedida": material["UNIDADMEDIDA"],
            "estado": estado_centro,
        }

    return resultado


@st.cache_data(show_spinner=False)
def construir_filas_inventario_necesidad(
    df_ancho: pd.DataFrame, grupo: str, semana: int, orden: str,
    centro_filtro: str | None = None, modo: str = "actual",
) -> list[dict]:
    """
    grupo: "MP" o "ME"
    semana: 0, 1 o 2
    orden: "fisico" o "razon_social"
    centro_filtro: si se indica, solo se devuelven filas de ese centro (ya clasificado)
    modo: "actual" o "simulado" (ver simular_semanas)

    Cuando dos IdCentro caen en el mismo nombre de centro (ej. CPS1 y CPS2
    -> "Super"), la pastilla de Centro se agrupa visualmente, pero
    Inventario/Necesidad/Entrega Pendiente/Fecha Entrega NO se suman: cada
    IdCentro conserva sus propios valores, en su propia fila.
    """
    centros = CENTROS_MP if grupo == "MP" else CENTROS_ME
    clasificar = clasificar_lugar_fisico if orden == "fisico" else clasificar_razon_social
    centros_ordenados = sorted(centros, key=lambda c: _indice_orden(clasificar(c)))

    prefijo = "13" if grupo == "MP" else "14"
    df_grupo = df_ancho[df_ancho["IDMATERIAL"].str.startswith(prefijo)]
    estados = simular_semanas(df_ancho, grupo, modo)

    filas = []
    for _, material in df_grupo.iterrows():
        id_mat = material["IDMATERIAL"]
        entrega_pendiente = material.get(f"Entrega Pendiente NS{semana}", 0) or 0
        fecha_entrega = material.get(f"Fecha Entrega Programada NS{semana}")
        estado_centro = estados[id_mat]["estado"]

        for centro in centros_ordenados:
            nombre = clasificar(centro)
            if centro_filtro is not None and nombre != centro_filtro:
                continue

            datos_semana = estado_centro[centro][semana]
            inv = datos_semana["inv_total"]
            nec = datos_semana["necesidad"]

            if inv == 0 and nec == 0 and entrega_pendiente == 0:
                continue

            filas.append({
                "IdMaterial": id_mat,
                "Material": material["MATERIAL"],
                "UnidadMedida": material["UNIDADMEDIDA"],
                "Centro": nombre,
                "IdCentro": centro,
                "Inventario": inv,
                "Necesidad": nec,
                "EntregaPendiente": entrega_pendiente,
                "FechaEntrega": fecha_entrega,
            })

    filas.sort(key=lambda f: (f["IdMaterial"], _indice_orden(f["Centro"])))
    return filas


@st.cache_data(show_spinner=False)
def construir_filas_traslados(
    df_ancho: pd.DataFrame, grupo: str, semana: int, modo: str,
    origen_filtro: str | None = None, destino_filtro: str | None = None,
    clasificacion_filtro: str | None = None,
) -> list[dict]:
    """Traslados sugeridos (Nivelacion / Venta Interna) para la semana y
    modo (actual/simulado) indicados, con filtros opcionales de Origen,
    Destino y Clasificacion (todos por IdCentro/nombre real)."""
    centros = CENTROS_MP if grupo == "MP" else CENTROS_ME
    estados = simular_semanas(df_ancho, grupo, modo)

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
