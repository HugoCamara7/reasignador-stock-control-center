from __future__ import annotations

import html

import pandas as pd
import streamlit as st

from reassignment_engine import NO_STOCK, REASSIGNABLE, REVIEW


STATE_COLORS = {
    REASSIGNABLE: "#16a34a",
    REVIEW: "#f59e0b",
    NO_STOCK: "#ef4444",
}


def inject_dashboard_styles() -> None:
    st.markdown(
        """
        <style>
        :root {
            --ink: #0f172a;
            --muted: #64748b;
            --line: #e5e7eb;
            --panel: #ffffff;
            --soft: #f8fafc;
            --purple: #6d4aff;
        }
        .block-container {
            max-width: 1680px;
            padding-top: 1rem;
            padding-left: 1.65rem;
            padding-right: 1.65rem;
        }
        [data-testid="stSidebar"] {
            background: radial-gradient(circle at 10% 0%, #132353 0%, #061127 44%, #020817 100%);
        }
        [data-testid="stSidebar"] * { color: #f8fafc; }
        [data-testid="stSidebar"] .stButton > button {
            background: transparent;
            color: #e5e7eb;
            border: 0;
            justify-content: flex-start;
            font-weight: 650;
        }
        [data-testid="stSidebar"] .stButton > button:hover {
            background: rgba(109, 74, 255, .22);
            color: #ffffff;
        }
        .brand-lockup {
            display: flex;
            gap: .75rem;
            align-items: center;
            padding: .25rem 0 1.25rem;
            border-bottom: 1px solid rgba(255, 255, 255, .12);
            margin-bottom: 1rem;
        }
        .brand-icon {
            width: 34px;
            height: 34px;
            border-radius: 8px;
            display: grid;
            place-items: center;
            background: rgba(109, 74, 255, .18);
            border: 1px solid rgba(167, 139, 250, .7);
            font-weight: 900;
            color: #a78bfa;
        }
        .brand-title { font-weight: 850; line-height: 1.15; }
        .brand-sub { color: #cbd5e1; font-size: .83rem; }
        .topbar {
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: 1rem;
            padding-bottom: .9rem;
            border-bottom: 1px solid var(--line);
            margin-bottom: 1rem;
        }
        .topbar h1 {
            margin: 0;
            color: var(--ink);
            font-size: clamp(1.55rem, 3vw, 2.25rem);
            letter-spacing: 0;
            line-height: 1.08;
        }
        .topbar p { margin: .35rem 0 0; color: var(--muted); font-size: 1rem; }
        .user-chip {
            display: flex;
            gap: .7rem;
            align-items: center;
            padding: .35rem .55rem;
            border-left: 1px solid var(--line);
            white-space: nowrap;
        }
        .avatar {
            width: 38px;
            height: 38px;
            border-radius: 999px;
            background: linear-gradient(135deg, #60a5fa, #2563eb);
            display: grid;
            place-items: center;
            color: #fff;
            font-weight: 900;
        }
        .filter-card, .panel-card, .detail-card, .table-card, .kpi-card {
            background: var(--panel);
            border: 1px solid var(--line);
            border-radius: 8px;
            box-shadow: 0 8px 24px rgba(15, 23, 42, .055);
        }
        .filter-card { padding: .85rem 1rem .2rem; margin-bottom: 1rem; }
        .kpi-grid {
            display: grid;
            grid-template-columns: repeat(6, minmax(0, 1fr));
            gap: .75rem;
            margin-bottom: .9rem;
        }
        .kpi-card { padding: 1rem; min-height: 116px; }
        .kpi-top { display: flex; justify-content: space-between; gap: .5rem; align-items: center; }
        .kpi-icon {
            width: 42px;
            height: 42px;
            border-radius: 999px;
            display: grid;
            place-items: center;
            font-size: 1.15rem;
            font-weight: 850;
        }
        .kpi-label { color: #334155; font-size: .78rem; font-weight: 800; }
        .kpi-value { color: var(--ink); font-size: 1.65rem; font-weight: 900; margin-top: .5rem; }
        .kpi-foot { color: var(--muted); font-size: .76rem; margin-top: .12rem; }
        .panel-card { padding: 1rem; min-height: 275px; }
        .panel-title {
            color: var(--ink);
            font-weight: 850;
            margin-bottom: .9rem;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }
        .donut-wrap {
            display: grid;
            grid-template-columns: 180px minmax(0, 1fr);
            gap: 1.25rem;
            align-items: center;
        }
        .donut {
            width: 168px;
            height: 168px;
            border-radius: 50%;
            background: conic-gradient(#22c55e var(--pct), #fb7185 0);
            display: grid;
            place-items: center;
        }
        .donut-inner {
            width: 105px;
            height: 105px;
            border-radius: 50%;
            background: #ffffff;
            display: grid;
            place-items: center;
            text-align: center;
            color: var(--ink);
            font-weight: 900;
            font-size: 1.45rem;
            box-shadow: inset 0 0 0 1px #e5e7eb;
        }
        .donut-inner span { display: block; color: var(--muted); font-size: .72rem; font-weight: 650; margin-top: .15rem; }
        .legend-row { display: flex; align-items: center; gap: .55rem; color: #334155; margin: .5rem 0; font-size: .9rem; }
        .legend-dot { width: 12px; height: 12px; border-radius: 999px; }
        .bar-row { display: grid; grid-template-columns: 116px minmax(0, 1fr) 76px; gap: .65rem; align-items: center; margin: .72rem 0; font-size: .88rem; }
        .bar-bg { height: 7px; border-radius: 999px; background: #eef2ff; overflow: hidden; }
        .bar-fill { height: 100%; border-radius: 999px; background: linear-gradient(90deg, #7c3aed, #4f46e5); }
        .table-card { padding: .9rem; margin-top: .9rem; }
        .table-head { display: flex; justify-content: space-between; align-items: center; gap: 1rem; margin-bottom: .55rem; }
        .table-title { color: var(--ink); font-size: 1rem; font-weight: 850; }
        .count-pill { background: #eef2ff; color: #4f46e5; border-radius: 999px; padding: .2rem .55rem; font-size: .75rem; font-weight: 800; margin-left: .4rem; }
        .detail-card { padding: 1rem; position: sticky; top: 1rem; min-height: 680px; }
        .detail-head { display:flex; justify-content:space-between; align-items:center; margin-bottom: .9rem; }
        .detail-title { color: var(--ink); font-weight: 850; font-size: 1rem; }
        .pill { display:inline-flex; align-items:center; border-radius: 999px; padding: .22rem .55rem; font-size: .76rem; font-weight: 800; }
        .pill-green { background:#dcfce7; color:#15803d; }
        .pill-yellow { background:#fef3c7; color:#b45309; }
        .pill-red { background:#fee2e2; color:#b91c1c; }
        .detail-section { border-top: 1px solid var(--line); padding-top: .85rem; margin-top: .85rem; }
        .detail-k { color: var(--muted); font-size: .76rem; margin-top: .55rem; }
        .detail-v { color: var(--ink); font-weight: 750; font-size: .88rem; }
        .option-card { border: 1px solid var(--line); border-radius: 8px; padding: .65rem; margin: .55rem 0; background:#fff; }
        .option-card.recommended { border-color: #6d4aff; background: #f7f5ff; }
        .info-strip { background:#eaf4ff; border: 1px solid #bfdbfe; color:#1e3a8a; border-radius: 8px; padding: .8rem 1rem; margin-top: .9rem; font-size:.88rem; }
        div.stButton > button, div.stDownloadButton > button {
            border-radius: 8px;
            min-height: 2.6rem;
            font-weight: 800;
        }
        div[data-testid="stMetric"] { background: #fff; }
        @media (max-width: 1300px) {
            .kpi-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
            .donut-wrap { grid-template-columns: 1fr; }
            .detail-card { position: static; min-height: auto; }
        }
        @media (max-width: 800px) {
            .topbar { flex-direction: column; }
            .kpi-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
            .bar-row { grid-template-columns: 1fr; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar() -> None:
    with st.sidebar:
        st.markdown(
            """
            <div class="brand-lockup">
              <div class="brand-icon">◇</div>
              <div>
                <div class="brand-title">Motor inteligente</div>
                <div class="brand-sub">de reasignacion</div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.button("Resumen", use_container_width=True)
        st.button("Pedidos con quiebre", use_container_width=True)
        st.button("Recomendaciones", use_container_width=True)
        st.button("Stock disponible", use_container_width=True)
        st.button("Historial de consultas", use_container_width=True)
        st.button("Descargas", use_container_width=True)
        st.write("")
        st.write("")
        st.button("Configuracion", use_container_width=True)
        st.button("Cerrar sesion", use_container_width=True)


def render_header(validate_shopify: bool) -> None:
    status = "Shopify activo" if validate_shopify else "Shopify opcional"
    st.markdown(
        f"""
        <div class="topbar">
          <div>
            <h1>Motor inteligente de reasignacion de pedidos</h1>
            <p>Lee ordenes desde Shopify, cruza stock desde BigQuery y recomienda tiendas con stock disponible</p>
          </div>
          <div class="user-chip">
            <div>
              <div style="font-weight:850;color:#0f172a;">Columbia</div>
              <div style="font-size:.78rem;color:#64748b;">{html.escape(status)}</div>
            </div>
            <div class="avatar">C</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_review_points() -> None:
    st.markdown(
        """
        <div class="panel-card" style="padding: .9rem 1rem; margin-bottom: .9rem;">
          <div class="panel-title" style="margin-bottom:.45rem;">Puntos importantes que revisa el motor</div>
          <div style="display:grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap:.65rem; font-size:.84rem; color:#334155;">
            <div><strong>1. Orden Shopify</strong><br>Busca tags, notas, estado pendiente o linea no preparada.</div>
            <div><strong>2. SKU exacto</strong><br>Para calzado no reemplaza talla ni color; solo cruza SKU exacto.</div>
            <div><strong>3. Stock BigQuery</strong><br>Calcula disponible - seguridad - reservado por tienda.</div>
            <div><strong>4. Confianza</strong><br>Marca riesgo si el stock es D-1 o si Shopify no valida stock actual.</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_filter_shell() -> None:
    st.markdown("<div class='filter-card'>", unsafe_allow_html=True)


def close_shell() -> None:
    st.markdown("</div>", unsafe_allow_html=True)


def render_kpi_dashboard(kpis: dict[str, float]) -> None:
    total = kpis.get("total", 0)
    recoverable = kpis.get("units_recoverable", 0)
    broken_units = kpis.get("units_broken", 0)
    no_stock = kpis.get("no_stock", 0)
    cards = [
        ("Pedidos con quiebre", total, "+12%", "⌁", "#ede9fe", "#6d4aff"),
        ("Pedidos reasignables", kpis.get("reassignable", 0), f"{_pct(kpis.get('reassignable', 0), total)}%", "✓", "#dcfce7", "#16a34a"),
        ("Unidades en quiebre", broken_units, "+8%", "□", "#ffedd5", "#f97316"),
        ("Unidades recuperables", recoverable, f"{_pct(recoverable, broken_units)}%", "◆", "#dcfce7", "#16a34a"),
        ("Sin stock disponible", no_stock, f"{_pct(no_stock, total)}%", "×", "#fee2e2", "#ef4444"),
        ("% recuperacion posible", f"{kpis.get('recovery_pct', 0):.1f}%", "+5.4 p.p.", "◔", "#dbeafe", "#2563eb"),
    ]
    html_parts = ["<div class='kpi-grid'>"]
    for label, value, delta, icon, bg, color in cards:
        html_parts.append(
            "<div class='kpi-card'>"
            "<div class='kpi-top'>"
            f"<div class='kpi-icon' style='background:{bg};color:{color}'>{html.escape(str(icon))}</div>"
            f"<div class='pill {'pill-green' if str(delta).startswith('+') or '%' in str(delta) else 'pill-red'}'>{html.escape(str(delta))}</div>"
            "</div>"
            f"<div class='kpi-label'>{html.escape(label)}</div>"
            f"<div class='kpi-value'>{html.escape(str(value))}</div>"
            "<div class='kpi-foot'>vs. periodo anterior</div>"
            "</div>"
        )
    html_parts.append("</div>")
    st.markdown("".join(html_parts), unsafe_allow_html=True)


def render_recovery_panel(kpis: dict[str, float]) -> None:
    pct = float(kpis.get("recovery_pct", 0) or 0)
    recoverable = int(kpis.get("units_recoverable", 0) or 0)
    not_recovered = max(int(kpis.get("units_broken", 0) or 0) - recoverable, 0)
    st.markdown(
        f"""
        <div class="panel-card">
          <div class="panel-title">Recuperacion posible en unidades <span class="pill pill-green">7 dias</span></div>
          <div class="donut-wrap">
            <div class="donut" style="--pct:{pct}%"><div class="donut-inner">{pct:.1f}%<span>Recuperacion<br>posible</span></div></div>
            <div>
              <div class="legend-row"><span class="legend-dot" style="background:#22c55e"></span> Recuperables {recoverable:,} ({pct:.1f}%)</div>
              <div class="legend-row"><span class="legend-dot" style="background:#fb7185"></span> No recuperables {not_recovered:,} ({max(100-pct, 0):.1f}%)</div>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_daily_breaks_panel(recommendations: pd.DataFrame) -> None:
    st.markdown("<div class='panel-card'><div class='panel-title'>Pedidos con quiebre por dia</div>", unsafe_allow_html=True)
    if recommendations.empty or "Fecha pedido" not in recommendations.columns:
        st.info("Sin datos diarios para graficar.")
    else:
        data = recommendations.copy()
        data["Fecha"] = pd.to_datetime(data["Fecha pedido"], errors="coerce").dt.date
        daily = data.dropna(subset=["Fecha"]).groupby("Fecha").size().reset_index(name="Pedidos")
        if daily.empty:
            st.info("Sin fecha de pedido disponible.")
        else:
            st.line_chart(daily, x="Fecha", y="Pedidos", use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)


def render_top_model_panel(recommendations: pd.DataFrame) -> None:
    st.markdown("<div class='panel-card'><div class='panel-title'>Top codigos modelo color con mas quiebre <span class='pill pill-green'>Top 5</span></div>", unsafe_allow_html=True)
    if recommendations.empty:
        st.info("Sin datos para mostrar.")
        st.markdown("</div>", unsafe_allow_html=True)
        return
    top = (
        recommendations.groupby("Modelo Color", dropna=False)
        .agg(Unidades=("Cantidad", "sum"))
        .reset_index()
        .sort_values("Unidades", ascending=False)
        .head(5)
    )
    max_units = max(float(top["Unidades"].max()), 1)
    parts = []
    for _, row in top.iterrows():
        units = int(row["Unidades"])
        width = int(units / max_units * 100)
        model = "Sin modelo" if pd.isna(row["Modelo Color"]) else str(row["Modelo Color"])
        parts.append(
            f"<div class='bar-row'><strong>{html.escape(model)}</strong>"
            f"<div class='bar-bg'><div class='bar-fill' style='width:{width}%'></div></div>"
            f"<span>{units} unidades</span></div>"
        )
    st.markdown("".join(parts), unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)


def render_recommendation_table(recommendations: pd.DataFrame) -> None:
    st.markdown(
        f"<div class='table-card'><div class='table-head'><div class='table-title'>Recomendaciones de reasignacion <span class='count-pill'>{len(recommendations)} resultados</span></div></div>",
        unsafe_allow_html=True,
    )
    columns = [
        "Pedido",
        "Fecha pedido",
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
    ]
    existing = [column for column in columns if column in recommendations.columns]
    table = recommendations[existing].copy()
    st.dataframe(_style_states(table), use_container_width=True, hide_index=True, height=360)
    st.markdown("</div>", unsafe_allow_html=True)


def render_detail_panel(recommendations: pd.DataFrame, alternatives: pd.DataFrame) -> None:
    st.markdown("<div class='detail-card'>", unsafe_allow_html=True)
    st.markdown("<div class='detail-head'><div class='detail-title'>Detalle del pedido</div><div style='color:#64748b'>×</div></div>", unsafe_allow_html=True)
    if recommendations.empty:
        st.info("Ejecuta una consulta para ver el detalle.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    orders = [str(value) for value in recommendations["Pedido"].dropna().unique()]
    selected = st.selectbox("Pedido", orders, label_visibility="collapsed")
    row = recommendations[recommendations["Pedido"].astype(str).eq(selected)].iloc[0]
    pill_class = _pill_class(str(row.get("Estado", "")))
    st.markdown(
        f"""
        <span class="pill {pill_class}">{html.escape(str(row.get('Estado')))}</span>
        <span style="float:right;color:#0f172a;font-weight:750;">Confianza {html.escape(str(row.get('Confianza', '')).lower())}</span>
        <div class="detail-section">
          <div class="detail-k">Pedido</div><div class="detail-v">{html.escape(str(row.get('Pedido')))}</div>
          <div class="detail-k">Fecha</div><div class="detail-v">{html.escape(str(row.get('Fecha pedido', '')))}</div>
          <div class="detail-k">Tienda origen</div><div class="detail-v">{html.escape(str(row.get('Tienda origen', '')))}</div>
          <div class="detail-k">Motivo del quiebre</div><div class="detail-v">{html.escape(str(row.get('Motivo quiebre', '')))}</div>
        </div>
        <div class="detail-section">
          <div class="detail-k">Producto</div><div class="detail-v">{html.escape(str(row.get('Modelo Color', '')))}</div>
          <div class="detail-k">SKU</div><div class="detail-v">{html.escape(str(row.get('SKU', '')))}</div>
          <div class="detail-k">Talla</div><div class="detail-v">{html.escape(str(row.get('Talla', '')))}</div>
          <div class="detail-k">Cantidad</div><div class="detail-v">{html.escape(str(row.get('Cantidad', '')))} unidad</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    candidates = alternatives[alternatives.get("order_number", pd.Series(dtype=str)).astype(str).eq(selected)].head(3)
    st.markdown("<div class='detail-section'><div class='detail-v'>Opciones de reasignacion</div>", unsafe_allow_html=True)
    if candidates.empty:
        store = row.get("Tienda recomendada") or "Sin tienda candidata"
        stock = row.get("Stock reasignable", 0)
        st.markdown(
            f"<div class='option-card recommended'><strong>{html.escape(str(store))}</strong><br><span class='detail-k'>Stock reasignable: {html.escape(str(stock))}</span></div>",
            unsafe_allow_html=True,
        )
    else:
        for idx, candidate in candidates.iterrows():
            klass = "option-card recommended" if int(candidate.get("rank", 0) or 0) == 1 else "option-card"
            badge = " <span class='pill pill-green'>Recomendado</span>" if "recommended" in klass else ""
            st.markdown(
                f"<div class='{klass}'><strong>{html.escape(str(candidate.get('store')))}</strong>{badge}<br>"
                f"<span class='detail-k'>Stock reasignable: {html.escape(str(candidate.get('stock_reassignable')))}</span></div>",
                unsafe_allow_html=True,
            )
    st.markdown("</div>", unsafe_allow_html=True)
    st.button("Marcar como revisado", type="primary", use_container_width=True)
    st.markdown("</div>", unsafe_allow_html=True)


def render_info_strip() -> None:
    st.markdown(
        "<div class='info-strip'>El stock mostrado puede provenir de cierre D-1. Se recomienda validar con Shopify API antes de confirmar la reasignacion.</div>",
        unsafe_allow_html=True,
    )


def render_empty_state(message: str) -> None:
    st.markdown(f"<div class='panel-card'>{html.escape(message)}</div>", unsafe_allow_html=True)


def _style_states(df: pd.DataFrame):
    def color_state(value: str) -> str:
        return f"color: {STATE_COLORS.get(value, '#64748b')}; font-weight: 800;"

    if "Estado" not in df.columns:
        return df.style
    return df.style.applymap(color_state, subset=["Estado"])


def _pct(value: float, total: float) -> float:
    return round((float(value) / float(total) * 100) if total else 0, 1)


def _pill_class(state: str) -> str:
    if state == REASSIGNABLE:
        return "pill-green"
    if state == NO_STOCK:
        return "pill-red"
    return "pill-yellow"
