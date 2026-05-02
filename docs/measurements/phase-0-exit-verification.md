# Phase 0 — Exit Verification

**Date completed:** _(fill at exit)_
**Architecture spec gate:** Phase 0 acceptance per `../superpowers/specs/phase-0-substrate-bringup/spec.md` §3.

| Acceptance criterion | Status |
|---|---|
| `git subtree add` lands NemoClaw cleanly | ✓ |
| `git subtree pull` exercise (no-op pull) clean | _(operator runs)_ |
| `docker compose up` brings Postgres + LiteLLM sidecars online | _(operator runs)_ |
| Postgres migrations apply; pgvector + 5 schemas + audit table | _(operator runs `tests/integration/phase-0/test_postgres_migrations.py`)_ |
| LiteLLM gateway answers calls against >=2 providers (Ollama + Anthropic) | _(operator runs)_ |
| `nemoclaw onboard` provisions the OpenClaw sandbox | _(operator runs `scripts/onboard.sh`)_ |
| Sandbox responds to a basic prompt within 30s | _(operator runs `tests/integration/phase-0/test_sandbox_smoke.py`)_ |
| Halt smoke: `nemoclaw stop` suspends within 1s; audit row written | _(operator runs `tests/integration/phase-0/test_halt_smoke.py`)_ |
| CI pipeline runs lint + unit + postgres smoke; green on `phase-0-substrate-bringup` | _(after push to GitHub)_ |
| Bootstrap LLM throughput measured and recorded | _(operator runs `make measure-llm`)_ |
| README documents `make up`, `make test`, `make down`, `make env-check`, `make measure-llm`, and the onboard flow | ✓ |

**Bootstrap throughput:** see [`phase-0-llm-throughput.md`](phase-0-llm-throughput.md). Result: __ mutations/hour (target >=30).

**Phase 1 readiness:** _GO / NO-GO based on throughput; describe any mitigations needed._

**Open items carried into Phase 1:**
- Verify the constructed `vendor/autoresearch/LICENSE` (we built an MIT template since upstream ships no LICENSE file but README declares MIT). Confirm with karpathy or accept as fair-use representation.
- (List any other deferred items at exit.)

**Tag:**

```bash
git tag -a phase-0-complete -m "Phase 0 substrate bring-up complete"
```
