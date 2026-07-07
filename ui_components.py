from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from config import RECOMMENDATION_STATES


def inject_styles() -> None:
    st.markdown(
        """
        <style>
        .block-container { padding-top: 1.2rem; max-width: 1440px; }
        [data-testid="stSidebar"] { background: #0f172a; }
        [data-testid="stSidebar"] * { color: #f8fafc; }
        .kpi-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 0.75rem;
            margin: 0.75rem 0 1rem;
        }
        .kpi-card {
            border: 1px solid #e5e7eb;
            border-radius: 8px;
            padding: 0.85rem 0.95rem;
            background: #ffffff;
            box-shadow: 0 1px 3px rgba(15, 23, 42, 0.08);
        }
        .kpi-label { color: #64748b; font-size: 0.78rem; font-weight: 700; text-transform: uppercase; }
        .kpi-value { color: #0f172a; font-size: 1.55rem; font-weight: 800; line-height: 1.2; margin-top: 0.2rem; }
        .status-pill {
            display: inline-block;
            color: #fff;
            padding: 0.18rem 0.55rem;
            border-radius: 999px;
            font-size: 0.78rem;
            font-weight: 700;
        }
        @media (max-width: 900px) { .kpi-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
        @media (max-width: 560px) { .kpi-grid { grid-template-columns: 1fr; } }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_header() -> None:
    st.title("Reasignación inteligente de pedidos por stock")
    st.caption("Recomendaciones operativas con trazabilidad, stock virtual acumulativo y exportación Excel.")


def render_kpi_cards(kpis: dict[str, float]) -> None:
    cards = [
        ("Pedidos con quiebre", f"{kpis['total_pedidos']:,.0f}"),
        ("Reasignables", f"{kpis['reasignables']:,.0f}"),
        ("No reasignables", f"{kpis['no_reasignables']:,.0f}"),
        ("Parciales", f"{kpis['parciales']:,.0f}"),
        ("Unidades en riesgo", f"{kpis['unidades_riesgo']:,.0f}"),
        ("Unidades recuperables", f"{kpis['unidades_recuperables']:,.0f}"),
        ("Recuperación posible", f"{kpis['recuperacion_pct']:,.1f}%"),
        ("Riesgo stock D-1", f"{kpis['riesgo_d1']:,.0f}"),
    ]
    html = ["<div class='kpi-grid'>"]
    for label, value in cards:
        html.append(f"<div class='kpi-card'><div class='kpi-label'>{label}</div><div class='kpi-value'>{value}</div></div>")
    html.append("</div>")
    st.markdown("".join(html), unsafe_allow_html=True)


def render_charts(results: pd.DataFrame) -> None:
    if results.empty:
        return
    left, right = st.columns(2)
    color_map = RECOMMENDATION_STATES
    with left:
        status = results["Estado"].value_counts().reset_index()
        status.columns = ["Estado", "Pedidos"]
        fig = px.bar(status, x="Estado", y="Pedidos", color="Estado", color_discrete_map=color_map, text_auto=True)
        fig.update_layout(showlegend=False, margin=dict(l=8, r=8, t=24, b=8), height=320)
        st.plotly_chart(fig, use_container_width=True)
    with right:
        stores = results.dropna(subset=["Tienda recomendada"])["Tienda recomendada"].value_counts().head(10).reset_index()
        stores.columns = ["Tienda recomendada", "Pedidos"]
        fig = px.bar(stores, x="Pedidos", y="Tienda recomendada", orientation="h", text_auto=True)
        fig.update_layout(margin=dict(l=8, r=8, t=24, b=8), height=320, yaxis={"categoryorder": "total ascending"})
        st.plotly_chart(fig, use_container_width=True)

    left, right = st.columns(2)
    with left:
        brands = results["Marca"].fillna("Sin marca").value_counts().head(10).reset_index()
        brands.columns = ["Marca", "Quiebres"]
        fig = px.bar(brands, x="Marca", y="Quiebres", text_auto=True)
        fig.update_layout(margin=dict(l=8, r=8, t=24, b=8), height=300)
        st.plotly_chart(fig, use_container_width=True)
    with right:
        skus = results["SKU"].fillna("Sin SKU").value_counts().head(10).reset_index()
        skus.columns = ["SKU", "Quiebres"]
        fig = px.bar(skus, x="Quiebres", y="SKU", orientation="h", text_auto=True)
        fig.update_layout(margin=dict(l=8, r=8, t=24, b=8), height=300, yaxis={"categoryorder": "total ascending"})
        st.plotly_chart(fig, use_container_width=True)


def style_results_table(df: pd.DataFrame):
    def color_state(value: str) -> str:
        color = RECOMMENDATION_STATES.get(value, "#64748b")
        return f"background-color: {color}; color: white; font-weight: 700;"

    visible = df.copy()
    return visible.style.applymap(color_state, subset=["Estado"])
