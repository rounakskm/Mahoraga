# Mahoraga modifications to NemoClaw

This file is the canonical record of any modifications made to the
vendored NemoClaw source tree under `vendor/nemoclaw/`. See architecture
spec §3 ("Three-tier extension model") — Tier 3 patches are last-resort.

## Vendored at

- Upstream: `https://github.com/NVIDIA/NemoClaw`
- Tag/SHA: `v0.0.38` (`c4aaec3bba3c9a1a1016c04dd4896b5ce1950f3f`)
- Date pulled: `2026-05-09`

### Vendoring history

| Date | Tag | SHA | Reason |
|---|---|---|---|
| 2026-04-26 | v0.0.27 | 6f7f0c6dd90c4c823923934d11a619beadc85f6b | Initial vendoring |
| 2026-05-09 | v0.0.38 | c4aaec3bba3c9a1a1016c04dd4896b5ce1950f3f | Phase 0 sandbox build under v0.0.27 failed at the OpenClaw post-install patch step (`replaceConfigFile`'s `writeConfigFile(params.nextConfig)` source pattern not found — OpenClaw shipped a new include-file mutation path between v0.0.27 and v0.0.38). v0.0.38 updates the patch script to match the newer OpenClaw shape and bumps `min_openclaw_version` to 2026.4.24. |

## Modifications

### 2026-06-12 — Unpin stale apt versions in Hermes base image

- **File:** `agents/hermes/Dockerfile.base` (the `apt-get install` block, ~line 32)
- **Scope:** Removed exact Debian version pins from the 16 OS packages
  (`python3`, `curl`, `libcap2-bin`, `socat`, …). Package names retained.
- **Reason:** Upstream pinned build-specific versions (e.g.
  `libcap2-bin=1:2.66-4+deb12u2+b2`). Debian's stable mirror keeps only the
  latest point-release of each package, so once a newer build shipped, the
  pinned version 404'd and `apt-get install` exited 100 — the Hermes base-image
  build failed and `nemoclaw onboard --agent hermes` aborted before sandbox
  creation. Discovered during the 2026-06-12 Rung-C bring-up.
- **Supply-chain note:** Integrity is still anchored by the upstream
  `HERMES_TARBALL_SHA256` + pinned `UV_VERSION` (unchanged). Only OS-package
  exact-version pinning was relaxed.
- **Upstream-PR status:** Not yet filed. Candidate to upstream to NVIDIA
  (`apt` exact-pin rot is a recurring base-image issue); track before the next
  subtree pull so the patch can be dropped if upstream fixes it.
- **Re-apply on subtree pull:** If a pull reverts this, re-check whether upstream
  switched to unpinned or snapshot.debian.org pins; re-apply only if still pinned
  to stale exact versions.

### 2026-06-20 — Add `mcp` extra to the Hermes base image

- **File:** `agents/hermes/Dockerfile.base` (`HERMES_UV_EXTRAS` build arg, ~line 29)
- **Scope:** `"messaging web"` -> `"messaging web mcp"`.
- **Reason:** The stock image omits the `mcp` extra, so the `mcp` Python package
  is absent and Hermes cannot act as an MCP **client** over any transport (HTTP
  fails with "mcp.client.streamable_http is not available"; stdio fails with
  "StdioServerParameters is not defined"). The agent venv is read-only, so the
  package can't be added at runtime — it must be baked into the image. Required
  for the Hindsight memory integration: Hermes reaches Hindsight via its MCP
  server. `mcp` is a first-class Hermes extra (`Provides-Extra: mcp`).
- **Upstream-PR status:** Not filed. Worth proposing to NVIDIA that the NemoClaw
  Hermes image include `mcp` by default (or expose HERMES_UV_EXTRAS at onboard).
- **Re-apply on subtree pull:** re-check `HERMES_UV_EXTRAS`; re-add `mcp` if a pull
  reverts it.

## Conventions for adding entries

When a Tier 3 patch is applied:

1. Tag the diff in source with `// MAHORAGA-PATCH(YYYY-MM-DD): <reason>`.
2. Record below: date, files touched, scope, reason, upstream-PR status.
