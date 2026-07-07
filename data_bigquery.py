from __future__ import annotations

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
def get_bigquery_client():
    try:
        from google.cloud import bigquery
    except ImportError as exc:
        raise RuntimeError("Falta instalar google-cloud-bigquery.") from exc

    project_id = _get_secret("bigquery.project_id")
    return bigquery.Client(project=project_id) if project_id else bigquery.Client()


def _table_secret(name: str) -> str:
    table = _get_secret(f"bigquery.{name}")
    if not table:
        raise RuntimeError(f"Configura st.secrets['bigquery']['{name}'] antes de consultar BigQuery.")
    return str(table)


@st.cache_data(ttl=900, show_spinner=False)
def query_stock_from_bigquery(skus: tuple[str, ...], brands: tuple[str, ...] = (), days_back: int = 2) -> pd.DataFrame:
    if not skus:
        return pd.DataFrame()

    from google.cloud import bigquery

    client = get_bigquery_client()
    stock_table = _table_secret("stock_table")
    since = date.today() - timedelta(days=days_back)

    query = f"""
        SELECT
          CAST(sku AS STRING) AS sku,
          CAST(store AS STRING) AS store,
          CAST(warehouse AS STRING) AS warehouse,
          CAST(brand AS STRING) AS brand,
          DATE(stock_date) AS stock_date,
          CAST(available_stock AS INT64) AS available_stock,
          COALESCE(CAST(stock_source AS STRING), 'D-1') AS stock_source,
          COALESCE(CAST(is_enabled AS BOOL), TRUE) AS is_enabled,
          COALESCE(CAST(is_priority AS BOOL), FALSE) AS is_priority,
          COALESCE(CAST(logistic_priority AS FLOAT64), 5) AS logistic_priority
        FROM `{stock_table}`
        WHERE CAST(sku AS STRING) IN UNNEST(@skus)
          AND DATE(stock_date) >= @since
          AND (@brand_count = 0 OR CAST(brand AS STRING) IN UNNEST(@brands))
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ArrayQueryParameter("skus", "STRING", list(skus)),
            bigquery.ArrayQueryParameter("brands", "STRING", list(brands)),
            bigquery.ScalarQueryParameter("brand_count", "INT64", len(brands)),
            bigquery.ScalarQueryParameter("since", "DATE", since.isoformat()),
        ]
    )
    return client.query(query, job_config=job_config).to_dataframe()


@st.cache_data(ttl=900, show_spinner=False)
def query_break_orders_from_bigquery(days_back: int = 7) -> pd.DataFrame:
    from google.cloud import bigquery

    client = get_bigquery_client()
    orders_table = _table_secret("orders_table")
    since = date.today() - timedelta(days=days_back)

    query = f"""
        SELECT
          CAST(order_number AS STRING) AS order_number,
          CAST(sku AS STRING) AS sku,
          CAST(model_color AS STRING) AS model_color,
          CAST(size AS STRING) AS size,
          CAST(quantity AS INT64) AS quantity,
          CAST(origin_store AS STRING) AS origin_store,
          CAST(brand AS STRING) AS brand,
          DATETIME(order_date) AS order_date,
          CAST(order_status AS STRING) AS order_status,
          CAST(break_reason AS STRING) AS break_reason,
          CAST(price AS FLOAT64) AS price
        FROM `{orders_table}`
        WHERE DATE(order_date) >= @since
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("since", "DATE", since.isoformat())]
    )
    return client.query(query, job_config=job_config).to_dataframe()


def tuple_from_series(values: Iterable[object]) -> tuple[str, ...]:
    return tuple(sorted({str(value).strip() for value in values if pd.notna(value) and str(value).strip()}))
