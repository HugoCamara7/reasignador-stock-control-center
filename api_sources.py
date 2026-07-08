from __future__ import annotations

import json
import urllib.error
import urllib.request
import urllib.parse
from datetime import date, datetime, timedelta, timezone
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

    project_id = _get_secret("bigquery.job_project_id") or _get_secret("bigquery.project_id")
    service_account_info = _get_secret("bigquery.service_account_info") or _get_secret("gcp_service_account")

    if service_account_info:
        credentials = service_account.Credentials.from_service_account_info(dict(service_account_info))
        return bigquery.Client(project=project_id or credentials.project_id, credentials=credentials)

    raise RuntimeError(
        "BigQuery no tiene credenciales configuradas. Agrega una cuenta de servicio en "
        "st.secrets['gcp_service_account'] o st.secrets['bigquery']['service_account_info']. Sin eso, Google intenta "
        "usar metadata.google.internal, que solo existe dentro de Google Cloud."
    )


def _table_secret(name: str) -> str:
    table = _get_secret(f"bigquery.{name}")
    if not table and name == "stock_table":
        table = _get_secret("bigquery.table")
    if not table:
        expected = "table o stock_table" if name == "stock_table" else name
        raise RuntimeError(f"Configura st.secrets['bigquery']['{expected}'] con la tabla correspondiente.")
    return str(table)


def _normalise_tuple(values: Iterable[object]) -> tuple[str, ...]:
    return tuple(sorted({str(value).strip() for value in values if pd.notna(value) and str(value).strip()}))


def _site_key(value: str | None) -> str:
    text = (value or "columbia").strip().lower()
    return text.replace(" ", "_").replace("-", "_")


def available_shopify_sites() -> list[str]:
    sites = _get_secret("shopify_sites", {})
    if sites:
        return sorted([str(key) for key in dict(sites).keys()])
    if _get_secret("shopify.shop_domain"):
        return ["shopify"]
    return ["columbia"]


def _shopify_secret(name: str, default=None, site_key: str | None = None):
    site = _site_key(site_key)
    value = _get_secret(f"shopify_sites.{site}.{name}")
    if value is not None:
        return value
    if name == "access_token":
        value = _get_secret(f"shopify_sites.{site}.admin_access_token")
        if value is not None:
            return value
    return _get_secret(f"shopify.{name}", default)


