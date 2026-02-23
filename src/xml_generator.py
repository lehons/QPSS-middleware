"""
Generate QuikPAK OUT XML files (HEADEROUT and DETAILOUT) from pending shipment data
merged with ShipStation shipment results.

Output format matches actual sample files:
- HEADEROUT: SmartlincOutHeader > OutQueueHeader
- DETAILOUT: SmartlincOutDetail > DetailLine (one per package)
- Empty fields use newline-padded format matching existing samples.
- File naming: HEADEROUT_SHIP*_YYYYMMDD_HHMMSS.XML (uppercase, no arch- prefix)
"""

import os
import logging
from datetime import datetime
from xml.etree.ElementTree import Element, SubElement, ElementTree, indent

logger = logging.getLogger("qpss")


def generate_out_files(
    pending: dict,
    shipment: dict,
    out_folder: str,
    ship_from: dict,
) -> tuple[str, str]:
    """Generate HEADEROUT and DETAILOUT XML files for a completed shipment.

    Args:
        pending: Dict loaded from the pending JSON file (original order data
            saved during Flow 1). Contains: shipment_id, order_number,
            ship_to, ship_via, is_cod, coll_type, packages, etc.
        shipment: ShipStation shipment dict from GET /shipments.
            Provides: trackingNumber, carrierCode, serviceCode, shipDate.
        out_folder: Path to QuikPAKOUT folder.
        ship_from: Dict with ship-from warehouse fields from config.

    Returns:
        Tuple of (header_path, detail_path) for the written files.
    """
    shipment_id = pending["shipment_id"]
    order_number = pending["order_number"]

    # Timestamp for filenames
    now = datetime.now()
    timestamp = now.strftime("%Y%m%d_%H%M%S")

    # Generate HEADEROUT
    header_xml = _build_header_out(
        shipment_id=shipment_id,
        order_number=order_number,
        pending=pending,
        shipment=shipment,
        ship_from=ship_from,
    )
    header_filename = f"HEADEROUT_{shipment_id}_{timestamp}.XML"
    header_path = os.path.join(out_folder, header_filename)

    # Generate DETAILOUT
    detail_xml = _build_detail_out(
        shipment_id=shipment_id,
        order_number=order_number,
        shipment=shipment,
        packages=pending.get("packages", []),
    )
    detail_filename = f"DETAILOUT_{shipment_id}_{timestamp}.XML"
    detail_path = os.path.join(out_folder, detail_filename)

    # Write files
    os.makedirs(out_folder, exist_ok=True)
    _write_xml(header_xml, header_path)
    _write_xml(detail_xml, detail_path)

    return header_path, detail_path


def _build_header_out(
    shipment_id: str,
    order_number: str,
    pending: dict,
    shipment: dict,
    ship_from: dict,
) -> Element:
    """Build the SmartlincOutHeader XML element tree."""
    root = Element("SmartlincOutHeader")
    hdr = SubElement(root, "OutQueueHeader")

    ship_to = pending.get("ship_to", {})

    # Core fields
    _add(hdr, "ShipmentID", shipment_id)
    _add(hdr, "P_ShipmentID", order_number)
    _add(hdr, "void", "N")
    _add(hdr, "errormessage", "")
    _add(hdr, "carriercode", shipment.get("carrierCode", ""))
    _add(hdr, "carrierservice", shipment.get("serviceCode", ""))

    # shipvia: the original requested shipping service from QuikPAK
    _add(hdr, "shipvia", pending.get("ship_via", ""))

    _add(hdr, "trackingNumber", shipment.get("trackingNumber", ""))

    # shipDate: convert from ISO to YYYYMMDD
    ship_date_raw = shipment.get("shipDate", "")
    _add(hdr, "shipDate", _to_yyyymmdd(ship_date_raw))

    # Ship-to address (from original order data)
    _add(hdr, "shiptoID", ship_to.get("company", ""))
    _add(hdr, "shipName", ship_to.get("name", ""))
    _add(hdr, "shipAddr1", ship_to.get("street1", ""))
    _add(hdr, "shipAddr2", ship_to.get("street2", ""))
    _add(hdr, "shipAddr3", ship_to.get("street3", ""))
    _add(hdr, "shipCity", ship_to.get("city", ""))
    _add(hdr, "shipState", ship_to.get("state", ""))
    _add(hdr, "shipCountry", ship_to.get("country", ""))
    _add(hdr, "shipzip", ship_to.get("postalCode", ""))
    _add(hdr, "shipContact", "")
    _add(hdr, "shipPhone", ship_to.get("phone", ""))
    _add(hdr, "shipEmail", ship_to.get("email", ""))

    # Flags (from original order data)
    residential = ship_to.get("residential", False)
    _add(hdr, "isCOD", pending.get("is_cod", "0"))
    _add(hdr, "isResidential", "1" if residential else "0")
    _add(hdr, "reference", "")
    _add(hdr, "colltype", pending.get("coll_type", "S"))

    # Costs (set to 0 as per design decision)
    _add(hdr, "shipperCost", "0.0000")
    _add(hdr, "actualCost", "")
    _add(hdr, "customerCharge", "")

    # Third party fields (empty)
    _add(hdr, "tpAccountno", "")
    _add(hdr, "tpName", "")
    _add(hdr, "tpAddr1", "")
    _add(hdr, "tpAddr2", "")
    _add(hdr, "tpAddr3", "")
    _add(hdr, "tpCity", "")
    _add(hdr, "tpState", "")
    _add(hdr, "tpZip", "")
    _add(hdr, "tpCountry", "")
    _add(hdr, "tpContact", "")
    _add(hdr, "tpPhone", "")

    # Ship-from fields (from warehouse config)
    _add(hdr, "SFACCOUNTNO", ship_from.get("account_no", ""))
    _add(hdr, "sfName", ship_from.get("name", ""))
    _add(hdr, "sfAddr1", ship_from.get("addr1", ""))
    _add(hdr, "sfAddr2", ship_from.get("addr2", ""))
    _add(hdr, "sfAddr3", ship_from.get("addr3", ""))
    _add(hdr, "sfAddr4", ship_from.get("addr4", ""))
    _add(hdr, "sfCity", ship_from.get("city", ""))
    _add(hdr, "sfState", ship_from.get("state", ""))
    _add(hdr, "sfZip", ship_from.get("zip", ""))
    _add(hdr, "sfCountry", ship_from.get("country", ""))
    _add(hdr, "sfContact", ship_from.get("contact", ""))
    _add(hdr, "sfPhone", ship_from.get("phone", ""))

    return root


