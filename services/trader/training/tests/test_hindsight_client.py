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


# --- the enabled path: assert the REAL vendored API paths/bodies via a stub ---
# (vendor/hindsight/hindsight-api-slim/hindsight_api/api/http.py)


class _Fake(HindsightClient):
    """Records the calls _post would have made instead of hitting the network."""

    def __init__(self, **kw):
        super().__init__(base_url="http://hindsight:8888", **kw)
        self.posts: list[tuple[str, dict]] = []
        # RetainResponse / RecallResponse shapes from the vendored API.
        self.retain_return: dict = {
            "success": True, "bank_id": "mahoraga-trader", "items_count": 1,
            "async": False,
        }
        self.recall_return: dict = {
            "results": [{"id": "f1", "text": "hi", "type": "experience",
                         "metadata": {"candidate_hash": "abc"}}],
        }

    def _post(self, path: str, payload: dict) -> dict:
        self.posts.append((path, payload))
        if path.endswith("/memories/recall"):
            return self.recall_return
        return self.retain_return


def test_enabled_retain_posts_items_to_memories_endpoint():
    c = _Fake()
    marker = c.retain("a trade context", {"regime": "trending", "n": 3})
    assert marker is not None  # success marker on the real success:true response
    path, payload = c.posts[-1]
    assert path == f"/v1/default/banks/{c.bank}/memories"
    (item,) = payload["items"]
    assert item["content"] == "a trade context"
    # metadata values are coerced to strings (API schema: dict[str, str])
    assert item["metadata"] == {"regime": "trending", "n": "3"}


def test_enabled_recall_posts_query_and_returns_results_list():
    c = _Fake()
    out = c.recall("query text", k=3)
    assert out == c.recall_return["results"]
    path, payload = c.posts[-1]
    assert path == f"/v1/default/banks/{c.bank}/memories/recall"
    assert payload["query"] == "query text"


def test_enabled_recall_slices_to_k():
    c = _Fake()
    c.recall_return = {"results": [{"id": str(i), "text": "t"} for i in range(9)]}
    assert len(c.recall("q", k=2)) == 2


def test_enabled_reflect_posts_query():
    c = _Fake()
    assert c.reflect() is None
    path, payload = c.posts[-1]
    assert path == f"/v1/default/banks/{c.bank}/reflect"
    assert isinstance(payload["query"], str) and payload["query"]


def test_first_failure_warns_once_then_stays_quiet(caplog):
    c = HindsightClient("http://127.0.0.1:9/unreachable", timeout=0.05)
    with caplog.at_level("WARNING", logger="services.trader.training.hindsight_client"):
        assert c.retain("x", {}) is None
        assert c.recall("x") == []
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1  # one-time, not per-call
