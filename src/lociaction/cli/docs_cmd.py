"""loci docs — version-matched documentation shipped with the installed package.

Does not require `.lociaction/`, network, an embedding server, or a distill
client. Markdown topics live in `lociaction.docs` and are read via
importlib.resources so an installed wheel matches this CLI version.
"""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Annotated, NamedTuple

import typer

DOCS_PACKAGE = "lociaction.docs"
SHOW_HELP = "Run `loci docs show <name>` to read a document."

docs_app = typer.Typer(
    help="Show version-matched documentation shipped with this install"
)


class DocTopic(NamedTuple):
    name: str
    description: str
    body: str


def _parse_frontmatter(text: str) -> tuple[str, str]:
    """Return (description, body). Body excludes a leading `---` description block."""
    if not text.startswith("---\n"):
        return "", text
    rest = text[4:]
    end = rest.find("\n---")
    if end < 0:
        return "", text
    header = rest[:end]
    body = rest[end + 4 :]
    if body.startswith("\n"):
        body = body[1:]
    description = ""
    for line in header.splitlines():
        if line.startswith("description:"):
            description = line[len("description:") :].strip()
            break
    return description, body


def load_topics() -> list[DocTopic]:
    root = files(DOCS_PACKAGE)
    topics: list[DocTopic] = []
    for entry in root.iterdir():
        filename = entry.name
        if not filename.endswith(".md"):
            continue
        text = entry.read_text(encoding="utf-8")
        description, body = _parse_frontmatter(text)
        topics.append(DocTopic(name=filename[:-3], description=description, body=body))
    topics.sort(key=lambda topic: topic.name)
    return topics


def load_topic(name: str) -> DocTopic | None:
    for topic in load_topics():
        if topic.name == name:
            return topic
    return None


@docs_app.command("list")
def docs_list(
    json_output: Annotated[bool, typer.Option("--json", help="JSON output")] = False,
) -> None:
    """List bundled documentation topics."""
    topics = load_topics()
    if json_output:
        payload = {
            "results": [
                {"name": topic.name, "description": topic.description}
                for topic in topics
            ],
            "help": SHOW_HELP,
        }
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    if not topics:
        typer.echo("No documents found.")
        return
    width = max(len(topic.name) for topic in topics)
    for topic in topics:
        typer.echo(f"{topic.name.ljust(width)}  {topic.description}")
    typer.echo()
    typer.echo(SHOW_HELP)


@docs_app.command("show")
def docs_show(
    name: Annotated[str, typer.Argument(help="Document name from `loci docs list`")],
) -> None:
    """Print a bundled documentation topic."""
    topic = load_topic(name)
    if topic is None:
        names = ", ".join(item.name for item in load_topics())
        typer.echo(f"Unknown document: {name}", err=True)
        typer.echo(f"Available: {names}", err=True)
        typer.echo("Run `loci docs list` to discover documents.", err=True)
        raise typer.Exit(1)
    typer.echo(topic.body, nl=False)
    if topic.body and not topic.body.endswith("\n"):
        typer.echo()
