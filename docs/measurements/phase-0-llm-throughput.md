# Bootstrap LLM throughput measurements

Phase 0 acceptance: target >=30 mutations/hour on this hardware.
The model column shows the LiteLLM alias and the actual Ollama tag in parens
(driven by `OLLAMA_MODEL` env per T1.5).

| date (UTC) | model (tag) | N | latency median | latency p90 | throughput |
|---|---|---|---|---|---|

_Rows appended by `scripts/measure_llm_throughput.py` — run via `make measure-llm`._
