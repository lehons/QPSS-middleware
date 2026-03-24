# Project Handoff

## Status
- [x] Spec approved by human
- [x] Implementation started
- [x] Implementation complete
- [x] Review complete (Architect code review passed 2026-03-16)
- [x] Bug fix: carrier detection (2026-03-18, Architect review passed)
- [x] Merged ups-tracking into main (2026-03-23, fast-forward, pushed to origin)
- [ ] End-to-end test of multi-package UPS tracking
- [ ] Bug fix: Streamlit UI not writing log files to disk
- [ ] Debug UPS child tracking — all packages getting master tracking number
- [ ] Debug date-related error with specific shipment
- [x] Streamlit Web UI: initial implementation (f13963a)
- [x] Streamlit Web UI: deployed to IS-APP-19 at http://192.168.0.3:8501
- [x] Streamlit Web UI: layout refinements + flow completion bug fix (c105b9c)
- [x] Streamlit Web UI: pull latest (c105b9c) to IS-APP-19 and restart Streamlit
- [x] Streamlit Web UI: Task Scheduler setup (confirmed working 2026-03-23)
- [ ] Streamlit Web UI: hide console window on server (cosmetic, not blocking)

---

## What We're Building

Add UPS API integration to Flow 2 so that multi-package UPS shipments get individual per-package tracking numbers in the DETAILOUT XML, instead of repeating the single master tracking number on every DetailLine. ShipStation only returns one tracking number per shipment (the master). For multi-package UPS shipments, we call the UPS Tracking API with that master number to retrieve child tracking numbers — one per package.

---

## Decisions Made

1. **No retry/timeout logic.** For the initial implementation, assume UPS returns tracking data immediately when we ask. If we discover a delay problem during testing, we'll add retry logic later as a separate change.

2. **Package-to-tracking mapping is loose.** We don't need to match specific UPS child tracking numbers to specific QuikPAK package lines. We just need the right *count* of unique tracking numbers distributed across the DetailLines. Sequence-based assignment (first child tracking → first DetailLine, etc.) is fine.

3. **UPS credentials in `config.ini`.** Same pattern as ShipStation and Sage 300 — a `[ups]` section with `client_id`, `client_secret`, `account_number`. Not committed to git.

4. **UPS credentials are unverified.** They were generated at developer.ups.com but never tested. Step 0 of implementation is to verify they work against the production tracking endpoint before writing any integration code.

5. **Only applies to UPS multi-package shipments.** Skip the UPS call entirely for:
   - Single-package shipments (any carrier)
   - Non-UPS carriers (FedEx, Purolator, etc.) — even if multi-package
   - These continue using the single ShipStation tracking number on all DetailLines

6. **Header tracking number stays as-is.** The HEADEROUT `<trackingNumber>` always gets the master tracking number from ShipStation. Only DETAILOUT DetailLines get individual child tracking numbers.

7. **Graceful fallback.** If the UPS API call fails for any reason (auth error, network error, unexpected response), fall back to the current behavior: use the master tracking number on all DetailLines. Log a warning. Don't block the shipment.

---

## File Structure

No new folders. One new file, changes to three existing files:

| File | Action | Purpose |
|------|--------|---------|
| `src/ups_client.py` | **NEW** | UPS OAuth 2.0 token management + tracking lookup |
| `config.ini.example` | EDIT | Add `[ups]` section |
| `src/xml_generator.py` | EDIT | Accept optional per-package tracking dict |
| `qpss_middleware.py` | EDIT | Conditional UPS call in Flow 2 loop |

### `src/ups_client.py` — New file

Responsibilities:
- **OAuth 2.0 token management**: POST to `https://onlinetools.ups.com/security/v1/oauth/token` with `grant_type=client_credentials`. Cache the token. Refresh when expired.
- **`get_child_tracking(master_tracking: str) -> list[str]`**: Call `GET https://onlinetools.ups.com/api/track/v1/shipment/details/{masterTrackingNumber}` (the shipment-level endpoint, NOT the single-package `/details/` endpoint). Parse the response `shipment[].package[]` array. Return a list of individual tracking numbers. Return empty list on any error.
- **Error handling**: Catch all exceptions. Log errors. Return empty list on failure (caller falls back to master tracking).
- **Headers**: `Authorization: Bearer {token}`, `transId: {uuid}`, `transactionSrc: QPSS-middleware`

### `config.ini.example` — Add section

```ini
; --- UPS API (for multi-package tracking) ---
; OAuth 2.0 credentials from https://developer.ups.com
; Only needed if you ship multi-package UPS shipments and want
; individual tracking numbers per package in the OUT XML.
[ups]
client_id = YOUR_UPS_CLIENT_ID
client_secret = YOUR_UPS_CLIENT_SECRET
account_number = YOUR_UPS_ACCOUNT_NUMBER
```

### `src/xml_generator.py` — Changes

`_build_detail_out()` currently puts the same `tracking` string on every DetailLine (line 173: `_add(line, "trackingNumber", tracking)`).

Change: accept an optional `package_tracking: list[str]` parameter. If provided and has the right count, assign tracking numbers positionally (first tracking → first DetailLine, second → second, etc.). If not provided or wrong count, fall back to the master tracking on all lines.

