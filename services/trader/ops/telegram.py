"""TelegramOps — the operator's chat surface for the kill-switch (Task 14).

Three commands trip or read the running fleet: `/halt [reason]`, `/resume`, and
`/status`. `.handle(command)` is pure routing over `HaltControl` + `Reporter` and
returns the reply text, so it works fully offline (`token=None`) for tests and
local use. `.poll()` is the real long-poll loop and runs only when a token is set;
without one it refuses (there is no bot to talk to).

# ponytail: httpx is imported lazily inside `.poll()` so the module imports with
# no network deps present — the offline path never touches it.
"""

from __future__ import annotations

from .halt import HaltControl
from .reporter import Reporter

_HELP = (
    "Mahoraga ops commands:\n"
    "  /halt [reason] — trip the kill-switch\n"
    "  /resume — clear the kill-switch\n"
    "  /status — fleet status"
)

_TELEGRAM_API = "https://api.telegram.org"


class TelegramOps:
    def __init__(
        self,
        halt: HaltControl,
        reporter: Reporter,
        token: str | None = None,
        allowed_chat_ids: set[str] | None = None,
    ) -> None:
        self.halt = halt
        self.reporter = reporter
        self.token = token
        # None -> open (offline/test path); a set -> only those chat ids may
        # drive the kill-switch. Unknown chats are silently ignored (no reply).
        self.allowed_chat_ids = allowed_chat_ids

    def handle(self, command: str) -> str:
        """Route a raw command line to the halt control / reporter; return reply."""
        parts = command.strip().split(maxsplit=1)
        if not parts:
            return _HELP
        verb = parts[0]
        rest = parts[1].strip() if len(parts) > 1 else ""
        if verb == "/halt":
            reason = rest or "operator halt"
            self.halt.halt(reason)
            return f"Halted. Reason: {reason}"
        if verb == "/resume":
            self.halt.resume()
            return "Resumed. Kill-switch cleared."
        if verb == "/status":
            return self.reporter.status().render()
        return _HELP

    def _should_act(self, update: dict) -> bool:
        """True when this poll update carries a text command from an allowed chat."""
        message = update.get("message", {})
        text = message.get("text")
        chat_id = message.get("chat", {}).get("id")
        if not text or chat_id is None:
            return False
        return self.allowed_chat_ids is None or str(chat_id) in self.allowed_chat_ids

    def _poll_once(self, client, base: str, offset: int) -> int:
        """One getUpdates round-trip; returns the next offset."""
        resp = client.get(
            f"{base}/getUpdates",
            params={"offset": offset, "timeout": 30},
        )
        resp.raise_for_status()
        for update in resp.json().get("result", []):
            offset = update["update_id"] + 1
            if not self._should_act(update):
                continue  # unauthorized / non-text: ignore, reply nothing
            message = update["message"]
            reply = self.handle(message["text"])
            client.post(
                f"{base}/sendMessage",
                json={"chat_id": message["chat"]["id"], "text": reply},
            )
        return offset

    def poll(self) -> None:
        """Long-poll Telegram for commands. Requires a token (no offline path)."""
        if not self.token:
            raise RuntimeError("no token")
        import time  # noqa: PLC0415

        import httpx  # noqa: PLC0415 (lazy: only the real path needs the network)

        base = f"{_TELEGRAM_API}/bot{self.token}"
        offset = 0
        with httpx.Client(timeout=35.0) as client:
            while True:
                try:
                    offset = self._poll_once(client, base, offset)
                except Exception:  # transient HTTP error must not kill the loop
                    time.sleep(2.0)
