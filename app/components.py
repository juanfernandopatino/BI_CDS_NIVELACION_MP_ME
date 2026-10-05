"""Helpers de UI reutilizables: header, tarjetas, pildoras y tablas HTML."""

from datetime import datetime

import pandas as pd

from styles import COMPANIA_COLORES, ESTADO_COLORES, CLASIFICACION_COLORES


def formato_valor(valor):
    """Nunca mostrar None/nan; helper de formato central."""
    if valor is None:
        return ""
    try:
        if valor != valor:  # NaN
            return ""
    except TypeError:
        pass
    return valor


def render_header(titulo: str, subtitulo_actualizacion: str | None = None, semana: int | None = None):
    if subtitulo_actualizacion is None:
        subtitulo_actualizacion = datetime.now().strftime("%d de %B de %Y, %H:%M")
    badge = f'<span class="status-dot"></span>Datos actualizados al <b>{subtitulo_actualizacion}</b>'
    if semana is not None:
        badge += f" &nbsp;·&nbsp; Semana {semana}"
    html = f"""
    <div class="app-header">
        <h1>{titulo}</h1>
        <div class="header-rule"></div>
        <span class="header-badge">{badge}</span>
    </div>
    """
    return html


def render_pill(texto: str, color: str) -> str:
    return f'<span class="pill" style="background:{color}">{texto}</span>'


def render_metric_table(row_labels: list[str], companias: list[str], valores: dict, filas_totales: set[str] | None = None) -> str:
    """
    valores: dict[label][compania] -> string ya formateado (ej "$100.597M")
    filas_totales: labels que deben resaltarse en negrilla (fila "Valor Inventario Total")
    """
    filas_totales = filas_totales or set()
    header_cells = "".join(
        f'<th>{render_pill(c, COMPANIA_COLORES.get(c, "#013066"))}</th>' for c in companias
    )
    rows_html = ""
    for label in row_labels:
        clase = "metric-total" if label in filas_totales else ""
        cells = "".join(f"<td>{formato_valor(valores.get(label, {}).get(c, ''))}</td>" for c in companias)
        rows_html += f'<tr class="{clase}"><td>{label}</td>{cells}</tr>'

    return f"""
    <table class="metric-table">
        <thead><tr><th></th>{header_cells}</tr></thead>
        <tbody>{rows_html}</tbody>
    </table>
    """


def render_status_strip(estados: list[tuple[str, str]]) -> str:
    """estados: lista de (nombre_estado, texto_a_mostrar) en el orden fijo deseado."""
    segs = "".join(
        f'<div class="seg" style="background:{ESTADO_COLORES.get(nombre, "#888")}">{texto}</div>'
        for nombre, texto in estados
    )
    return f'<div class="status-strip">{segs}</div>'


def render_count_badges(pares: list[tuple[str, str, str]]) -> str:
    """pares: lista de (etiqueta, valor, color)."""
    return "".join(
        f'<span class="count-badge" style="background:{color}">{etiqueta}: {valor}</span>'
        for etiqueta, valor, color in pares
    )


def render_detail_table(columnas: list[str], filas: list[tuple], columna_estado_idx: int | None = None) -> str:
    """
    Renderiza tabla HTML de detalle usando itertuples-friendly input (lista de tuplas),
    NUNCA con iterrows + concatenacion de strings.
    columna_estado_idx: si se define, esa columna se pinta con un punto de color segun ESTADO_COLORES.
    """
    header_html = "".join(f"<th>{c}</th>" for c in columnas)

    partes = []
    for fila in filas:
        celdas = []
        for idx, valor in enumerate(fila):
            valor_fmt = formato_valor(valor)
            if idx == columna_estado_idx:
                color = ESTADO_COLORES.get(valor_fmt, "#999")
                celdas.append(
                    f'<td style="text-align:left"><span class="status-dot-cell" '
                    f'style="background:{color}"></span>{valor_fmt}</td>'
                )
            else:
                celdas.append(f"<td>{valor_fmt}</td>")
        partes.append(f"<tr>{''.join(celdas)}</tr>")

    body_html = "".join(partes)

    return f"""
    <div class="detail-table-outer">
        <div class="detail-table-wrap">
            <table class="detail-table">
                <thead><tr>{header_html}</tr></thead>
                <tbody>{body_html}</tbody>
            </table>
        </div>
    </div>
    """