### `qpss_middleware.py` — Changes in `run_flow2()`

In the shipment processing loop (around line 721), after loading the pending JSON and before calling `generate_out_files()`:

```
# Determine if we need per-package UPS tracking
package_tracking = []
packages = pending.get("packages", [])
carrier = shipment.get("carrierCode", "")

if len(packages) > 1 and carrier.lower().startswith("ups"):
    # Multi-package UPS shipment — look up child tracking numbers
    ups = _build_ups_client(config)
    if ups:
        master = shipment.get("trackingNumber", "")
        package_tracking = ups.get_child_tracking(master)
        if len(package_tracking) < len(packages):
            logger.warning(f"{shipment_id} | UPS returned {len(package_tracking)} "
                           f"tracking numbers but expected {len(packages)} — "
                           "using master tracking for all packages")
            package_tracking = []  # fall back

# Pass to generate_out_files (which passes to _build_detail_out)
```

Also add a `_build_ups_client(config)` helper (similar to `_build_sage_client`) that returns `None` if `[ups]` section is missing or incomplete.

---

## Constraints

- **Do not add retry/timeout/state-tracking logic.** Keep it simple for now.
- **Do not block shipment processing on UPS failure.** Always fall back to master tracking.
- **Do not change Flow 1.** This feature is entirely within Flow 2.
- **Do not change the HEADEROUT format.** Only DETAILOUT tracking numbers change.
- **Do not store UPS tokens on disk.** Cache in memory only (token lives for the duration of one Flow 2 run).
- **Verify UPS credentials work before writing integration code.** Write a small test script or add a `--test-ups` CLI flag to hit the token endpoint and confirm auth works.
- **Work on a Git branch, not `main`.** All development happens on a branch called `ups-tracking`. Do not commit to `main` directly. Merge only after testing is complete and the human approves.

## Git Branching — How to Switch Versions

All development for this feature happens on the `ups-tracking` branch. The `main` branch stays untouched and deployable at all times.

**To run the stable (current) version:**
```
cd Prototype
git checkout main
```
Then run `Push Orders to ShipStation.bat` or `Query Shipments from ShipStation.bat` as normal. Everything is exactly as it was before.

**To switch back to the development version:**
```
cd Prototype
git checkout ups-tracking
```
Now you're looking at the in-progress UPS work.

**Important:** Always make sure work is saved (committed) before switching. Git will warn you if there are unsaved changes — it won't let you lose anything.

---

## Open Questions for Human

None — all resolved.

### Resolved

1. **Test data.** Coder will find test shipments by querying ShipStation for recent shipments where customField3 = "Multi Package" AND carrier = UPS. Use the most recent ones, and test with multiple shipments (not just one). These provide master tracking numbers for verifying UPS API credentials and response format.

2. **`carrierCode` values for UPS in ShipStation.** Coder will determine this empirically by inspecting ShipStation API responses for the test shipments found above.

---

## Coder -> Architect Questions

### 2026-03-16 — BLOCKER: UPS Tracking API does not return child tracking numbers

**The core assumption in the spec is wrong.** The UPS Tracking API does NOT return all package tracking numbers when queried with the master tracking number. It only returns the single queried package.

#### What I tested

1. **SHIP0000446908** (confirmed multi-package UPS, Jan 7 2026, `advancedOptions.customField3 = "Multi package"`)
   - ShipStation returns ONE shipment with master tracking `1Z7VY2950305181657`
   - UPS Tracking API returns 1 package with `packageCount: 2` — but only the master's data
   - The UPS API spec explicitly says: *"packageCount: The total number of packages in the shipment. Note that this number may be greater than the number of returned packages in the response. In such cases subsequent calls are needed to get additional packages."*
   - But it never tells us the OTHER tracking numbers. You need to already know them to query them.

2. **Sequential tracking number derivation** — I tried incrementing the package ID portion of the tracking number and recalculating the UPS check digit. The predicted second tracking number (`1Z7VY2950305181666`) returned "Tracking Information Not Found". Brute-forced offsets -2 to +9 — nothing.

3. **UPS Track-by-Reference API** — Tried querying by reference numbers (`2235109`, `SHIP0000446908`) with shipper number `7VY295`. Returns 404. This endpoint may require additional API permissions.

4. **ShipStation API** — The V1 `/shipments` endpoint only returns ONE `trackingNumber` per shipment. No `packages` array, no child tracking fields. The `/fulfillments` endpoint returns empty for this order.

#### Why the initial search missed multi-package shipments

Two reasons:
1. `customField3` is in `advancedOptions.customField3`, NOT at the top-level order `customField3` field (which is always null). My initial search checked the wrong field.
2. I searched `/shipments` (not `/orders`) — shipments don't have customField3 at all.

The `carrierCode` value for UPS is simply `"ups"` (lowercase). The current code using `carrier.lower().startswith("ups")` is correct.

#### The fundamental problem

Neither the UPS Tracking API nor the ShipStation V1 API exposes per-package tracking numbers for multi-package shipments after the fact. The child tracking numbers are only available at label creation time (in the ShipStation V2/ShipEngine label creation response), but:
- We use V1 API
- We don't create labels — the warehouse creates them in ShipStation's UI
- We only poll for completed shipments

