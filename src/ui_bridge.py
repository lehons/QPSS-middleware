"""
Streamlit UI bridge — connects the middleware (running in a background thread)
to the Streamlit front-end.

Two components:
  StreamlitLogHandler  — logging.Handler that captures log records for live display.
  StreamlitPromptBridge — thread-safe prompt/response handshake so Streamlit can
                          render buttons for mid-flow questions.
"""

import logging
import threading


class StreamlitLogHandler(logging.Handler):
    """Logging handler that appends formatted log records to a thread-safe list.

    Streamlit reads ``handler.lines`` to render live output.
    """

    def __init__(self):
        super().__init__()
        self._lock = threading.Lock()
        self.lines: list[str] = []
        self.setFormatter(logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(message)s",
            datefmt="%H:%M:%S",
        ))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            with self._lock:
                self.lines.append(msg)
        except Exception:
            self.handleError(record)

    def get_lines(self) -> list[str]:
        """Return a snapshot of all captured lines."""
        with self._lock:
            return list(self.lines)

    def clear(self) -> None:
        with self._lock:
            self.lines.clear()


class StreamlitPromptBridge:
    """Thread-safe prompt/response bridge between a middleware thread and Streamlit.

    Middleware thread calls ``bridge.prompt(message, choices)`` which blocks
    until the Streamlit main loop calls ``bridge.respond(choice)``.

    Streamlit detects a pending prompt via ``bridge.pending_prompt``.
    """

    def __init__(self):
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._message: str | None = None
        self._choices: list[str] | None = None
        self._response: str | None = None

    # -- called by middleware thread ------------------------------------------

    def prompt(self, message: str, choices: list[str]) -> str:
        """Display *message* to the user and block until they pick a choice.

        Returns the chosen string (one of *choices*).
        This is passed as ``prompt_fn`` to the middleware functions.
        """
        with self._lock:
            self._message = message
            self._choices = choices
            self._response = None
            self._event.clear()

        # Block until Streamlit calls respond()
        self._event.wait()

        with self._lock:
            return self._response  # type: ignore[return-value]

    # -- called by Streamlit main loop ----------------------------------------

    @property
    def pending_prompt(self) -> tuple[str, list[str]] | None:
        """Return ``(message, choices)`` if a prompt is waiting, else ``None``."""
        with self._lock:
            if self._message is not None and self._response is None:
                return (self._message, self._choices or [])
        return None

    def respond(self, choice: str) -> None:
        """Deliver the user's choice to the blocked middleware thread."""
        with self._lock:
            self._response = choice
            self._message = None
            self._choices = None
        self._event.set()

    def reset(self) -> None:
        """Clear any pending state (e.g. between runs)."""
        with self._lock:
            self._message = None
            self._choices = None
            self._response = None
            self._event.clear()
