from __future__ import annotations

import html

import pandas as pd
import streamlit as st

from reassignment_engine import NO_STOCK, REASSIGNABLE, REVIEW


STATE_COLORS = {
    REASSIGNABLE: "#16a34a",
    REVIEW: "#f59e0b",
    NO_STOCK: "#dc2626",
}


def inject_executive_styles() -> None:
    st.markdown(
        """
        <style>
        .block-container { max-width: 1500px; padding-top: 1.1rem; }
        .top-hero {
            border: 1px solid #e5e7eb;
            border-radius: 8px;
            padding: 1.25rem 1.35rem;
            background: #ffffff;
            box-shadow: 0 1px 4px rgba(15, 23, 42, .08);
            margin-bottom: .85rem;
        }
        .top-hero h1 { margin: 0; color: #111827; font-size: clamp(2rem, 4vw, 3rem); letter-spacing: 0; }
        .top-hero p { color: #64748b; margin: .35rem 0 0; font-size: 1rem; }
        .kpi-grid {
            display: grid;
            grid-template-columns: repeat(5, minmax(0, 1fr));
            gap: .75rem;
            margin: .9rem 0;
        }
        .kpi-card {
            border: 1px solid #e5e7eb;
            border-radius: 8px;
            background: #ffffff;
            padding: .9rem;
            box-shadow: 0 1px 3px rgba(15, 23, 42, .07);
        }
        .kpi-label { color: #64748b; font-size: .75rem; font-weight: 800; text-transform: uppercase; }
        .kpi-value { color: #111827; font-size: 1.55rem; font-weight: 850; margin-top: .2rem; }
        .empty-state {
            border: 1px dashed #94a3b8;
            border-radius: 8px;
            padding: 1rem;
            color: #475569;
            background: #f8fafc;
        }
        @media (max-width: 1100px) { .kpi-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
        @media (max-width: 620px) { .kpi-grid { grid-template-columns: 1fr; } }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_header() -> None:
    st.markdown(
        """
        <section class="top-hero">
          <h1>Motor inteligente de reasignación de pedidos</h1>
          <p>Detecta quiebres de stock y recomienda tiendas con stock disponible.</p>
        </section>
        """,
        unsafe_allow_html=True,
    )


def render_kpi_dashboard(kpis: dict[str, float]) -> None:
    cards = [
        ("Pedidos con quiebre", f"{kpis.get('total', 0):,.0f}"),
        ("Reasignables", f"{kpis.get('reassignable', 0):,.0f}"),
        ("Sin stock disponible", f"{kpis.get('no_stock', 0):,.0f}"),
        ("Unidades recuperables", f"{kpis.get('units_recoverable', 0):,.0f}"),
        ("% recuperacion", f"{kpis.get('recovery_pct', 0):,.1f}%"),
    ]
    parts = ["<div class='kpi-grid'>"]
    for label, value in cards:
        parts.append(
            f"<div class='kpi-card'><div class='kpi-label'>{html.escape(label)}</div>"
            f"<div class='kpi-value'>{html.escape(value)}</div></div>"
        )
    parts.append("</div>")
    st.markdown("".join(parts), unsafe_allow_html=True)

    chart_data = pd.DataFrame(
        [
            {"Categoria": "Recuperables", "Unidades": kpis.get("units_recoverable", 0)},
            {
                "Categoria": "Sin recuperar",
                "Unidades": max(kpis.get("units_broken", 0) - kpis.get("units_recoverable", 0), 0),
            },
        ]
    )
    st.markdown("**Recuperacion posible por unidades**")
    st.bar_chart(chart_data, x="Categoria", y="Unidades", use_container_width=True)


def render_recommendation_table(recommendations: pd.DataFrame) -> pd.DataFrame:
    display_columns = [
        "Pedido",
        "SKU",
        "Modelo Color",
        "Talla",
        "Cantidad",
        "Tienda origen",
        "Tienda recomendada",
        "Stock disponible",
        "Stock reasignable",
        "Estado",
        "Confianza",
        "Motivo",
    ]
    existing = [column for column in display_columns if column in recommendations.columns]
    table = recommendations[existing].copy()
    st.dataframe(_style_states(table), use_container_width=True, hide_index=True, height=440)
    return table


def _style_states(df: pd.DataFrame):
    def color_state(value: str) -> str:
        color = STATE_COLORS.get(value, "#64748b")
        return f"background-color: {color}; color: white; font-weight: 750;"

    if "Estado" not in df.columns:
        return df.style
    return df.style.applymap(color_state, subset=["Estado"])


def render_selected_order_detail(recommendations: pd.DataFrame, alternatives: pd.DataFrame) -> None:
    st.subheader("Detalle del pedido seleccionado")
    if recommendations.empty:
        st.markdown("<div class='empty-state'>Ejecuta una consulta para ver el detalle de un pedido.</div>", unsafe_allow_html=True)
        return

    order_options = [str(value) for value in recommendations["Pedido"].dropna().unique()]
    selected_order = st.selectbox("Pedido", order_options)
    row = recommendations[recommendations["Pedido"].astype(str).eq(selected_order)].iloc[0]

    left, right = st.columns(2)
    with left:
        st.write(f"**Pedido:** {row.get('Pedido')}")
        st.write(f"**Producto:** {row.get('SKU')} | {row.get('Modelo Color')} | {row.get('Talla')}")
        st.write(f"**Cantidad:** {row.get('Cantidad')}")
        st.write(f"**Motivo del quiebre:** {row.get('Motivo quiebre')}")
    with right:
        st.write(f"**Recomendacion final:** {row.get('Tienda recomendada') or 'Sin tienda candidata'}")
        st.write(f"**Estado:** {row.get('Estado')}")
        st.write(f"**Confianza:** {row.get('Confianza')}")
        st.write(f"**Motivo:** {row.get('Motivo')}")

    candidate_rows = alternatives[alternatives["order_number"].astype(str).eq(selected_order)]
    if candidate_rows.empty:
        st.info("No hay opciones alternativas para este pedido.")
    else:
        st.markdown("**Opciones alternativas de tienda**")
        st.dataframe(candidate_rows, use_container_width=True, hide_index=True)


def render_empty_state(message: str) -> None:
    st.markdown(f"<div class='empty-state'>{html.escape(message)}</div>", unsafe_allow_html=True)
