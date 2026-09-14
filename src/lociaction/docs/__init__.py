"""Package marker for bundled agent-facing documentation.

Markdown topics in this directory are the single source of truth for
`loci docs list` / `loci docs show`. They are shipped as package data so an
installed wheel serves version-matched documentation without network access,
a `.lociaction/` project, an embedding server, or a distillation client.
"""
