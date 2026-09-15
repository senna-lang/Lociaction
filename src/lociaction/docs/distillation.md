---
description: Choose a distill client, understand billing vs local models, check readiness, and run setup.
---

# Distillation

Distillation turns indexed exchanges into palace objects (`exchange_core`, `specific_context`, room tags, symbols). One configured client processes every undistilled exchange, regardless of which harness produced it.

Do not trigger a paid client merely to make a test pass. Use a local model when token cost or data locality matters.

## Client identifiers

```text
claude-cli  codex-cli  gemini-cli  grok-cli  opencode-cli  omp-cli
llamacpp-ft   openai-compat
```

`.lociaction/config.toml`:

```toml
[distill]
client = "claude-cli"
model = "claude-haiku-4-5-20251001"    # optional; client default if omitted
batch_limit = 20
min_chars = 100                        # skip distillation for short indexed exchanges
```

`loci init` and `loci distill --setup` write `client`. The legacy `provider` + `base_url` form is still read.

## Setup and readiness

```bash
loci distill --setup
loci status --check
```

`--setup` rediscovers clients, offers local-model setup when appropriate, and saves the choice. `loci distill` without `--setup` uses the configured client.

If the configured client is not ready, lociaction does **not** silently switch. In a non-interactive run it prints the reason and skips. Reconfigure with `loci distill --setup`, or run `loci distill` in an interactive terminal.

If no client is configured:

```bash
loci distill --setup
```

## Local models

`loci init` may offer to `ollama pull` `qwen2.5-7b-memory-distiller` (~4.7GB) and select `llamacpp-ft`. Pass `--no-local-distiller` to skip that offer.

### `llamacpp-ft` (speculative decoding)

Ollama's `DRAFT` Modelfile path cannot accelerate this GGUF fine-tune (it is safetensors/MTP-only). `llamacpp-ft` instead starts an ephemeral `llama-server` for each `loci distill` run, with `--model-draft` against the same GGUF blobs Ollama already stored.

Requirements:

- `llama-server` on `PATH`, or `LOCI_LLAMACPP_SERVER` pointing at the binary
- the FT model blob (`loci distill --setup` can `ollama pull` it)
- draft model `qwen2.5:0.5b` by default (`ollama pull qwen2.5:0.5b`, or set `LOCI_LLAMACPP_DRAFT_MODEL=` to opt out)

The process binds `127.0.0.1` only and is stopped when the distill batch ends. GPU offload is left to llama.cpp unless you set `LOCI_LLAMACPP_GPU_LAYERS` / `LOCI_LLAMACPP_DRAFT_GPU_LAYERS`. Logs: `.lociaction/logs/llama-server.log`.

Selecting/setting up a client is still TTY-gated. An already-configured `llamacpp-ft` may run from a hook; it will not download models without you.

Any OpenAI-compatible local endpoint works as `openai-compat` (both `model` and `base_url` required). No `Authorization` header is sent unless the invoking user's own `LOCIACTION_DISTILL_API_KEY` environment variable is set — project config cannot set or request an API key, so a hostile `.lociaction/config.toml` cannot make lociaction send credentials it doesn't already have:

```toml
[distill]
client = "openai-compat"
model = "qwen2.5:7b"
base_url = "http://localhost:11434/v1"
```

Ollama's HTTP API is `openai-compat` with a loopback `base_url`. The bundled FT model uses `llamacpp-ft`.

## Remote OpenAI-compatible endpoints

Project-local `.lociaction/config.toml` can use only loopback endpoints by default.
This prevents a cloned or otherwise untrusted project configuration from silently
sending session text to a remote host. To use a remote endpoint, explicitly opt in
through the invoking user's environment, bound to the exact endpoint origin:

```bash
export LOCIACTION_REMOTE_DISTILL_ORIGINS=https://api.example.com
loci distill
```

Set this only for origins you trust. A project config cannot widen that allowlist.

## Paid CLI backends

If Claude / Codex / Gemini / Grok / OpenCode / Oh My Pi is installed and authenticated, select that id. Only clients actually on `PATH` appear as ready.

## Running distillation

```bash
loci distill
loci distill --limit 20
```

A lock file prevents overlapping distill runs. Failures are recorded; `loci status` shows the last distill error.
