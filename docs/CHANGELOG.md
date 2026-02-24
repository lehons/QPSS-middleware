# Changelog

All notable changes to the QPSS Middleware are documented here.

## [0.1.0] — 2026-02-23

Initial prototype release. Built for UAT testing with test company environment.

### Features

- **Flow 1 (QuikPAK → ShipStation):** Parse XML IN files, create orders via ShipStation V1 API.
- **Flow 2 (ShipStation → QuikPAK):** Poll for completed shipments, generate OUT XML files.
- **Holding tank architecture:** Pending JSON links Flow 1 and Flow 2 per shipment.
- **Dual-account routing:** Canadian orders route to CA ShipStation account, all others to US.
- **Sage 300 item lookup:** Order line items (SKU, description, qty, price) fetched from OEORDD via SQL for packing slips.
- **Interactive prompts:** User prompted when Sage items are missing — push without items or skip. Batch prompt at end for all unmatched orders.
- **Dry-run mode:** Both flows support `--dry-run` for testing without side effects.
- **Test file generator:** `generate_test.py` / `generate_test.bat` creates test XML pairs with auto-incrementing ShipmentIDs.
- **Pending cleanup:** `--cleanup-pending DAYS` removes orphaned pending JSONs older than N days.
- **State file cap:** Flow 2 processed IDs list auto-capped at 500 entries.
- **Error handling:** Permanent errors → Error folder + description file. Transient errors → leave in place for retry.
- **Daily log rotation:** `qpss-YYYY-MM-DD.log` files with DEBUG (file) and INFO (console) levels.

### Known Limitations

- **Multi-package orders:** ShipStation V1 API does not support multiple packages per order. Multi-package shipments use summed weight and largest dimensions. Flagged as "Multi Package" in customField3.
- **RateOnly shipments:** Skipped (not sent to ShipStation). Needs business decision on whether these are relevant.
- **Voided shipments:** Not communicated back from ShipStation to QuikPAK. Needs business decision.
- **Shipping service mapping:** SHIPVIA codes (FEDEXG, UPSG, etc.) are passed as-is to ShipStation. Carrier mapping is handled by ShipStation automation rules.
