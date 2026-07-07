from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd


REASSIGNABLE = "Reasignable"
NO_STOCK = "Sin stock disponible"
REVIEW = "Revisar manualmente"


@dataclass
class ReassignmentSettings:
    safety_stock: int = 1
    validate_shopify: bool = False
    max_stock_age_hours: int = 30


def _normalise_key(value: object) -> str:
    return "" if pd.isna(value) else str(value).strip().lower()


def _is_d1_stock(value: object) -> bool:
    text = _normalise_key(value)
    return text in {"d-1", "d1", "cierre", "cierre anterior", "dia anterior", "día anterior"}


def _stock_age_hours(value: object) -> float | None:
    if pd.isna(value):
        return None
    timestamp = pd.to_datetime(value, errors="coerce")
    if pd.isna(timestamp):
        return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize(timezone.utc)
    return max((datetime.now(timezone.utc) - timestamp.to_pydatetime()).total_seconds() / 3600, 0)


def calculate_reassignable_stock(stock: pd.DataFrame, default_safety_stock: int = 1) -> pd.DataFrame:
    stock_work = stock.copy()
    for column, default in {
        "available_stock": 0,
        "reserved_stock": 0,
        "safety_stock": default_safety_stock,
    }.items():
        if column not in stock_work.columns:
            stock_work[column] = default
        stock_work[column] = pd.to_numeric(stock_work[column], errors="coerce").fillna(default).astype(int)

    stock_work["stock_reassignable"] = (
        stock_work["available_stock"] - stock_work["safety_stock"] - stock_work["reserved_stock"]
    ).clip(lower=0)
    return stock_work


