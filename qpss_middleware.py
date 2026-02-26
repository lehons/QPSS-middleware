"""
QPSS Middleware - QuikPAK / ShipStation Integration

Flow 1: Reads XML files from QuikPAKIN, creates orders in ShipStation V1 API.
        Saves a pending JSON per shipment for Flow 2 to use later.
Flow 2: Polls ShipStation for completed shipments, matches to pending JSON,
        generates OUT XML for QuikPAK.

Usage:
    python qpss_middleware.py --flow1
    python qpss_middleware.py --flow1 --dry-run
    python qpss_middleware.py --flow2
    python qpss_middleware.py --flow2 --dry-run
    python qpss_middleware.py --list-stores
    python qpss_middleware.py --list-stores --account ca
    python qpss_middleware.py --cleanup-pending 90
"""

import argparse
import configparser
import json
import os
import re
import sys
from datetime import datetime, timedelta

from src.logger import setup_logger
from src.xml_parser import parse_header, parse_detail
from src.order_mapper import map_to_shipstation, build_order_number
from src.file_manager import scan_for_pairs, move_to_processed, move_to_error
from src.xml_generator import generate_out_files
from src.shipstation_client import (
    ShipStationClient,
    ShipStationError,
    ShipStationTransientError,
)
from src.sage_client import SageClient, SageConnectionError, SageQueryError


def load_config(config_path: str, dry_run: bool = False) -> configparser.ConfigParser:
    """Load and validate config.ini."""
    if not os.path.exists(config_path):
        print(f"ERROR: Config file not found: {config_path}")
        print("Copy config.ini.example to config.ini and fill in your settings.")
        sys.exit(1)

    config = configparser.ConfigParser()
    config.read(config_path, encoding="utf-8")

    # Validate required sections and keys
    required = {
        "paths": ["quikpak_in", "quikpak_in_processed", "quikpak_in_error", "log_dir"],
        "shipstation": ["api_key", "api_secret", "base_url"],
        "settings": ["retry_attempts", "retry_delay_seconds"],
    }
    for section, keys in required.items():
        if not config.has_section(section):
            print(f"ERROR: Missing [{section}] section in config.ini")
            sys.exit(1)
        for key in keys:
            if not config.get(section, key, fallback=""):
                print(f"ERROR: Missing {section}.{key} in config.ini")
                sys.exit(1)

    # Check for placeholder values (skip in dry-run mode)
    if not dry_run:
        api_key = config.get("shipstation", "api_key")
        if api_key == "YOUR_API_KEY":
            print("ERROR: Replace YOUR_API_KEY in config.ini with your ShipStation API key")
            sys.exit(1)

    return config


def _build_client(
    config: configparser.ConfigParser, section: str = "shipstation"
) -> ShipStationClient:
    """Create a ShipStationClient from a config section.

    Args:
        config: Parsed config.ini.
        section: Config section name — 'shipstation' (US) or 'shipstation_ca' (CA).
    """
    return ShipStationClient(
        api_key=config.get(section, "api_key"),
        api_secret=config.get(section, "api_secret"),
        base_url=config.get(section, "base_url"),
        retry_attempts=config.getint("settings", "retry_attempts"),
        retry_delay=config.getint("settings", "retry_delay_seconds"),
    )


def _get_all_accounts(config: configparser.ConfigParser) -> list[tuple[str, str]]:
    """Return list of (config_section, label) for all configured ShipStation accounts.

    Always includes the US account ([shipstation]).
    Adds CA account ([shipstation_ca]) if the section exists and has an API key.
    """
    accounts = [("shipstation", "US")]
    if (config.has_section("shipstation_ca")
            and config.get("shipstation_ca", "api_key", fallback="")):
        accounts.append(("shipstation_ca", "CA"))
    return accounts


def _get_account_for_country(
    config: configparser.ConfigParser, country: str
) -> tuple[str, str, int | None]:
    """Determine which ShipStation account to use based on ship-to country.

    Returns (config_section, label, store_id) tuple.
    Falls back to US account if CA section is not configured.
    """
    if (country.upper() == "CA"
            and config.has_section("shipstation_ca")
            and config.get("shipstation_ca", "api_key", fallback="")):
        section = "shipstation_ca"
        label = "CA"
    else:
        section = "shipstation"
        label = "US"

    store_id_str = config.get(section, "store_id", fallback="")
    store_id = int(store_id_str) if store_id_str.isdigit() else None
    return section, label, store_id


