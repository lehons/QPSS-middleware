"""
Maps parsed QuikPAK XML data to ShipStation V1 API order format.

V1 endpoint: POST /orders/createorder
Field names use camelCase. Has advancedOptions with customField1/2/3 and source.
orderKey enables upsert: if key exists, order is updated; otherwise created.

Items (SKU, description, qty) come from Sage 300 OEORDD via sage_client,
looked up by order number. These appear on ShipStation packing slips.
"""

import logging
from src.xml_parser import ShipmentHeader, ShipmentDetail

logger = logging.getLogger("qpss")


def build_order_number(header: ShipmentHeader) -> str:
    """Build the ShipStation order number: customercode_ShipmentID."""
    return f"{header.customer_code}_{header.shipment_id}"


def map_to_shipstation(
    header: ShipmentHeader,
    detail: ShipmentDetail,
    store_id: int = None,
    items: list = None,
) -> dict:
    """Map QuikPAK header+detail to a ShipStation V1 order dict.

    Args:
        header: Parsed HeaderIn XML.
        detail: Parsed DetailIn XML.
        store_id: ShipStation store ID (optional).
        items: List of OrderItem objects from Sage 300 (optional).
               If provided, these are included as ShipStation line items
               for packing slip printing.

    Returns the order object ready for POST /orders/createorder.
    """
    order_number = build_order_number(header)

    order = {
        "orderNumber": order_number,
        "orderKey": order_number,  # Same as orderNumber — enables upsert
        "orderStatus": "awaiting_shipment",
        "shipTo": _build_ship_to(header),
        "billTo": _build_ship_to(header),  # V1 requires billTo; use same as shipTo
        "packageCode": "package",  # Standard box — required for label creation
        "requestedShippingService": header.ship_via_code,  # Pass as-is
        "advancedOptions": _build_advanced_options(header, detail, store_id),
    }

    # Dates (convert YYYYMMDD to YYYY-MM-DDTHH:MM:SS)
    order_date = _format_datetime(header.order_date)
    if order_date:
        order["orderDate"] = order_date

    ship_date = _format_datetime(header.ship_date)
    if ship_date:
        order["shipDate"] = ship_date

    # Weight & dimensions from packages
    # Single package: use its weight and dimensions directly
    # Multi package: sum weights, use largest package dimensions
    if detail.packages:
        total_weight = sum(p.weight for p in detail.packages)
        if total_weight > 0:
            order["weight"] = {
                "value": total_weight,
                "units": "pounds",
            }

        # Use the largest package by volume for dimensions
        largest = max(
            detail.packages,
            key=lambda p: p.length * p.width * p.height,
        )
        if largest.length > 0 and largest.width > 0 and largest.height > 0:
            order["dimensions"] = {
                "length": largest.length,
                "width": largest.width,
                "height": largest.height,
                "units": "inches",
            }

    # Internal notes (shipping terms + carrier account + per-package breakdown)
    notes_parts = []
    if header.optional_text_009:
        notes_parts.append(f"Shipping terms: {header.optional_text_009}")
    if header.optional_text_010 and header.optional_text_010 != "0":
        notes_parts.append(f"Carrier account: {header.optional_text_010}")

    # For multi-package: include per-package weight and dimensions
    if len(detail.packages) > 1:
        notes_parts.append(f"Packages: {len(detail.packages)}")
        for p in detail.packages:
            notes_parts.append(
                f"Pkg {p.package_no}: {p.weight} lbs {p.length}x{p.width}x{p.height}"
            )

    if notes_parts:
        order["internalNotes"] = " | ".join(notes_parts)

    # Items from Sage 300 (for packing slips)
    if items:
        order["items"] = _build_items(items)

    return order


def _build_ship_to(header: ShipmentHeader) -> dict:
    """Build the shipTo address object from header fields."""
    ship_to = {
        "name": header.ship_name,
        "street1": header.ship_addr1,
        "city": header.ship_city,
        "state": header.ship_state,
        "postalCode": header.ship_zip,
        "country": header.ship_country,
    }

    # Optional fields — only include if populated
    if header.ship_addr2:
        ship_to["street2"] = header.ship_addr2
    if header.ship_addr3:
        ship_to["street3"] = header.ship_addr3
    if header.optional_text_001:
        ship_to["phone"] = header.optional_text_001
    if header.ship_email:
        ship_to["email"] = header.ship_email

    # Residential indicator: "0" -> False, "1" -> True
    ship_to["residential"] = header.is_residential == "1"

    return ship_to


def _build_advanced_options(
    header: ShipmentHeader,
    detail: ShipmentDetail,
    store_id: int = None,
) -> dict:
    """Build the advancedOptions object with custom fields and source."""
    options = {
        "source": header.customer_code,                # Order Source (e.g., "HO1001")
        "customField1": header.po_number,              # PO number
        "customField2": header.shipment_id,            # ShipmentID
        "customField3": detail.package_count_label,    # "Single Package" or "Multi Package"
    }

    if store_id is not None:
        options["storeId"] = store_id

    return options


def _build_items(items: list) -> list[dict]:
    """Build the ShipStation items array from Sage 300 OrderItem objects.

    ShipStation V1 items appear on packing slips and provide line-item detail.
    Each item maps to one line on the packing slip.
    """
    ss_items = []
    for item in items:
        ss_item = {
            "lineItemKey": str(item.line_number),
            "sku": item.item_number,
            "name": item.description,
            "quantity": int(item.qty_ordered),
        }
        if item.unit_price > 0:
            ss_item["unitPrice"] = round(item.unit_price, 2)
        ss_items.append(ss_item)
    return ss_items


def _format_datetime(date_str: str) -> str:
    """Convert YYYYMMDD to YYYY-MM-DDTHH:MM:SS, or return empty string."""
    if not date_str or len(date_str) != 8:
        return ""
    try:
        return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}T00:00:00"
    except (IndexError, ValueError):
        return ""
