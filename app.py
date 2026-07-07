from __future__ import annotations

from io import BytesIO

import pandas as pd
import streamlit as st

from data_bigquery import query_break_orders_from_bigquery, query_stock_from_bigquery, tuple_from_series
from export_excel import build_excel
from stock_engine import RecommendationSettings, build_kpis, recommend_orders
from ui_redesign import (
    inject_styles,
    render_charts,
    render_header,
    render_kpi_cards,
    render_status_panel,
    render_steps,
    style_results_table,
)
from validations import build_operational_warnings, prepare_orders, prepare_stock


st.set_page_config(
    page_title="Reasignación inteligente de stock",
    page_icon="📦",
    layout="wide",
)


def _read_file(uploaded_file) -> pd.DataFrame:
    if uploaded_file is None:
        return pd.DataFrame()
    suffix = uploaded_file.name.lower().split(".")[-1]
    if suffix == "csv":
        return pd.read_csv(uploaded_file)
    return pd.read_excel(uploaded_file)


def _split_text(value: str) -> set[str]:
    return {item.strip() for item in value.split(",") if item.strip()}


def _priority_map(value: str) -> dict[str, int]:
    priorities = {}
    for idx, item in enumerate([part.strip() for part in value.split(",") if part.strip()], start=1):
        priorities[item.lower()] = max(1, 10 - idx)
    return priorities


def _apply_filters(results: pd.DataFrame) -> pd.DataFrame:
    filtered = results.copy()
    with st.sidebar.expander("Filtros", expanded=True):
        for label, column in [
            ("Marca", "Marca"),
            ("Tienda original", "Tienda actual/origen"),
            ("Tienda recomendada", "Tienda recomendada"),
            ("Estado", "Estado"),
            ("SKU", "SKU"),
            ("Código modelo color", "Código modelo color"),
            ("Talla", "Talla"),
            ("Tipo de quiebre", "Tipo de quiebre"),
            ("Tipo stock", "Fuente stock"),
        ]:
            if column in filtered.columns:
                options = sorted([str(v) for v in filtered[column].dropna().unique()])
                selected = st.multiselect(label, options)
                if selected:
                    filtered = filtered[filtered[column].astype(str).isin(selected)]

        if "Fecha de pedido" in filtered.columns and filtered["Fecha de pedido"].notna().any():
            dates = pd.to_datetime(filtered["Fecha de pedido"], errors="coerce").dropna()
            start, end = st.date_input("Fecha de pedido", value=(dates.min().date(), dates.max().date()))
            filtered = filtered[
                pd.to_datetime(filtered["Fecha de pedido"], errors="coerce").dt.date.between(start, end)
            ]
    return filtered


def _empty_template(kind: str) -> bytes:
    if kind == "orders":
        columns = [
            "Número de pedido",
            "SKU",
            "Código modelo color",
            "Talla",
            "Cantidad",
            "Tienda original",
            "Marca",
            "Fecha de pedido",
            "Estado del pedido",
            "Motivo del quiebre",
            "Precio",
        ]
    else:
        columns = [
            "SKU",
            "Tienda",
            "Bodega",
            "Marca",
            "Fecha de stock",
            "Stock disponible",
            "Tipo stock",
            "Tienda habilitada",
            "Prioritaria ecommerce",
            "Prioridad logística",
        ]
    output = BytesIO()
    pd.DataFrame(columns=columns).to_excel(output, index=False)
    output.seek(0)
    return output.read()


def _read_file_safe(uploaded_file, label: str) -> pd.DataFrame:
    if uploaded_file is None:
        return pd.DataFrame()
    try:
        suffix = uploaded_file.name.lower().split(".")[-1]
        if suffix == "csv":
            try:
                return pd.read_csv(uploaded_file)
            except UnicodeDecodeError:
                uploaded_file.seek(0)
                return pd.read_csv(uploaded_file, encoding="latin-1")
        return pd.read_excel(uploaded_file)
    except Exception as exc:
        st.error(f"No pude leer el archivo de {label}. Revisa que sea un Excel o CSV valido. Detalle: {exc}")
        return pd.DataFrame()


