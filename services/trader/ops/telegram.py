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
    ) -> None:
        self.halt = halt
        self.reporter = reporter
        self.token = token

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

    def poll(self) -> None:
        """Long-poll Telegram for commands. Requires a token (no offline path)."""
        if not self.token:
            raise RuntimeError("no token")
        import httpx  # noqa: PLC0415 (lazy: only the real path needs the network)

        base = f"{_TELEGRAM_API}/bot{self.token}"
        offset = 0
        with httpx.Client(timeout=35.0) as client:
            while True:
                resp = client.get(
                    f"{base}/getUpdates",
                    params={"offset": offset, "timeout": 30},
                )
                resp.raise_for_status()
                for update in resp.json().get("result", []):
                    offset = update["update_id"] + 1
                    message = update.get("message", {})
                    text = message.get("text")
                    chat = message.get("chat", {})
                    chat_id = chat.get("id")
                    if not text or chat_id is None:
                        continue
                    reply = self.handle(text)
                    client.post(
                        f"{base}/sendMessage",
                        json={"chat_id": chat_id, "text": reply},
                    )