def render_card(contenido_html: str, titulo: str | None = None) -> str:
    """Envuelve contenido HTML en una tarjeta blanca en UN SOLO string.

    Streamlit renderiza cada st.markdown como un fragmento HTML aislado:
    abrir el <div> en una llamada y el contenido en otra deja el div vacio
    (el navegador lo autocierra) y el contenido cae fuera, sin estilo.
    Por eso el div y su contenido deben ir siempre en un unico st.markdown.
    """
    titulo_html = f'<div class="card-title">{titulo}</div>' if titulo else ""
    return f'<div class="card">{titulo_html}{contenido_html}</div>'


def _formato_fecha(valor) -> str:
    valor_fmt = formato_valor(valor)
    if valor_fmt == "":
        return ""
    if hasattr(valor_fmt, "strftime"):
        return valor_fmt.strftime("%d/%m")
    try:
        return pd.to_datetime(valor_fmt).strftime("%d/%m")
    except (ValueError, TypeError):
        return str(valor_fmt)


def _formato_numero(valor) -> str:
    valor_fmt = formato_valor(valor)
    if isinstance(valor_fmt, (int, float)):
        return f"{valor_fmt:,.0f}"
    return valor_fmt




def render_traslados_table(filas: list[dict]) -> str:
    """
    Tabla HTML agrupada: ID/Material/UM con rowspan sobre todo el material,
    y Origen con rowspan sobre sus destinos consecutivos dentro del mismo
    material (cuando un origen reparte a varios destinos). `filas` debe
    venir ordenada por (IdMaterial, Origen). Orden de columnas:
    ID, Material, UM, Origen, Cantidad, Destino, Clasificacion.
    Construida con listas + "".join(...), nunca iterrows + concatenacion.
    """
    columnas = ["ID", "Material", "UM", "Origen", "Cantidad", "Destino", "Clasificacion"]
    header_html = "".join(f"<th>{c}</th>" for c in columnas)

    materiales: dict[str, list[dict]] = {}
    orden_materiales: list[str] = []
    for fila in filas:
        id_mat = fila["IdMaterial"]
        if id_mat not in materiales:
            materiales[id_mat] = []
            orden_materiales.append(id_mat)
        materiales[id_mat].append(fila)

    partes = []
    for id_mat in orden_materiales:
        filas_material = materiales[id_mat]
        primera = filas_material[0]
        total_filas_material = len(filas_material)
        borde_grupo = "border-bottom:2px solid #013066;"

        rowspan_restante = 0
        for i, fila in enumerate(filas_material):
            celdas = []
            if i == 0:
                celdas.append(f'<td rowspan="{total_filas_material}">{formato_valor(primera["IdMaterial"])}</td>')
                celdas.append(f'<td rowspan="{total_filas_material}" style="text-align:left">{formato_valor(primera["Material"])}</td>')
                celdas.append(f'<td rowspan="{total_filas_material}">{formato_valor(primera["UnidadMedida"])}</td>')

            if rowspan_restante == 0:
                rowspan_restante = 1
                while (
                    i + rowspan_restante < total_filas_material
                    and filas_material[i + rowspan_restante]["Origen"] == fila["Origen"]
                ):
                    rowspan_restante += 1
                celdas.append(f'<td rowspan="{rowspan_restante}">{formato_valor(fila["Origen"])}</td>')

            clasificacion = formato_valor(fila["Clasificacion"])
            color = CLASIFICACION_COLORES.get(clasificacion, "#546E7A")
            celdas.append(f"<td style='text-align: right;'>{_formato_numero(fila['Cantidad'])}</td>")
            celdas.append(f'<td>{formato_valor(fila["Destino"])}</td>')
            celdas.append(f"<td>{render_pill(clasificacion, color)}</td>")

            rowspan_restante -= 1

            estilo_borde = f' style="{borde_grupo}"' if i == total_filas_material - 1 else ""
            partes.append(f"<tr{estilo_borde}>{''.join(celdas)}</tr>")

    body_html = "".join(partes)

    return f"""
    <div class="detail-table-outer">
        <div class="detail-table-wrap">
            <table class="detail-table">
                <thead><tr>{header_html}</tr></thead>
                <tbody>{body_html}</tbody>
            </table>
        </div>
    </div>
    """