def _apply_filters_v2(results: pd.DataFrame) -> pd.DataFrame:
    filtered = results.copy()
    with st.sidebar.expander("Filtros de resultado", expanded=False):
        filter_columns = [
            ("Marca", "Marca"),
            ("Tienda origen", "Tienda actual/origen"),
            ("Tienda recomendada", "Tienda recomendada"),
            ("Estado", "Estado"),
            ("SKU", "SKU"),
            ("Codigo modelo color", "Codigo modelo color"),
            ("Talla", "Talla"),
            ("Tipo de quiebre", "Tipo de quiebre"),
            ("Fuente de stock", "Fuente stock"),
        ]
        for label, column in filter_columns:
            target_column = column if column in filtered.columns else column.replace("Codigo", "Código")
            if target_column in filtered.columns:
                options = sorted([str(v) for v in filtered[target_column].dropna().unique()])
                selected = st.multiselect(label, options, key=f"filter_{label}")
                if selected:
                    filtered = filtered[filtered[target_column].astype(str).isin(selected)]

        if "Fecha de pedido" in filtered.columns and filtered["Fecha de pedido"].notna().any():
            dates = pd.to_datetime(filtered["Fecha de pedido"], errors="coerce").dropna()
            if not dates.empty:
                start, end = st.date_input(
                    "Fecha de pedido",
                    value=(dates.min().date(), dates.max().date()),
                    key="filter_order_date",
                )
                filtered = filtered[
                    pd.to_datetime(filtered["Fecha de pedido"], errors="coerce").dt.date.between(start, end)
                ]
    return filtered


def _show_dataframe_preview(title: str, dataframe: pd.DataFrame) -> None:
    if dataframe.empty:
        return
    st.caption(f"{title}: {len(dataframe):,} filas cargadas")
    st.dataframe(dataframe.head(8), use_container_width=True, hide_index=True)


def _settings_panel() -> RecommendationSettings:
    with st.sidebar:
        st.header("Reglas del analisis")
        st.caption("Puedes dejar estos valores por defecto para una primera prueba.")
        safety_stock = st.number_input("Stock de seguridad", min_value=0, max_value=50, value=1, step=1)
        use_d1_stock = st.toggle("Permitir stock D-1", value=True)
        allow_partial = st.toggle("Permitir recomendacion parcial", value=True)
        prioritize_mode = st.radio("Criterio principal", ["Mayor stock", "Prioridad logística"], horizontal=False)

        with st.expander("Configuracion avanzada", expanded=False):
            enabled_stores = _split_text(st.text_area("Solo estas tiendas habilitadas", height=70))
            blocked_stores = _split_text(st.text_area("Tiendas bloqueadas", height=70))
            priority_stores = _priority_map(st.text_area("Tiendas ecommerce prioritarias", height=70))
            included_brands = _split_text(st.text_input("Marcas incluidas"))
            max_store_sku = st.number_input("Maximo pedidos por tienda + SKU", min_value=1, value=9999, step=1)

    return RecommendationSettings(
        safety_stock=int(safety_stock),
        enabled_stores=enabled_stores,
        blocked_stores=blocked_stores,
        priority_stores=priority_stores,
        use_d1_stock=use_d1_stock,
        allow_partial=allow_partial,
        prioritize_mode=prioritize_mode,
        included_brands=included_brands,
        max_recommendations_per_store_sku=int(max_store_sku),
    )


