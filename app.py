"""
QPSS Middleware — Streamlit Web UI

Single-page app to trigger and monitor the middleware from a browser.
Run with:  streamlit run app.py --server.address 0.0.0.0 --server.port 8501
"""

import configparser
import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timedelta

import streamlit as st

from src.ui_bridge import StreamlitLogHandler, StreamlitPromptBridge

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Map single-letter prompt choices to friendly button labels.
# The bridge still sends the letter back to the middleware.
_CHOICE_LABELS = {
    "C": "Continue without items",
    "A": "Abort",
    "P": "Push all without items",
    "S": "Skip all (retry later)",
    "Y": "Yes, delete",
    "N": "No, cancel",
}

# Friendly names for flows (used in status banner + previous run)
_FLOW_NAMES = {
    "flow1": "Send Orders to ShipStation",
    "flow2": "Get Tracking from ShipStation",
    "cleanup": "Clean Up Pending Files",
}

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------


def _load_config() -> configparser.ConfigParser:
    config_path = os.path.join(_SCRIPT_DIR, "config.ini")
    config = configparser.ConfigParser()
    config.read(config_path, encoding="utf-8")
    return config


def _get_pending_folder(config: configparser.ConfigParser) -> str:
    folder = config.get("paths", "quikpak_pending", fallback="")
    if not folder:
        folder = os.path.join(_SCRIPT_DIR, "QuikPAK", "Pending")
    return folder


# ---------------------------------------------------------------------------
# Pending files helpers
# ---------------------------------------------------------------------------


def _scan_pending(pending_folder: str) -> tuple[int, int | None]:
    """Return (count, oldest_age_days) for JSON files in the pending folder."""
    if not os.path.isdir(pending_folder):
        return 0, None

    now = datetime.now()
    oldest = None
    count = 0

    for fname in os.listdir(pending_folder):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(pending_folder, fname)
        if not os.path.isfile(fpath):
            continue
        count += 1

        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            created_str = data.get("created_at", "")
            if created_str:
                created = datetime.fromisoformat(created_str)
            else:
                created = datetime.fromtimestamp(os.path.getmtime(fpath))
        except Exception:
            created = datetime.fromtimestamp(os.path.getmtime(fpath))

        age = (now - created).days
        if oldest is None or age > oldest:
            oldest = age

    return count, oldest


# ---------------------------------------------------------------------------
# Log display helpers
# ---------------------------------------------------------------------------

# Matches "HH:MM:SS | " at the start of a log line (the timestamp prefix
# added by the StreamlitLogHandler formatter).
_TIMESTAMP_RE = re.compile(r"^\d{2}:\d{2}:\d{2} \| ")


def _strip_timestamps(lines: list[str]) -> list[str]:
    """Remove the timestamp prefix from log lines for cleaner UI display."""
    return [_TIMESTAMP_RE.sub("", line) for line in lines]


# ---------------------------------------------------------------------------
# Status banner helpers
# ---------------------------------------------------------------------------


def _extract_summary(lines: list[str]) -> str:
    """Pull the SUMMARY line from log output."""
    for line in reversed(lines):
        if "SUMMARY" in line:
            # Strip timestamp and "SUMMARY: " prefix for a clean string
            clean = _TIMESTAMP_RE.sub("", line)
            clean = clean.replace("INFO     | ", "").replace("INFO | ", "")
            clean = clean.replace("SUMMARY: ", "")
            return clean.strip("- ")
    return ""


def _show_status_banner():
    """Render a status banner reflecting the current/last run state."""
    running = st.session_state["running"]
    flow_key = st.session_state.get("current_flow", "")
    flow_name = _FLOW_NAMES.get(flow_key, flow_key)

    if running:
        st.info(f"Running: {flow_name}...")
        return

    last_run = st.session_state.get("last_run")
    if last_run:
        summary = last_run.get("summary", "")
        if "error" in summary.lower() and "0 error" not in summary.lower():
            st.error(f"Finished with errors \u2014 {summary}")
        else:
            st.success(f"Done \u2014 {summary}")
    else:
        st.info("Ready")


# ---------------------------------------------------------------------------
# Thread runner
# ---------------------------------------------------------------------------


def _run_in_thread(
    target,
    config: configparser.ConfigParser,
    bridge: StreamlitPromptBridge,
    log_handler: StreamlitLogHandler,
    flow_key: str,
    **kwargs,
):
    """Run *target(config, ..., prompt_fn=bridge.prompt)* in a daemon thread."""
    logger = logging.getLogger("qpss")

    def wrapper():
        logger.addHandler(log_handler)
        try:
            target(config, prompt_fn=bridge.prompt, **kwargs)
        except Exception as exc:
            logger.error(f"Unhandled exception: {type(exc).__name__}: {exc}")
        finally:
            logger.removeHandler(log_handler)
            st.session_state["running"] = False

    t = threading.Thread(target=wrapper, daemon=True)
    st.session_state["flow_thread"] = t
    st.session_state["running"] = True
    st.session_state["current_flow"] = flow_key
    t.start()


def _run_flow2_in_thread(
    config: configparser.ConfigParser,
    log_handler: StreamlitLogHandler,
    dry_run: bool,
):
    """run_flow2 has no prompt_fn — special-case wrapper."""
    from qpss_middleware import run_flow2

    logger = logging.getLogger("qpss")

    def wrapper():
        logger.addHandler(log_handler)
        try:
            run_flow2(config, dry_run=dry_run)
        except Exception as exc:
            logger.error(f"Unhandled exception: {type(exc).__name__}: {exc}")
        finally:
            logger.removeHandler(log_handler)
            st.session_state["running"] = False

    t = threading.Thread(target=wrapper, daemon=True)
    st.session_state["flow_thread"] = t
    st.session_state["running"] = True
    st.session_state["current_flow"] = "flow2"
    t.start()