def _build_sage_client(config: configparser.ConfigParser) -> SageClient | None:
    """Create a SageClient from config, or return None if not configured.

    The [sage300] section is optional. If absent or missing required fields,
    items will not be looked up and orders will be created without line items.
    """
    if not config.has_section("sage300"):
        return None
    server = config.get("sage300", "server", fallback="")
    database = config.get("sage300", "database", fallback="")
    if not server or not database:
        return None

    return SageClient(
        server=server,
        database=database,
        username=config.get("sage300", "username", fallback=""),
        password=config.get("sage300", "password", fallback=""),
        odbc_driver=config.get("sage300", "odbc_driver",
                               fallback="ODBC Driver 17 for SQL Server"),
    )


def run_list_stores(config: configparser.ConfigParser, account: str = "us") -> None:
    """List all stores in a ShipStation account."""
    logger = setup_logger(config.get("paths", "log_dir"))

    section = "shipstation_ca" if account == "ca" else "shipstation"
    label = "CA" if account == "ca" else "US"

    if not config.has_section(section):
        print(f"ERROR: [{section}] section not found in config.ini")
        print(f"Add a [{section}] section with api_key, api_secret, and base_url.")
        sys.exit(1)

    logger.info(f"Fetching stores for {label} account...")
    client = _build_client(config, section)

    try:
        stores = client.list_stores()
        if not stores:
            print(f"No stores found in {label} account.")
            return
        print(f"\n{label} Account Stores:")
        print(f"{'Store ID':<12} {'Store Name':<40} {'Marketplace'}")
        print("-" * 70)
        for store in stores:
            sid = store.get("storeId", "?")
            name = store.get("storeName", "?")
            marketplace = store.get("marketplaceName", "?")
            print(f"{sid:<12} {name:<40} {marketplace}")
        print(f"\nUse the Store ID in config.ini [{section}] store_id field.")
    except Exception as e:
        print(f"ERROR: Could not fetch stores from {label} account: {e}")
        sys.exit(1)


# ─── Pending JSON helpers ──────────────────────────────────────────


