"""
Generate test XML file pairs (HeaderIn + DetailIn) for Flow 1 testing.

Scans the QuikPAKIN folder (including Processed and Error subfolders) to
auto-increment the ShipmentID.  Writes the new pair directly into QuikPAKIN
so it will be picked up by the next Flow 1 run.

Usage:
    python generate_test.py                          # use defaults
    python generate_test.py --orderno ORD0469657     # override order number
    python generate_test.py --shipvia FEDEXG         # override carrier
    python generate_test.py --country CA --state QC  # ship to Canada
    python generate_test.py --help                   # show all options
"""

import argparse
import os
import re
import sys
from datetime import datetime


# ── Defaults ───────────────────────────────────────────────────────

DEFAULTS = {
    "orderno":      "ORD0469657",
    "shipviacode":  "UPS",
    "location":     "CAN",
    "customercode": "HO1002",
    "comment":      "BKGLKBL:Keyed Deadbolt, Black;BKGLKW:Keyed Deadbolt, White;",
    # Ship-to (US address)
    "shipname":     "John Smith",
    "shipaddr1":    "100 Main Street",
    "shipaddr2":    "",
    "shipaddr3":    "",
    "shipcity":     "Buffalo",
    "shipstate":    "NY",
    "shipcountry":  "US",
    "shipzip":      "14201",
    "shipemail":    "jsmith@example.com",
    "shipphone":    "7165551234",
    "shiptoID":     "",
    # Package
    "weight":       "5.2500",
    "length":       "18.0000",
    "width":        "12.0000",
    "height":       "6.0000",
    "units":        "LB",
    "declaredValue": "0.000",
    "codAmount":    "0.000",
    # Other header fields
    "ponumber":     "TEST-PO-001",
    "colltype":     "S",
    "iscod":        "0",
    "isresidential": "1",
    "void":         "N",
    "rateonly":     "N",
    "orgid":        "ISIDAT",
}


# ── Auto-increment ────────────────────────────────────────────────

def _find_next_test_number(quikpak_in: str) -> int:
    """Scan QuikPAKIN (and Processed/Error) to find the highest TEST##### number."""
    pattern = re.compile(r"TEST(\d+)", re.IGNORECASE)
    highest = 0

    # Check the IN folder and its subdirectories
    for dirpath, _dirs, files in os.walk(quikpak_in):
        for fname in files:
            m = pattern.search(fname)
            if m:
                num = int(m.group(1))
                if num > highest:
                    highest = num

    return highest + 1


# ── XML templates ─────────────────────────────────────────────────

HEADER_TEMPLATE = """\
<?xml version="1.0" standalone="yes"?>
<ProcessWeaverInHeader>
<ShipmentID>{shipment_id}</ShipmentID>
<BOLNo>{bolno}</BOLNo>
<carriercode/>
<carrierservice/>
<colltype>{colltype}</colltype>
<errortext/>
<iscod>{iscod}</iscod>
<location>{location}</location>
<isresidential>{isresidential}</isresidential>
<orderno>{orderno}</orderno>
<order_date>{order_date}</order_date>
<ponumber>{ponumber}</ponumber>
<reference/>
<sfaccountno/>
<sfaddr1/>
<sfaddr2/>
<sfaddr3/>
<sfaddr4/>
<sfcity/>
<sfcontact/>
<sfcountry/>
<sfname/>
<sfphone/>
<sfstate/>
<sfzip/>
<shipaddr1>{shipaddr1}</shipaddr1>
<shipaddr2>{shipaddr2}</shipaddr2>
<shipaddr3>{shipaddr3}</shipaddr3>
<shipcity>{shipcity}</shipcity>
<shipcontact/>
<shipcountry>{shipcountry}</shipcountry>
<shipdate>{shipdate}</shipdate>
<shipemail>{shipemail}</shipemail>
<shipname>{shipname}</shipname>
<shipphone/>
<shipstate>{shipstate}</shipstate>
<shiptoID>{shiptoID}</shiptoID>
<shipviacode>{shipviacode}</shipviacode>
<shipzip>{shipzip}</shipzip>
<ship_comments/>
<tpaccountno/>
<tpaddr1/>
<tpaddr2/>
<tpaddr3/>
<tpaddr4/>
<tpcity/>
<tpcontact/>
<tpcountry/>
<tpname/>
<tpphone/>
<tpstate/>
<tpzip/>
<void>{void}</void>
<pknumber>{pknumber}</pknumber>
<customercode>{customercode}</customercode>
<optionaltext001>{shipphone_opt}</optionaltext001>
<optionaltext002/>
<optionaltext003/>
<optionaltext004/>
<optionaltext005/>
<optionaltext006/>
<optionaltext007/>
<optionaltext008/>
<optionaltext009/>
<optionaltext010/>
<optionaldate001>{optdate}</optionaldate001>
<optionaldate002>{optdate}</optionaldate002>
<optionalnumber001/>
<optionalnumber002/>
<OrgID>{orgid}</OrgID>
<trackingNumber/>
<RateOnly>{rateonly}</RateOnly>
</ProcessWeaverInHeader>
"""

