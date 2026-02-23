"""
XML parser for QuikPAK HeaderIn and DetailIn files.

HeaderIn: flat XML under <ProcessWeaverInHeader>
DetailIn: <ProcessWeaverInDetail> containing one or more <InQueueDetail> elements
"""

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PackageDetail:
    """One package from a DetailIn <InQueueDetail> element."""
    shipment_id: str = ""
    cod_amount: float = 0.0
    comment: str = ""
    declared_value: float = 0.0
    height: float = 0.0
    length: float = 0.0
    package_id: str = ""
    package_no: int = 1
    units: str = "LB"
    weight: float = 0.0
    width: float = 0.0


@dataclass
class ShipmentHeader:
    """Parsed HeaderIn file."""
    shipment_id: str = ""
    bol_no: str = ""
    carrier_code: str = ""
    carrier_service: str = ""
    coll_type: str = ""
    is_cod: str = "0"
    location: str = ""
    is_residential: str = "0"
    order_no: str = ""
    order_date: str = ""
    po_number: str = ""
    ship_addr1: str = ""
    ship_addr2: str = ""
    ship_addr3: str = ""
    ship_city: str = ""
    ship_contact: str = ""
    ship_country: str = ""
    ship_date: str = ""
    ship_email: str = ""
    ship_name: str = ""
    ship_phone: str = ""
    ship_state: str = ""
    ship_via_code: str = ""
    ship_zip: str = ""
    void: str = "N"
    pk_number: str = ""
    customer_code: str = ""
    optional_text_001: str = ""
    optional_text_009: str = ""
    optional_text_010: str = ""
    org_id: str = ""
    tracking_number: str = ""
    rate_only: str = "N"


@dataclass
class ShipmentDetail:
    """Parsed DetailIn file (may contain multiple packages)."""
    packages: list = field(default_factory=list)

    @property
    def package_count(self) -> int:
        return len(self.packages)

    @property
    def package_count_label(self) -> str:
        return "Single Package" if self.package_count <= 1 else "Multi Package"


# Mapping from XML element names to ShipmentHeader field names
_HEADER_FIELD_MAP = {
    "ShipmentID": "shipment_id",
    "BOLNo": "bol_no",
    "carriercode": "carrier_code",
    "carrierservice": "carrier_service",
    "colltype": "coll_type",
    "iscod": "is_cod",
    "location": "location",
    "isresidential": "is_residential",
    "orderno": "order_no",
    "order_date": "order_date",
    "ponumber": "po_number",
    "shipaddr1": "ship_addr1",
    "shipaddr2": "ship_addr2",
    "shipaddr3": "ship_addr3",
    "shipcity": "ship_city",
    "shipcontact": "ship_contact",
    "shipcountry": "ship_country",
    "shipdate": "ship_date",
    "shipemail": "ship_email",
    "shipname": "ship_name",
    "shipphone": "ship_phone",
    "shipstate": "ship_state",
    "shipviacode": "ship_via_code",
    "shipzip": "ship_zip",
    "void": "void",
    "pknumber": "pk_number",
    "customercode": "customer_code",
    "optionaltext001": "optional_text_001",
    "optionaltext009": "optional_text_009",
    "optionaltext010": "optional_text_010",
    "OrgID": "org_id",
    "trackingNumber": "tracking_number",
    "RateOnly": "rate_only",
}


def parse_header(file_path: str) -> ShipmentHeader:
    """Parse a HeaderIn XML file into a ShipmentHeader object."""
    tree = ET.parse(file_path)
    root = tree.getroot()

    header = ShipmentHeader()
    for element in root:
        tag = element.tag
        text = (element.text or "").strip()
        field_name = _HEADER_FIELD_MAP.get(tag)
        if field_name:
            setattr(header, field_name, text)

    return header


def parse_detail(file_path: str) -> ShipmentDetail:
    """Parse a DetailIn XML file into a ShipmentDetail object."""
    tree = ET.parse(file_path)
    root = tree.getroot()

    detail = ShipmentDetail()

    for queue_detail in root.findall("InQueueDetail"):
        pkg = PackageDetail()
        pkg.shipment_id = _get_text(queue_detail, "ShipmentID")
        pkg.cod_amount = _get_float(queue_detail, "codAmount")
        pkg.comment = _get_text(queue_detail, "comment")
        pkg.declared_value = _get_float(queue_detail, "declaredValue")
        pkg.height = _get_float(queue_detail, "height")
        pkg.length = _get_float(queue_detail, "length")
        pkg.package_id = _get_text(queue_detail, "packageID")
        pkg.package_no = int(_get_float(queue_detail, "packageno") or 1)
        pkg.units = _get_text(queue_detail, "units") or "LB"
        pkg.weight = _get_float(queue_detail, "weight")
        pkg.width = _get_float(queue_detail, "width")
        detail.packages.append(pkg)

    return detail


def _get_text(parent: ET.Element, tag: str) -> str:
    """Get text content of a child element, or empty string if missing/empty."""
    el = parent.find(tag)
    if el is None or el.text is None:
        return ""
    return el.text.strip()


def _get_float(parent: ET.Element, tag: str) -> float:
    """Get float value of a child element, or 0.0 if missing/empty."""
    text = _get_text(parent, tag)
    if not text:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0