def _save_pending_shipment(
    pending_folder: str,
    header,
    detail,
    order_number: str,
    account: str = "shipstation",
    items: list = None,
) -> str:
    """Save original order data as a pending JSON file for Flow 2.

    Captures everything the OUT XML generator will need: ship-to address,
    original package details, flags, the ship_via code, which ShipStation
    account the order was created in, and optionally the Sage 300 line items.

    Returns the path to the saved JSON file.
    """
    os.makedirs(pending_folder, exist_ok=True)

    # Build ship_to dict matching the key names the xml_generator expects
    ship_to = {
        "name": header.ship_name,
        "company": "",  # Not in our IN files; shiptoID in OUT will be empty
        "street1": header.ship_addr1,
        "street2": header.ship_addr2,
        "street3": header.ship_addr3,
        "city": header.ship_city,
        "state": header.ship_state,
        "country": header.ship_country,
        "postalCode": header.ship_zip,
        "phone": header.optional_text_001,
        "email": header.ship_email,
        "residential": header.is_residential == "1",
    }

    # Build package list from detail
    packages = []
    for pkg in detail.packages:
        packages.append({
            "package_id": pkg.package_id,
            "package_no": pkg.package_no,
            "weight": pkg.weight,
            "length": pkg.length,
            "width": pkg.width,
            "height": pkg.height,
            "declared_value": pkg.declared_value,
            "cod_amount": pkg.cod_amount,
            "units": pkg.units,
            "comment": pkg.comment,
        })

    pending_data = {
        "shipment_id": header.shipment_id,
        "order_number": order_number,
        "customer_code": header.customer_code,
        "ship_to": ship_to,
        "ship_via": header.ship_via_code,
        "is_cod": header.is_cod,
        "coll_type": header.coll_type,
        "packages": packages,
        "items": [
            {
                "line_number": item.line_number,
                "item_number": item.item_number,
                "description": item.description,
                "qty_ordered": item.qty_ordered,
                "unit_price": item.unit_price,
            }
            for item in (items or [])
        ],
        "account": account,
        "created_at": datetime.now().isoformat(),
    }

    filename = f"{header.shipment_id}.json"
    filepath = os.path.join(pending_folder, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(pending_data, f, indent=2)

    return filepath


def _load_pending_shipment(pending_folder: str, shipment_id: str) -> dict | None:
    """Load a pending JSON file by ShipmentID.

    Returns the pending data dict, or None if not found.
    """
    filepath = os.path.join(pending_folder, f"{shipment_id}.json")
    if not os.path.exists(filepath):
        return None
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def _delete_pending_shipment(pending_folder: str, shipment_id: str) -> None:
    """Delete a pending JSON file after successful OUT generation."""
    filepath = os.path.join(pending_folder, f"{shipment_id}.json")
    if os.path.exists(filepath):
        os.remove(filepath)


# ─── Flow 1: QuikPAK -> ShipStation ────────────────────────────────


def run_flow1(config: configparser.ConfigParser, dry_run: bool = False) -> None:
    """Execute Flow 1: QuikPAK -> ShipStation order creation."""
    logger = setup_logger(config.get("paths", "log_dir"))

    logger.info("=" * 60)
    logger.info("QPSS Middleware - Flow 1: QuikPAK -> ShipStation")
    if dry_run:
        logger.info("*** DRY RUN MODE - No API calls, no file moves ***")
    logger.info("=" * 60)

    # Pre-build ShipStation clients for each configured account
    accounts = _get_all_accounts(config)
    clients = {}
    for section, label in accounts:
        clients[section] = _build_client(config, section)
    account_labels = ", ".join(label for _, label in accounts)
    logger.info(f"Configured accounts: {account_labels}")

    # Initialize Sage 300 client for item lookups (optional)
    sage = _build_sage_client(config)
    if sage:
        try:
            sage.test_connection()
            logger.info("Sage 300 DB: connected — items will be included in orders")
        except SageConnectionError as e:
            logger.warning(f"Sage 300 DB unavailable: {e}")
            print(f"\n*** Sage 300 database connection failed ***")
            print(f"    Error: {e}")
            print()
            while True:
                choice = input(
                    "    [C]ontinue without items for all orders, or [A]bort? "
                ).strip().upper()
                if choice in ("C", "A"):
                    break
                print("    Please enter C or A.")
            if choice == "A":
                logger.info("User chose to ABORT (Sage 300 unavailable)")
                print("Aborted.")
                return
            logger.info("User chose to continue without items (Sage 300 unavailable)")
            sage = None
    else:
        logger.info("Sage 300 DB: not configured — orders will have no line items")

    in_folder = config.get("paths", "quikpak_in")
    processed_folder = config.get("paths", "quikpak_in_processed")
    error_folder = config.get("paths", "quikpak_in_error")
    pending_folder = config.get("paths", "quikpak_pending", fallback="")
    if not pending_folder:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        pending_folder = os.path.join(script_dir, "QuikPAK", "Pending")

    # Step 1: Scan for file pairs
    logger.info(f"Scanning: {in_folder}")
    pairs = scan_for_pairs(in_folder)

    if not pairs:
        logger.info("No file pairs found to process.")
        return

    logger.info(f"Found {len(pairs)} file pair(s) to process")

    # Counters
    processed = 0
    skipped = 0
    errors = 0
    transient_failures = 0

    # Orders held back because Sage returned no items (not found or query error).
    # These are processed in a second pass after the user is prompted.
    # Each entry: (pair, header, detail, account_section, store_id, reason)
    held_orders = []

    # Step 2: Process each pair — orders WITH items go through immediately,
    #         orders without items are collected for a single prompt at the end.
    for pair in pairs:
        sid = pair.shipment_id
        logger.info(f"{sid} | Processing...")

        try:
            # Parse XML files
            header = parse_header(pair.header_path)
            detail = parse_detail(pair.detail_path)

            # Validate ShipmentID consistency
            if detail.packages and detail.packages[0].shipment_id != header.shipment_id:
                raise ValueError(
                    f"ShipmentID mismatch: header={header.shipment_id}, "
                    f"detail={detail.packages[0].shipment_id}")

            # Skip void shipments
            if header.void.upper() == "Y":
                logger.info(f"{sid} | SKIPPED: void=Y")
                skipped += 1
                if not dry_run:
                    move_to_processed(pair, processed_folder)
                continue

            # Skip RateOnly shipments (deferred — flag for follow-up)
            if header.rate_only.upper() == "Y":
                logger.info(f"{sid} | SKIPPED: RateOnly=Y (flagged for follow-up)")
                skipped += 1
                if not dry_run:
                    move_to_processed(pair, processed_folder)
                continue

            # Determine which ShipStation account based on destination country
            account_section, account_label, store_id = _get_account_for_country(
                config, header.ship_country
            )
            client = clients[account_section]
            logger.info(f"{sid} | Routing to {account_label} account "
                        f"(country: {header.ship_country})")

            # Look up line items from Sage 300
            items = []
            sage_problem = None
            if sage and header.order_no:
                try:
                    items = sage.get_order_items(header.order_no)
                    if items:
                        logger.info(f"{sid} | Sage 300: {len(items)} item(s) "
                                    f"for order {header.order_no}")
                    else:
                        sage_problem = (
                            f"Order {header.order_no} not found in Sage 300"
                        )
                        logger.warning(f"{sid} | {sage_problem}")
                except (SageConnectionError, SageQueryError) as e:
                    sage_problem = f"Query error: {e}"
                    logger.warning(f"{sid} | Sage 300 item lookup failed: {e}")

            # If Sage is configured but returned no items, hold this order
            # for the batch prompt at the end (don't push without items yet).
            if sage and header.order_no and not items:
                held_orders.append(
                    (pair, header, detail, account_section, store_id,
                     sage_problem or "No items returned")
                )
                logger.info(f"{sid} | HELD — waiting for user decision "
                            "(no items from Sage)")
                continue

            # Build ShipStation order
            order_number = build_order_number(header)
            order_data = map_to_shipstation(header, detail, store_id, items=items)

            if dry_run:
                logger.info(f"{sid} | DRY RUN: Would create order {order_number}")
                logger.debug(f"{sid} | Payload:\n{json.dumps(order_data, indent=2)}")
                processed += 1
                continue

            # Check for existing order (duplicate handling)
            existing = client.find_order_by_number(order_number)
            if existing:
                logger.info(f"{sid} | Order {order_number} already exists — "
                            "attempting update (may be intentional re-send)")

            # Create/update order in ShipStation (V1 upserts via orderKey)
            result = client.create_or_update_order(order_data)
            logger.info(f"{sid} | SUCCESS: Order {order_number} created/updated "
                        f"(orderId={result.get('orderId', '?')})")
            logger.debug(f"{sid} | API response: {json.dumps(result, indent=2)}")

            # Save pending JSON for Flow 2
            pending_path = _save_pending_shipment(
                pending_folder, header, detail, order_number,
                account=account_section, items=items,
            )
            logger.debug(f"{sid} | Pending data saved: {os.path.basename(pending_path)}")

            # Move files to Processed
            move_to_processed(pair, processed_folder)
            processed += 1

        except (ShipStationError, ValueError) as e:
            # Permanent failure — move to Error folder
            logger.error(f"{sid} | PERMANENT ERROR: {e}")
            if not dry_run:
                move_to_error(pair, error_folder, str(e))
            errors += 1

        except ShipStationTransientError as e:
            # Transient failure — leave files in place for next run
            logger.warning(f"{sid} | TRANSIENT ERROR (will retry next run): {e}")
            transient_failures += 1

        except Exception as e:
            # Unexpected error — move to Error folder
            logger.error(f"{sid} | UNEXPECTED ERROR: {type(e).__name__}: {e}")
            if not dry_run:
                move_to_error(pair, error_folder, f"{type(e).__name__}: {e}")
            errors += 1

    # ── Step 3: Handle held orders (no Sage items) ───────────────
    if held_orders:
        print(f"\n{'=' * 60}")
        print(f"  {len(held_orders)} order(s) had NO ITEMS from Sage 300:")
        print(f"{'=' * 60}")
        for pair, header, detail, acct, sid_store, reason in held_orders:
            print(f"    {header.shipment_id:<20} order={header.order_no:<16} "
                  f"reason: {reason}")
        print(f"{'=' * 60}")
        print()

        if dry_run:
            logger.info(f"DRY RUN: {len(held_orders)} order(s) held "
                        "(no Sage items) — skipping prompt")
            for pair, header, detail, acct, sid_store, reason in held_orders:
                logger.info(f"{header.shipment_id} | DRY RUN: Would hold "
                            f"(no items for {header.order_no})")
                skipped += 1
        else:
            while True:
                choice = input(
                    "    [P]ush all without items, or [S]kip all "
                    "(leave in QuikPAKIN for retry)? "
                ).strip().upper()
                if choice in ("P", "S"):
                    break
                print("    Please enter P or S.")

            if choice == "S":
                for pair, header, detail, acct, sid_store, reason in held_orders:
                    logger.info(f"{header.shipment_id} | User chose to SKIP "
                                f"(no items for {header.order_no})")
                    skipped += 1
                print(f"\n  Skipped {len(held_orders)} order(s). "
                      "Files left in QuikPAKIN.\n")
            else:
                # Push all held orders without items
                for pair, header, detail, acct, sid_store, reason in held_orders:
                    hsid = header.shipment_id
                    try:
                        client = clients[acct]
                        order_number = build_order_number(header)
                        order_data = map_to_shipstation(
                            header, detail, sid_store, items=[]
                        )
                        existing = client.find_order_by_number(order_number)
                        if existing:
                            logger.info(f"{hsid} | Order {order_number} already "
                                        "exists — attempting update")
                        result = client.create_or_update_order(order_data)
                        logger.info(
                            f"{hsid} | SUCCESS (no items): Order {order_number} "
                            f"created/updated "
                            f"(orderId={result.get('orderId', '?')})")

                        pending_path = _save_pending_shipment(
                            pending_folder, header, detail, order_number,
                            account=acct, items=[],
                        )
                        logger.debug(f"{hsid} | Pending data saved: "
                                     f"{os.path.basename(pending_path)}")
                        move_to_processed(pair, processed_folder)
                        processed += 1

                    except (ShipStationError, ValueError) as e:
                        logger.error(f"{hsid} | PERMANENT ERROR: {e}")
                        move_to_error(pair, error_folder, str(e))
                        errors += 1
                    except ShipStationTransientError as e:
                        logger.warning(f"{hsid} | TRANSIENT ERROR "
                                       f"(will retry next run): {e}")
                        transient_failures += 1
                    except Exception as e:
                        logger.error(f"{hsid} | UNEXPECTED ERROR: "
                                     f"{type(e).__name__}: {e}")
                        move_to_error(pair, error_folder,
                                      f"{type(e).__name__}: {e}")
                        errors += 1

                print(f"\n  Pushed {len(held_orders)} order(s) without items.\n")

    # Summary
    logger.info("-" * 60)
    logger.info(f"SUMMARY: {processed} processed, {skipped} skipped, "
                f"{errors} errors, {transient_failures} left for retry")
    logger.info("-" * 60)


# ─── Flow 2: ShipStation -> QuikPAK ────────────────────────────────


def _load_flow2_state(state_path: str) -> dict:
    """Load Flow 2 state (last poll date, processed shipment IDs)."""
    if os.path.exists(state_path):
        with open(state_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"last_poll_date": None, "processed_shipment_ids": []}


def _save_flow2_state(state_path: str, state: dict) -> None:
    """Save Flow 2 state to JSON file."""
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)