def main_v2() -> None:
    inject_styles()
    render_header()
    render_steps()

    settings = _settings_panel()

    render_status_panel(
        "Como leer los estados",
        [
            ("#16a34a", "Reasignable", "hay una tienda que cubre el pedido completo respetando stock de seguridad"),
            ("#f59e0b", "Parcial / revision", "hay stock, pero no cubre todo o requiere validacion operativa"),
            ("#dc2626", "No reasignable", "no hay stock suficiente para recomendar una tienda"),
            ("#f97316", "Riesgo D-1", "la recomendacion usa stock de cierre anterior y debe validarse antes de ejecutar"),
        ],
    )

    source_col, action_col = st.columns([2.2, 1])
    with source_col:
        st.subheader("1. Carga la informacion")
        source = st.radio("Pedidos", ["Archivo", "BigQuery"], horizontal=True, key="orders_source_v2")
        stock_source = st.radio("Stock", ["Archivo", "BigQuery"], horizontal=True, key="stock_source_v2")
    with action_col:
        st.subheader("Plantillas")
        st.download_button("Plantilla pedidos", _empty_template("orders"), "plantilla_pedidos_quiebre.xlsx", use_container_width=True)
        st.download_button("Plantilla stock", _empty_template("stock"), "plantilla_stock.xlsx", use_container_width=True)

    upload_orders, upload_stock = st.columns(2)
    with upload_orders:
        st.markdown("<div class='upload-card'>", unsafe_allow_html=True)
        st.markdown("**Pedidos con quiebre**")
        st.caption("Obligatorio: numero de pedido, SKU y cantidad. Recomendado: tienda origen, marca, talla, fecha y motivo.")
        if source == "Archivo":
            orders_file = st.file_uploader("Subir pedidos Excel/CSV", type=["xlsx", "xls", "csv"], key="orders_file_v2")
            raw_orders = _read_file_safe(orders_file, "pedidos")
        else:
            days_back = st.number_input("Dias hacia atras", min_value=1, max_value=60, value=7, key="orders_days_v2")
            if st.button("Consultar pedidos en BigQuery", use_container_width=True):
                with st.spinner("Consultando pedidos..."):
                    st.session_state["raw_orders_bq_v2"] = query_break_orders_from_bigquery(int(days_back))
            raw_orders = st.session_state.get("raw_orders_bq_v2", pd.DataFrame())
        st.markdown("</div>", unsafe_allow_html=True)

    with upload_stock:
        st.markdown("<div class='upload-card'>", unsafe_allow_html=True)
        st.markdown("**Stock disponible**")
        st.caption("Obligatorio: SKU, tienda y stock disponible. Recomendado: fecha de stock, fuente D-1/actualizada y tienda habilitada.")
        if stock_source == "Archivo":
            stock_file = st.file_uploader("Subir stock Excel/CSV", type=["xlsx", "xls", "csv"], key="stock_file_v2")
            raw_stock = _read_file_safe(stock_file, "stock")
        else:
            raw_stock = pd.DataFrame()
        st.markdown("</div>", unsafe_allow_html=True)

    if raw_orders.empty:
        st.info("Primero carga pedidos con quiebre. La app todavia no analiza nada porque no sabe que pedidos recuperar.")
        return

    orders_result = prepare_orders(raw_orders)
    orders = orders_result.dataframe

    with st.expander("Vista previa de pedidos cargados", expanded=True):
        _show_dataframe_preview("Pedidos", orders)
        if not orders_result.issues.empty:
            st.warning("Hay observaciones en pedidos. Puedes seguir, pero revisa estos puntos.")
            st.dataframe(orders_result.issues, use_container_width=True, hide_index=True)

    if stock_source == "BigQuery":
        with st.spinner("Consultando stock en BigQuery..."):
            raw_stock = query_stock_from_bigquery(tuple_from_series(orders["sku"]), tuple_from_series(orders["brand"]))

    if raw_stock.empty:
        st.info("Ahora carga el stock disponible. Sin stock, la app no puede recomendar tiendas.")
        return

    stock_result = prepare_stock(raw_stock)
    stock = stock_result.dataframe
    with st.expander("Vista previa de stock cargado", expanded=True):
        _show_dataframe_preview("Stock", stock)
        if not stock_result.issues.empty:
            st.warning("Hay observaciones en stock. Revisa especialmente stock negativo o columnas faltantes.")
            st.dataframe(stock_result.issues, use_container_width=True, hide_index=True)

    st.subheader("2. Ejecuta el analisis")
    st.write(
        "La app va pedido por pedido, busca tiendas candidatas, aplica stock de seguridad y descuenta stock virtualmente. "
        "Eso evita recomendar la misma unidad a varios pedidos."
    )
    if st.button("Analizar pedidos y recomendar tiendas", type="primary", use_container_width=True):
        progress = st.progress(0, text="Preparando datos")
        with st.spinner("Calculando recomendaciones..."):
            progress.progress(30, text="Validando pedidos y stock")
            results = recommend_orders(orders, stock, settings)
            progress.progress(80, text="Armando KPIs, motivos y validaciones")
            warnings = build_operational_warnings(results)
            kpis = build_kpis(results)
            st.session_state["results_v2"] = results
            st.session_state["warnings_v2"] = warnings
            st.session_state["kpis_v2"] = kpis
            progress.progress(100, text="Analisis listo")

    results = st.session_state.get("results_v2", pd.DataFrame())
    if results.empty:
        st.caption("Cuando presiones el boton, aqui apareceran KPIs, tabla operativa y descarga Excel.")
        return

    filtered = _apply_filters_v2(results)
    kpis = build_kpis(filtered)
    warnings = build_operational_warnings(filtered)

    st.subheader("3. Resultado operativo")
    render_kpi_cards(kpis)

    tab_table, tab_charts, tab_validations = st.tabs(["Tabla para operar", "Graficos", "Validaciones"])
    with tab_table:
        search = st.text_input("Buscar en resultado", placeholder="Pedido, SKU, tienda, motivo...", key="search_v2")
        table = filtered.copy()
        if search:
            mask = table.astype(str).apply(lambda col: col.str.contains(search, case=False, na=False)).any(axis=1)
            table = table[mask]
        st.dataframe(style_results_table(table), use_container_width=True, hide_index=True, height=460)

        excel = build_excel(filtered, kpis, warnings)
        st.download_button(
            "Descargar Excel operativo",
            excel,
            file_name="recomendaciones_reasignacion_stock.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
            use_container_width=True,
        )

    with tab_charts:
        render_charts(filtered)

    with tab_validations:
        if warnings.empty:
            st.success("No se detectaron alertas operativas principales en el resultado filtrado.")
        else:
            st.dataframe(warnings, use_container_width=True, hide_index=True)


