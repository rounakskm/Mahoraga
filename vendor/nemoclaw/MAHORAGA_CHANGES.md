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

_None yet._

## Conventions for adding entries

When a Tier 3 patch is applied:

1. Tag the diff in source with `// MAHORAGA-PATCH(YYYY-MM-DD): <reason>`.
2. Record below: date, files touched, scope, reason, upstream-PR status.
