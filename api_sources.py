from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import date, timedelta
from typing import Iterable

import pandas as pd
import streamlit as st


def _get_secret(path: str, default=None):
    node = st.secrets
    for key in path.split("."):
        if key not in node:
            return default
        node = node[key]
    return node


@st.cache_resource(show_spinner=False)
def _bigquery_client():
    try:
        from google.cloud import bigquery
        from google.oauth2 import service_account
    except ImportError as exc:
        raise RuntimeError("Falta instalar google-cloud-bigquery y google-auth. Revisa requirements.txt.") from exc

    project_id = _get_secret("bigquery.project_id")
    service_account_info = _get_secret("bigquery.service_account_info")

    if service_account_info:
        credentials = service_account.Credentials.from_service_account_info(dict(service_account_info))
        return bigquery.Client(project=project_id or credentials.project_id, credentials=credentials)

    raise RuntimeError(
        "BigQuery no tiene credenciales configuradas. Agrega una cuenta de servicio en "
        "st.secrets['bigquery']['service_account_info']. Sin eso, Google intenta usar metadata.google.internal, "
        "que solo existe dentro de Google Cloud."
    )


def _table_secret(name: str) -> str:
    table = _get_secret(f"bigquery.{name}")
    if not table:
        raise RuntimeError(f"Configura st.secrets['bigquery']['{name}'] con la tabla correspondiente.")
    return str(table)


def _normalise_tuple(values: Iterable[object]) -> tuple[str, ...]:
    return tuple(sorted({str(value).strip() for value in values if pd.notna(value) and str(value).strip()}))


@st.cache_data(ttl=600, show_spinner=False)
def fetch_broken_orders_from_bigquery(days_back: int, brands: tuple[str, ...] = ()) -> pd.DataFrame:
    from google.cloud import bigquery

    client = _bigquery_client()
    since = date.today() - timedelta(days=days_back)
    custom_query = _get_secret("bigquery.broken_orders_query")

    if custom_query:
        query = str(custom_query)
    else:
        orders_table = _table_secret("orders_table")
        query = f"""
            SELECT
              CAST(order_number AS STRING) AS order_number,
              CAST(order_id AS STRING) AS order_id,
              DATETIME(order_date) AS order_date,
              CAST(brand AS STRING) AS brand,
              CAST(sku AS STRING) AS sku,
              CAST(model_color AS STRING) AS model_color,
              CAST(size AS STRING) AS size,
              CAST(quantity AS INT64) AS quantity,
              CAST(origin_store AS STRING) AS origin_store,
              CAST(origin_location_id AS STRING) AS origin_location_id,
              CAST(city AS STRING) AS city,
              CAST(order_status AS STRING) AS order_status,
              CAST(break_reason AS STRING) AS break_reason
            FROM `{orders_table}`
            WHERE DATE(order_date) >= @since
              AND CAST(sku AS STRING) IS NOT NULL
              AND COALESCE(CAST(quantity AS INT64), 0) > 0
              AND (
                LOWER(COALESCE(CAST(order_status AS STRING), '')) LIKE '%sin stock%'
                OR LOWER(COALESCE(CAST(order_status AS STRING), '')) LIKE '%terminado%'
                OR LOWER(COALESCE(CAST(order_status AS STRING), '')) LIKE '%pendiente%'
                OR LOWER(COALESCE(CAST(break_reason AS STRING), '')) LIKE '%quiebre%'
                OR LOWER(COALESCE(CAST(break_reason AS STRING), '')) LIKE '%stock%'
              )
              AND (@brand_count = 0 OR CAST(brand AS STRING) IN UNNEST(@brands))
        """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("since", "DATE", since.isoformat()),
            bigquery.ArrayQueryParameter("brands", "STRING", list(brands)),
            bigquery.ScalarQueryParameter("brand_count", "INT64", len(brands)),
        ]
    )
    return client.query(query, job_config=job_config).to_dataframe()


