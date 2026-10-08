# Qwen and vLLM on a 12 GB laptop GPU

Research date: 2026-09-01

## Recommendation

Run one persistent vLLM deployment and use the same model and OpenAI-compatible endpoint for both workloads:

- statement extraction/classification sends an independent request with a strict JSON schema, bounded input batches, non-thinking mode, and deterministic or near-deterministic sampling;
- the Financial Assistant sends its own message history and tool schemas, with tool calling enabled;
- the application schedules chat ahead of background statement work and records separate prompt/model configurations for the two roles.

Do **not** redeploy or restart vLLM between classification and chat requests. A restart is needed when changing model weights or server configuration, or when recovering from a fault—not to prevent one request's conversation from leaking into another.

Start with [`Qwen/Qwen3-8B-AWQ`](https://huggingface.co/Qwen/Qwen3-8B-AWQ/tree/main). It is an official 4-bit AWQ checkpoint whose repository is about 6.11 GB, leaving substantially more of a 12 GB GPU for the serving runtime and KV cache than the 14B checkpoint. Then benchmark [`Qwen/Qwen3-14B-AWQ`](https://huggingface.co/Qwen/Qwen3-14B-AWQ) as a stretch candidate: Qwen identifies it as 14.8B parameters, 4-bit AWQ, with 32,768 native context, while its official repository is about 9.99 GB. The claim that 8B has safer headroom and 14B is tight is an engineering estimate from checkpoint size, not a vendor guarantee.

## Why one endpoint is safe

The Chat Completions API receives the messages for each request; the client/application is responsible for sending the intended conversation history. vLLM allocates KV-cache blocks to requests and frees a finished request's blocks when no active request references them. Its optional automatic prefix cache may retain full blocks for later reuse and evicts them using LRU. Reuse occurs by matching token-prefix hashes; it is a computation optimization, not hidden conversational memory. vLLM describes prefix caching as avoiding recomputation without changing model outputs. See the [vLLM OpenAI-compatible server](https://docs.vllm.ai/en/latest/serving/online_serving/openai_compatible_server/) and [automatic prefix-caching design](https://docs.vllm.ai/en/latest/design/prefix_caching/).

Consequences:

- classification cannot inherit chat history unless the application mistakenly includes that history in the classification request;
- chat cannot inherit a statement prompt merely because the requests shared an endpoint;
- clearing the KV cache is not required between request types;
- restarting only discards a useful optimization and adds downtime/model-loading cost.

Prefix caching does have a cross-tenant timing side channel. vLLM recommends `cache_salt` for multi-tenant isolation, while explicitly saying it is unnecessary for a single-tenant deployment. This application is single-user and cluster-internal, so no salt is required for the MVP. If the product later becomes multi-user, use a secret per-tenant salt and review the broader endpoint security boundary. See [vLLM security: cache salting](https://docs.vllm.ai/en/latest/usage/security/#cache-salting).

vLLM exposes a prefix-cache reset route only among development-mode endpoints and warns that development endpoints should not be enabled in production. That is another reason not to build routine cache clearing into the application. See [vLLM online serving: development mode](https://docs.vllm.ai/en/latest/serving/online_serving/#server-in-development-mode).

## Workload separation without separate deployments

Use two application-level inference profiles against the same model:

| Concern | Statement extraction/classification | Financial Assistant |
|---|---|---|
| Input | bounded statement or transaction batch | current conversation window plus selected tool results |
| Output | `response_format: json_schema`, then application validation | natural language and zero or one tool call per turn initially |
| Thinking | disabled initially | disabled initially; evaluate thinking separately |
| Sampling | explicit low-variance settings | explicit Qwen-recommended non-thinking settings, then tune |
| Tools | bounded internal merchant-evidence lookup, executed by the host | allowlisted read-only MCP tools; proposals require confirmation |
| Scheduling | background priority | interactive priority |

vLLM supports JSON-schema response formats and structured outputs in its OpenAI-compatible API. It also supports request priorities when the server uses `--scheduling-policy priority`; lower values run earlier. See [structured response formats](https://docs.vllm.ai/en/latest/serving/online_serving/openai_compatible_server/#extra-parameters) and [priority scheduling](https://docs.vllm.ai/en/latest/cli/serve/#scheduling-policy).

Prefer an application job queue even when vLLM priority scheduling is enabled. It provides a stable product rule—chat first, background work between interactive turns—and prevents a large statement batch from surprising the UI. Send a negative priority value for chat and the default or a positive value for background requests only after the behavior is covered by an integration test.

## Model candidates

### 1. Recommended baseline: Qwen3-8B-AWQ

[`Qwen/Qwen3-8B-AWQ`](https://huggingface.co/Qwen/Qwen3-8B-AWQ/tree/main) is an official Qwen 4-bit AWQ checkpoint of about 6.11 GB. Qwen's Qwen3 documentation uses the 8B model for vLLM function-calling examples and recommends Hermes-style tool use. The Qwen3 family supports 32K native context and extension with YaRN, but this application should start far below the advertised maximum. See [Qwen3 function calling](https://qwen.readthedocs.io/en/stable/framework/function_call.html) and the [Qwen3 release](https://qwenlm.github.io/blog/qwen3/).

Why it is the baseline: the extra VRAM headroom is likely to matter more than the 14B parameter count when the same server must retain KV capacity for both statement and interactive requests. This must still be verified on the exact laptop, driver, CUDA, container, and vLLM build.

### 2. Stretch candidate: Qwen3-14B-AWQ

[`Qwen/Qwen3-14B-AWQ`](https://huggingface.co/Qwen/Qwen3-14B-AWQ) is the closest clean match to the desired 14B size. The official model card states 14.8B parameters, 4-bit AWQ, and 32,768 native context (131,072 with YaRN). The [official repository](https://huggingface.co/Qwen/Qwen3-14B-AWQ/tree/main) is about 9.99 GB before runtime allocations and KV cache.

Treat 12 GB compatibility as unproven until measured. Begin with one sequence and a 4K context cap. If it starts and passes load tests, try 8K. Do not enable YaRN: Qwen warns that static YaRN can degrade shorter-context performance and recommends it only when long context is actually required.

### 3. Newer candidate that does not cleanly fit this trust boundary: Qwen3.5-9B

[`Qwen/Qwen3.5-9B`](https://huggingface.co/Qwen/Qwen3.5-9B) is newer, officially supports vLLM and tool calling, and Qwen documents a `qwen3_coder` tool parser. However, the [official checkpoint repository](https://huggingface.co/Qwen/Qwen3.5-9B/tree/main) is about 19.3 GB. No official Qwen 4-bit checkpoint was found in the sources reviewed. A 12 GB deployment would therefore require an independently published quantization or offloading, which introduces a separate artifact-quality and compatibility decision. Do not make it the MVP baseline without explicitly approving and evaluating that artifact.

### 4. Older fallback: Qwen2.5-14B-Instruct-AWQ

[`Qwen/Qwen2.5-14B-Instruct-AWQ`](https://huggingface.co/Qwen/Qwen2.5-14B-Instruct-AWQ) is an official 4-bit 14B-era checkpoint with a strong emphasis on structured/JSON output. It remains a reasonable A/B candidate for extraction and classification, but it should not displace Qwen3 for the MCP agent without task-specific evidence.

## Initial vLLM profiles

Use a pinned container/image digest after the exact GPU and CUDA combination passes a smoke test. Do not infer Blackwell/CUDA support from the model card alone.

Baseline 8B profile:

```bash
vllm serve Qwen/Qwen3-8B-AWQ \
  --host 0.0.0.0 \
  --port 8000 \
  --max-model-len 8192 \
  --max-num-seqs 2 \
  --gpu-memory-utilization 0.90 \
  --enable-prefix-caching \
  --scheduling-policy priority \
  --enable-auto-tool-choice \
  --tool-call-parser hermes \
  --reasoning-parser qwen3 \
  --generation-config vllm
```

The current Qwen guide uses Hermes-style tool parsing for Qwen3, and vLLM documents `--enable-auto-tool-choice` plus a model-appropriate parser as required for automatic tool choice. Qwen also warns that malformed tool calls remain possible, so the application must validate tool name and arguments and recover safely. See [Qwen function calling](https://qwen.readthedocs.io/en/stable/framework/function_call.html) and [vLLM tool calling](https://docs.vllm.ai/en/latest/features/tool_calling/).

`--generation-config vllm` prevents a model repository's `generation_config.json` from silently changing server defaults; callers should send explicit per-role sampling settings. vLLM documents this behavior in its [OpenAI-compatible server guide](https://docs.vllm.ai/en/latest/serving/online_serving/openai_compatible_server/).

For the 14B experiment, change only the model and begin conservatively:

```text
--max-model-len 4096
--max-num-seqs 1
--gpu-memory-utilization 0.90
```

If initialization or graph capture runs out of memory, vLLM recommends reducing `max_model_len` and `max_num_seqs`; `--enforce-eager` can additionally remove CUDA-graph capture memory at a performance cost. See [vLLM memory conservation](https://docs.vllm.ai/en/latest/configuration/conserving_memory/). Do not turn on CPU offload as the first fix because it changes latency substantially; evaluate the 8B model first.

These values are starting hypotheses, not production guarantees. Record vLLM version, image digest, driver, CUDA runtime, model revision, and measured cache capacity with every result.

## Evaluation gates

Do not select 14B merely because it starts. Compare 8B and 14B on the same redacted corpus and require all of the following:

1. **Runtime fit:** cold start succeeds repeatedly; no OOM during the longest allowed prompt/output; no unexplained worker restart.
2. **Financial extraction:** exact date, sign, amount, currency, description, and transaction-count accuracy; balance/statement-total validation is still deterministic and outside the model.
3. **Structured classification:** schema-valid response rate, allowed-enum rate, transaction coverage, category accuracy, movement-kind accuracy, payment-channel accuracy, and abstention/review quality.
4. **Agent tools:** valid tool-name rate, JSON-schema-valid arguments, correct choice of read-only tool, correct handling of empty/provisional results, and no mutation without a confirmed proposal flow.
5. **Grounded answers:** every financial claim traces to returned tool data; totals come from backend aggregates rather than model arithmetic.
6. **Shared-endpoint behavior:** chat latency while one background job is queued/running; background completion time; no OOM or pathological preemption; isolation tests proving that omitted chat history is not reproduced in unrelated requests.
7. **Operational envelope:** p50/p95 time to first token, tokens per second, peak VRAM, KV-cache usage, preemption count, and maximum safe prompt/output combination.

Promote the 14B model only if its task accuracy improvement is material and it still meets the interactive latency and stability budgets. Otherwise retain 8B and improve prompts, rules, deterministic validation, retrieval examples, and transaction batching first.

## Decision summary

- One model and endpoint for both roles: **yes**.
- Restart between classification and chat: **no**.
- Clear KV cache between roles: **no**.
- First model on 12 GB: **Qwen3-8B-AWQ**.
- 14B candidate: **Qwen3-14B-AWQ**, gated by a 4K/one-sequence test first.
- Qwen3.5-9B: promising, but not an official-checkpoint fit for 12 GB in the sources reviewed.
- Production controls: bounded contexts, explicit per-role sampling, structured-output validation, tool-argument validation, application scheduling, and pinned reproducible runtime versions.
