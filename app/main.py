"""Tablero Nivelacion y Ventas Internas Materias Primas y Material Empaque."""

import base64
import html as html_lib
from pathlib import Path

import streamlit as st

from styles import GLOBAL_CSS, CLASIFICACION_COLORES
from components import (
    render_combinado_table,
    render_card,
    render_pill_filtro_css,
    render_count_badges,
)
from data import cargar_inventario_necesidad
from logic_inventario import (
    construir_filas_combinadas,
    centros_disponibles,
    CENTROS_MP,
    CENTROS_ME,
)

st.set_page_config(page_title="Nivelacion y Ventas Internas MP y ME", layout="wide")
st.markdown(GLOBAL_CSS, unsafe_allow_html=True)

# ---------- Header ----------
fecha_actualizacion = ""  # Deja vacío si no necesitas la fecha
semana_actual = None

_semana_txt = f" &nbsp;·&nbsp; Semana <b>{semana_actual}</b>" if semana_actual else ""
sello_fecha = (
    f"<div class='updated'>Datos actualizados al <b>{html_lib.escape(fecha_actualizacion)}</b>"
    f"{_semana_txt}</div>"
    if fecha_actualizacion
    else ""
)

# Cargar el logo
logo_path = Path("app/static/logo_super.png")
logo_b64 = ""
if logo_path.exists():
    with open(logo_path, "rb") as f:
        logo_b64 = base64.b64encode(f.read()).decode()
else:
    # Fallback si se ejecuta desde dentro de app/
    logo_path_fallback = Path("static/logo_super.png")
    if logo_path_fallback.exists():
        with open(logo_path_fallback, "rb") as f:
            logo_b64 = base64.b64encode(f.read()).decode()

# Renderizar el encabezado completo (Hero)
st.markdown(
    "<div class='hero'>"
    f"<img src='data:image/png;base64,{logo_b64}' style='position: absolute; left: 4%; top: 50%; transform: translateY(-50%); height: 75px; filter: drop-shadow(0px 0px 8px rgba(255,219,0,0.6)) drop-shadow(0px 4px 12px rgba(0,51,160,0.7));'>"
    "<h1>NIVELACIÓN Y VENTAS INTERNAS MP Y ME</h1>"
    "<div class='bar'></div>"
    f"{sello_fecha}</div>",
    unsafe_allow_html=True,
)

with st.spinner("Cargando datos desde Snowflake..."):
    df_consolidado = cargar_inventario_necesidad()

# ================= Filtros generales =================
col_orden, col_semana, col_grupo, col_modo = st.columns(4)
with col_orden:
    st.markdown("**Orden**")
    orden_label = st.radio(
        "orden", ["Por lugar físico", "Por razón social"],
        horizontal=True, label_visibility="collapsed", key="orden",
    )
with col_semana:
    st.markdown("**Semana**")
    semana_label = st.radio(
        "semana", ["Semana actual", "Próxima semana", "Semana actual + 2"],
        horizontal=True, label_visibility="collapsed", key="semana",
    )
with col_grupo:
    st.markdown("**Grupo**")
    grupo_label = st.radio(
        "grupo", ["Materia Prima", "Material de Empaque"],
        horizontal=True, label_visibility="collapsed", key="grupo",
    )
with col_modo:
    st.markdown("**Inventario**")
    modo_label = st.radio(
        "modo", ["Actual", "Simulado"],
        horizontal=True, label_visibility="collapsed", key="modo",
    )

orden = "fisico" if orden_label == "Por lugar físico" else "razon_social"
semana = {"Semana actual": 0, "Próxima semana": 1, "Semana actual + 2": 2}[semana_label]
grupo = "MP" if grupo_label == "Materia Prima" else "ME"
modo = "actual" if modo_label == "Actual" else "simulado"

centros_grupo = CENTROS_MP if grupo == "MP" else CENTROS_ME

st.markdown("**Centro**")
opciones_centro = centros_disponibles(grupo, orden)

if st.session_state.get("centro_activo") not in opciones_centro:
    st.session_state["centro_activo"] = None

st.markdown(render_pill_filtro_css(opciones_centro, st.session_state["centro_activo"], "pill"), unsafe_allow_html=True)

with st.container(key="fila_pills_centro"):
    for nombre in opciones_centro:
        clave_boton = f"pill_{nombre}".replace(" ", "_")
        with st.container(key=clave_boton):
            if st.button(nombre, key=f"pill_btn_{clave_boton}"):
                st.session_state["centro_activo"] = (
                    None if st.session_state["centro_activo"] == nombre else nombre
                )

centro_filtro = st.session_state["centro_activo"]

busqueda = st.text_input("🔍 Buscar Material (ID o Nombre)", key="busqueda")

# ================= Filtros de nivelacion/venta interna =================
col_idcentro, col_clasif, col_destino = st.columns(3)
with col_idcentro:
    st.markdown("**IdCentro**")
    idcentro_label = st.selectbox(
        "idcentro_filtro", ["Todos"] + centros_grupo, label_visibility="collapsed", key="idcentro_filtro",
    )
with col_clasif:
    st.markdown("**Clasificación**")
    clasificacion_label = st.radio(
        "clasificacion_filtro", ["Todas", "Nivelacion", "Venta Interna"],
        horizontal=True, label_visibility="collapsed", key="clasificacion_filtro",
    )
with col_destino:
    st.markdown("**Centro Destino**")
    centro_destino_label = st.selectbox(
        "centro_destino_filtro", ["Todos"] + centros_grupo, label_visibility="collapsed", key="centro_destino_filtro",
    )

idcentro_filtro = None if idcentro_label == "Todos" else idcentro_label
clasificacion_filtro = None if clasificacion_label == "Todas" else clasificacion_label
centro_destino_filtro = None if centro_destino_label == "Todos" else centro_destino_label

filas_combinadas = construir_filas_combinadas(
    df_consolidado, grupo=grupo, semana=semana, orden=orden, modo=modo,
    centro_filtro=centro_filtro, idcentro_filtro=idcentro_filtro,
    centro_destino_filtro=centro_destino_filtro, clasificacion_filtro=clasificacion_filtro,
)

if busqueda:
    termino = busqueda.lower()
    filas_combinadas = [
        f for f in filas_combinadas
        if termino in str(f.get("IdMaterial", "")).lower() or termino in str(f.get("Material", "")).lower()
    ]

total_nivelacion = sum(1 for f in filas_combinadas if f.get("ClasificacionNivelar") == "Nivelacion")
total_venta_interna = sum(1 for f in filas_combinadas if f.get("ClasificacionNivelar") == "Venta Interna")

st.markdown(
    render_count_badges([
        ("TOTAL TRASLADOS", str(total_nivelacion + total_venta_interna), "#013066"),
        ("NIVELACION", str(total_nivelacion), CLASIFICACION_COLORES["Nivelacion"]),
        ("VENTA INTERNA", str(total_venta_interna), CLASIFICACION_COLORES["Venta Interna"]),
    ]),
    unsafe_allow_html=True,
)

if not filas_combinadas:
    st.info("No hay datos para los filtros seleccionados.")
else:
    st.markdown(render_card(render_combinado_table(filas_combinadas)), unsafe_allow_html=True)
