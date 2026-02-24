# QPSS Middleware — Architecture

Technical reference for developers maintaining or extending the middleware.

## System Context

```
┌─────────────┐     XML files      ┌──────────────────┐     REST API      ┌─────────────┐
│   QuikPAK   │ ──────────────────►│  QPSS Middleware  │───────────────────►│ ShipStation │
│   (Sage     │                    │                   │                    │  (US + CA   │
│    CMS)     │ ◄──────────────────│   Windows Server  │◄───────────────────│  accounts)  │
└─────────────┘     XML files      │                   │     REST API      └─────────────┘
                                   │                   │
                                   │         ┌─────────┴────────┐
                                   │         │    SQL (ODBC)     │
                                   │         └─────────┬────────┘
                                   └──────────────────┐│
                                                      ││
                                              ┌───────┘▼────────┐
                                              │   Sage 300 ERP  │
                                              │   (IS-SQL-19 /  │
                                              │    ISIDAT)       │
                                              └─────────────────┘
```

## Data Flow — Flow 1 (Order Creation)

```
QuikPAK drops XML          Middleware                              ShipStation
─────────────────          ──────────                              ──────────

HeaderIn_SHIP..._*.xml ──► xml_parser.py
DetailIn_SHIP..._*.xml ──► parse_header() / parse_detail()
                                │
                                ▼
                           file_manager.py
                           scan_for_pairs() — match by ShipmentID
                                │
                                ▼
                           sage_client.py
                           get_order_items(order_no)
                           OEORDH.ORDNUMBER → OEORDD items
                                │
                                ▼
                           order_mapper.py
                           map_to_shipstation(header, detail, items)
                                │
                                ▼
                           shipstation_client.py  ──────────►  POST /orders/createorder
                           create_or_update_order()                   │
                                │                                     ▼
                                ▼                              Order visible in
                           Save pending JSON                   ShipStation UI
                           (Pending/{ShipmentID}.json)
                                │
                                ▼
                           Move XML to Processed/
```

### Key Decision Points in Flow 1

1. **Void check** — `<void>Y</void>` → skip, move to Processed
2. **RateOnly check** — `<RateOnly>Y</RateOnly>` → skip, move to Processed
3. **Country routing** — `<shipcountry>CA</shipcountry>` → CA account, else → US
4. **Sage item lookup** — no items found → hold for batch prompt at end
5. **Sage query error** — same as no items found → hold for batch prompt

## Data Flow — Flow 2 (Shipment Confirmation)

```
ShipStation                    Middleware                         QuikPAK
──────────                     ──────────                         ───────

GET /shipments ◄────────── shipstation_client.py
(both US + CA)             list_shipments(start_date)
      │                         │
      ▼                         ▼
Shipment data             Filter: is_our_order()?
                          Filter: already processed?
                                │
                                ▼
                          Load pending JSON
                          (Pending/{ShipmentID}.json)
                                │
                                ▼
                          xml_generator.py          ──────────►  HeaderOut_*.xml
                          generate_out_files()                   DetailOut_*.xml
                                │                                (in QuikPAKOUT/)
                                ▼
                          Delete pending JSON
                          Update flow2_state.json
```

### Flow 2 Identification

Flow 2 only processes shipments whose `orderNumber` matches the format `customercode_ShipmentID` (e.g., `HO1002_SHIP0000447530`). All other shipments are silently ignored.

## The Holding Tank (Pending JSON)

The pending JSON is the critical link between Flow 1 and Flow 2. It exists because:

- Flow 2 needs original order data (ship-to address, packages, customer code) to generate OUT XML
- ShipStation's API does not return all original order fields in the shipment response
- The XML IN files have been moved to Processed by the time Flow 2 runs

### Pending JSON Structure

```json
{
  "shipment_id": "SHIP0000447530",
  "order_number": "HO1002_SHIP0000447530",
  "customer_code": "HO1002",
  "ship_to": { "name": "...", "street1": "...", ... },
  "ship_via": "UPS",
  "packages": [ { "package_id": "...", "weight": 5.25, ... } ],
  "items": [ { "item_number": "BKGLKBL", "description": "...", ... } ],
  "account": "shipstation",
  "created_at": "2026-02-23T12:00:00.000000"
}
```

### Lifecycle

