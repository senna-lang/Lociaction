---
description: Handle session logs, raw transcripts, credentials, and private source code safely.
---

# Privacy

Session logs and stored exchanges may contain credentials, API keys, private file paths, personal data, and unpublished source code. Lociaction indexes that content locally. It does not redact it.

## Commands that emit raw or near-raw content

- `loci show` — stored `user_content` / `agent_content` for one exchange
- `loci dump` — distilled palace objects, which still quote concrete details
- `loci context --full` / `loci recall --session --full` — include verbatim fields

Session transcripts may contain credentials, private source code, paths, or personal data. Do not paste `loci show` or `loci dump` output into chat, issues, commits, or logs without reviewing and redacting it.

This applies to coding-agent responses too. Prefer summarizing what you learned over quoting the transcript.

## JSON and help

Privacy guidance lives in `--help` and in this document. Lociaction never mixes warning banners into `--json` stdout — that would break machine-readable output.

## Local data

Project state lives under `.lociaction/` (`memory.db`, `config.toml`, sockets, locks). Do not commit `.lociaction/`, personal session logs, or local model data. Distillation clients receive exchange text; a paid cloud CLI will send that text to the provider. Use `llamacpp-ft` or `openai-compat` against a local endpoint when the corpus must stay on the machine.

See `loci docs show distillation`.