DETAIL_TEMPLATE = """\
<?xml version="1.0" standalone="yes"?>
<ProcessWeaverInDetail>
<InQueueDetail>
<ShipmentID>{shipment_id}</ShipmentID>
<codAmount>{codAmount}</codAmount>
<comment>{comment}</comment>
<declaredValue>{declaredValue}</declaredValue>
<height>{height}</height>
<length>{length}</length>
<packageID>{packageID}</packageID>
<packageno>1</packageno>
<units>{units}</units>
<weight>{weight}</weight>
<width>{width}</width>
<NMFCCode/>
<FreightClass/>
<Hazardous>0</Hazardous>
</InQueueDetail>
</ProcessWeaverInDetail>
"""


# ── Main ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Generate a test XML pair for Flow 1 (QuikPAK -> ShipStation)."
    )
    parser.add_argument("--orderno",      default=DEFAULTS["orderno"],
                        help=f"Sage 300 order number (default: {DEFAULTS['orderno']})")
    parser.add_argument("--shipvia",      default=DEFAULTS["shipviacode"],
                        help=f"Ship-via code (default: {DEFAULTS['shipviacode']})")
    parser.add_argument("--location",     default=DEFAULTS["location"],
                        help=f"Location code (default: {DEFAULTS['location']})")
    parser.add_argument("--customer",     default=DEFAULTS["customercode"],
                        help=f"Customer code (default: {DEFAULTS['customercode']})")
    parser.add_argument("--comment",      default=DEFAULTS["comment"],
                        help="Package comment line")
    parser.add_argument("--name",         default=DEFAULTS["shipname"],
                        help=f"Ship-to name (default: {DEFAULTS['shipname']})")
    parser.add_argument("--addr1",        default=DEFAULTS["shipaddr1"],
                        help=f"Ship-to address line 1 (default: {DEFAULTS['shipaddr1']})")
    parser.add_argument("--addr2",        default=DEFAULTS["shipaddr2"],
                        help="Ship-to address line 2")
    parser.add_argument("--city",         default=DEFAULTS["shipcity"],
                        help=f"Ship-to city (default: {DEFAULTS['shipcity']})")
    parser.add_argument("--state",        default=DEFAULTS["shipstate"],
                        help=f"Ship-to state (default: {DEFAULTS['shipstate']})")
    parser.add_argument("--country",      default=DEFAULTS["shipcountry"],
                        help=f"Ship-to country (default: {DEFAULTS['shipcountry']})")
    parser.add_argument("--zip",          default=DEFAULTS["shipzip"],
                        help=f"Ship-to zip (default: {DEFAULTS['shipzip']})")
    parser.add_argument("--email",        default=DEFAULTS["shipemail"],
                        help=f"Ship-to email (default: {DEFAULTS['shipemail']})")
    parser.add_argument("--phone",        default=DEFAULTS["shipphone"],
                        help=f"Ship-to phone (default: {DEFAULTS['shipphone']})")
    parser.add_argument("--weight",       default=DEFAULTS["weight"],
                        help=f"Package weight (default: {DEFAULTS['weight']})")
    parser.add_argument("--length",       default=DEFAULTS["length"],
                        help=f"Package length (default: {DEFAULTS['length']})")
    parser.add_argument("--width",        default=DEFAULTS["width"],
                        help=f"Package width (default: {DEFAULTS['width']})")
    parser.add_argument("--height",       default=DEFAULTS["height"],
                        help=f"Package height (default: {DEFAULTS['height']})")
    parser.add_argument("--ponumber",     default=DEFAULTS["ponumber"],
                        help=f"PO number (default: {DEFAULTS['ponumber']})")
    parser.add_argument("--residential",  default=DEFAULTS["isresidential"],
                        choices=["0", "1"],
                        help=f"Is residential (default: {DEFAULTS['isresidential']})")
    parser.add_argument("--void",         default=DEFAULTS["void"],
                        choices=["Y", "N"],
                        help=f"Void flag (default: {DEFAULTS['void']})")
    parser.add_argument("--rateonly",     default=DEFAULTS["rateonly"],
                        choices=["Y", "N"],
                        help=f"RateOnly flag (default: {DEFAULTS['rateonly']})")
    parser.add_argument("--config",       default=None,
                        help="Path to config.ini (to locate QuikPAKIN folder)")

    args = parser.parse_args()

    # Locate QuikPAKIN folder
    script_dir = os.path.dirname(os.path.abspath(__file__))

    if args.config:
        import configparser
        config = configparser.ConfigParser()
        config.read(args.config, encoding="utf-8")
        quikpak_in = config.get("paths", "quikpak_in")
    else:
        # Try config.ini in script dir, fall back to default location
        config_path = os.path.join(script_dir, "config.ini")
        if os.path.exists(config_path):
            import configparser
            config = configparser.ConfigParser()
            config.read(config_path, encoding="utf-8")
            quikpak_in = config.get("paths", "quikpak_in")
        else:
            quikpak_in = os.path.join(script_dir, "QuikPAK", "QuikPAKIN")

    if not os.path.isdir(quikpak_in):
        print(f"ERROR: QuikPAKIN folder not found: {quikpak_in}")
        sys.exit(1)

    # Auto-increment ShipmentID
    next_num = _find_next_test_number(quikpak_in)
    shipment_id = f"TEST{next_num:05d}"

    now = datetime.now()
    timestamp = now.strftime("%Y%m%d-%H%M%S")
    date_short = now.strftime("%Y%m%d")

    # Build values
    bolno = f"00569470{next_num:010d}"
    pknumber = f"PK{next_num:010d}"
    packageID = f"0000056947{next_num:010d}"

    vals = {
        "shipment_id":  shipment_id,
        "bolno":        bolno,
        "colltype":     DEFAULTS["colltype"],
        "iscod":        DEFAULTS["iscod"],
        "location":     args.location,
        "isresidential": args.residential,
        "orderno":      args.orderno,
        "order_date":   date_short,
        "ponumber":     args.ponumber,
        "shipaddr1":    args.addr1,
        "shipaddr2":    args.addr2,
        "shipaddr3":    "",
        "shipcity":     args.city,
        "shipcountry":  args.country,
        "shipdate":     date_short,
        "shipemail":    args.email,
        "shipname":     args.name,
        "shipstate":    args.state,
        "shiptoID":     "",
        "shipviacode":  args.shipvia,
        "shipzip":      args.zip,
        "void":         args.void,
        "pknumber":     pknumber,
        "customercode": args.customer,
        "shipphone_opt": args.phone,
        "optdate":      date_short,
        "orgid":        DEFAULTS["orgid"],
        "rateonly":     args.rateonly,
        # Detail values
        "codAmount":    DEFAULTS["codAmount"],
        "comment":      args.comment,
        "declaredValue": DEFAULTS["declaredValue"],
        "height":       args.height,
        "length":       args.length,
        "packageID":    packageID,
        "units":        DEFAULTS["units"],
        "weight":       args.weight,
        "width":        args.width,
    }

    # Generate XML
    header_xml = HEADER_TEMPLATE.format(**vals)
    detail_xml = DETAIL_TEMPLATE.format(**vals)

    # Write files
    header_fname = f"HeaderIn_{shipment_id}_{timestamp}.xml"
    detail_fname = f"DetailIn_{shipment_id}_{timestamp}.xml"
    header_path = os.path.join(quikpak_in, header_fname)
    detail_path = os.path.join(quikpak_in, detail_fname)

    with open(header_path, "w", encoding="utf-8") as f:
        f.write(header_xml)
    with open(detail_path, "w", encoding="utf-8") as f:
        f.write(detail_xml)

    # Summary
    print(f"Generated test files for {shipment_id}:")
    print(f"  {header_fname}")
    print(f"  {detail_fname}")
    print()
    print(f"  Order:    {args.orderno}")
    print(f"  Customer: {args.customer}")
    print(f"  Ship Via: {args.shipvia}")
    print(f"  Ship To:  {args.name}, {args.city}, {args.state} {args.zip} {args.country}")
    print(f"  Location: {args.location}")
    print(f"  Package:  {args.weight} {DEFAULTS['units']} "
          f"({args.length} x {args.width} x {args.height})")
    print(f"  Comment:  {args.comment[:60]}{'...' if len(args.comment) > 60 else ''}")
    print()
    print(f"  Output:   {quikpak_in}")
    print()
    print("Ready for Flow 1.  Run:  python qpss_middleware.py --flow1")


if __name__ == "__main__":
    main()
