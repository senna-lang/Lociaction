---
description: Choose among `loci context`, `loci search`, `loci recall`, and `loci show` when retrieving past work.
---

# Recall

The primary user of these commands is the coding agent. Prefer `--json`. Empty JSON results are `[]`. Warnings go to stderr; success stdout is JSON only.

Do not paste `loci show` or `loci dump` output into chat, issues, commits, or logs without reviewing it. See `loci docs show privacy`.

## `loci context` — recall from code (primary)

Use this before editing a symbol or file.

```bash
# File + symbol (primary)
loci context src/lociaction/search.py:search_combined --json

# File only
loci context src/lociaction/search.py --json

# Line number (IDE selection); resolved to the enclosing symbol
loci context src/lociaction/search.py:142 --json

# Branch
loci context --branch feature/foo --json
```

If there is no exact hit, lociaction widens the search (same file → same directory → semantic) and returns a confidence score. Each hit may include a `context` array of related exchanges (`ply_adjacent`, `parent_session`). Those supporting entries have no confidence score.

`--symbol` remains as a compatibility flag. Prefer the positional `<file>[:<symbol-or-line>]` form.

## `loci search` — semantic query (secondary)

Use this when you do not know which file or symbol to look at.

```bash
loci search "BM25 RRF fusion ranking" --json --limit 5
loci search "connection pool" --branch feature/db-pool --json
```

Results include `exchange_id`, `score`, distilled fields, symbols, `verbatim_ref`, and `git_branch`.

## `loci recall` — resume-style session browser

```bash
# Newest sessions
loci recall --json

# Rank sessions by keyword relevance
loci recall "grouped query attention" --json

# One session's digest (prefix of session_id is enough)
loci recall --session abcdef123456 --json

# Filter either mode
loci recall --file src/foo.py --json
loci recall --branch feat --json
```

`--session` cannot be combined with a keyword query.

## `loci show` — stored verbatim exchange

```bash
loci show "<exchange_id>" --json
```

Use `exchange_id` from `context` / `search` / `recall`, not `verbatim_ref`. `loci show` also returns ply-adjacent neighbors in `context`; chain on those ids to walk further.

`loci dump` lists distilled palace objects (newest first). It is for inspection, not day-to-day recall.