1. **Created** by Flow 1 after successful ShipStation API call
2. **Read** by Flow 2 when a matching shipment is found
3. **Deleted** by Flow 2 after successful OUT XML generation
4. **Orphaned** if the order is cancelled in ShipStation → cleaned up via `--cleanup-pending`

## Module Reference

### `qpss_middleware.py` — Main Entry Point

All command routing, Flow 1 orchestration, Flow 2 orchestration, cleanup logic.

Key functions:
- `run_flow1(config, dry_run)` — Flow 1 main loop
- `run_flow2(config, dry_run)` — Flow 2 main loop
- `run_cleanup_pending(config, days)` — Orphan cleanup
- `_get_account_for_country(config, country)` — Routing logic
- `_build_sage_client(config)` — Sage 300 client factory
- `_save_pending_shipment(...)` / `_load_pending_shipment(...)` — Holding tank I/O

### `src/xml_parser.py` — IN XML Parsing

Parses `ProcessWeaverInHeader` and `ProcessWeaverInDetail` XML files into Python dataclasses (`ShipmentHeader`, `ShipmentDetail`, `PackageDetail`).

### `src/xml_generator.py` — OUT XML Generation

Generates `SmartlincOutHeader` and `SmartlincOutDetail` XML files.

> **Note:** The PDF docs say the root elements should be `ProcessWeaverOut*` but the actual sample files use `SmartlincOut*`. We match the samples.

### `src/order_mapper.py` — XML → ShipStation Mapping

Converts parsed XML data + Sage 300 items into a ShipStation V1 order JSON payload.

Key mappings:
- `orderNumber` = `customercode_ShipmentID`
- `orderKey` = same (enables upsert)
- `customField1` = PO number
- `customField2` = ship-via code
- `customField3` = "Single Package" or "Multi Package"
- `items[]` = from Sage 300 OEORDD (SKU, description, qty, unit price)

### `src/shipstation_client.py` — ShipStation V1 API Client

HTTP client for ShipStation V1 API with Basic auth, retry logic, and rate limit handling.

Endpoints used:
- `POST /orders/createorder` — Create/update order (upserts via orderKey)
- `GET /orders` — Find existing orders by orderNumber
- `GET /shipments` — Poll for completed shipments
- `GET /stores` — List configured stores

### `src/sage_client.py` — Sage 300 ERP Client

ODBC client for Sage 300 database queries via `pyodbc`.

Query chain: `OEORDH.ORDNUMBER` → `OEORDH.ORDUNIQ` → `OEORDD` line items.

Columns used from `dbo.OEORDD`: LINENUM, ITEM, DESC, QTYORDERED, QTYSHIPPED, UNITPRICE.

### `src/file_manager.py` — File Operations

Scans QuikPAKIN for HeaderIn/DetailIn pairs, matches by ShipmentID regex, moves files to Processed or Error folders.

Filename pattern: `HeaderIn_{ShipmentID}_{timestamp}.xml` where ShipmentID matches `[A-Za-z]+\d+`.

### `src/logger.py` — Logging

Creates daily rotating log files (`qpss-YYYY-MM-DD.log`) with both file (DEBUG level) and console (INFO level) output.

## Configuration Schema

See `config.ini.example` for the template. Key notes:

- All paths must be **absolute**
- ShipStation API keys expire **annually**
- The `[shipstation_ca]` section is optional — if absent, all orders route to US
- The `[sage300]` section is optional — if absent, orders are created without line items
- `flow2_state_file` defaults to `flow2_state.json` in the script directory if blank

## Error Handling Strategy

| Error Type | Behavior | Files |
|------------|----------|-------|
| Permanent (bad data, API rejection) | Move to Error/ + `.error.txt` | Removed from IN |
| Transient (timeout, rate limit, 5xx) | Leave in IN for next run | Stay in IN |
| Sage connection failure (startup) | User prompt: Continue or Abort | N/A |
| Sage item not found (per-order) | Collect all, prompt once at end | Stay in IN until decision |

## State Management

### flow2_state.json

```json
{
  "last_poll_date": "2026-02-23",
  "processed_shipment_ids": [412021985, 412028514, ...]
}
```

- `processed_shipment_ids` is auto-capped at **500 entries** (oldest trimmed first)
- Safe to edit manually: change `last_poll_date` to re-poll, remove an ID to re-process
- Safe to delete entirely: Flow 2 will start fresh (poll last 7 days)