#### Possible paths forward

1. **ShipStation V2 API** — The newer ShipEngine-based API may expose per-package tracking when listing shipments/labels. Would require migrating our shipment polling from V1 to V2. Significant work, unknown if it actually returns what we need.

2. **Capture tracking at label creation time** — If ShipStation has webhooks or if the warehouse workflow can be modified to export the child tracking numbers when labels are printed, we could store them. This is a workflow change, not just a code change.

3. **UPS Shipping API** — If we created the labels through the UPS Shipping API directly (instead of through ShipStation), we'd get all tracking numbers in the response. Major architectural change.

4. **Accept the limitation** — Use the master tracking number for all packages (current behavior). It's still a valid tracking number — UPS's website shows all packages when you enter the master. The customer can see all package statuses. They just won't have per-package tracking in the QuikPAK OUT XML.

**I'm blocked. Which path should we take?**

---

## Architect -> Coder Responses

### 2026-03-18 — Bug fix: carrier detection never triggers UPS lookup

**Problem:** End-to-end testing on 2026-03-18 confirmed the UPS tracking feature never fires. All multi-package shipments still get the master tracking number on every DetailLine. Logs show zero UPS client activity.

**Root cause:** ShipStation's `/shipments` V1 endpoint returns `carrierCode: null` and `serviceCode: null` for all shipments. The condition at `qpss_middleware.py` line 779 (`carrier.lower().startswith("ups")`) always evaluates to False, so the UPS client is never instantiated and never called.

**Fix — use tracking number prefix instead of carrierCode:**

In `qpss_middleware.py`, change the carrier detection block (lines 777–779) from:

```python
carrier = shipment.get("carrierCode", "")

if len(packages) > 1 and carrier.lower().startswith("ups"):
```

To:

```python
tracking = shipment.get("trackingNumber", "")

if len(packages) > 1 and tracking.startswith("1Z"):
```

Remove the `carrier` variable — nothing else uses it.

**Why tracking number prefix, not `requestedShippingService`:** The warehouse sometimes ships with a different carrier than what the order requested. The tracking number returned by ShipStation reflects what was *actually* shipped. `1Z` is the standard UPS tracking number prefix — it's ground truth.

**Nothing else changes.** The UPS client, token management, child tracking lookup, fallback behavior, and XML generation are all correct. Only the gate condition was wrong.

**Test shipment for verification:** SHIP0000474171, master tracking `1Z88XW192093833233`, 2 packages. After the fix, the second DetailLine should get tracking number `1Z88XW192090498245` (the child tracking number from UPS).

---

### 2026-03-16 — Re: "could not find multi-package UPS shipment"

There are plenty of multi-package UPS shipments in ShipStation. You need to test against real ones before this can be marked complete.

**1. Case sensitivity issue.** Our middleware sets `customField3 = "Multi Package"` (capital P), but older/manually-created shipments may use `"Multi package"` (lowercase p). Search for both variants, or search case-insensitively.

**2. Test shipment provided.** Use **SHIP0000446908** (from Jan 7 2026) — this is a confirmed multi-package UPS shipment. Look it up in ShipStation by orderNumber, get its master tracking number, and call the UPS Tracking API with it. Verify that multiple child tracking numbers come back.

**3. Find more test cases.** Don't stop at one. Find at least 2-3 more recent multi-package UPS shipments and test the UPS API response for each. Widen your date range — go back months if needed.

**4. Explain your search.** When you report back, tell us: what API endpoint did you use to search, what parameters, and what date range? We need to understand why the initial search failed so the same mistake doesn't carry into the carrier detection logic in `run_flow2()`.

### 2026-03-16 — Re: BLOCKER — Wrong UPS API endpoint

**You used the wrong endpoint.** The blocker is resolved.

**Wrong endpoint (what you used):**
`GET /track/v1/details/{inquiryNumber}` — Returns only the single queried package.

**Correct endpoint (use this instead):**
`GET /track/v1/shipment/details/{inquiryNumber}` — Explicitly designed for "Track Each Package in Shipment." Pass the master/lead tracking number and it returns ALL child packages with their individual tracking numbers.

This endpoint supports pagination:
- `offset` — 0-based start index (default 0)
- `count` — max packages to return (default 50)

Same auth (OAuth Bearer token), same headers (`transId`, `transactionSrc`). Just a different path.

**Action items:**
1. Update `src/ups_client.py` to use `/track/v1/shipment/details/{masterTracking}` instead of `/track/v1/details/{masterTracking}`
2. Re-test with **SHIP0000446908** (master tracking `1Z7VY2950305181657`) — you should now get 2 packages back, each with its own tracking number
3. Test with at least 2-3 more multi-package UPS shipments
4. Report back with the actual API response structure so we can confirm the parsing logic is correct

**Note on Quantum View:** UPS Quantum View exists but is overkill for this use case — it's a bulk event firehose for your entire account. The `/shipment/details/` endpoint is the targeted query we need. No need to go down the Quantum View path.

**Note on UPS data retention:** UPS tracking data is retained for 120 days. SHIP0000446908 is from Jan 7 (~68 days ago) so it should still be available, but keep this in mind for older shipments.

### 2026-03-24 — Bug fix: Streamlit UI not writing log files to disk