@st.cache_data(ttl=600, show_spinner=False)
def fetch_available_stock_from_bigquery(skus: tuple[str, ...], days_back: int = 2) -> pd.DataFrame:
    if not skus:
        return pd.DataFrame()

    from google.cloud import bigquery

    client = _bigquery_client()
    stock_table = _table_secret("stock_table")
    since = date.today() - timedelta(days=days_back)

    query = f"""
        SELECT
          CAST(sku AS STRING) AS sku,
          CAST(store AS STRING) AS store,
          CAST(location_id AS STRING) AS location_id,
          CAST(warehouse AS STRING) AS warehouse,
          CAST(brand AS STRING) AS brand,
          CAST(city AS STRING) AS city,
          CAST(zone AS STRING) AS zone,
          DATE(stock_date) AS stock_date,
          DATETIME(updated_at) AS updated_at,
          CAST(available_stock AS INT64) AS available_stock,
          COALESCE(CAST(reserved_stock AS INT64), 0) AS reserved_stock,
          COALESCE(CAST(safety_stock AS INT64), 0) AS safety_stock,
          COALESCE(CAST(stock_source AS STRING), 'D-1') AS stock_source,
          COALESCE(CAST(is_ecommerce_enabled AS BOOL), TRUE) AS is_ecommerce_enabled,
          COALESCE(CAST(risk_score AS FLOAT64), 0) AS risk_score,
          CAST(inventory_item_id AS STRING) AS inventory_item_id
        FROM `{stock_table}`
        WHERE CAST(sku AS STRING) IN UNNEST(@skus)
          AND DATE(stock_date) >= @since
          AND COALESCE(CAST(available_stock AS INT64), 0) > 0
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ArrayQueryParameter("skus", "STRING", list(skus)),
            bigquery.ScalarQueryParameter("since", "DATE", since.isoformat()),
        ]
    )
    return client.query(query, job_config=job_config).to_dataframe()


def validate_stock_with_shopify_api(stock_candidates: pd.DataFrame) -> tuple[dict[tuple[str, str], dict[str, object]], list[str]]:
    shop_domain = _get_secret("shopify.shop_domain")
    access_token = _get_secret("shopify.access_token")
    api_version = _get_secret("shopify.api_version", "2024-10")
    warnings: list[str] = []
    validations: dict[tuple[str, str], dict[str, object]] = {}

    if stock_candidates.empty:
        return validations, warnings
    if not shop_domain or not access_token:
        warnings.append("Shopify API no esta configurada en st.secrets; se usara solo BigQuery.")
        return validations, warnings

    required = {"location_id", "inventory_item_id", "sku"}
    if not required.issubset(stock_candidates.columns):
        warnings.append("No se encontro location_id/inventory_item_id en stock; Shopify no pudo validar stock actual.")
        return validations, warnings

    headers = {"X-Shopify-Access-Token": str(access_token), "Content-Type": "application/json"}
    unique_rows = stock_candidates.dropna(subset=["location_id", "inventory_item_id", "sku"]).drop_duplicates(
        subset=["location_id", "inventory_item_id", "sku"]
    )

    for _, row in unique_rows.iterrows():
        location_id = str(row["location_id"])
        inventory_item_id = str(row["inventory_item_id"])
        sku = str(row["sku"]).strip().lower()
        url = (
            f"https://{shop_domain}/admin/api/{api_version}/inventory_levels.json"
            f"?location_ids={location_id}&inventory_item_ids={inventory_item_id}"
        )
        key = (location_id.strip().lower(), sku)
        try:
            request = urllib.request.Request(url, headers=headers, method="GET")
            with urllib.request.urlopen(request, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
            levels = payload.get("inventory_levels", [])
            available = levels[0].get("available") if levels else None
            validations[key] = {"status": "Validado", "available_stock": available}
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            validations[key] = {"status": f"Error Shopify: {exc}", "available_stock": None}
            warnings.append(f"Shopify fallo para location {location_id}, SKU {row['sku']}: {exc}")

    return validations, warnings


def skus_from_orders(orders: pd.DataFrame) -> tuple[str, ...]:
    return _normalise_tuple(orders.get("sku", pd.Series(dtype=str)))
