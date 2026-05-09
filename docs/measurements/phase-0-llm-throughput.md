# Bootstrap LLM throughput measurements

Phase 0 acceptance: target >=30 mutations/hour on this hardware.
The model column shows the LiteLLM alias and the actual Ollama tag in parens
(driven by `OLLAMA_MODEL` env per T1.5).

| date (UTC) | model (tag) | N | latency median | latency p90 | throughput |
|---|---|---|---|---|---|

_Rows appended by `scripts/measure_llm_throughput.py` — run via `make measure-llm`._
| 2026-05-09T09:36:00.833117+00:00 | ollama/gemma4 (gemma4-cpu:e4b) | 10 | 8.28s median | 8.56s p90 | 434.6/hr |