def main() -> None:
    inject_styles()
    render_header()

    with st.sidebar:
        st.header("Configuración")
        source = st.radio("Fuente de pedidos", ["Archivo", "BigQuery"], horizontal=True)
        stock_source = st.radio("Fuente de stock", ["Archivo", "BigQuery"], horizontal=True)
        safety_stock = st.number_input("Stock mínimo de seguridad", min_value=0, max_value=50, value=1, step=1)
        use_d1_stock = st.toggle("Usar stock D-1", value=True)
        allow_partial = st.toggle("Permitir reasignación parcial", value=True)
        prioritize_mode = st.radio("Priorizar", ["Mayor stock", "Prioridad logística"], horizontal=True)
        enabled_stores = _split_text(st.text_area("Tiendas habilitadas (separadas por coma)", height=70))
        blocked_stores = _split_text(st.text_area("Tiendas bloqueadas (separadas por coma)", height=70))
        priority_stores = _priority_map(st.text_area("Prioridad de tiendas ecommerce (orden por coma)", height=70))
        included_brands = _split_text(st.text_input("Marcas incluidas (opcional, separadas por coma)"))
        max_store_sku = st.number_input("Máximo pedidos por tienda + SKU", min_value=1, value=9999, step=1)

    settings = RecommendationSettings(
        safety_stock=int(safety_stock),
        enabled_stores=enabled_stores,
        blocked_stores=blocked_stores,
        priority_stores=priority_stores,
        use_d1_stock=use_d1_stock,
        allow_partial=allow_partial,
        prioritize_mode=prioritize_mode,
        included_brands=included_brands,
        max_recommendations_per_store_sku=int(max_store_sku),
    )

    upload_col, template_col = st.columns([2, 1])
    with upload_col:
        if source == "Archivo":
            orders_file = st.file_uploader("Carga pedidos con quiebre (Excel o CSV)", type=["xlsx", "xls", "csv"])
            raw_orders = _read_file(orders_file)
        else:
            days_back = st.number_input("Días hacia atrás para pedidos BigQuery", min_value=1, max_value=60, value=7)
            if st.button("Consultar pedidos en BigQuery", use_container_width=True):
                with st.spinner("Consultando pedidos con quiebre..."):
                    raw_orders = query_break_orders_from_bigquery(int(days_back))
                    st.session_state["raw_orders_bq"] = raw_orders
            raw_orders = st.session_state.get("raw_orders_bq", pd.DataFrame())

        if stock_source == "Archivo":
            stock_file = st.file_uploader("Carga stock disponible (Excel o CSV)", type=["xlsx", "xls", "csv"])
            raw_stock = _read_file(stock_file)
        else:
            raw_stock = pd.DataFrame()

    with template_col:
        st.download_button("Descargar plantilla pedidos", _empty_template("orders"), "plantilla_pedidos_quiebre.xlsx")
        st.download_button("Descargar plantilla stock", _empty_template("stock"), "plantilla_stock.xlsx")

    if raw_orders.empty:
        st.info("Carga un archivo de pedidos o consulta BigQuery para iniciar el análisis.")
        return

    orders_result = prepare_orders(raw_orders)
    orders = orders_result.dataframe
    if not orders_result.issues.empty:
        st.warning("Se encontraron observaciones en pedidos.")
        st.dataframe(orders_result.issues, use_container_width=True, hide_index=True)

    if stock_source == "BigQuery":
        with st.spinner("Consultando stock en BigQuery..."):
            raw_stock = query_stock_from_bigquery(
                tuple_from_series(orders["sku"]),
                tuple_from_series(orders["brand"]),
            )

    if raw_stock.empty:
        st.info("Carga stock o consulta BigQuery para calcular recomendaciones.")
        return

    stock_result = prepare_stock(raw_stock)
    stock = stock_result.dataframe
    if not stock_result.issues.empty:
        st.warning("Se encontraron observaciones en stock.")
        st.dataframe(stock_result.issues, use_container_width=True, hide_index=True)

    if st.button("Analizar reasignaciones", type="primary", use_container_width=True):
        progress = st.progress(0, text="Preparando datos")
        with st.spinner("Calculando recomendaciones con stock virtual acumulativo..."):
            progress.progress(30, text="Validando pedidos y stock")
            results = recommend_orders(orders, stock, settings)
            progress.progress(80, text="Armando KPIs y validaciones")
            warnings = build_operational_warnings(results)
            kpis = build_kpis(results)
            st.session_state["results"] = results
            st.session_state["warnings"] = warnings
            st.session_state["kpis"] = kpis
            progress.progress(100, text="Análisis listo")

    results = st.session_state.get("results", pd.DataFrame())
    if results.empty:
        st.caption("Presiona Analizar reasignaciones para generar recomendaciones.")
        return

    filtered = _apply_filters(results)
    kpis = build_kpis(filtered)
    warnings = build_operational_warnings(filtered)

    render_kpi_cards(kpis)
    render_charts(filtered)

    st.subheader("Tabla operativa")
    search = st.text_input("Buscar en tabla", placeholder="Pedido, SKU, tienda, motivo...")
    table = filtered.copy()
    if search:
        mask = table.astype(str).apply(lambda col: col.str.contains(search, case=False, na=False)).any(axis=1)
        table = table[mask]

    st.dataframe(style_results_table(table), use_container_width=True, hide_index=True, height=460)

    if not warnings.empty:
        st.subheader("Validaciones operativas")
        st.dataframe(warnings, use_container_width=True, hide_index=True)

    excel = build_excel(filtered, kpis, warnings)
    st.download_button(
        "Descargar Excel operativo",
        excel,
        file_name="recomendaciones_reasignacion_stock.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
        use_container_width=True,
    )


if __name__ == "__main__":
    from app_bq import main_bq

    main_bq()