def build_reassignment_recommendations(
    orders: pd.DataFrame,
    stock: pd.DataFrame,
    settings: ReassignmentSettings,
    shopify_validation: dict[tuple[str, str], dict[str, object]] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if orders.empty:
        return pd.DataFrame(), pd.DataFrame()

    stock_work = calculate_reassignable_stock(stock, settings.safety_stock)
    stock_work["sku_key"] = stock_work["sku"].map(_normalise_key)
    stock_work["store_key"] = stock_work["store"].map(_normalise_key)
    if "is_ecommerce_enabled" not in stock_work.columns:
        stock_work["is_ecommerce_enabled"] = True
    stock_work["is_ecommerce_enabled"] = stock_work["is_ecommerce_enabled"].fillna(True).astype(bool)
    if "risk_score" not in stock_work.columns:
        stock_work["risk_score"] = 0
    stock_work["risk_score"] = pd.to_numeric(stock_work["risk_score"], errors="coerce").fillna(0)
    if "city" not in stock_work.columns:
        stock_work["city"] = ""
    if "stock_source" not in stock_work.columns:
        stock_work["stock_source"] = "Desconocido"

    rows: list[dict[str, object]] = []
    alternatives: list[dict[str, object]] = []

    ordered_orders = orders.copy()
    ordered_orders["order_date"] = pd.to_datetime(ordered_orders.get("order_date"), errors="coerce")
    ordered_orders = ordered_orders.sort_values(["order_date", "order_number"], na_position="last")

    for _, order in ordered_orders.iterrows():
        sku_key = _normalise_key(order.get("sku"))
        origin_key = _normalise_key(order.get("origin_store"))
        quantity = int(order.get("quantity", 0) or 0)
        candidates = stock_work[
            stock_work["sku_key"].eq(sku_key)
            & stock_work["is_ecommerce_enabled"]
            & ~stock_work["store_key"].eq(origin_key)
            & stock_work["stock_reassignable"].ge(quantity)
        ].copy()

        if candidates.empty:
            rows.append(_empty_recommendation(order, NO_STOCK, "No hay tienda habilitada con stock reasignable suficiente."))
            continue

        date_column = "updated_at" if "updated_at" in candidates.columns else "stock_date"
        candidates["stock_age_hours"] = candidates[date_column].map(_stock_age_hours) if date_column in candidates.columns else None
        candidates["same_city"] = candidates["city"].map(_normalise_key).eq(_normalise_key(order.get("city")))
        candidates["is_d1"] = candidates["stock_source"].map(_is_d1_stock)
        candidates["score"] = candidates.apply(_candidate_score, axis=1)
        candidates = candidates.sort_values(["score", "stock_reassignable", "available_stock"], ascending=False)

        selected = candidates.iloc[0].copy()
        shopify_key = (_normalise_key(selected.get("location_id") or selected.get("store")), sku_key)
        shopify_result = (shopify_validation or {}).get(shopify_key, {})
        shopify_status = str(shopify_result.get("status", "No validado"))
        shopify_available = shopify_result.get("available_stock")

        state = REASSIGNABLE
        confidence = _confidence_from_candidate(selected)
        reason = "SKU exacto con stock reasignable suficiente en tienda ecommerce habilitada."

        if bool(selected.get("is_d1")):
            state = REVIEW
            confidence = "Medio" if confidence == "Alto" else confidence
            reason = "Tiene stock suficiente, pero la fuente es D-1 y requiere validacion actual."

        if settings.validate_shopify:
            if shopify_status == "Validado" and shopify_available is not None and int(shopify_available) < quantity:
                state = REVIEW
                confidence = "Bajo"
                reason = "BigQuery indica stock, pero Shopify no confirma unidades suficientes."
            elif shopify_status not in {"Validado", "No validado"}:
                state = REVIEW
                confidence = "Medio"
                reason = f"Stock candidato encontrado, pero Shopify devolvio advertencia: {shopify_status}."

        rows.append(_recommendation_row(order, selected, state, confidence, reason, shopify_status, shopify_available))

        for rank, candidate in enumerate(candidates.head(5).to_dict("records"), start=1):
            alternatives.append(
                {
                    "order_number": order.get("order_number"),
                    "sku": order.get("sku"),
                    "rank": rank,
                    "store": candidate.get("store"),
                    "available_stock": candidate.get("available_stock"),
                    "stock_reassignable": candidate.get("stock_reassignable"),
                    "score": round(float(candidate.get("score", 0)), 1),
                    "stock_source": candidate.get("stock_source"),
                    "updated_at": candidate.get("updated_at"),
                }
            )

        stock_work.loc[selected.name, "stock_reassignable"] = int(selected["stock_reassignable"]) - quantity

    return pd.DataFrame(rows), pd.DataFrame(alternatives)


def _candidate_score(row: pd.Series) -> float:
    score = 0.0
    score += 40 if bool(row.get("is_ecommerce_enabled")) else 0
    score += min(float(row.get("stock_reassignable", 0)), 30) * 1.5
    score += 18 if bool(row.get("same_city")) else 0
    score -= min(float(row.get("risk_score", 0)), 10) * 2
    if bool(row.get("is_d1")):
        score -= 14
    age = row.get("stock_age_hours")
    if age is not None:
        score += max(0, 18 - min(float(age), 72) / 4)
    return score


def _confidence_from_candidate(row: pd.Series) -> str:
    if bool(row.get("is_d1")):
        return "Medio"
    if float(row.get("score", 0)) >= 80:
        return "Alto"
    if float(row.get("score", 0)) >= 55:
        return "Medio"
    return "Bajo"


def _empty_recommendation(order: pd.Series, state: str, reason: str) -> dict[str, object]:
    return {
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
        "Estado": state,
        "Confianza": "Bajo",
        "Motivo": reason,
        "Motivo quiebre": order.get("break_reason"),
        "Fuente stock": None,
        "Ultima actualizacion stock": None,
        "Shopify": "No validado",
    }


def _recommendation_row(
    order: pd.Series,
    selected: pd.Series,
    state: str,
    confidence: str,
    reason: str,
    shopify_status: str,
    shopify_available: object,
) -> dict[str, object]:
    return {
        "Pedido": order.get("order_number"),
        "Order ID": order.get("order_id"),
        "Fecha pedido": order.get("order_date"),
        "Marca": order.get("brand"),
        "SKU": order.get("sku"),
        "Modelo Color": order.get("model_color"),
        "Talla": order.get("size"),
        "Cantidad": int(order.get("quantity", 0) or 0),
        "Tienda origen": order.get("origin_store"),
        "Tienda recomendada": selected.get("store"),
        "Stock disponible": int(selected.get("available_stock", 0)),
        "Stock reasignable": int(selected.get("stock_reassignable", 0)),
        "Estado": state,
        "Confianza": confidence,
        "Motivo": reason,
        "Motivo quiebre": order.get("break_reason"),
        "Fuente stock": selected.get("stock_source"),
        "Ultima actualizacion stock": selected.get("updated_at", selected.get("stock_date")),
        "Shopify": shopify_status,
        "Stock Shopify": shopify_available,
        "Score": round(float(selected.get("score", 0)), 1),
    }


def build_reassignment_kpis(results: pd.DataFrame) -> dict[str, float]:
    if results.empty:
        return {
            "total": 0,
            "reassignable": 0,
            "no_stock": 0,
            "review": 0,
            "units_broken": 0,
            "units_recoverable": 0,
            "recovery_pct": 0,
        }
    recoverable = results["Estado"].isin([REASSIGNABLE, REVIEW])
    units_broken = int(results["Cantidad"].sum())
    units_recoverable = int(results.loc[recoverable, "Cantidad"].sum())
    return {
        "total": int(len(results)),
        "reassignable": int(results["Estado"].eq(REASSIGNABLE).sum()),
        "no_stock": int(results["Estado"].eq(NO_STOCK).sum()),
        "review": int(results["Estado"].eq(REVIEW).sum()),
        "units_broken": units_broken,
        "units_recoverable": units_recoverable,
        "recovery_pct": round((units_recoverable / units_broken * 100) if units_broken else 0, 1),
    }
