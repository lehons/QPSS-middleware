"""
File manager for scanning, pairing, and moving QuikPAK XML files.

Scans QuikPAKIN folder for HeaderIn/DetailIn pairs matched by ShipmentID.
Moves processed files to Processed or Error subfolders.
"""

import os
import re
import shutil
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("qpss")

# Patterns to extract ShipmentID from filenames
# HeaderIn_SHIP0000447526_20260213-063014.xml
# DetailIn_SHIP0000447526_20260213-063014.xml
# Also supports TEST-prefixed IDs: HeaderIn_TEST0000000001_20260222-120000.xml
_HEADER_PATTERN = re.compile(r"^HeaderIn_([A-Za-z]+\d+)_.*\.xml$", re.IGNORECASE)
_DETAIL_PATTERN = re.compile(r"^DetailIn_([A-Za-z]+\d+)_.*\.xml$", re.IGNORECASE)


@dataclass
class FilePair:
    """A matched HeaderIn + DetailIn file pair."""
    shipment_id: str
    header_path: str
    detail_path: str


def scan_for_pairs(in_folder: str) -> list[FilePair]:
    """Scan QuikPAKIN folder and return matched HeaderIn/DetailIn pairs.

    Only looks at files directly in the folder (not subfolders).
    Logs warnings for orphaned files (header without detail or vice versa).
    """
    if not os.path.isdir(in_folder):
        logger.error(f"QuikPAKIN folder does not exist: {in_folder}")
        return []

    headers: dict[str, str] = {}  # shipment_id -> file path
    details: dict[str, str] = {}  # shipment_id -> file path

    for filename in os.listdir(in_folder):
        filepath = os.path.join(in_folder, filename)
        if not os.path.isfile(filepath):
            continue

        header_match = _HEADER_PATTERN.match(filename)
        if header_match:
            sid = header_match.group(1)
            headers[sid] = filepath
            continue

        detail_match = _DETAIL_PATTERN.match(filename)
        if detail_match:
            sid = detail_match.group(1)
            details[sid] = filepath

    # Match pairs
    pairs = []
    all_ids = set(headers.keys()) | set(details.keys())

    for sid in sorted(all_ids):
        has_header = sid in headers
        has_detail = sid in details

        if has_header and has_detail:
            pairs.append(FilePair(
                shipment_id=sid,
                header_path=headers[sid],
                detail_path=details[sid],
            ))
        elif has_header and not has_detail:
            logger.error(f"{sid} | HeaderIn found but no matching DetailIn — orphaned file")
        elif has_detail and not has_header:
            logger.error(f"{sid} | DetailIn found but no matching HeaderIn — orphaned file")

    return pairs


def move_to_processed(pair: FilePair, processed_folder: str) -> None:
    """Move both files of a pair to the Processed folder."""
    _move_file(pair.header_path, processed_folder)
    _move_file(pair.detail_path, processed_folder)
    logger.debug(f"{pair.shipment_id} | Files moved to Processed")


def move_to_error(pair: FilePair, error_folder: str, error_message: str) -> None:
    """Move both files to the Error folder and create a .error.txt companion."""
    _move_file(pair.header_path, error_folder)
    _move_file(pair.detail_path, error_folder)

    # Write error description file
    error_txt_name = f"{pair.shipment_id}.error.txt"
    error_txt_path = os.path.join(error_folder, error_txt_name)
    try:
        with open(error_txt_path, "w", encoding="utf-8") as f:
            f.write(f"ShipmentID: {pair.shipment_id}\n")
            f.write(f"Error: {error_message}\n")
    except OSError as e:
        logger.error(f"{pair.shipment_id} | Failed to write error file: {e}")

    logger.debug(f"{pair.shipment_id} | Files moved to Error")


def _move_file(src: str, dest_folder: str) -> None:
    """Move a single file to a destination folder, creating it if needed."""
    os.makedirs(dest_folder, exist_ok=True)
    filename = os.path.basename(src)
    dest = os.path.join(dest_folder, filename)

    # If destination already exists, add a numeric suffix
    if os.path.exists(dest):
        base, ext = os.path.splitext(filename)
        counter = 1
        while os.path.exists(dest):
            dest = os.path.join(dest_folder, f"{base}_{counter}{ext}")
            counter += 1

    shutil.move(src, dest)