def _is_our_order(order_number: str) -> bool:
    """Check if an orderNumber matches our format: customercode_ShipmentID.

    Our orders always have an underscore separating customercode from ShipmentID,
    where ShipmentID starts with SHIP or TEST followed by digits.
    """
    if "_" not in order_number:
        return False
    parts = order_number.split("_", 1)
    if len(parts) != 2:
        return False
    # ShipmentID portion should match our pattern
    return bool(re.match(r"^[A-Za-z]+\d+$", parts[1]))


def run_flow2(config: configparser.ConfigParser, dry_run: bool = False) -> None:
    """Execute Flow 2: Poll ShipStation for completed shipments, generate OUT XML.

    For each new shipment found:
    1. Check if a pending JSON exists (saved by Flow 1)
    2. If yes: merge ShipStation data with pending data, generate OUT XML, delete JSON
    3. If no: log a warning and skip (no original data to echo back)
    """
    logger = setup_logger(config.get("paths", "log_dir"))

    logger.info("=" * 60)
    logger.info("QPSS Middleware - Flow 2: ShipStation -> QuikPAK")
    if dry_run:
        logger.info("*** DRY RUN MODE - No files written, state not updated ***")
    logger.info("=" * 60)

    out_folder = config.get("paths", "quikpak_out")
    pending_folder = config.get("paths", "quikpak_pending", fallback="")
    if not pending_folder:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        pending_folder = os.path.join(script_dir, "QuikPAK", "Pending")

    state_path = config.get("settings", "flow2_state_file", fallback="")
    if not state_path:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        state_path = os.path.join(script_dir, "flow2_state.json")

    # Load state
    state = _load_flow2_state(state_path)
    processed_ids = set(state.get("processed_shipment_ids", []))

    # Determine date range for polling (based on shipment creation date,
    # i.e. when the label was generated — not the original order date)
    last_poll = state.get("last_poll_date")
    if last_poll:
        start_date = last_poll
        logger.info(f"Polling shipments created from {start_date} (last poll date)")
    else:
        # First run: look back 7 days
        start_date = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        logger.info(f"First run — polling shipments created from {start_date} (last 7 days)")

    today = datetime.now().strftime("%Y-%m-%d")

    # Fetch shipments from ALL configured ShipStation accounts.
    # The processed_shipment_ids set prevents duplicates across runs.
    all_shipments = []
    accounts = _get_all_accounts(config)
    account_labels = ", ".join(label for _, label in accounts)
    logger.info(f"Polling accounts: {account_labels}")

    for account_section, account_label in accounts:
        client = _build_client(config, account_section)
        store_id_str = config.get(account_section, "store_id", fallback="")
        store_id = int(store_id_str) if store_id_str.isdigit() else None

        logger.info(f"Polling {account_label} account for shipments...")
        page = 1
        while True:
            try:
                result = client.list_shipments(
                    store_id=store_id,
                    create_date_start=start_date,
                    page=page,
                    page_size=100,
                )
            except (ShipStationError, ShipStationTransientError) as e:
                logger.error(f"Failed to fetch shipments from {account_label}: {e}")
                break  # Skip this account, continue with others

            shipments = result.get("shipments", [])
            all_shipments.extend(shipments)

            total_pages = result.get("pages", 1)
            logger.info(f"  {account_label} page {page}/{total_pages}: "
                        f"{len(shipments)} shipment(s)")

            if page >= total_pages:
                break
            page += 1

    logger.info(f"Total shipments fetched across all accounts: {len(all_shipments)}")

    # Filter to our orders and skip already-processed
    new_shipments = []
    for s in all_shipments:
        ss_id = s.get("shipmentId")
        order_num = s.get("orderNumber", "")

        if not _is_our_order(order_num):
            continue  # Not our order — skip silently

        if ss_id in processed_ids:
            logger.debug(f"Shipment {ss_id} ({order_num}) already processed — skipping")
            continue

        new_shipments.append(s)

    if not new_shipments:
        logger.info("No new shipments to process.")
        # Still update the poll date
        if not dry_run:
            state["last_poll_date"] = today
            _save_flow2_state(state_path, state)
        return

    logger.info(f"Found {len(new_shipments)} new shipment(s) to process")

    # Counters
    processed = 0
    skipped = 0
    errors = 0

    for shipment in new_shipments:
        ss_shipment_id = shipment.get("shipmentId")
        order_num = shipment.get("orderNumber", "")
        shipment_id = order_num.split("_", 1)[1] if "_" in order_num else order_num
        tracking = shipment.get("trackingNumber", "(none)")

        logger.info(f"{shipment_id} | Processing shipment {ss_shipment_id} "
                     f"(tracking: {tracking})")

        try:
            # Load pending data (saved by Flow 1)
            pending = _load_pending_shipment(pending_folder, shipment_id)

            if not pending:
                logger.warning(
                    f"{shipment_id} | No pending JSON found — skipping. "
                    "This shipment may have been created before the holding "
                    "tank was implemented, or was not created by Flow 1."
                )
                skipped += 1
                # Still mark as processed so we don't warn on every poll
                processed_ids.add(ss_shipment_id)
                continue

            logger.debug(f"{shipment_id} | Loaded pending data "
                         f"({len(pending.get('packages', []))} package(s))")

            if dry_run:
                logger.info(f"{shipment_id} | DRY RUN: Would generate OUT files "
                            f"(tracking: {tracking}, "
                            f"packages: {len(pending.get('packages', []))})")
                processed += 1
                continue

            # Generate OUT XML files
            header_path, detail_path = generate_out_files(
                pending=pending,
                shipment=shipment,
                out_folder=out_folder,
            )
            logger.info(f"{shipment_id} | SUCCESS: Generated OUT files")
            logger.info(f"{shipment_id} |   {os.path.basename(header_path)}")
            logger.info(f"{shipment_id} |   {os.path.basename(detail_path)}")

            # Clean up: delete the pending JSON
            _delete_pending_shipment(pending_folder, shipment_id)
            logger.debug(f"{shipment_id} | Pending JSON deleted")

            # Track as processed
            processed_ids.add(ss_shipment_id)
            processed += 1

        except Exception as e:
            logger.error(f"{shipment_id} | ERROR: {type(e).__name__}: {e}")
            errors += 1

    # Update state — cap processed IDs to the most recent MAX_PROCESSED_IDS
    # to prevent the state file from growing forever.  Oldest entries are
    # trimmed first; they'll never match a pending JSON anyway.
    MAX_PROCESSED_IDS = 500
    if not dry_run:
        state["last_poll_date"] = today
        id_list = list(processed_ids)
        if len(id_list) > MAX_PROCESSED_IDS:
            trimmed = len(id_list) - MAX_PROCESSED_IDS
            id_list = id_list[-MAX_PROCESSED_IDS:]
            logger.info(f"State file trimmed: dropped {trimmed} oldest "
                        f"processed IDs (cap={MAX_PROCESSED_IDS})")
        state["processed_shipment_ids"] = id_list
        _save_flow2_state(state_path, state)
        logger.debug(f"State saved: {state_path}")

    # Summary
    logger.info("-" * 60)
    logger.info(f"SUMMARY: {processed} processed, {skipped} skipped, {errors} errors")
    logger.info("-" * 60)


