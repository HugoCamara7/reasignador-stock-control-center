from __future__ import annotations

import pandas as pd
import streamlit as st

from api_sources import (
    available_shopify_sites,
    fetch_available_stock_from_bigquery,
    fetch_broken_orders_from_shopify,
    skus_from_orders,
    validate_stock_with_shopify_api,
)
from dashboard_ui import (
    inject_dashboard_styles,
    render_daily_breaks_panel,
    render_detail_panel,
    render_empty_state,
    render_filter_shell,
    render_header,
    render_info_strip,
    render_kpi_dashboard,
    render_recovery_panel,
    render_recommendation_table,
    render_review_points,
    render_sidebar,
    render_top_model_panel,
    close_shell,
)
from export_reassignment import export_reassignment_excel
from reassignment_engine import (
    NO_STOCK,
    REASSIGNABLE,
    REVIEW,
    ReassignmentSettings,
    build_reassignment_kpis,
    build_reassignment_recommendations,
)


def _filter_options(dataframe: pd.DataFrame, column: str) -> list[str]:
    if dataframe.empty or column not in dataframe.columns:
        return []
    return sorted([str(value) for value in dataframe[column].dropna().unique()])


def _apply_top_filters(recommendations: pd.DataFrame) -> pd.DataFrame:
    filtered = recommendations.copy()
    filter_cols = st.columns([1.2, 1.2, 1.4, 1.2])
    with filter_cols[0]:
        brands = st.multiselect("Marca", _filter_options(filtered, "Marca"))
    with filter_cols[1]:
        origin_stores = st.multiselect("Tienda origen", _filter_options(filtered, "Tienda origen"))
    with filter_cols[2]:
        states = st.multiselect("Estado", [REASSIGNABLE, REVIEW, NO_STOCK])
    with filter_cols[3]:
        confidence = st.multiselect("Nivel de confianza", ["Alto", "Medio", "Bajo"])

    if brands:
        filtered = filtered[filtered["Marca"].astype(str).isin(brands)]
    if origin_stores:
        filtered = filtered[filtered["Tienda origen"].astype(str).isin(origin_stores)]
    if states:
        filtered = filtered[filtered["Estado"].astype(str).isin(states)]
    if confidence:
        filtered = filtered[filtered["Confianza"].astype(str).isin(confidence)]
    return filtered


def _apply_selected_filters(
    recommendations: pd.DataFrame,
    origin_store: str,
    state: str,
    confidence: str,
) -> pd.DataFrame:
    filtered = recommendations.copy()
    if origin_store != "Todas":
        filtered = filtered[filtered["Tienda origen"].astype(str).eq(origin_store)]
    if state != "Todos":
        filtered = filtered[filtered["Estado"].astype(str).eq(state)]
    if confidence != "Todos":
        filtered = filtered[filtered["Confianza"].astype(str).eq(confidence)]
    return filtered


def _top_charts(recommendations: pd.DataFrame, alternatives: pd.DataFrame) -> None:
    left, right = st.columns(2)
    with left:
        st.markdown("**Top codigos modelo color con mayor quiebre**")
        if recommendations.empty:
            st.info("Sin datos para graficar.")
        else:
            top_model = (
                recommendations.groupby("Modelo Color", dropna=False)
                .agg(Pedidos=("Pedido", "count"), Unidades=("Cantidad", "sum"))
                .reset_index()
                .sort_values(["Pedidos", "Unidades"], ascending=False)
                .head(10)
            )
            st.bar_chart(top_model, x="Modelo Color", y="Pedidos", use_container_width=True)
    with right:
        st.markdown("**Tiendas con mas stock candidato**")
        if alternatives.empty:
            st.info("Sin stock candidato para graficar.")
        else:
            top_store = (
                alternatives.groupby("store", dropna=False)
                .agg(Stock_candidato=("stock_reassignable", "sum"))
                .reset_index()
                .sort_values("Stock_candidato", ascending=False)
                .head(10)
            )
            st.bar_chart(top_store, x="store", y="Stock_candidato", use_container_width=True)


def _run_analysis(
    site_key: str,
    days_back: int,
    stock_days_back: int,
    brands: tuple[str, ...],
    settings: ReassignmentSettings,
    include_unfulfilled_risk: bool,
) -> None:
    try:
        with st.spinner("Consultando ordenes con posible quiebre en Shopify API..."):
            orders = fetch_broken_orders_from_shopify(
                days_back=days_back,
                brands=brands,
                include_unfulfilled_risk=include_unfulfilled_risk,
                site_key=site_key,
            )
    except Exception as exc:
        st.error(f"Shopify API no respondio al consultar ordenes: {exc}")
        return

    if orders.empty:
        st.session_state["bq_recommendations"] = pd.DataFrame()
        st.session_state["bq_alternatives"] = pd.DataFrame()
        st.session_state["bq_shopify_warnings"] = []
        st.info("No se encontraron ordenes Shopify con señal de quiebre para los filtros seleccionados.")
        return

    try:
        with st.spinner("Consultando stock disponible en BigQuery..."):
            stock = fetch_available_stock_from_bigquery(skus_from_orders(orders), days_back=stock_days_back)
    except Exception as exc:
        st.error(f"BigQuery no respondio al consultar stock: {exc}")
        return

    if stock.empty:
        recommendations = _empty_no_stock_recommendations(orders)
        st.session_state["bq_recommendations"] = recommendations
        st.session_state["bq_alternatives"] = pd.DataFrame()
        st.session_state["bq_shopify_warnings"] = ["No se encontro stock candidato en BigQuery."]
        return

    shopify_validation = {}
    shopify_warnings: list[str] = []
    if settings.validate_shopify:
        with st.spinner("Validando stock actual contra Shopify API..."):
            shopify_validation, shopify_warnings = validate_stock_with_shopify_api(stock, site_key=site_key)

    recommendations, alternatives = build_reassignment_recommendations(
        orders=orders,
        stock=stock,
        settings=settings,
        shopify_validation=shopify_validation,
    )
    st.session_state["bq_recommendations"] = recommendations
    st.session_state["bq_alternatives"] = alternatives
    st.session_state["bq_shopify_warnings"] = shopify_warnings


