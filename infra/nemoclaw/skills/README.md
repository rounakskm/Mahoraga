# Hermes skills — audited promotion pipeline (Mitigation 2)

**Anchor:** [`docs/superpowers/specs/2026-06-12-hermes-runtime-migration.md`](../../../docs/superpowers/specs/2026-06-12-hermes-runtime-migration.md) §4, Mitigation 2.

Hermes is a self-evolving harness: after a task with ≥5 tool calls it writes a
`SKILL.md` (YAML frontmatter + learned procedure) on its own. That capability is
why we migrated to Hermes — but for a system that will trade real capital, the
agent's behavior must never change on the trading path in a way the operator
can't see, review, or revert. This directory enforces that.

## Two directories, one rule

```
infra/nemoclaw/skills/
├── agent_created/   ← Hermes writes auto-generated SKILL.md here. QUARANTINED.
│                       NEVER mounted to the live trading assistant's skills_dir.
└── stable/          ← operator-reviewed, promoted skills. THIS is skills_dir
                        in blueprint.yaml. Only these run on the trading path.
```

**The rule:** No auto-generated skill affects the trading path until a human
promotes it from `agent_created/` to `stable/`.

`blueprint.yaml` sets `agent.skills_dir: skills/stable/` — so the live assistant
only ever loads promoted skills. `agent_created/` is a staging area the operator
reviews out-of-band; it is bind-mounted read-write for Hermes to write into
(see `policies/filesystem.yaml`) but is **not** on the tool-resolution path.

## Promotion checklist

Before moving a skill from `agent_created/` to `stable/`, the operator confirms:

1. **Read every line.** The skill body is a procedure the agent will follow
   verbatim. Understand exactly what it does.
2. **Trading-path scrutiny.** If the skill references any data-read, signal-
   generation, risk-check, or order-routing tool, it gets heightened review —
   does it preserve PIT correctness, the vault embargo, and the hard risk
   limits? When in doubt, do not promote.
3. **No credential or egress surprises.** The skill must not attempt to reach
   hosts outside `policies/egress.yaml` or read paths outside
   `policies/filesystem.yaml`.
4. **Deterministic + idempotent** where it touches state.
5. **Record the promotion** — commit the moved file with a message noting why it
   was promoted and what it does. The git history is the audit trail.

## CI guard (lands with Phase 3)

A CI lint will fail the build if any skill under `agent_created/` references a
trading-execution tool — a backstop in case the quarantine directory is ever
mis-wired onto the live path. Tracked in the Phase-3 plan; until then the
directory convention + `skills_dir: skills/stable/` is the enforcement.

## Why not just disable self-evolution?

Because the self-evolution is the point of the Hermes migration — the agent gets
better at operational tasks (data wrangling, report formatting, KB hygiene)
without us hand-authoring every skill. We keep the upside and gate the blast
radius: skills accrue freely in `agent_created/`; only reviewed ones reach the
capital-touching path.
