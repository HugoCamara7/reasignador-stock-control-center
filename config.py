from __future__ import annotations

RECOMMENDATION_STATES = {
    "Reasignable": "#16a34a",
    "Reasignable parcial": "#f59e0b",
    "No reasignable": "#dc2626",
    "Requiere revisión": "#eab308",
    "Riesgo por stock D-1": "#f97316",
}

DEFAULT_STOCK_SAFETY = 1
DEFAULT_MAX_RECOMMENDATIONS_PER_STORE_SKU = 9999

ORDER_COLUMNS = {
    "order_number": "Número de pedido",
    "sku": "SKU",
    "model_color": "Código modelo color",
    "size": "Talla",
    "quantity": "Cantidad",
    "origin_store": "Tienda original",
    "brand": "Marca",
    "order_date": "Fecha de pedido",
    "order_status": "Estado del pedido",
    "break_reason": "Motivo del quiebre",
    "price": "Precio",
}

STOCK_COLUMNS = {
    "sku": "SKU",
    "store": "Tienda",
    "warehouse": "Bodega",
    "brand": "Marca",
    "stock_date": "Fecha de stock",
    "available_stock": "Stock disponible",
    "stock_source": "Tipo stock",
    "is_enabled": "Tienda habilitada",
    "is_priority": "Prioritaria ecommerce",
    "logistic_priority": "Prioridad logística",
}

EXPORT_COLUMNS = [
    "Número de pedido",
    "SKU",
    "Código modelo color",
    "Talla",
    "Cantidad",
    "Tienda actual/origen",
    "Tienda recomendada",
    "Stock disponible",
    "Stock restante después de reasignación",
    "Estado",
    "Motivo",
    "Score",
    "Fecha de stock",
    "Acción sugerida",
]

COLUMN_ALIASES = {
    "order_number": [
        "numero de pedido",
        "número de pedido",
        "pedido",
        "order",
        "order_number",
        "name",
    ],
    "sku": ["sku", "variant sku", "codigo sku", "código sku"],
    "model_color": [
        "codigo modelo color",
        "código modelo color",
        "modelo color",
        "cod_modelo_color",
        "model_color",
    ],
    "size": ["talla", "size", "variant option2", "option2"],
    "quantity": ["cantidad", "qty", "quantity", "unidades"],
    "origin_store": ["tienda original", "tienda origen", "origen", "store origin"],
    "brand": ["marca", "brand", "vendor"],
    "order_date": ["fecha de pedido", "fecha pedido", "created at", "order_date"],
    "order_status": ["estado del pedido", "estado", "status", "order_status"],
    "break_reason": ["motivo del quiebre", "motivo", "tipo de quiebre", "break_reason"],
    "price": ["precio", "price", "monto", "venta"],
    "store": ["tienda", "store", "sucursal"],
    "warehouse": ["bodega", "warehouse", "almacen", "almacén"],
    "stock_date": ["fecha de stock", "fecha cierre", "stock_date", "date"],
    "available_stock": ["stock disponible", "stock", "available_stock", "disponible"],
    "stock_source": ["tipo stock", "stock source", "stock_source", "fuente stock"],
    "is_enabled": ["tienda habilitada", "habilitada", "enabled", "is_enabled"],
    "is_priority": ["prioritaria ecommerce", "prioridad ecommerce", "is_priority"],
    "logistic_priority": ["prioridad logística", "prioridad logistica", "logistic_priority"],
}