def _empty_no_stock_recommendations(orders: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, order in orders.iterrows():
        rows.append(
            {
                "Pedido": order.get("order_number"),
                "Order ID": order.get("order_id"),
                "Fecha pedido": order.get("order_date"),
                "Marca": order.get("brand"),
                "SKU": order.get("sku"),
                "Modelo Color": order.get("model_color"),
                "Talla": order.get("size"),
                "Cantidad": int(order.get("quantity", 0) or 0),
                "Tienda origen": order.get("origin_store"),
                "Tienda recomendada": None,
                "Stock disponible": 0,
                "Stock reasignable": 0,
                "Estado": NO_STOCK,
                "Confianza": "Bajo",
                "Motivo": "No se encontro stock candidato en BigQuery.",
                "Motivo quiebre": order.get("break_reason"),
            }
        )
    return pd.DataFrame(rows)


def main_bq() -> None:
    inject_dashboard_styles()
    render_sidebar()

    recommendations = st.session_state.get("bq_recommendations", pd.DataFrame())
    alternatives = st.session_state.get("bq_alternatives", pd.DataFrame())

    validate_shopify = st.session_state.get("validate_shopify_ui", False)
    render_header(validate_shopify)
    render_review_points()

    render_filter_shell()
    filter_bar = st.columns([1.0, 1.0, 1.0, 1.15, 1.15, 1.2, 1.35])
    with filter_bar[0]:
        site_key = st.selectbox("Sitio Shopify", available_shopify_sites(), index=0)
    with filter_bar[1]:
        brands_text = st.text_input("Marca", value=site_key.replace("_", " ").title(), placeholder="Columbia")
    with filter_bar[2]:
        days_back = st.number_input("Dias hacia atras", min_value=1, max_value=90, value=7, step=1)
    with filter_bar[3]:
        origin_options = ["Todas"] + _filter_options(recommendations, "Tienda origen")
        origin_store = st.selectbox("Tienda origen", origin_options)
    with filter_bar[4]:
        state = st.selectbox("Estado", ["Todos", REASSIGNABLE, REVIEW, NO_STOCK])
    with filter_bar[5]:
        confidence = st.selectbox("Nivel de confianza", ["Todos", "Alto", "Medio", "Bajo"])
    with filter_bar[6]:
        st.write("")
        run = st.button("Consultar quiebres y recomendar reasignación", type="primary", use_container_width=True)
    close_shell()

    control_bar = st.columns([1.25, 1, 1.1, 3])
    with control_bar[0]:
        validate_shopify = st.toggle("Validar stock con Shopify", value=False)
        st.session_state["validate_shopify_ui"] = validate_shopify
    with control_bar[1]:
        stock_days_back = st.number_input("Dias de stock", min_value=1, max_value=10, value=2, step=1)
    with control_bar[2]:
        safety_stock = st.number_input("Stock seguridad", min_value=0, max_value=50, value=1, step=1)
    with control_bar[3]:
        max_stock_age_hours = st.number_input("Max horas stock actualizado", min_value=1, max_value=168, value=30)
    include_unfulfilled_risk = st.toggle(
        "Incluir ordenes Shopify pendientes/no preparadas como riesgo de quiebre",
        value=True,
        help="Activalo si una orden no preparada con unidades pendientes debe entrar al motor aunque no tenga tag explicito de quiebre.",
    )

    settings = ReassignmentSettings(
        safety_stock=int(safety_stock),
        validate_shopify=validate_shopify,
        max_stock_age_hours=int(max_stock_age_hours),
    )
    brands = tuple(part.strip() for part in brands_text.split(",") if part.strip())

    if run:
        _run_analysis(site_key, int(days_back), int(stock_days_back), brands, settings, include_unfulfilled_risk)

    shopify_warnings = st.session_state.get("bq_shopify_warnings", [])

    if recommendations.empty:
        render_empty_state("Presiona el boton principal para consultar ordenes Shopify y cruzarlas contra stock BigQuery.")
        return

    if "Fuente stock" in recommendations.columns and recommendations["Fuente stock"].astype(str).str.lower().isin(["d-1", "d1", "cierre"]).any():
        st.warning("Hay recomendaciones basadas en stock D-1. Valida contra Shopify API o contra la ultima actualizacion disponible antes de ejecutar.")
    for warning in shopify_warnings[:5]:
        st.warning(warning)

    filtered = _apply_selected_filters(recommendations, origin_store, state, confidence)
    kpis = build_reassignment_kpis(filtered)
    render_kpi_dashboard(kpis)

    main_col, detail_col = st.columns([4.6, 1.25])
    with main_col:
        chart_cols = st.columns([1.1, 1.15, 1.05])
        with chart_cols[0]:
            render_recovery_panel(kpis)
        with chart_cols[1]:
            render_daily_breaks_panel(filtered)
        with chart_cols[2]:
            render_top_model_panel(filtered)

        table_actions = st.columns([3, 1.1])
        with table_actions[1]:
            excel = export_reassignment_excel(filtered, alternatives, kpis)
            st.download_button(
                "Descargar Excel",
                excel,
                file_name="recomendaciones_reasignacion_pedidos.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
        render_recommendation_table(filtered)
        render_info_strip()

    with detail_col:
        render_detail_panel(filtered, alternatives)
