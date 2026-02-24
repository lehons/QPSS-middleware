# QPSS Middleware

Middleware integration between **QuikPAK** (warehouse management / CMS) and **ShipStation** (shipping platform) for Ideal Security Inc.

QuikPAK communicates via XML file exchange. ShipStation communicates via REST API. This middleware bridges the two.

## How It Works

```
QuikPAK                    QPSS Middleware                   ShipStation
─────────                  ───────────────                   ──────────
                    FLOW 1 (Order Creation)
XML IN files  ──────►  Parse + Sage lookup  ──────►  Create order (API)
(HeaderIn/DetailIn)     Save pending JSON              ▼
                                                  Order visible in
                                                  ShipStation UI
                                                       │
                                              (warehouse ships it)
                                                       │
                    FLOW 2 (Shipment Confirmation)     ▼
XML OUT files  ◄──────  Generate OUT XML  ◄──────  Poll shipments (API)
(HeaderOut/DetailOut)   Delete pending JSON
```

**Flow 1** reads XML files dropped by QuikPAK, looks up item details from Sage 300 ERP, and creates orders in ShipStation via the V1 API.

**Flow 2** polls ShipStation for completed shipments, matches them to pending orders, and generates OUT XML files for QuikPAK to consume.

A "pending JSON" file links the two flows — Flow 1 saves it, Flow 2 consumes it.

## Prerequisites

- **Python 3.12+** (tested on 3.14)
- **ODBC Driver 17 for SQL Server** (for Sage 300 item lookups)
- **Network access** to ShipStation API (`ssapi.shipstation.com`) and Sage 300 SQL Server
- **Windows** (batch files assume Windows; Python code is cross-platform)

## Installation

```bash
# 1. Clone or copy the repository
git clone https://github.com/YOUR_ORG/qpss-middleware.git
cd qpss-middleware

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. Create your configuration file
copy config.ini.example config.ini
# Edit config.ini with your actual credentials and paths
```

## Configuration

Copy `config.ini.example` to `config.ini` and fill in all values. The file is excluded from version control (`.gitignore`) because it contains credentials.

### Sections

| Section | What to configure |
|---------|-------------------|
| `[paths]` | Absolute paths to QuikPAK IN/OUT folders, Pending folder, log directory |
| `[shipstation]` | US account API key, secret, store ID |
| `[shipstation_ca]` | Canadian account API key, secret, store ID |
| `[sage300]` | SQL Server hostname, database name, credentials, ODBC driver |
| `[settings]` | Retry attempts, delay, Flow 2 state file location |

### ShipStation API Keys

API keys are generated in **ShipStation > Settings > Account > API Settings**.

> **Keys expire annually.** When they expire, ShipStation API calls will return `401 Unauthorized`. Generate new keys in ShipStation and update `config.ini`.

There are two separate ShipStation accounts (US and CA), each with their own API key pair.

### Store IDs

To find available store IDs:

```bash
python qpss_middleware.py --list-stores              # US account
python qpss_middleware.py --list-stores --account ca  # CA account
```

## Usage

### Batch Files (recommended for operators)

| Batch File | What It Does |
|------------|-------------|
| `Push Orders to ShipStation.bat` | Runs Flow 1 — reads XML IN files, creates ShipStation orders |
| `Query Shipments from ShipStation.bat` | Runs Flow 2 — polls for shipped orders, generates XML OUT files |
| `tools\generate_test.bat` | Generates test XML file pairs for Flow 1 testing |

Double-click any batch file to run it. They automatically set the working directory, so **you can rename them or create shortcuts to them anywhere** — they will still work because they use `cd /d "%~dp0"` to find the script directory.

### Command Line

```bash
# Flow 1: QuikPAK -> ShipStation
python qpss_middleware.py --flow1
python qpss_middleware.py --flow1 --dry-run          # parse only, no API calls

# Flow 2: ShipStation -> QuikPAK
python qpss_middleware.py --flow2
python qpss_middleware.py --flow2 --dry-run          # poll only, no files written

# Utilities
python qpss_middleware.py --list-stores              # show US stores
python qpss_middleware.py --list-stores --account ca  # show CA stores
python qpss_middleware.py --cleanup-pending 90        # remove orphaned pending JSONs > 90 days

# Test file generation (from project root)
python tools\generate_test.py                              # generate with defaults
python tools\generate_test.py --orderno ORD0469657         # override order number
python tools\generate_test.py --country CA --state QC      # ship to Canada
python tools\generate_test.py --help                       # show all options
```

### Dry Run Mode