def _build_detail_out(
    shipment_id: str,
    order_number: str,
    shipment: dict,
    packages: list[dict],
) -> Element:
    """Build the SmartlincOutDetail XML element tree.

    Uses original package data from the pending JSON.
    If packages list is empty, generates a single minimal DetailLine
    from shipment-level data (fallback for legacy orders without pending data).
    """
    root = Element("SmartlincOutDetail")
    tracking = shipment.get("trackingNumber", "")

    if packages:
        for pkg in packages:
            line = SubElement(root, "DetailLine")
            _add(line, "ShipmentID", shipment_id)
            _add(line, "P_ShipmentID", order_number)
            _add(line, "packageID", pkg.get("package_id", ""))
            _add(line, "packageno", str(pkg.get("package_no", "1")))
            _add(line, "weight", _fmt_decimal(pkg.get("weight", 0), 6))
            _add(line, "length", _fmt_decimal(pkg.get("length", 0), 6))
            _add(line, "width", _fmt_decimal(pkg.get("width", 0), 6))
            _add(line, "height", _fmt_decimal(pkg.get("height", 0), 6))
            _add(line, "declaredValue", _fmt_decimal(pkg.get("declared_value", 0), 4))
            _add(line, "codAmount", _fmt_decimal(pkg.get("cod_amount", 0), 4))
            _add(line, "units", pkg.get("units", "LB"))
            _add(line, "packageCost", "0.0")
            _add(line, "trackingNumber", tracking)
            _add(line, "comment", pkg.get("comment", ""))
    else:
        # Fallback: generate one package from shipment-level data
        line = SubElement(root, "DetailLine")
        _add(line, "ShipmentID", shipment_id)
        _add(line, "P_ShipmentID", order_number)
        _add(line, "packageID", "")
        _add(line, "packageno", "1")
        weight = shipment.get("weight", {})
        weight_val = weight.get("value", 0)
        weight_units = weight.get("units", "ounces")
        # Convert ounces to pounds if needed
        if weight_units == "ounces" and weight_val:
            weight_val = weight_val / 16.0
        _add(line, "weight", _fmt_decimal(weight_val, 6))
        dims = shipment.get("dimensions", {})
        _add(line, "length", _fmt_decimal(dims.get("length", 0), 6))
        _add(line, "width", _fmt_decimal(dims.get("width", 0), 6))
        _add(line, "height", _fmt_decimal(dims.get("height", 0), 6))
        _add(line, "declaredValue", "0.0000")
        _add(line, "codAmount", "0.0000")
        _add(line, "units", "LB")
        _add(line, "packageCost", "0.0")
        _add(line, "trackingNumber", tracking)
        _add(line, "comment", "")

    return root


def _add(parent: Element, tag: str, text: str) -> Element:
    """Add a child element. Empty strings get newline padding to match sample format."""
    el = SubElement(parent, tag)
    if text:
        el.text = text
    else:
        el.text = "\n        "  # Match sample whitespace for empty fields
    return el


def _to_yyyymmdd(iso_date: str) -> str:
    """Convert ISO date string to YYYYMMDD format.

    Handles formats like: 2026-02-18T11:34:18.000
    Returns empty string if parsing fails.
    """
    if not iso_date:
        return ""
    try:
        # Take just the date part
        date_part = iso_date[:10]
        return date_part.replace("-", "")
    except (IndexError, ValueError):
        return ""


def _fmt_decimal(value, decimal_places: int) -> str:
    """Format a number to a fixed number of decimal places."""
    try:
        return f"{float(value):.{decimal_places}f}"
    except (ValueError, TypeError):
        return f"{'0'}.{'0' * decimal_places}"


def _write_xml(root: Element, filepath: str) -> None:
    """Write an ElementTree to file with XML declaration and indentation."""
    indent(root, space="    ")
    tree = ElementTree(root)
    with open(filepath, "wb") as f:
        tree.write(f, encoding="UTF-8", xml_declaration=True)
    logger.debug(f"Wrote: {filepath}")