# ─── Cleanup: orphaned pending JSONs ─────────────────────────────────


def run_cleanup_pending(config: configparser.ConfigParser, days: int) -> None:
    """Remove pending JSON files older than N days.

    These are orders that Flow 1 pushed to ShipStation but that were never
    shipped (cancelled, test orders, etc.).  Their pending JSONs sit in the
    Pending folder forever because Flow 2 never finds a matching shipment.

    This command lists them, shows their age, and asks for confirmation
    before deleting.
    """
    logger = setup_logger(config.get("paths", "log_dir"))

    logger.info("=" * 60)
    logger.info(f"QPSS Middleware - Cleanup pending JSONs older than {days} day(s)")
    logger.info("=" * 60)

    pending_folder = config.get("paths", "quikpak_pending", fallback="")
    if not pending_folder:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        pending_folder = os.path.join(script_dir, "QuikPAK", "Pending")

    if not os.path.isdir(pending_folder):
        print(f"Pending folder does not exist: {pending_folder}")
        return

    now = datetime.now()
    cutoff = now - timedelta(days=days)
    stale = []

    for fname in sorted(os.listdir(pending_folder)):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(pending_folder, fname)
        if not os.path.isfile(fpath):
            continue

        # Try to read created_at from the JSON; fall back to file mtime
        age_source = "file"
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            created_str = data.get("created_at", "")
            if created_str:
                created = datetime.fromisoformat(created_str)
                age_source = "json"
            else:
                created = datetime.fromtimestamp(os.path.getmtime(fpath))
        except Exception:
            created = datetime.fromtimestamp(os.path.getmtime(fpath))

        if created < cutoff:
            age_days = (now - created).days
            order_no = data.get("order_number", "?") if age_source == "json" else "?"
            shipment_id = fname.replace(".json", "")
            stale.append((fpath, fname, shipment_id, order_no, age_days))

    if not stale:
        print(f"\nNo pending JSONs older than {days} day(s). Nothing to clean up.")
        logger.info("No stale pending files found.")
        return

    # Show what we found
    print(f"\n{'=' * 70}")
    print(f"  {len(stale)} pending JSON(s) older than {days} day(s):")
    print(f"{'=' * 70}")
    print(f"  {'Shipment ID':<25} {'Order':<18} {'Age':>6}")
    print(f"  {'-' * 25} {'-' * 18} {'-' * 6}")
    for fpath, fname, sid, order_no, age_days in stale:
        print(f"  {sid:<25} {order_no:<18} {age_days:>4}d")
    print(f"{'=' * 70}")
    print()

    while True:
        choice = input(
            f"  Delete all {len(stale)} file(s)? [Y]es or [N]o? "
        ).strip().upper()
        if choice in ("Y", "N"):
            break
        print("  Please enter Y or N.")

    if choice == "N":
        print("  Cancelled. No files deleted.")
        logger.info("User cancelled pending cleanup.")
        return

    deleted = 0
    for fpath, fname, sid, order_no, age_days in stale:
        try:
            os.remove(fpath)
            logger.info(f"Deleted pending JSON: {fname} "
                        f"(order={order_no}, age={age_days}d)")
            deleted += 1
        except OSError as e:
            logger.error(f"Failed to delete {fname}: {e}")

    print(f"\n  Deleted {deleted} of {len(stale)} file(s).")
    logger.info(f"Pending cleanup complete: {deleted} file(s) deleted.")