Both flows support `--dry-run`. In this mode:
- XML files are parsed and validated but not moved
- ShipStation API is not called
- No OUT files are written
- No state is updated

Use dry-run to verify configuration and test new XML files without side effects.

## Folder Structure

```
Prototype/
├── qpss_middleware.py          # Main entry point (both flows + utilities)
├── config.ini                  # Your credentials and paths (NOT in git)
├── config.ini.example          # Template for config.ini
├── requirements.txt            # Python dependencies
├── flow2_state.json            # Flow 2 runtime state (NOT in git)
├── Push Orders to ShipStation.bat      # Flow 1 launcher
├── Query Shipments from ShipStation.bat # Flow 2 launcher
├── README.md
├── src/                        # Source modules
│   ├── __init__.py
│   ├── file_manager.py         # XML file scanning, pairing, moving
│   ├── logger.py               # Daily rotating log setup
│   ├── order_mapper.py         # XML data -> ShipStation order JSON
│   ├── sage_client.py          # Sage 300 ERP database queries
│   ├── shipstation_client.py   # ShipStation V1 API client
│   ├── xml_generator.py        # OUT XML file generation
│   └── xml_parser.py           # IN XML file parsing
├── docs/                       # Documentation
│   ├── ARCHITECTURE.md         # Technical architecture reference
│   └── CHANGELOG.md            # Version history
├── tools/                      # Dev / test utilities
│   ├── generate_test.py        # Test XML file generator
│   └── generate_test.bat       # Batch wrapper for test generator
├── QuikPAK/                    # Runtime XML folders (NOT in git)
│   ├── QuikPAKIN/              # Incoming XML from QuikPAK
│   │   ├── Processed/          # Successfully processed files
│   │   └── Error/              # Failed files + error descriptions
│   ├── QuikPAKOUT/             # Generated OUT XML for QuikPAK
│   └── Pending/                # JSON holding tank (Flow 1 -> Flow 2)
└── logs/                       # Daily log files (NOT in git)
```

## Dual-Account Routing

Orders are automatically routed to the correct ShipStation account based on the ship-to country:

- **Ship to Canada (`CA`)** → Canadian ShipStation account (`[shipstation_ca]`)
- **All other countries** → US ShipStation account (`[shipstation]`)

Flow 2 polls both accounts for completed shipments.

## Sage 300 Integration

Flow 1 looks up order line items from the Sage 300 ERP database:

1. XML `<orderno>` (e.g., `ORD0469657`) → `dbo.OEORDH.ORDNUMBER`
2. `OEORDH.ORDUNIQ` → `dbo.OEORDD.ORDUNIQ` (line items)
3. Items (SKU, description, quantity, price) are sent to ShipStation for packing slips

If Sage 300 is unavailable or an order is not found, the user is prompted to push the order without items or skip it.

## Maintenance

### Log Files

Daily log files are written to the `logs/` directory as `qpss-YYYY-MM-DD.log`. These contain detailed records of every operation including API responses.

### Pending JSON Cleanup

Over time, cancelled or test orders may leave orphaned JSON files in the Pending folder. To clean them up:

```bash
python qpss_middleware.py --cleanup-pending 90   # remove files older than 90 days
python qpss_middleware.py --cleanup-pending 365  # remove files older than 1 year
```

The command shows what it will delete and asks for confirmation before proceeding.

### Flow 2 State File

`flow2_state.json` tracks:
- `last_poll_date` — the date of the last successful Flow 2 poll
- `processed_shipment_ids` — ShipStation shipment IDs already converted to OUT XML

The processed IDs list is automatically capped at 500 entries (oldest trimmed first) to prevent unbounded growth.

If you need to re-process a shipment, delete its ID from this file. If you need to re-poll from an earlier date, edit `last_poll_date`.

## Error Handling

| Scenario | What Happens |
|----------|-------------|
| **ShipStation API error (permanent)** | Files moved to `Error/` folder with `.error.txt` description |
| **ShipStation API error (transient)** | Files left in `QuikPAKIN/` for next run to retry |
| **Sage 300 connection failed (startup)** | User prompted: Continue without items or Abort |
| **Sage 300 order not found** | Order held; user prompted at end of batch: Push all without items or Skip all |
| **Sage 300 query error** | Same as order not found — held and prompted |
| **Void shipment (`<void>Y</void>`)** | Skipped, moved to Processed |
| **RateOnly shipment** | Skipped, moved to Processed |
| **Duplicate order** | ShipStation upserts via orderKey — updates existing order |