# ---------------------------------------------------------------------------
# Session state initialisation
# ---------------------------------------------------------------------------


def _init_state():
    defaults = {
        "running": False,
        "flow_thread": None,
        "bridge": StreamlitPromptBridge(),
        "log_handler": StreamlitLogHandler(),
        "last_run": None,
        "current_flow": "",
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------


def main():
    st.set_page_config(page_title="QPSS Middleware", layout="wide")
    _init_state()

    config = _load_config()
    bridge: StreamlitPromptBridge = st.session_state["bridge"]
    log_handler: StreamlitLogHandler = st.session_state["log_handler"]
    running: bool = st.session_state["running"]

    # ── 1. Title + subtitle ────────────────────────────────────────
    st.title("QPSS Middleware")
    st.caption("QuikPAK / ShipStation Integration")

    # ── 2. Status banner ───────────────────────────────────────────
    _show_status_banner()

    # ── 3–4. Run section — left (controls) / right (output) ───────
    left_col, right_col = st.columns([1, 2])

    with left_col:
        with st.container(border=True):
            if st.button("Send Orders to ShipStation", disabled=running,
                          use_container_width=True):
                bridge.reset()
                log_handler.clear()
                from qpss_middleware import run_flow1

                _run_in_thread(
                    run_flow1, config, bridge, log_handler,
                    flow_key="flow1",
                    dry_run=st.session_state.get("dry_run", False),
                )
                st.rerun()
            st.caption("Reads new orders from QuikPAK and pushes them to "
                       "ShipStation. May ask you to decide what to do if "
                       "Sage 300 is unavailable.")

            st.write("")  # spacing

            if st.button("Get Tracking from ShipStation", disabled=running,
                          use_container_width=True):
                bridge.reset()
                log_handler.clear()
                _run_flow2_in_thread(
                    config, log_handler,
                    dry_run=st.session_state.get("dry_run", False),
                )
                st.rerun()
            st.caption("Checks ShipStation for shipped orders and writes "
                       "tracking info back to QuikPAK.")

            st.write("")  # spacing

            st.checkbox("Dry Run", disabled=running, key="dry_run")
            st.caption("Test mode \u2014 shows what would happen without "
                       "actually sending orders or moving files.")

    with right_col:
        with st.container(border=True):
            st.subheader("Live Output" if running else "Output")

            # ── 5. Interactive prompt with friendly labels ─────────
            pending_prompt = bridge.pending_prompt
            if pending_prompt:
                message, choices = pending_prompt
                st.warning(message)
                prompt_cols = st.columns(len(choices))
                for i, choice in enumerate(choices):
                    label = _CHOICE_LABELS.get(choice, choice)
                    if prompt_cols[i].button(label, key=f"prompt_{choice}"):
                        bridge.respond(choice)
                        st.rerun()

            # ── 6. Log lines (timestamps stripped) ─────────────────
            lines = log_handler.get_lines()
            if lines:
                st.code("\n".join(_strip_timestamps(lines)), language=None)

            # Auto-refresh while running
            if running:
                time.sleep(1)
                st.rerun()
            else:
                # Flow just finished — save to last_run
                thread = st.session_state.get("flow_thread")
                if thread is not None and not thread.is_alive() and lines:
                    flow_key = st.session_state.get("current_flow", "")
                    flow_name = _FLOW_NAMES.get(flow_key, flow_key)
                    summary = _extract_summary(lines)

                    st.session_state["last_run"] = {
                        "flow_name": flow_name,
                        "timestamp": datetime.now().strftime(
                            "%Y-%m-%d %H:%M"),
                        "summary": summary,
                        "log_lines": list(lines),
                    }
                    st.session_state["flow_thread"] = None
                    st.rerun()

    # ── 7. Previous Run ───────────────────────────────────────────
    last_run = st.session_state.get("last_run")
    if last_run and not running:
        st.divider()
        with st.container(border=True):
            st.subheader("Previous Run")
            st.caption(
                f"{last_run.get('flow_name', '')} \u00b7 "
                f"{last_run['timestamp']} \u00b7 "
                f"{last_run['summary']}"
            )
            with st.expander("Full log"):
                st.code(
                    "\n".join(_strip_timestamps(last_run["log_lines"])),
                    language=None,
                )

    # ── 8. Pending Files — collapsible, at the bottom ─────────────
    st.divider()

    pending_folder = _get_pending_folder(config)
    p_count, p_oldest = _scan_pending(pending_folder)

    if p_count == 0:
        expander_label = "Pending Files (none)"
    else:
        oldest_str = (f" \u00b7 oldest: {p_oldest} days"
                      if p_oldest is not None else "")
        expander_label = f"Pending Files ({p_count} files{oldest_str})"

    with st.expander(expander_label, expanded=False):
        st.caption(
            "Orders that were sent to ShipStation but haven't shipped yet. "
            "Old files may be cancelled or test orders that can be cleaned up."
        )
        if p_count == 0:
            st.info("No pending files.")
        else:
            col_a, col_b = st.columns([1, 2])
            threshold = col_a.number_input(
                "Age threshold (days)", min_value=1, value=90,
                disabled=running,
            )
            with col_b:
                st.write("")  # spacer
                st.write("")
                if st.button("Clean Up", disabled=running):
                    bridge.reset()
                    log_handler.clear()
                    from qpss_middleware import run_cleanup_pending

                    _run_in_thread(
                        run_cleanup_pending, config, bridge, log_handler,
                        flow_key="cleanup",
                        days=int(threshold),
                    )
                    st.rerun()


if __name__ == "__main__":
    main()