def _shopify_request(path: str, site_key: str | None = None) -> dict[str, object]:
    shop_domain = _shopify_secret("shop_domain", site_key=site_key)
    access_token = _shopify_secret("access_token", site_key=site_key)
    api_version = _shopify_secret("api_version", "2024-10", site_key=site_key)
    if not shop_domain or not access_token:
        site = _site_key(site_key)
        raise RuntimeError(
            f"Configura st.secrets['shopify_sites']['{site}']['shop_domain'] y "
            f"st.secrets['shopify_sites']['{site}']['admin_access_token']."
        )

    url = f"https://{shop_domain}/admin/api/{api_version}/{path}"
    request = urllib.request.Request(
        url,
        headers={"X-Shopify-Access-Token": str(access_token), "Content-Type": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
            link_header = response.headers.get("Link", "")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Shopify API respondio {exc.code}: {body[:300]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Shopify API no respondio: {exc}") from exc

    payload["_next_page_info"] = _extract_next_page_info(link_header)
    return payload


def _extract_next_page_info(link_header: str) -> str | None:
    if not link_header:
        return None
    for part in link_header.split(","):
        if 'rel="next"' not in part:
            continue
        start = part.find("page_info=")
        if start == -1:
            continue
        value = part[start + len("page_info=") :]
        value = value.split("&")[0].split(">")[0].strip()
        return value or None
    return None


def _keyword_list(secret_name: str, defaults: list[str], site_key: str | None = None) -> list[str]:
    configured = _shopify_secret(secret_name, site_key=site_key)
    if isinstance(configured, str):
        return [item.strip().lower() for item in configured.split(",") if item.strip()]
    if configured:
        return [str(item).strip().lower() for item in configured if str(item).strip()]
    return defaults


def _contains_any(text: object, keywords: list[str]) -> bool:
    value = "" if text is None else str(text).lower()
    return any(keyword in value for keyword in keywords)


def _sku_model_color(sku: object) -> tuple[str | None, str | None]:
    text = "" if sku is None else str(sku).strip()
    if not text:
        return None, None
    parts = text.split("-")
    if len(parts) >= 3:
        return "-".join(parts[:-1]), parts[-1]
    return text, None


def _first(value: object, default=None):
    return value if value not in (None, "") else default


@st.cache_data(ttl=300, show_spinner=False)
def fetch_broken_orders_from_shopify(
    days_back: int,
    brands: tuple[str, ...] = (),
    include_unfulfilled_risk: bool = True,
    site_key: str | None = "columbia",
) -> pd.DataFrame:
    created_at_min = (datetime.now(timezone.utc) - timedelta(days=days_back)).isoformat()
    break_keywords = _keyword_list(
        "break_keywords",
        ["sin stock", "quiebre", "stockout", "falta stock", "pendiente stock", "terminado", "no stock"],
        site_key=site_key,
    )
    tag_keywords = _keyword_list("break_tags", ["sin stock", "quiebre", "stockout", "falta stock"], site_key=site_key)
    brand_filter = {brand.strip().lower() for brand in brands if brand.strip()}

    rows: list[dict[str, object]] = []
    page_info = None
    pages = 0
    while True:
        if page_info:
            path = "orders.json?" + urllib.parse.urlencode({"limit": 250, "page_info": page_info})
        else:
            path = "orders.json?" + urllib.parse.urlencode(
                {"status": "any", "limit": 250, "created_at_min": created_at_min}
            )
        payload = _shopify_request(path, site_key=site_key)
        pages += 1
        for order in payload.get("orders", []):
            fulfillment_locations = _fulfillment_order_locations(order.get("id"), site_key=site_key)
            order_tags = str(order.get("tags", ""))
            order_note = str(order.get("note", ""))
            order_cancel_reason = str(order.get("cancel_reason", ""))
            order_break_signal = (
                _contains_any(order_tags, tag_keywords)
                or _contains_any(order_note, break_keywords)
                or _contains_any(order_cancel_reason, break_keywords)
                or _contains_any(order.get("fulfillment_status"), break_keywords)
            )

            origin_location = _order_origin_location(order)
            for item in order.get("line_items", []):
                sku = str(item.get("sku") or "").strip()
                if not sku:
                    continue
                brand = str(item.get("vendor") or order.get("source_name") or "").strip()
                if brand_filter and brand.lower() not in brand_filter:
                    continue
                item_signal_text = " ".join(
                    [
                        str(item.get("fulfillment_status") or ""),
                        str(item.get("title") or ""),
                        str(item.get("variant_title") or ""),
                        str(item.get("properties") or ""),
                    ]
                )
                line_break_signal = _contains_any(item_signal_text, break_keywords)
                unfulfilled_qty = int(item.get("fulfillable_quantity") or item.get("quantity") or 0)
                is_unfulfilled_risk = include_unfulfilled_risk and unfulfilled_qty > 0 and order.get("fulfillment_status") != "fulfilled"
                if not (order_break_signal or line_break_signal or is_unfulfilled_risk):
                    continue

                model_color, parsed_size = _sku_model_color(sku)
                assigned_location = fulfillment_locations.get(str(item.get("id"))) or _order_origin_location(order)
                rows.append(
                    {
                        "order_number": order.get("name") or order.get("order_number"),
                        "order_id": str(order.get("id")),
                        "order_date": order.get("created_at"),
                        "brand": brand,
                        "sku": sku,
                        "model_color": model_color,
                        "size": _first(item.get("variant_title"), parsed_size),
                        "quantity": unfulfilled_qty or int(item.get("quantity") or 1),
                        "origin_store": assigned_location,
                        "origin_location_id": item.get("origin_location", {}).get("id") if isinstance(item.get("origin_location"), dict) else None,
                        "city": _shipping_city(order),
                        "order_status": order.get("fulfillment_status") or order.get("financial_status"),
                        "break_reason": _break_reason(order_break_signal, line_break_signal, is_unfulfilled_risk, order_tags),
                    }
                )

        page_info = payload.get("_next_page_info")
        if not page_info or pages >= 12:
            break

    return pd.DataFrame(rows)


def _order_origin_location(order: dict[str, object]) -> str:
    source = order.get("source_name")
    if source:
        return str(source)
    location = order.get("location_id")
    if location:
        return str(location)
    return "Shopify"


def _fulfillment_order_locations(order_id: object, site_key: str | None = None) -> dict[str, str]:
    if not order_id or not bool(_shopify_secret("fetch_fulfillment_orders", True, site_key=site_key)):
        return {}
    try:
        payload = _shopify_request(f"orders/{order_id}/fulfillment_orders.json", site_key=site_key)
    except RuntimeError:
        return {}
    locations: dict[str, str] = {}
    for fulfillment_order in payload.get("fulfillment_orders", []):
        assigned = fulfillment_order.get("assigned_location") or {}
        assigned_name = assigned.get("name") or assigned.get("location_id")
        for line_item in fulfillment_order.get("line_items", []):
            shopify_line_item_id = line_item.get("line_item_id")
            if shopify_line_item_id and assigned_name:
                locations[str(shopify_line_item_id)] = str(assigned_name)
    return locations


def _shipping_city(order: dict[str, object]) -> str | None:
    address = order.get("shipping_address") or {}
    if isinstance(address, dict):
        return address.get("city")
    return None


def _break_reason(order_signal: bool, line_signal: bool, unfulfilled_risk: bool, tags: str) -> str:
    if order_signal:
        return f"Señal de quiebre en orden/tags: {tags}".strip()
    if line_signal:
        return "Señal de quiebre en linea Shopify"
    if unfulfilled_risk:
        return "Pedido no preparado/pendiente con unidades por cumplir"
    return "Requiere revision"


@st.cache_data(ttl=600, show_spinner=False)
def fetch_available_stock_from_bigquery(skus: tuple[str, ...], days_back: int = 2) -> pd.DataFrame:
    if not skus:
        return pd.DataFrame()
    if _get_secret("bigquery.enabled", True) is False:
        raise RuntimeError("BigQuery esta deshabilitado en secrets: [bigquery] enabled = false.")

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
    return client.query(query, job_config=job_config, location=_get_secret("bigquery.location")).to_dataframe()


def validate_stock_with_shopify_api(
    stock_candidates: pd.DataFrame,
    site_key: str | None = "columbia",
) -> tuple[dict[tuple[str, str], dict[str, object]], list[str]]:
    shop_domain = _shopify_secret("shop_domain", site_key=site_key)
    access_token = _shopify_secret("access_token", site_key=site_key)
    api_version = _shopify_secret("api_version", "2024-10", site_key=site_key)
    warnings: list[str] = []
    validations: dict[tuple[str, str], dict[str, object]] = {}

    if stock_candidates.empty:
        return validations, warnings
    if not shop_domain or not access_token:
        warnings.append(f"Shopify API no esta configurada para {_site_key(site_key)}; se usara solo BigQuery.")
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
