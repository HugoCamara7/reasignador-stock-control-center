from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

import pandas as pd

from config import COLUMN_ALIASES


@dataclass
class ValidationResult:
    dataframe: pd.DataFrame
    issues: pd.DataFrame
    summary: dict[str, int]


def _slug(value: object) -> str:
    text = "" if value is None else str(value)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = text.lower().strip()
    return re.sub(r"\s+", " ", text)


def normalize_columns(df: pd.DataFrame, required: list[str]) -> pd.DataFrame:
    normalized = df.copy()
    current = {_slug(column): column for column in normalized.columns}
    rename_map: dict[str, str] = {}

    for canonical in required:
        aliases = [_slug(canonical), *[_slug(alias) for alias in COLUMN_ALIASES.get(canonical, [])]]
        for alias in aliases:
            if alias in current:
                rename_map[current[alias]] = canonical
                break

    normalized = normalized.rename(columns=rename_map)
    return normalized


def prepare_orders(df: pd.DataFrame) -> ValidationResult:
    required = [
        "order_number",
        "sku",
        "model_color",
        "size",
        "quantity",
        "origin_store",
        "brand",
        "order_date",
        "order_status",
        "break_reason",
        "price",
    ]
    orders = normalize_columns(df, required)
    issues = []

    for column in ["order_number", "sku", "quantity"]:
        if column not in orders.columns:
            orders[column] = pd.NA
            issues.append({"Tipo": "Columna faltante", "Detalle": f"Falta columna obligatoria: {column}"})

    for optional in ["model_color", "size", "origin_store", "brand", "order_date", "order_status", "break_reason", "price"]:
        if optional not in orders.columns:
            orders[optional] = pd.NA

    orders["quantity"] = pd.to_numeric(orders["quantity"], errors="coerce").fillna(0).astype(int)
    orders["price"] = pd.to_numeric(orders["price"], errors="coerce").fillna(0.0)
    orders["order_date"] = pd.to_datetime(orders["order_date"], errors="coerce")
    orders["sku"] = orders["sku"].astype(str).str.strip()
    orders["order_number"] = orders["order_number"].astype(str).str.strip()

    duplicate_mask = orders.duplicated(subset=["order_number", "sku"], keep=False)
    if duplicate_mask.any():
        issues.append({"Tipo": "Pedidos duplicados", "Detalle": f"{int(duplicate_mask.sum())} filas duplicadas por pedido + SKU"})

    invalid_qty = orders["quantity"].le(0)
    if invalid_qty.any():
        issues.append({"Tipo": "Cantidad inválida", "Detalle": f"{int(invalid_qty.sum())} pedidos tienen cantidad menor o igual a cero"})

    summary = {
        "filas": int(len(orders)),
        "duplicados": int(duplicate_mask.sum()),
        "cantidad_invalida": int(invalid_qty.sum()),
    }
    return ValidationResult(orders, pd.DataFrame(issues), summary)


def prepare_stock(df: pd.DataFrame) -> ValidationResult:
    required = [
        "sku",
        "store",
        "warehouse",
        "brand",
        "stock_date",
        "available_stock",
        "stock_source",
        "is_enabled",
        "is_priority",
        "logistic_priority",
    ]
    stock = normalize_columns(df, required)
    issues = []

    for column in ["sku", "store", "available_stock"]:
        if column not in stock.columns:
            stock[column] = pd.NA
            issues.append({"Tipo": "Columna faltante", "Detalle": f"Falta columna obligatoria de stock: {column}"})

    for optional in ["warehouse", "brand", "stock_date", "stock_source", "is_enabled", "is_priority", "logistic_priority"]:
        if optional not in stock.columns:
            stock[optional] = pd.NA

    stock["available_stock"] = pd.to_numeric(stock["available_stock"], errors="coerce").fillna(0).astype(int)
    stock["stock_date"] = pd.to_datetime(stock["stock_date"], errors="coerce")
    stock["stock_source"] = stock["stock_source"].fillna("D-1").astype(str)
    stock["is_enabled"] = stock["is_enabled"].fillna(True).astype(str).str.lower().isin(["true", "1", "si", "sí", "yes", "y"])
    stock["is_priority"] = stock["is_priority"].fillna(False).astype(str).str.lower().isin(["true", "1", "si", "sí", "yes", "y"])
    stock["logistic_priority"] = pd.to_numeric(stock["logistic_priority"], errors="coerce").fillna(5).astype(float)
    stock["sku"] = stock["sku"].astype(str).str.strip()
    stock["store"] = stock["store"].astype(str).str.strip()

    negative_stock = stock["available_stock"].lt(0)
    if negative_stock.any():
        issues.append({"Tipo": "Stock negativo", "Detalle": f"{int(negative_stock.sum())} filas tienen stock negativo"})

    summary = {
        "filas": int(len(stock)),
        "stock_negativo": int(negative_stock.sum()),
        "tiendas": int(stock["store"].nunique()),
        "skus": int(stock["sku"].nunique()),
    }
    return ValidationResult(stock, pd.DataFrame(issues), summary)


def build_operational_warnings(results: pd.DataFrame) -> pd.DataFrame:
    warnings = []
    if results.empty:
        return pd.DataFrame(warnings)

    duplicated = results.duplicated(subset=["Número de pedido", "SKU"], keep=False)
    if duplicated.any():
        warnings.append({"Validación": "Duplicados", "Detalle": f"{int(duplicated.sum())} filas duplicadas en resultado"})

    no_sku = results["Estado"].eq("No reasignable") & results["Motivo"].str.contains("SKU no encontrado", na=False)
    if no_sku.any():
        warnings.append({"Validación": "SKUs no encontrados", "Detalle": f"{int(no_sku.sum())} pedidos sin SKU en stock"})

    heavy_store = results[results["Tienda recomendada"].notna()].groupby("Tienda recomendada").size()
    heavy_store = heavy_store[heavy_store >= 10]
    if not heavy_store.empty:
        stores = ", ".join(f"{store} ({count})" for store, count in heavy_store.items())
        warnings.append({"Validación": "Concentración por tienda", "Detalle": stores})

    multi_unit = results["Cantidad"].gt(1)
    if multi_unit.any():
        warnings.append({"Validación": "Pedidos multiunidad", "Detalle": f"{int(multi_unit.sum())} pedidos requieren más de una unidad"})

    return pd.DataFrame(warnings)
