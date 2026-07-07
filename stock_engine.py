from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass
class RecommendationSettings:
    safety_stock: int = 1
    enabled_stores: set[str] = field(default_factory=set)
    blocked_stores: set[str] = field(default_factory=set)
    priority_stores: dict[str, int] = field(default_factory=dict)
    use_d1_stock: bool = True
    allow_partial: bool = True
    prioritize_mode: str = "Mayor stock"
    included_brands: set[str] = field(default_factory=set)
    max_recommendations_per_store_sku: int = 9999


def _clean_store_set(values: set[str]) -> set[str]:
    return {value.strip().lower() for value in values if value and value.strip()}


def _stock_source_is_d1(value: object) -> bool:
    text = str(value or "").strip().lower()
    return text in {"d-1", "d1", "cierre", "cierre anterior", "dia anterior", "día anterior"}


def _score_candidate(row: pd.Series, remaining_after: int, settings: RecommendationSettings) -> float:
    stock_score = min(max(int(row["virtual_stock"]), 0), 50) * 2
    priority_score = 25 if bool(row.get("is_priority", False)) else 0
    store_priority = settings.priority_stores.get(str(row["store"]).strip().lower(), 0) * 8
    logistic_score = max(0, 10 - float(row.get("logistic_priority", 5))) * 4
    source_penalty = -15 if _stock_source_is_d1(row.get("stock_source")) else 10
    safety_bonus = min(max(remaining_after, 0), 10) * 3

    if settings.prioritize_mode == "Prioridad logística":
        return logistic_score * 1.8 + priority_score + store_priority + stock_score * 0.65 + source_penalty + safety_bonus
    return stock_score + priority_score + store_priority + logistic_score + source_penalty + safety_bonus


def recommend_orders(orders: pd.DataFrame, stock: pd.DataFrame, settings: RecommendationSettings) -> pd.DataFrame:
    if orders.empty:
        return pd.DataFrame()

    enabled_stores = _clean_store_set(settings.enabled_stores)
    blocked_stores = _clean_store_set(settings.blocked_stores)
    included_brands = {brand.strip().lower() for brand in settings.included_brands if brand and brand.strip()}

    stock_work = stock.copy()
    stock_work["store_key"] = stock_work["store"].astype(str).str.strip().str.lower()
    stock_work["sku_key"] = stock_work["sku"].astype(str).str.strip().str.lower()
    stock_work["brand_key"] = stock_work["brand"].astype(str).str.strip().str.lower()

    if enabled_stores:
        stock_work = stock_work[stock_work["store_key"].isin(enabled_stores)]
    if blocked_stores:
        stock_work = stock_work[~stock_work["store_key"].isin(blocked_stores)]
    if included_brands:
        stock_work = stock_work[stock_work["brand_key"].isin(included_brands)]
    if not settings.use_d1_stock:
        stock_work = stock_work[~stock_work["stock_source"].map(_stock_source_is_d1)]

    stock_work = stock_work[stock_work["is_enabled"].fillna(True)]
    stock_work = stock_work[stock_work["available_stock"].fillna(0).ge(0)]
    stock_work["virtual_stock"] = stock_work["available_stock"].astype(int)
    stock_work = stock_work.sort_values(["sku_key", "store_key", "stock_date"], ascending=[True, True, False])
    stock_work = stock_work.drop_duplicates(subset=["sku_key", "store_key"], keep="first")

    usage_counter: dict[tuple[str, str], int] = {}
    rows = []
    ordered_orders = orders.copy().sort_values(["order_date", "order_number"], na_position="last")

    for _, order in ordered_orders.iterrows():
        sku_key = str(order["sku"]).strip().lower()
        brand_key = str(order.get("brand", "")).strip().lower()
        quantity = int(order.get("quantity", 0) or 0)
        candidates = stock_work[stock_work["sku_key"].eq(sku_key)].copy()

        if brand_key and brand_key != "nan":
            branded = candidates[candidates["brand_key"].eq(brand_key)]
            if not branded.empty:
                candidates = branded

        if candidates.empty:
            rows.append(_result_row(order, None, "No reasignable", "SKU no encontrado con stock disponible", 0, quantity))
            continue

        candidates["enough_after_safety"] = candidates["virtual_stock"] - quantity - settings.safety_stock
        full_candidates = candidates[candidates["enough_after_safety"].ge(0)].copy()
        partial_candidates = candidates[candidates["virtual_stock"].gt(settings.safety_stock)].copy()

        if not full_candidates.empty:
            full_candidates["score"] = full_candidates.apply(
                lambda row: _score_candidate(row, int(row["enough_after_safety"]), settings),
                axis=1,
            )
            selected = full_candidates.sort_values("score", ascending=False).iloc[0]
            selected_key = (str(selected["sku_key"]), str(selected["store_key"]))
            if usage_counter.get(selected_key, 0) >= settings.max_recommendations_per_store_sku:
                rows.append(_result_row(order, None, "Requiere revisión", "La tienda candidata llegó al máximo configurado de recomendaciones", 0, quantity))
                continue

            remaining = int(selected["virtual_stock"]) - quantity
            stock_work.loc[selected.name, "virtual_stock"] = remaining
            usage_counter[selected_key] = usage_counter.get(selected_key, 0) + 1
            state = "Riesgo por stock D-1" if _stock_source_is_d1(selected.get("stock_source")) else "Reasignable"
            reason = "Cubre pedido completo con stock de seguridad"
            if state == "Riesgo por stock D-1":
                reason = "Cubre pedido completo, pero usa cierre D-1 y requiere validación"
            rows.append(_result_row(order, selected, state, reason, float(selected["score"]), quantity, remaining))
            continue

        if settings.allow_partial and not partial_candidates.empty:
            partial_candidates["score"] = partial_candidates.apply(
                lambda row: _score_candidate(row, int(row["virtual_stock"]) - settings.safety_stock, settings),
                axis=1,
            )
            selected = partial_candidates.sort_values("score", ascending=False).iloc[0]
            available_to_assign = max(int(selected["virtual_stock"]) - settings.safety_stock, 0)
            remaining = int(selected["virtual_stock"]) - available_to_assign
            stock_work.loc[selected.name, "virtual_stock"] = remaining
            rows.append(
                _result_row(
                    order,
                    selected,
                    "Reasignable parcial",
                    f"Solo cubre {available_to_assign} de {quantity} unidades respetando stock de seguridad",
                    float(selected["score"]),
                    available_to_assign,
                    remaining,
                )
            )
            continue

        rows.append(_result_row(order, None, "No reasignable", "No existe tienda con stock suficiente después del stock de seguridad", 0, quantity))

    return pd.DataFrame(rows)


