from __future__ import annotations

import html

import pandas as pd
import streamlit as st

from config import RECOMMENDATION_STATES


def inject_styles() -> None:
    st.markdown(
        """
        <style>
        .block-container { padding-top: 1rem; max-width: 1480px; }
        [data-testid="stSidebar"] { background: #111827; }
        [data-testid="stSidebar"] * { color: #f9fafb; }
        [data-testid="stSidebar"] input, [data-testid="stSidebar"] textarea {
            background: #ffffff !important;
            color: #111827 !important;
        }
        .hero {
            border: 1px solid #dbe3ef;
            border-radius: 8px;
            padding: 1.35rem 1.5rem;
            background: linear-gradient(135deg, #f8fafc 0%, #eef6ff 100%);
            margin-bottom: 1rem;
        }
        .hero h1 {
            margin: 0 0 .35rem 0;
            font-size: clamp(2rem, 4vw, 3.05rem);
            line-height: 1.05;
            letter-spacing: 0;
            color: #111827;
        }
        .hero p { margin: 0; max-width: 980px; color: #475569; font-size: 1rem; }
        .step-grid, .kpi-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: .75rem;
            margin: .75rem 0 1rem;
        }
        .step-card, .kpi-card, .status-panel {
            border: 1px solid #e5e7eb;
            border-radius: 8px;
            background: #ffffff;
            box-shadow: 0 1px 3px rgba(15, 23, 42, 0.08);
        }
        .step-card { padding: .9rem; min-height: 108px; }
        .step-num {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 28px;
            height: 28px;
            border-radius: 999px;
            background: #0f766e;
            color: #ffffff;
            font-weight: 800;
            margin-bottom: .55rem;
        }
        .step-title { font-weight: 800; color: #111827; margin-bottom: .2rem; }
        .step-text { color: #64748b; font-size: .9rem; line-height: 1.35; }
        .kpi-card { padding: .85rem .95rem; }
        .kpi-label { color: #64748b; font-size: .75rem; font-weight: 800; text-transform: uppercase; }
        .kpi-value { color: #111827; font-size: 1.55rem; font-weight: 850; line-height: 1.2; margin-top: .2rem; }
        .status-panel { padding: 1rem; margin: .5rem 0 1rem; }
        .status-title { color: #111827; font-size: 1rem; font-weight: 850; margin-bottom: .45rem; }
        .status-row { display: flex; gap: .5rem; align-items: flex-start; color: #475569; margin: .25rem 0; }
        .dot { width: 9px; height: 9px; border-radius: 999px; margin-top: .45rem; flex: 0 0 auto; }
        .upload-card {
            border: 1px solid #dbe3ef;
            border-radius: 8px;
            padding: 1rem;
            background: #ffffff;
            min-height: 210px;
        }
        .small-note { color: #64748b; font-size: .88rem; line-height: 1.4; }
        div[data-testid="stFileUploaderDropzone"] {
            background: #f8fafc;
            border: 1px dashed #94a3b8;
            border-radius: 8px;
        }
        div.stButton > button, div.stDownloadButton > button {
            border-radius: 8px;
            min-height: 2.65rem;
            font-weight: 750;
        }
        @media (max-width: 1050px) {
            .step-grid, .kpi-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        }
        @media (max-width: 620px) {
            .step-grid, .kpi-grid { grid-template-columns: 1fr; }
            .hero { padding: 1rem; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_header() -> None:
    st.markdown(
        """
        <section class="hero">
            <h1>Recuperador de pedidos sin stock</h1>
            <p>
                La app toma pedidos con quiebre, busca stock disponible en otras tiendas o bodegas,
                descuenta stock virtual para no sobreasignar y entrega una recomendacion exportable.
                En esta version no reasigna automaticamente.
            </p>
        </section>
        """,
        unsafe_allow_html=True,
    )


def render_steps() -> None:
    steps = [
        ("1", "Sube pedidos", "Archivo con pedidos sin stock: pedido, SKU, cantidad, tienda origen y marca."),
        ("2", "Sube stock", "Archivo o BigQuery con stock por SKU y tienda. Puede ser cierre D-1 o stock actualizado."),
        ("3", "Ajusta reglas", "Define stock de seguridad, tiendas bloqueadas y si permites recomendaciones parciales."),
        ("4", "Analiza y exporta", "La tabla final indica tienda recomendada, motivo, score y accion sugerida."),
    ]
    html_parts = ["<div class='step-grid'>"]
    for number, title, text in steps:
        html_parts.append(
            "<div class='step-card'>"
            f"<div class='step-num'>{html.escape(number)}</div>"
            f"<div class='step-title'>{html.escape(title)}</div>"
            f"<div class='step-text'>{html.escape(text)}</div>"
            "</div>"
        )
    html_parts.append("</div>")
    st.markdown("".join(html_parts), unsafe_allow_html=True)


def render_status_panel(title: str, rows: list[tuple[str, str, str]]) -> None:
    html_parts = [f"<div class='status-panel'><div class='status-title'>{html.escape(title)}</div>"]
    for color, label, text in rows:
        html_parts.append(
            "<div class='status-row'>"
            f"<span class='dot' style='background:{html.escape(color)}'></span>"
            f"<span><strong>{html.escape(label)}</strong>: {html.escape(text)}</span>"
            "</div>"
        )
    html_parts.append("</div>")
    st.markdown("".join(html_parts), unsafe_allow_html=True)


def render_kpi_cards(kpis: dict[str, float]) -> None:
    cards = [
        ("Pedidos con quiebre", f"{kpis['total_pedidos']:,.0f}"),
        ("Reasignables", f"{kpis['reasignables']:,.0f}"),
        ("No reasignables", f"{kpis['no_reasignables']:,.0f}"),
        ("Parciales", f"{kpis['parciales']:,.0f}"),
        ("Unidades en riesgo", f"{kpis['unidades_riesgo']:,.0f}"),
        ("Unidades recuperables", f"{kpis['unidades_recuperables']:,.0f}"),
        ("Recuperacion posible", f"{kpis['recuperacion_pct']:,.1f}%"),
        ("Riesgo stock D-1", f"{kpis['riesgo_d1']:,.0f}"),
    ]
    html_parts = ["<div class='kpi-grid'>"]
    for label, value in cards:
        html_parts.append(
            f"<div class='kpi-card'><div class='kpi-label'>{html.escape(label)}</div>"
            f"<div class='kpi-value'>{html.escape(value)}</div></div>"
        )
    html_parts.append("</div>")
    st.markdown("".join(html_parts), unsafe_allow_html=True)


def render_charts(results: pd.DataFrame) -> None:
    if results.empty:
        return
    left, right = st.columns(2)
    with left:
        st.markdown("**Pedidos por estado**")
        status = results["Estado"].value_counts().reset_index()
        status.columns = ["Estado", "Pedidos"]
        st.bar_chart(status, x="Estado", y="Pedidos", use_container_width=True)
    with right:
        st.markdown("**Tiendas mas recomendadas**")
        stores = results.dropna(subset=["Tienda recomendada"])["Tienda recomendada"].value_counts().head(10).reset_index()
        stores.columns = ["Tienda recomendada", "Pedidos"]
        st.bar_chart(stores, x="Tienda recomendada", y="Pedidos", use_container_width=True)

    left, right = st.columns(2)
    with left:
        st.markdown("**Marcas con mas quiebres**")
        brands = results["Marca"].fillna("Sin marca").value_counts().head(10).reset_index()
        brands.columns = ["Marca", "Quiebres"]
        st.bar_chart(brands, x="Marca", y="Quiebres", use_container_width=True)
    with right:
        st.markdown("**SKUs con mas quiebres**")
        skus = results["SKU"].fillna("Sin SKU").value_counts().head(10).reset_index()
        skus.columns = ["SKU", "Quiebres"]
        st.bar_chart(skus, x="SKU", y="Quiebres", use_container_width=True)


def style_results_table(df: pd.DataFrame):
    def color_state(value: str) -> str:
        color = RECOMMENDATION_STATES.get(value, "#64748b")
        return f"background-color: {color}; color: white; font-weight: 700;"

    visible = df.copy()
    if "Estado" not in visible.columns:
        return visible.style
    return visible.style.applymap(color_state, subset=["Estado"])