# ─── Main ────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="QPSS Middleware - QuikPAK / ShipStation Integration"
    )
    parser.add_argument(
        "--flow1", action="store_true",
        help="Run Flow 1: QuikPAK -> ShipStation order creation",
    )
    parser.add_argument(
        "--flow2", action="store_true",
        help="Run Flow 2: ShipStation -> QuikPAK shipment confirmation",
    )
    parser.add_argument(
        "--list-stores", action="store_true",
        help="List all stores in your ShipStation account (to find your store ID)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Parse and map files but don't call ShipStation API or move files",
    )
    parser.add_argument(
        "--account", choices=["us", "ca"], default="us",
        help="Which ShipStation account to target (default: us). "
             "Used with --list-stores to discover store IDs.",
    )
    parser.add_argument(
        "--cleanup-pending", type=int, default=None, metavar="DAYS",
        help="Remove orphaned pending JSONs older than DAYS days. "
             "Example: --cleanup-pending 90",
    )
    parser.add_argument(
        "--config", default=None,
        help="Path to config.ini (default: config.ini in script directory)",
    )

    args = parser.parse_args()

    has_action = (args.flow1 or args.flow2 or args.list_stores
                  or args.cleanup_pending is not None)
    if not has_action:
        parser.print_help()
        print("\nError: Specify --flow1, --flow2, --list-stores, "
              "or --cleanup-pending DAYS")
        sys.exit(1)

    # Find config.ini relative to the script location
    if args.config:
        config_path = args.config
    else:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(script_dir, "config.ini")

    config = load_config(config_path, dry_run=args.dry_run)

    if args.cleanup_pending is not None:
        if args.cleanup_pending < 1:
            print("ERROR: --cleanup-pending requires a positive number of days.")
            sys.exit(1)
        run_cleanup_pending(config, days=args.cleanup_pending)
    elif args.list_stores:
        run_list_stores(config, account=args.account)
    elif args.flow1:
        run_flow1(config, dry_run=args.dry_run)
    elif args.flow2:
        run_flow2(config, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