def _result_row(
    order: pd.Series,
    selected: pd.Series | None,
    state: str,
    reason: str,
    score: float,
    quantity_to_assign: int,
    remaining_stock: int | None = None,
) -> dict[str, object]:
    recommended_store = None if selected is None else selected.get("store")
    stock_available = None if selected is None else int(selected.get("available_stock", 0))
    stock_date = None if selected is None else selected.get("stock_date")
    action = "Reasignar" if state in {"Reasignable", "Riesgo por stock D-1"} else "Revisar" if state != "No reasignable" else "Sin acción"
    if state == "Riesgo por stock D-1":
        action = "Validar stock actualizado antes de reasignar"

    return {
        "Número de pedido": order.get("order_number"),
        "SKU": order.get("sku"),
        "Código modelo color": order.get("model_color"),
        "Talla": order.get("size"),
        "Cantidad": int(order.get("quantity", 0) or 0),
        "Cantidad sugerida": int(quantity_to_assign or 0),
        "Tienda actual/origen": order.get("origin_store"),
        "Marca": order.get("brand"),
        "Fecha de pedido": order.get("order_date"),
        "Tipo de quiebre": order.get("break_reason"),
        "Tienda recomendada": recommended_store,
        "Stock disponible": stock_available,
        "Stock restante después de reasignación": remaining_stock,
        "Estado": state,
        "Motivo": reason,
        "Score": round(score, 1),
        "Fecha de stock": stock_date,
        "Acción sugerida": action,
        "Precio": float(order.get("price", 0) or 0),
        "Fuente stock": None if selected is None else selected.get("stock_source"),
    }


def build_kpis(results: pd.DataFrame) -> dict[str, float]:
    if results.empty:
        return {
            "total_pedidos": 0,
            "reasignables": 0,
            "no_reasignables": 0,
            "parciales": 0,
            "unidades_riesgo": 0,
            "unidades_recuperables": 0,
            "recuperacion_pct": 0,
            "riesgo_d1": 0,
            "venta_recuperable": 0,
        }

    recoverable_states = {"Reasignable", "Reasignable parcial", "Riesgo por stock D-1"}
    units_risk = int(results["Cantidad"].sum())
    units_recoverable = int(results.loc[results["Estado"].isin(recoverable_states), "Cantidad sugerida"].sum())
    return {
        "total_pedidos": int(len(results)),
        "reasignables": int(results["Estado"].isin(["Reasignable", "Riesgo por stock D-1"]).sum()),
        "no_reasignables": int(results["Estado"].eq("No reasignable").sum()),
        "parciales": int(results["Estado"].eq("Reasignable parcial").sum()),
        "unidades_riesgo": units_risk,
        "unidades_recuperables": units_recoverable,
        "recuperacion_pct": round((units_recoverable / units_risk * 100) if units_risk else 0, 1),
        "riesgo_d1": int(results["Estado"].eq("Riesgo por stock D-1").sum()),
        "venta_recuperable": float(results.loc[results["Estado"].isin(recoverable_states), "Precio"].sum()),
    }
