"""loci show / loci dump コマンド"""

from __future__ import annotations

import json
from typing import Annotated, Any

import typer

from lociaction.utils import sanitize_terminal_text


def show(
    exchange_id: Annotated[str, typer.Argument(help="exchange id from search/context")],
    json_output: Annotated[bool, typer.Option("--json", help="JSON output")] = False,
) -> None:
    """Retrieve the stored verbatim exchange for an id.

    Also returns ply-adjacent neighbors in `context` (same additive lane as
    `loci context`). Chain `loci show` on those exchange ids to walk further.

    Session transcripts may contain credentials, private source code, paths, or
    personal data. Do not paste this output into chat, issues, commits, or logs
    without reviewing and redacting it.
    """
    from lociaction.context_lookup import ply_adjacent_context
    from lociaction.db import get_connection
    from lociaction.paths import db_path, find_project_root

    root = find_project_root()
    db = db_path(root)
    if not db.exists():
        from lociaction.cli.errors import abort_not_initialized

        abort_not_initialized()

    con = get_connection(db)
    row = con.execute(
        """
        SELECT e.id, e.user_content, e.agent_content, e.ply_start, e.ply_end,
               e.harness, e.session_ref, e.conversation_id, c.source_path
        FROM exchanges e
        JOIN conversations c ON c.id = e.conversation_id
        WHERE e.id = ?
        """,
        (exchange_id,),
    ).fetchone()

    if row is None:
        con.close()
        typer.echo(f"Exchange not found: {exchange_id}", err=True)
        raise typer.Exit(1)

    context = ply_adjacent_context(
        con, row["conversation_id"], row["id"], row["source_path"]
    )
    con.close()

    if json_output:
        typer.echo(
            json.dumps(
                {
                    "exchange_id": row["id"],
                    "user_content": row["user_content"],
                    "agent_content": row["agent_content"],
                    "ply_start": row["ply_start"],
                    "ply_end": row["ply_end"],
                    "harness": row["harness"],
                    "session_ref": row["session_ref"],
                    "context": [
                        {
                            "relation": s.relation,
                            "exchange_id": s.exchange_id,
                            "ply": s.ply,
                            "exchange_core": s.exchange_core,
                            "specific_context": s.specific_context,
                            "verbatim_ref": s.verbatim_ref,
                        }
                        for s in context
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        typer.echo(f"[User] (ply {row['ply_start']}-{row['ply_end']})")
        typer.echo(sanitize_terminal_text(row["user_content"]))
        typer.echo("\n[Agent]")
        typer.echo(sanitize_terminal_text(row["agent_content"]))
        for s in context:
            label = "前" if s.ply < row["ply_start"] else "後"
            preview = s.exchange_core or (s.user_content or "")[:80]
            typer.echo(
                f"\n[{label}: {s.exchange_id}] {sanitize_terminal_text(preview)}"
            )


def dump(
    distilled: Annotated[
        bool,
        typer.Option(
            "--distilled",
            help="Emit distilled palace objects (compatibility flag; this is the only mode)",
        ),
    ] = False,
    limit: Annotated[int, typer.Option("--limit", "-n", help="Maximum results")] = 1000,
    json_output: Annotated[bool, typer.Option("--json", help="JSON output")] = False,
) -> None:
    """Dump distilled palace objects, newest first.

    Session transcripts may contain credentials, private source code, paths, or
    personal data. Do not paste this output into chat, issues, commits, or logs
    without reviewing and redacting it.
    """
    from lociaction.db import get_connection
    from lociaction.paths import db_path, find_project_root

    root = find_project_root()
    db = db_path(root)
    if not db.exists():
        from lociaction.cli.errors import abort_not_initialized

        abort_not_initialized()

    con = get_connection(db)
    try:
        rows = con.execute(
            """
            SELECT p.id, p.exchange_id, p.exchange_core, p.specific_context,
                   e.distilled_at
            FROM palace_objects p
            JOIN exchanges e ON e.id = p.exchange_id
            ORDER BY e.distilled_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

        room_rows = []
        if rows:
            palace_ids = [r["id"] for r in rows]
            placeholders = ",".join("?" * len(palace_ids))
            room_rows = con.execute(
                f"""
                SELECT palace_object_id, room_type, room_key, room_label
                FROM rooms
                WHERE palace_object_id IN ({placeholders})
                ORDER BY relevance DESC
                """,
                palace_ids,
            ).fetchall()
    finally:
        con.close()

    if not rows:
        typer.echo("No distilled objects found.")
        return

    rooms_map: dict[str, list[Any]] = {}
    for r in room_rows:
        rooms_map.setdefault(r["palace_object_id"], []).append(
            {
                "room_type": r["room_type"],
                "room_key": r["room_key"],
                "room_label": r["room_label"],
            }
        )

    if json_output:
        output = [
            {
                "exchange_core": r["exchange_core"],
                "specific_context": r["specific_context"],
                "rooms": rooms_map.get(r["id"], []),
                "date": (r["distilled_at"] or "")[:10],
            }
            for r in rows
        ]
        typer.echo(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        for r in rows:
            date = (r["distilled_at"] or "")[:10]
            typer.echo(f"\n[{date}] {sanitize_terminal_text(r['exchange_core'])}")
            if r["specific_context"]:
                typer.echo(f"  {sanitize_terminal_text(r['specific_context'])}")
            for rm in rooms_map.get(r["id"], [])[:2]:
                typer.echo(f"  #{sanitize_terminal_text(rm['room_key'])}")