**Problem:** When Flow 1, Flow 2, or Cleanup runs through the Streamlit UI, no log file is created on disk. Log lines appear in the Streamlit live output but are never written to `logs/qpss-YYYY-MM-DD.log`. This was discovered on 2026-03-24 when a multi-package UPS tracking failure occurred and there was no log file to diagnose it.

**Root cause:** `src/logger.py` `setup_logger()` line 19 has a guard: `if logger.handlers: return logger`. This prevents adding duplicate handlers on repeated calls. But in the Streamlit path, `app.py` adds a `StreamlitLogHandler` to the `qpss` logger *before* calling `run_flow2()` (or `run_flow1()`). When `run_flow2()` then calls `setup_logger()`, it sees the StreamlitLogHandler and returns early — the `FileHandler` and `StreamHandler` are never added.

**Fix — `src/logger.py`:** Change the guard on line 19 from:

```python
if logger.handlers:
    return logger
```

To:

```python
if any(isinstance(h, logging.FileHandler) for h in logger.handlers):
    return logger
```

This checks specifically for a `FileHandler` instead of any handler. Effect:
- **CLI path (unchanged):** No handlers exist → adds FileHandler + StreamHandler as before.
- **Streamlit path (fixed):** StreamlitLogHandler exists but no FileHandler → adds FileHandler + StreamHandler. Log lines now go to both the UI and disk.
- **Repeated calls (unchanged):** FileHandler already exists → skips, no duplicates.

**One file changed:** `src/logger.py` — one line.