def render_combinado_table(filas: list[dict]) -> str:
    """
    Tabla HTML con 2 niveles de agrupacion visual, `filas` debe venir
    ordenada por material y por IdCentro (una fila por cada traslado en el
    que participa un IdCentro, o una sola si no participa en ninguno):
      - Material: ID/Material/UM con rowspan sobre TODO el material.
      - IdCentro: Inventario/Necesidad/Entrega Pendiente/Fecha Entrega se
        agrupan (rowspan) sobre las sub-filas de nivelacion de ESE IdCentro
        (puede tener 0, 1 o varios traslados).
      - Centro a Nivelar/Cantidad a Nivelar/Clasificacion: una fila por
        cada traslado real; vacias si el IdCentro no tiene ninguno.
    Construida con listas + "".join(...), nunca iterrows + concatenacion.
    """
    columnas = [
        "ID", "Material", "UM", "IdCentro", "Inventario", "Necesidad",
        "Entrega Pendiente", "Fecha Entrega", "Centro a Nivelar", "Cantidad a Nivelar", "Clasificacion",
    ]
    header_html = "".join(f"<th>{c}</th>" for c in columnas)

    materiales: dict[str, list[dict]] = {}
    orden_materiales: list[str] = []
    for fila in filas:
        id_mat = fila["IdMaterial"]
        if id_mat not in materiales:
            materiales[id_mat] = []
            orden_materiales.append(id_mat)
        materiales[id_mat].append(fila)

    partes = []
    for id_mat in orden_materiales:
        filas_material = materiales[id_mat]
        primera = filas_material[0]
        total_filas_material = len(filas_material)
        borde_grupo = "border-bottom:2px solid #013066;"

        rowspan_idcentro_restante = 0
        for i, fila in enumerate(filas_material):
            celdas = []
            if i == 0:
                celdas.append(f'<td rowspan="{total_filas_material}">{formato_valor(primera["IdMaterial"])}</td>')
                celdas.append(f'<td rowspan="{total_filas_material}" style="text-align:left">{formato_valor(primera["Material"])}</td>')
                celdas.append(f'<td rowspan="{total_filas_material}">{formato_valor(primera["UnidadMedida"])}</td>')

            if rowspan_idcentro_restante == 0:
                rowspan_idcentro_restante = 1
                while (
                    i + rowspan_idcentro_restante < total_filas_material
                    and filas_material[i + rowspan_idcentro_restante]["IdCentro"] == fila["IdCentro"]
                ):
                    rowspan_idcentro_restante += 1
                celdas.append(f'<td rowspan="{rowspan_idcentro_restante}">{formato_valor(fila["IdCentro"])}</td>')
                celdas.append(f"<td rowspan=\"{rowspan_idcentro_restante}\" style='text-align: right;'>{_formato_numero(fila['Inventario'])}</td>")
                celdas.append(f"<td rowspan=\"{rowspan_idcentro_restante}\" style='text-align: right;'>{_formato_numero(fila['Necesidad'])}</td>")

            if i == 0:
                celdas.append(f"<td rowspan=\"{total_filas_material}\" style='text-align: right;'>{_formato_numero(primera['EntregaPendiente'])}</td>")
                celdas.append(f'<td rowspan="{total_filas_material}" style="text-align: center;">{_formato_fecha(primera["FechaEntrega"])}</td>')

            centro_nivelar = formato_valor(fila.get("CentroNivelar"))
            if centro_nivelar != "":
                clasificacion_nivelar = formato_valor(fila.get("ClasificacionNivelar"))
                color = CLASIFICACION_COLORES.get(clasificacion_nivelar, "#546E7A")
                celdas.append(f"<td>{centro_nivelar}</td>")
                celdas.append(f"<td style='text-align: right;'>{_formato_numero(fila.get('CantidadNivelar'))}</td>")
                celdas.append(f"<td>{render_pill(clasificacion_nivelar, color)}</td>")
            else:
                celdas.append("<td></td><td></td><td></td>")

            rowspan_idcentro_restante -= 1

            estilo_borde = f' style="{borde_grupo}"' if i == total_filas_material - 1 else ""
            partes.append(f"<tr{estilo_borde}>{''.join(celdas)}</tr>")

    body_html = "".join(partes)

    return f"""
    <div class="detail-table-outer">
        <div class="detail-table-wrap">
            <table class="detail-table">
                <thead><tr>{header_html}</tr></thead>
                <tbody>{body_html}</tbody>
            </table>
        </div>
    </div>
    """


def render_section_title(texto: str) -> str:
    return f'<div class="section-title">{texto}<div class="rule"></div></div>'


def render_filtro_label(texto: str) -> str:
    return f'<span class="filtro-label">{texto}</span>'
