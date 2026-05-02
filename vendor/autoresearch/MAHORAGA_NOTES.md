# Mahoraga adaptation of karpathy/autoresearch

**Status:** Frozen one-time copy. We do not pull updates from upstream.

## What was copied

- `LICENSE` — preserved verbatim (MIT)
- `program.md` → `program.md.upstream` — kept as reference; the Mahoraga-adapted version lives at `training/program.md` (Phase 3)
- `README.md` → `README.md.upstream` — kept as reference

## What was discarded

- `prepare.py` — language-modeling data prep; not applicable to backtesting
- `train.py` — GPT model code; loop scaffolding pattern was studied but our loop lives at `training/loop.py` (Phase 3 task)

## License obligations

- Preserve `vendor/autoresearch/LICENSE` verbatim
- Preserve copyright notice when adapting program.md content into `training/program.md` (Phase 3 task)

## Upstream reference

- Repository: https://github.com/karpathy/autoresearch
- Copied at commit: 228791fb499afffb54b46200aca536f79142f117 (2026-03-25)
- Project description: Autonomous AI research agent that self-modifies training code and experiments overnight