**How to verify:** Run Flow 2 (dry run is fine) through the Streamlit UI on IS-APP-19. Check `C:\QPSS-middleware\logs\` — a `qpss-2026-03-24.log` file should exist. Then run the same flow from the CLI batch file — confirm it still writes to the same log file without errors.

**After deploying this fix:** Re-run Flow 2 (not dry run) through the Streamlit UI so the next multi-package UPS shipment produces a log file. That log will tell us exactly why child tracking numbers are not being assigned — whether the UPS client is not being called, the API is returning warnings that trigger the early-exit path, or there's a count mismatch. Do NOT attempt to fix the UPS tracking bug until we have log data.

### 2026-03-24 — UPS child tracking still broken (pending diagnosis)

**Symptom:** SHIP0000448306 (3-package UPS shipment, 2026-03-24):
- Box 1 tracking: `1Z88XW192094472336` (correct — this is the master)
- Box 2 tracking: `1Z88XW192094472336` (wrong — should be `1Z88XW192093919347`)
- Box 3 tracking: `1Z88XW192094472336` (wrong — should be `1Z88XW192092306555`)

All three boxes got the master tracking number. The per-package child tracking numbers exist in UPS but were not assigned.

**This was the first run through the Streamlit UI**, and also the first real end-to-end test of multi-package UPS tracking since the carrier detection fix (2026-03-18) was merged to main.

**No log file exists** for this run (see logging bug above). We cannot determine the root cause without logs.

**Top hypothesis:** `ups_client.py` lines 86–91 — the `warnings` check returns `[]` immediately if the UPS API response contains *any* warning, even informational ones that accompany valid package data. This would cause the fallback to master tracking on all packages. But this is unconfirmed.

**Other possibilities:**
1. `_build_ups_client()` returning `None` (config issue — less likely since credentials were verified)
2. Count mismatch between UPS response and pending JSON package count
3. UPS API returning all packages with the master tracking number (least likely — user confirmed correct child numbers exist)

**Action:** Fix the logging bug first. Deploy to server. Run Flow 2 again. Read the log. Then we diagnose and fix the tracking bug based on actual data.

---

## Implementation Notes

### 2026-03-16 — Implementation complete + tested

**Credential verification (Step 0):**
- UPS OAuth 2.0 token endpoint works — got a valid Bearer token
- `carrierCode` for UPS in ShipStation is simply `"ups"` (lowercase)

**Endpoint fix:**
- Originally used `/track/v1/details/{trackingNumber}` (single-package endpoint) — only returned 1 package
- Fixed to `/track/v1/shipment/details/{trackingNumber}` (shipment-level endpoint) — returns ALL packages

**Multi-package UPS shipments tested (4 shipments):**

| Order | Ship Date | Packages | Result |
|-------|-----------|----------|--------|
| SHIP0000446908 | 2026-01-07 | 2 | 2 distinct tracking numbers returned |
| SHIP0000446339 | 2025-12-03 | 4 | 4 distinct tracking numbers returned |
| SHIP0000446819 | 2026-01-03 | 2 | 2 distinct tracking numbers returned |
| SHIP0000446968 | 2026-01-08 | 10 | 10 distinct tracking numbers returned |

**UPS API response structure (confirmed):**
```json
{
  "trackResponse": {
    "shipment": [{
      "inquiryNumber": "1Z...",
      "package": [
        { "trackingNumber": "1Z...(master)", "packageCount": 2, "currentStatus": {...} },
        { "trackingNumber": "1Z...(child)", "packageCount": 2, "currentStatus": {...} }
      ]
    }]
  }
}
```
Warnings array appears instead of package array when tracking not found.

**How to find multi-package orders in ShipStation:**
- `customField3` is NOT at the top-level order object — it's in `advancedOptions.customField3`
- Value is `"Multi package"` (lowercase 'p')
- ShipStation `/shipments` endpoint doesn't expose this field at all — must check `/orders`

**Files changed:**
1. `src/ups_client.py` — NEW: UPSClient class with OAuth token caching + `get_child_tracking()` using `/track/v1/shipment/details/`
2. `config.ini.example` — Added `[ups]` section with placeholder credentials
3. `config.ini` — Added `[ups]` section with real credentials
4. `src/xml_generator.py` — `generate_out_files()` and `_build_detail_out()` now accept optional `package_tracking: list[str]` parameter; uses positional assignment when list has correct count
5. `qpss_middleware.py` — Added `UPSClient` import, `_build_ups_client()` helper, conditional UPS call in `run_flow2()` loop

**Branch:** `ups-tracking` (created from `main`)
**Commit:** `0677c32 Add UPS multi-package tracking integration to Flow 2`
**Pushed to origin:** 2026-03-16
**Server (C:\QPSS-middleware):** checked out to `ups-tracking` branch, ready for testing

### Next steps (2026-03-17)
1. **Test multi-package UPS shipment end-to-end.** Run Flow 2 on the server against a real multi-package UPS shipment. Verify the DETAILOUT XML has distinct tracking numbers per DetailLine.
2. **If test passes:** merge `ups-tracking` into `main` and deploy.
3. **If test fails:** switch server back to `main` (`git checkout main`) and investigate.

### 2026-03-18 — Carrier detection bug fix (commits 4a9de04 + 55c0ec6)

**Bug fix (`4a9de04`):** Changed UPS carrier detection from `shipment.carrierCode` (always null in ShipStation V1) to `tracking.startswith("1Z")` (UPS tracking number prefix). Also simplified by reusing the existing `tracking` variable instead of a separate `master` variable.

**Merge from main (`55c0ec6`):** Merged `main` into `ups-tracking` to pick up the duplicate-check feature. No conflicts.

**Architect review: Passed.** Fix matches spec, merge is clean, no issues found.

**Next:** Push to origin, pull on server, re-test Flow 2 with SHIP0000474171 (or a new multi-package UPS shipment). Logs should now show UPS client activity and distinct tracking numbers per DetailLine.

### 2026-03-18 — Duplicate-check branch merged to main

`claude/shipstation-duplicate-check-J1Cgp` merged into `main` and pushed to origin (commit `12179ef`). This branch modified `qpss_middleware.py` (Flow 1 duplicate order detection).

**Coder action required:** Before merging `ups-tracking` into `main`, first merge `main` into `ups-tracking` to pick up the duplicate-check changes. Both branches modify `qpss_middleware.py` so there may be merge conflicts to resolve. Do this after the carrier detection bug fix is committed.

### Deployment notes
- Alice has been testing in the TEST environment and thinks we can go live 2026-03-17.
- Server is already on `ups-tracking` branch for testing.
- **Server also needs `git pull origin main` on `main` to pick up the duplicate-check merge.**
- To merge after successful test: `git checkout main && git merge ups-tracking && git push origin main`
- To roll back if needed: `git checkout main` (instant, no data loss)
- After merge, clean up: `git branch -d ups-tracking && git push origin --delete ups-tracking`

### Streamlit Web UI — Spec approved, ready for implementation

Single-page web app to trigger and monitor the middleware from a browser on the internal network.

**Server:** IS-APP-19 (`C:\QPSS-middleware`)

**Prerequisites:**
- [x] Requested Windows Firewall inbound rule for TCP port **8501** (internal/LAN only) from MSP
- [x] MSP confirmed: Windows Firewall not enabled (behind FortiGate physical firewall)

**Users:** Human (developer), Alice, Amy (warehouse associate). No authentication needed.

**Branch:** Build on `ups-tracking` (already includes everything from `main`).

---

#### What the UI does

- **Run flows:** Buttons to trigger Flow 1, Flow 2. Dry-run checkbox.
- **Interactive prompts:** When a flow asks a question (e.g., "Sage 300 failed — Continue or Abort?"), the UI shows buttons instead of a terminal prompt. The flow pauses until the user responds.
- **Live log output:** Log lines stream in real-time while a flow is running.
- **Previous run:** Shows log from the last completed run (in-memory only, lost on app restart — real history is in daily log files on disk).
- **Pending files summary:** Shows count and oldest file age on page load. If files exist, offers a cleanup action with configurable age threshold (default 90 days).
- **No concurrent runs:** Buttons disabled while a flow is running.

#### Layout

```
┌──────────────────────────────────────────────────┐
│  QPSS Middleware                                 │
├──────────────────────────────────────────────────┤
│  ┌─ Run ────────────────────────────────────┐    │
│  │ [▶ Flow 1]   [▶ Flow 2]   [☐ Dry Run]   │    │
│  └──────────────────────────────────────────┘    │
│                                                  │
│  ┌─ Pending Files ──────────────────────────┐    │
│  │ 12 files · oldest: 87 days               │    │
│  │ Age threshold: [90] days  [Clean Up]      │    │
│  └──────────────────────────────────────────┘    │
│                                                  │
│  ┌─ Live Output ────────────────────────────┐    │
│  │ (log lines stream here while running)    │    │
│  │                                          │    │
│  │ ┌─ PROMPT ────────────────────────────┐  │    │
│  │ │ Sage 300 connection failed.         │  │    │
│  │ │ [Continue without items] [Abort]    │  │    │
│  │ └────────────────────────────────────┘  │    │
│  └──────────────────────────────────────────┘    │
│                                                  │
│  ┌─ Previous Run ───────────────────────────┐    │
│  │ Flow 1 · 2026-03-22 14:32 · 5 processed │    │
│  │ (collapsible full log)                   │    │
│  └──────────────────────────────────────────┘    │
└──────────────────────────────────────────────────┘
```

#### File changes

| File | Action | Purpose |
|------|--------|---------|
| `app.py` | **NEW** | Streamlit entry point |
| `src/ui_bridge.py` | **NEW** | Log handler + prompt bridge between middleware and Streamlit |
| `qpss_middleware.py` | EDIT | Add `prompt_fn` parameter to `run_flow1()` and `run_cleanup_pending()` |
| `requirements.txt` | EDIT | Add `streamlit` |

#### Callback refactor — changes to `qpss_middleware.py`

Two functions get an optional `prompt_fn` parameter:

1. **`run_flow1(config, dry_run=False, prompt_fn=None)`**
2. **`run_cleanup_pending(config, days, prompt_fn=None)`**

`run_flow2` is unchanged (no prompts).

If `prompt_fn` is `None`, default to `input()` — CLI behavior is unchanged. Batch files and `main()` are untouched.

Signature: `prompt_fn(message: str, choices: list[str]) -> str`

Example — Sage 300 prompt changes from:
```python
choice = input("    [C]ontinue without items, or [A]bort? ").strip().upper()
```
to:
```python
choice = prompt_fn(
    "Sage 300 database connection failed.\n"
    "[C]ontinue without items for all orders, or [A]bort?",
    ["C", "A"]
)
```

The `print()` calls around each prompt (banners, held-order lists, cleanup file listings) become `logger.info()` calls so they appear in both CLI and Streamlit output. Formatted to stay human-readable.

#### `src/ui_bridge.py` — new file

**`StreamlitLogHandler`** — `logging.Handler` subclass that appends formatted log records to a thread-safe list. Streamlit reads this list to render live output.

**`StreamlitPromptBridge`** — manages the prompt/response handshake:
- Middleware thread calls `bridge.prompt(message, choices)` → stores the question, blocks on `threading.Event`
- Streamlit main loop detects `bridge.pending_prompt`, renders buttons
- User clicks a button → Streamlit calls `bridge.respond(choice)` → sets the Event, unblocking the middleware thread

#### `app.py` — new file

**Session state:** `running` (bool), `flow_thread` (Thread), `bridge` (PromptBridge), `log_lines` (list), `last_run` (dict: flow, timestamp, summary, log_lines).

**Execution flow:**
1. User clicks flow button → spawns `threading.Thread` with `prompt_fn=bridge.prompt`
2. Streamlit auto-refreshes to poll for new log lines and pending prompts
3. When prompt detected → render buttons. On click → `bridge.respond()` + rerun
4. Thread completes → save log to `last_run`, clear running state

**Pending files section:**
- On page load: scan Pending folder, show count + oldest age
- If files exist: number input for threshold (default 90), "Clean Up" button
- Clean Up uses same thread/prompt pattern (has Y/N confirmation)

**Buttons disabled while running** to prevent concurrent execution.

**Previous Run:** shows which flow, when, summary line. Expandable for full log.

#### Deployment steps

1. Install Streamlit: `C:\QPSS-middleware\.venv\Scripts\pip install streamlit`
2. Test locally on server: `streamlit run app.py --server.address 0.0.0.0 --server.port 8501`
3. Verify access from another machine on the LAN at `http://IS-APP-19:8501`
4. Create a **Windows Task Scheduler** task to run Streamlit at system startup:
   - Action: `C:\QPSS-middleware\.venv\Scripts\streamlit.exe run C:\QPSS-middleware\app.py --server.address 0.0.0.0 --server.port 8501`
   - Run whether user is logged on or not
   - Restart on failure

