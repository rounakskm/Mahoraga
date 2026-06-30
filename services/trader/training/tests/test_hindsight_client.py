"""Hindsight client: the graceful-offline contract is the load-bearing one.

`HindsightClient(base_url=None)` (or an unreachable endpoint) must be a safe no-op:
every call returns the empty default, never raises, and never touches the network —
exactly the `ProvenanceWriter(dsn=None)` pattern. A `_Fake` subclass stubs the
transport to assert the URL/bank shape only on the *enabled* path.
"""

from __future__ import annotations

from services.trader.training.hindsight_client import HindsightClient

# --- the offline / no-op contract (tested FIRST, must pass in isolation) ---


def test_disabled_when_base_url_none():
    c = HindsightClient(None)
    assert c.is_enabled() is False


def test_disabled_calls_are_safe_no_ops():
    c = HindsightClient(None)
    # no raise, empty defaults, and (implicitly) no network — there is no endpoint.
    assert c.retain("anything", {"k": "v"}) is None
    assert c.recall("anything") == []
    assert c.reflect() is None


def test_unreachable_endpoint_degrades_to_no_op():
    # a bogus endpoint must NOT raise — try/except fallback like llm.py.
    c = HindsightClient("http://127.0.0.1:9/unreachable")
    assert c.is_enabled() is True  # configured, just not reachable
    assert c.retain("x", {}) is None
    assert c.recall("x") == []
    assert c.reflect() is None


def test_default_bank():
    assert HindsightClient(None).bank == "mahoraga-trader"
    assert HindsightClient(None, bank="other").bank == "other"


# --- the enabled path: assert URL/bank shape via a transport stub ---


class _Fake(HindsightClient):
    """Records the calls _post/_get would have made instead of hitting the network."""

    def __init__(self, **kw):
        super().__init__(base_url="http://hindsight:8888", **kw)
        self.posts: list[tuple[str, dict]] = []
        self.gets: list[tuple[str, dict]] = []
        self.post_return: dict = {"id": "fact-123"}
        self.get_return: dict = {"results": [{"text": "hi", "score": 0.9}]}

    def _post(self, path: str, payload: dict) -> dict:
        self.posts.append((path, payload))
        return self.post_return

    def _get(self, path: str, params: dict) -> dict:
        self.gets.append((path, params))
        return self.get_return


def test_enabled_retain_posts_to_bank():
    c = _Fake()
    fact_id = c.retain("a trade context", {"regime": "trending"})
    assert fact_id == "fact-123"
    path, payload = c.posts[-1]
    assert c.bank in path or payload.get("bank") == c.bank
    assert payload["text"] == "a trade context"
    assert payload["metadata"] == {"regime": "trending"}


def test_enabled_recall_returns_results_list():
    c = _Fake()
    out = c.recall("query text", k=3)
    assert out == [{"text": "hi", "score": 0.9}]
    path, params = c.gets[-1]
    assert c.bank in path or params.get("bank") == c.bank


def test_enabled_reflect_posts():
    c = _Fake()
    assert c.reflect() is None
    path, _payload = c.posts[-1]
    assert "reflect" in path