#### Constraints

- No changes to Flow 2 logic
- CLI still works identically (`prompt_fn=None` → `input()`)
- No authentication
- No concurrent runs
- No persistent run history (last run in memory only)
- No branch switching in UI

---

### Streamlit UI Refinements — Spec (2026-03-22)

**Files changed:** `app.py` + new `.streamlit/config.toml`. No middleware or bridge changes.

#### 0. Hide the Streamlit deploy button

Create `.streamlit/config.toml` in the `prototype/` directory:

```toml
[ui]
hideDeployButton = true
```

#### 1. Page header

- `st.title("QPSS Middleware")`
- `st.caption("QuikPAK / ShipStation Integration")` — gives context if someone bookmarks the page

#### 2. Status banner

At the top, below the header, show a persistent status indicator:
- **Idle:** `st.info("Ready")` (or no banner at all — up to the Coder's judgment)
- **Running:** `st.info("Running: Send Orders to ShipStation...")` (or whichever flow)
- **Done (success):** `st.success("Done — 5 orders processed, 0 errors")` — extracted from the SUMMARY log line
- **Done (with errors):** `st.error("Finished with 2 errors — check log below")`

This tells Amy at a glance what's happening, even if she scrolled away from the output.

#### 3. Friendlier labels and descriptions

Rename buttons and add descriptions. Amy needs to understand what each button does without asking.

**Button labels:**
- "Flow 1 Push Orders" → **"Send Orders to ShipStation"**
- "Flow 2 Query Shipments" → **"Get Tracking from ShipStation"**

**Descriptions (use `st.caption()` below each button):**
- Send Orders: *"Reads new orders from QuikPAK and pushes them to ShipStation. May ask you to decide what to do if Sage 300 is unavailable."*
- Get Tracking: *"Checks ShipStation for shipped orders and writes tracking info back to QuikPAK."*
- Dry Run checkbox: *"Test mode — shows what would happen without actually sending orders or moving files."*

#### 4. Split the Run section: controls left, output right

Replace the current vertical layout with a left/right split using `st.columns([1, 2])`:

```
┌─ Left column (~1/3) ─────────────┐  ┌─ Right column (~2/3) ─────────────┐
│                                   │  │                                   │
│  [Send Orders to ShipStation]     │  │  ┌─ Output (bordered) ──────────┐ │
│  caption: Reads new orders...     │  │  │                              │ │
│                                   │  │  │  14:32 | Scanning...         │ │
│  [Get Tracking from ShipStation]  │  │  │  14:32 | Found 3 pair(s)    │ │
│  caption: Checks ShipStation...   │  │  │  ...                         │ │
│                                   │  │  │                              │ │
│  ☐ Dry Run                        │  │  │  ┌─ PROMPT (warning) ─────┐  │ │
│  caption: Test mode...            │  │  │  │ Sage 300 unavailable.  │  │ │
│                                   │  │  │  │ [Continue] [Abort]     │  │ │
│                                   │  │  │  └────────────────────────┘  │ │
│                                   │  │  │                              │ │
│                                   │  │  └──────────────────────────────┘ │
└───────────────────────────────────┘  └───────────────────────────────────┘
```

**Left column:** Wrap in `st.container(border=True)`. Add vertical spacing (`st.write("")` or similar) between the buttons so they aren't crammed together.

**Right column:** Wrap the output area in `st.container(border=True)`. Show "Output" label when idle, "Live Output" when running.

#### 5. Prompt styling

Prompts must visually stand out — they're "this needs your attention" moments:
- Use `st.warning()` inside the output container
- **Use full-word button labels**, not letter codes. The middleware sends `["C", "A"]` but the UI should map these to readable labels:
  - `C` → "Continue without items"
  - `A` → "Abort"
  - `P` → "Push all without items"
  - `S` → "Skip all (retry later)"
  - `Y` → "Yes, delete"
  - `N` → "No, cancel"
- The bridge still sends the single letter back to the middleware — only the button *label* changes.

#### 6. Cleaner log display

The raw log lines with timestamps and pipe separators are dense for warehouse users. In the live output and previous run log:
- Strip the timestamp prefix from each line for display (e.g., show `INFO | Found 3 pair(s)` not `14:32:01 | INFO | Found 3 pair(s)`)
- Keep using `st.code()` (monospace) but consider `language=None` for a lighter background
- The full timestamped log is still written to disk — this is just the UI display

#### 7. Previous Run section

Placed **below** the Run section, **above** Pending Files. Only shown when a completed run exists.

- Bordered container
- One-line summary: `st.caption("Get Tracking from ShipStation · 2026-03-22 14:32 · 5 processed, 0 errors")`
- `st.expander("Full log")` with the complete log inside
- Separated from the Run section with `st.divider()`

#### 8. Pending Files — collapsible, at the bottom

Wrap in `st.expander()`. Include the count and age in the expander label: `"Pending Files (12 files · oldest: 87 days)"`. If no files: `"Pending Files (none)"`.

Inside the expander:
- Description: *"Orders that were sent to ShipStation but haven't shipped yet. Old files may be cancelled or test orders that can be cleaned up."*
- Age threshold input + Clean Up button
- Separated from Previous Run with `st.divider()`

#### 9. Page order (top to bottom)

1. Title + subtitle
2. Status banner
3. Run section (left: controls, right: output) — bordered containers
4. `st.divider()`
5. Previous Run — bordered container with collapsible log
6. `st.divider()`
7. Pending Files — collapsible expander

#### 10. Bug fix: flow doesn't return to Ready when done

**Problem:** After a flow completes, the UI stays in the "running" state. The user has to manually refresh the page to get back to Ready. The status banner, buttons, and output don't update.

**Root cause:** The background thread sets `st.session_state["running"] = False` when the flow finishes, but Streamlit's main loop has already stopped rerunning (the `time.sleep(1) + st.rerun()` polling loop exits when the thread signals completion, but the timing means the final rerun sees `running=False` before the last state update is rendered). There may also be a race between the thread writing to session state and Streamlit reading it.

**Fix:** Use `st.empty()` containers or Streamlit's callback mechanism to ensure a final rerun happens after the thread completes. One reliable approach:
- In the polling loop, after detecting the thread is no longer alive (`not thread.is_alive()`), do one final state update (save `last_run`, clear `running`, clear `flow_thread`) and then `st.rerun()` to render the idle state.
- Make sure the `running` check and the `thread.is_alive()` check are handled in the right order — check `is_alive()` *first*, then check `running`.

The Coder should test this by running Flow 2 with dry run (fast, no prompts) and confirming the UI returns to Ready without a manual refresh.

---

### Deployment Notes (2026-03-22)

**Server:** IS-APP-19 at `192.168.0.3`

**Current state (2026-03-23):**
- `ups-tracking` merged into `main` (fast-forward). Server is on `main`.
- Streamlit running via Task Scheduler (`QPSS Streamlit UI` task) on IS-APP-19.
- Accessible at `http://IS-APP-19:8501` or `http://192.168.0.3:8501` from LAN.
- Task Scheduler configured as "Run only when user is logged on" + trigger "At log on" for SRV_APP (needed for Tornado event loop — "Run whether user is logged on or not" causes `RuntimeError: Event loop is closed`).
- **Known issue:** A console window remains visible on the server desktop even with the Task Scheduler "Hidden" checkbox enabled. Not user-facing (only visible via RDP), but should be addressed. Options to investigate: NSSM (run as a Windows service), a VBS wrapper to launch the batch file hidden, or `pythonw.exe` instead of `python.exe`.

**Environment:**
- No `.venv` — everything is installed in the system Python (`C:\Users\SRV_APP\AppData\Roaming\Python\Python314\`)
- Streamlit version: 1.55.0
- `hideDeployButton` config option was removed in this Streamlit version — delete that line from `.streamlit/config.toml` (or leave the file empty as it is now)

**Startup quirks:**
- Streamlit prompts for an email on first run. Must be run interactively (RDP, local PowerShell) the first time so you can press Enter to dismiss. After that it doesn't ask again.
- Remote PowerShell sessions (Enter-PSSession) have no interactive stdin, so Streamlit exits immediately on the email prompt. This is a one-time issue — once dismissed via RDP, it won't recur.
- Credentials file is at `C:\Users\SRV_APP\.streamlit\credentials.toml`

**Remaining deployment steps (pick up at step 4):**

#### Step 4 — Task Scheduler

On IS-APP-19, open **Task Scheduler** and create a new task:

- **Name:** `QPSS Streamlit UI`
- **General tab:**
  - Run whether user is logged on or not
  - Check "Run with highest privileges"
- **Triggers tab:**
  - New trigger → "At startup"
- **Actions tab:**
  - Action: Start a program
  - Program: `C:\Progra~1\Python314\python.exe`
  - Arguments: `-m streamlit run C:\QPSS-middleware\app.py --server.address 0.0.0.0 --server.port 8501`
  - Start in: `C:\QPSS-middleware`
  - Note: Must use the short path `Progra~1` to avoid spaces in "Program Files" — Task Scheduler doesn't handle quoted paths in the Program field.
- **Settings tab:**
  - Check "If the task fails, restart every 1 minute"
  - Attempt restart up to 3 times
  - Do **not** check "Stop the task if it runs longer than..." (it runs indefinitely)

Click OK. Enter the service account credentials when prompted.

**Note:** Task Scheduler runs non-interactively, same as remote PowerShell. The email prompt must already be dismissed (via prior RDP session) or the credentials.toml must work. Verify by right-clicking the task → Run, then checking `http://192.168.0.3:8501` from a browser.

#### Step 5 — Verify and close the RDP PowerShell window

Once Task Scheduler is confirmed working, close the temporary PowerShell window that's currently running Streamlit.

### 2026-03-22 — Streamlit UI refinements + bug fix (commits f13963a + c105b9c)

**Initial implementation (f13963a):**
- `app.py` — NEW: Streamlit entry point
- `src/ui_bridge.py` — NEW: StreamlitLogHandler + StreamlitPromptBridge (thread-safe log capture and prompt/response handshake)
- `.streamlit/config.toml` — NEW (initially had hideDeployButton, later emptied)
- `qpss_middleware.py` — Added `prompt_fn` parameter to `run_flow1()` and `run_cleanup_pending()`, replaced 3 `input()` calls, converted `print()` banners to `logger.info()`
- `requirements.txt` — Added `streamlit>=1.30.0`

**Layout refinements + bug fix (c105b9c):**
- Status banner: Ready / Running / Done (success) / Finished with errors
- Friendly button labels: "Send Orders to ShipStation", "Get Tracking from ShipStation"
- `st.caption()` descriptions under each button and dry-run checkbox
- Prompt letter codes mapped to full-word labels (C → "Continue without items", etc.)
- Timestamps stripped from log display (full log still on disk)
- Left/right column layout with bordered containers
- Previous Run section with collapsible full log, above Pending Files
- Pending Files in collapsible `st.expander()` with count in label
- **Bug fix:** Flow completion race condition — now checks `thread.is_alive()` before the `running` flag so the final state update + rerun always fires
- Removed deprecated `hideDeployButton` from `.streamlit/config.toml` (removed in Streamlit 1.55.0)

**Confirmed working** on IS-APP-19 (2026-03-22). Human verified flow runs and returns to Ready state without manual refresh.
