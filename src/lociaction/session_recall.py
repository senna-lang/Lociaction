"""
`loci recall` のセッション粒度ロジック（recall 再設計、2026-09）。

旧 recall は exchange 単位で context+search をマージし、recency 減衰
（半減期14日）でソートしていた。しかし semantic hit の confidence が一律
0.10 だったため実質的にソートは recency だけで決まり、「今このセッション」
の雑談 exchange が件数で押し寄せて古い実装セッションを覆い隠す問題があった
（issue: GQA実装セッションが直近の会話ノイズに埋もれた）。

再設計は Claude Code の `resume` に近い2段構成にする:
  1. セッション一覧 — 引数なしなら新しい順、キーワードありなら関連度順
     （exchange 単位の RRF スコアを session_id へ max 集約。sum にしないのは
     長いセッションが件数だけで勝たないようにするため）。
  2. セッション要点ダイジェスト — `palace_objects.exchange_core`（distill 済み
     "1行の決定"）を ply 順に並べるだけで、全文を返さない。distill は既に
     圧縮を終えている資産なので、ここで追加の LLM 呼び出しは要らない。

本モジュールは `context_lookup.py` と同じ設計方針を踏襲する: sqlite3.Connection
だけで完結し、書き込みは行わない。embedding・BM25/HNSW 実行は呼び出し側
（CLI 層）の責務とし、ここでは「exchange_id → score の辞書」を受け取って
session 単位に集約するところから始める。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass, field, replace

from lociaction.utils import escape_like

# セッション一覧に添えるタイトルの最大文字数（先頭 user メッセージの1行を要約）。
_TITLE_MAX_CHARS = 80

# ヘッドラインに載せる rooms / files の上限（design: Tier 0 ヘッドライン）。
_TOP_ROOMS_LIMIT = 5
_TOP_FILES_LIMIT = 8

# ダイジェストの既定行数上限（design: Tier 1 既定ダイジェスト）。
DEFAULT_DIGEST_LINES = 20

# セッション一覧の既定件数。
DEFAULT_LIST_LIMIT = 10


@dataclass(frozen=True)
class SessionSummary:
    """セッション一覧の1件（design: Tier 0 ヘッドライン相当）"""

    session_id: str
    harness: str
    git_branch: str | None
    started_at: str | None
    updated_at: str
    title: str
    exchange_count: int
    distilled_count: int
    files_touched: list[str] = field(default_factory=list)
    top_rooms: list[dict[str, str]] = field(default_factory=list)
    # キーワード一覧モードの関連度（RRF スコアの session 内 max）。新しい順一覧では None。
    score: float | None = None


@dataclass(frozen=True)
class DigestLine:
    """ダイジェストの1 exchange 分（design: Tier 1/2）"""

    exchange_id: str
    ply_start: int
    exchange_core: str | None
    distilled: bool
    specific_context: str | None = None
    user_content: str | None = None
    agent_content: str | None = None


@dataclass(frozen=True)
class SessionDigest:
    """`loci recall --session <id>` の1回分の応答"""

    summary: SessionSummary
    lines: list[DigestLine]
    total_exchanges: int

    @property
    def truncated_count(self) -> int:
        return max(0, self.total_exchanges - len(self.lines))


def summarize_title(user_content: str | None, max_chars: int = _TITLE_MAX_CHARS) -> str:
    """先頭 user メッセージの1行をタイトルとして要約する純関数。

    LLM を使わない決定的な合成（design A採用）: `sessions.title` は現状どの
    ハーネスアダプタも埋めておらず常に NULL のため、最初の user メッセージが
    実質的にタスク宣言文になっている実測に基づき、読み取り時にその場で合成する。
    """
    if not user_content:
        return "(empty)"
    first_line = user_content.strip().splitlines()[0].strip() if user_content.strip() else ""
    if not first_line:
        return "(empty)"
    if len(first_line) > max_chars:
        return first_line[: max_chars - 1].rstrip() + "…"
    return first_line


def _fetch_session_rows(
    con: sqlite3.Connection,
    session_ids: list[str] | None,
    *,
    file_path: str | None,
    alias_paths: tuple[str, ...],
    branch: str | None,
) -> list[sqlite3.Row]:
    """`sessions` をフィルタ付きで取得する。exchange が1件も無いセッションは
    「再開する対象が無い」ため除外する。
    """
    where = ["EXISTS (SELECT 1 FROM exchanges e WHERE e.session_id = s.id)"]
    params: list[object] = []

    if session_ids is not None:
        if not session_ids:
            return []
        placeholders = ",".join("?" * len(session_ids))
        where.append(f"s.id IN ({placeholders})")
        params.extend(session_ids)

    if branch is not None:
        where.append("s.git_branch_last LIKE ? ESCAPE '\\'")
        params.append(f"%{escape_like(branch)}%")

    if file_path is not None:
        paths = (file_path, *alias_paths)
        placeholders = ",".join("?" * len(paths))
        where.append(
            f"""
            s.id IN (
                SELECT e.session_id FROM exchanges e
                JOIN exchange_files ef ON ef.exchange_id = e.id
                WHERE ef.file_path IN ({placeholders})
                UNION
                SELECT e.session_id FROM exchanges e
                JOIN code_touches ct ON ct.exchange_id = e.id
                WHERE ct.file_path IN ({placeholders})
            )
            """
        )
        params.extend(paths)
        params.extend(paths)

    where_sql = " AND ".join(where)
    return con.execute(f"SELECT s.* FROM sessions s WHERE {where_sql}", params).fetchall()  # noqa: S608


def _enrich_session_summaries(
    con: sqlite3.Connection, rows: list[sqlite3.Row]
) -> list[SessionSummary]:
    """`sessions` の行リストへ exchange_count/distilled_count/title/files/rooms を
    バッチクエリで付加する（`search._enrich_results` と同じ N+1 回避パターン）。
    渡した `rows` の順序をそのまま保つ。
    """
    if not rows:
        return []
    ids = [r["id"] for r in rows]
    placeholders = ",".join("?" * len(ids))

    exchange_rows = con.execute(
        f"""
        SELECT id, session_id, ply_start, user_content, distill_status
        FROM exchanges
        WHERE session_id IN ({placeholders})
        ORDER BY session_id, ply_start ASC, rowid ASC
        """,  # noqa: S608
        ids,
    ).fetchall()

    counts: dict[str, int] = {}
    distilled: dict[str, int] = {}
    titles: dict[str, str] = {}
    for row in exchange_rows:
        sid = row["session_id"]
        counts[sid] = counts.get(sid, 0) + 1
        if row["distill_status"] == "distilled":
            distilled[sid] = distilled.get(sid, 0) + 1
        if sid not in titles:
            # ORDER BY session_id, ply_start, rowid のため、そのセッションで
            # 最初に現れた行が最も早い exchange (= 先頭 user メッセージ)。
            titles[sid] = summarize_title(row["user_content"])

    file_rows = con.execute(
        f"""
        SELECT session_id, file_path FROM (
            SELECT e.session_id, ef.file_path
            FROM exchanges e JOIN exchange_files ef ON ef.exchange_id = e.id
            WHERE e.session_id IN ({placeholders})
            UNION
            SELECT e.session_id, ct.file_path
            FROM exchanges e JOIN code_touches ct ON ct.exchange_id = e.id
            WHERE e.session_id IN ({placeholders})
        )
        """,  # noqa: S608
        ids + ids,
    ).fetchall()
    files: dict[str, list[str]] = {}
    for row in file_rows:
        bucket = files.setdefault(row["session_id"], [])
        if row["file_path"] not in bucket and len(bucket) < _TOP_FILES_LIMIT:
            bucket.append(row["file_path"])

    room_rows = con.execute(
        f"""
        SELECT e.session_id, r.room_type, r.room_key, r.room_label, r.relevance
        FROM exchanges e
        JOIN palace_objects p ON p.exchange_id = e.id
        JOIN rooms r ON r.palace_object_id = p.id
        WHERE e.session_id IN ({placeholders})
        ORDER BY r.relevance DESC
        """,  # noqa: S608
        ids,
    ).fetchall()
    rooms: dict[str, list[dict[str, str]]] = {}
    seen_rooms: dict[str, set[str]] = {}
    for row in room_rows:
        sid = row["session_id"]
        bucket = rooms.setdefault(sid, [])
        dedup_key = f"{row['room_type']}:{row['room_key']}"
        seen = seen_rooms.setdefault(sid, set())
        if dedup_key in seen or len(bucket) >= _TOP_ROOMS_LIMIT:
            continue
        seen.add(dedup_key)
        bucket.append(
            {
                "room_type": row["room_type"],
                "room_key": row["room_key"],
                "room_label": row["room_label"],
            }
        )

    out = []
    for row in rows:
        sid = row["id"]
        out.append(
            SessionSummary(
                session_id=sid,
                harness=row["harness"],
                git_branch=row["git_branch_last"],
                started_at=row["started_at"],
                updated_at=row["updated_at"],
                title=titles.get(sid, "(no exchanges)"),
                exchange_count=counts.get(sid, 0),
                distilled_count=distilled.get(sid, 0),
                files_touched=files.get(sid, []),
                top_rooms=rooms.get(sid, []),
            )
        )
    return out


def list_sessions_by_recency(
    con: sqlite3.Connection,
    limit: int,
    *,
    file_path: str | None = None,
    alias_paths: tuple[str, ...] = (),
    branch: str | None = None,
) -> list[SessionSummary]:
    """`loci recall`（キーワードなし）: 新しい順のセッション一覧。"""
    rows = _fetch_session_rows(
        con, None, file_path=file_path, alias_paths=alias_paths, branch=branch
    )
    rows_sorted = sorted(rows, key=lambda r: r["updated_at"] or "", reverse=True)[:limit]
    return _enrich_session_summaries(con, rows_sorted)


def list_sessions_by_relevance(
    con: sqlite3.Connection,
    exchange_scores: Mapping[str, float],
    limit: int,
    *,
    file_path: str | None = None,
    alias_paths: tuple[str, ...] = (),
    branch: str | None = None,
) -> list[SessionSummary]:
    """`loci recall "keyword"`: exchange 単位の RRF スコアを session_id へ
    max 集約し、上位 `limit` 件をセッション一覧として返す。

    sum ではなく max にするのは、exchange 数が多いだけの長いセッションが
    件数で上位に来る歪みを避けるため（1件でも強く当たれば十分）。
    """
    if not exchange_scores:
        return []
    ex_ids = list(exchange_scores)
    placeholders = ",".join("?" * len(ex_ids))
    rows = con.execute(
        f"SELECT id, session_id FROM exchanges WHERE id IN ({placeholders})",  # noqa: S608
        ex_ids,
    ).fetchall()

    session_max: dict[str, float] = {}
    for row in rows:
        sid = row["session_id"]
        if sid is None:
            continue
        score = exchange_scores[row["id"]]
        if score > session_max.get(sid, float("-inf")):
            session_max[sid] = score
    if not session_max:
        return []

    candidate_ids = list(session_max)
    session_rows = _fetch_session_rows(
        con, candidate_ids, file_path=file_path, alias_paths=alias_paths, branch=branch
    )
    session_rows.sort(key=lambda r: session_max[r["id"]], reverse=True)
    session_rows = session_rows[:limit]

    summaries = _enrich_session_summaries(con, session_rows)
    return [replace(s, score=session_max[s.session_id]) for s in summaries]


def resolve_session_id(con: sqlite3.Connection, session_ref: str) -> tuple[str | None, list[str]]:
    """`session_ref` を session id へ解決する（完全一致 → 前方一致の順、git の
    短縮ハッシュと同じ感覚）。

    戻り値は `(resolved_id, candidates)`。完全一致または前方一致が一意なら
    `resolved_id` にその id を、複数一致（曖昧）なら `resolved_id=None` と
    候補一覧を返す。0件なら両方空。呼び出し側（CLI）がメッセージを組み立てる。
    """
    exact = con.execute("SELECT id FROM sessions WHERE id = ?", (session_ref,)).fetchone()
    if exact is not None:
        return exact["id"], [exact["id"]]

    rows = con.execute(
        "SELECT id FROM sessions WHERE id LIKE ? ESCAPE '\\'",
        (escape_like(session_ref) + "%",),
    ).fetchall()
    candidates = [r["id"] for r in rows]
    if len(candidates) == 1:
        return candidates[0], candidates
    return None, candidates


def build_session_digest(
    con: sqlite3.Connection,
    session_id: str,
    *,
    limit_lines: int = DEFAULT_DIGEST_LINES,
    full: bool = False,
) -> SessionDigest | None:
    """`loci recall --session <id>` の要点ダイジェストを組み立てる（design: Tier 1/2）。

    `exchange_core`（distill 済みの「1行の決定」）を ply 順に並べるだけで、
    全文（user_content/agent_content）は既定では含めない——distill は既に
    圧縮を終えている資産であり、逐語が必要なら `loci show <exchange_id>` に
    降りる方がトークン効率が良い。`full=True` で specific_context と全文を
    行ごとに付加する（`context`/`search` の既存 `--full` と同じ意味）。
    未 distill（`exchange_core` が無い）行は先頭 user メッセージの1行で
    フォールバックする。
    """
    rows = _fetch_session_rows(con, [session_id], file_path=None, alias_paths=(), branch=None)
    if not rows:
        return None
    summary = _enrich_session_summaries(con, rows)[0]

    ex_rows = con.execute(
        """
        SELECT e.id, e.ply_start, e.user_content, e.agent_content,
               e.distill_status, p.exchange_core, p.specific_context
        FROM exchanges e
        LEFT JOIN palace_objects p ON p.exchange_id = e.id
        WHERE e.session_id = ?
        ORDER BY e.ply_start ASC, e.rowid ASC
        """,
        (session_id,),
    ).fetchall()

    total = len(ex_rows)
    lines = []
    for row in ex_rows[:limit_lines]:
        core = row["exchange_core"] or summarize_title(row["user_content"])
        lines.append(
            DigestLine(
                exchange_id=row["id"],
                ply_start=row["ply_start"],
                exchange_core=core,
                distilled=row["distill_status"] == "distilled",
                specific_context=row["specific_context"] if full else None,
                user_content=row["user_content"] if full else None,
                agent_content=row["agent_content"] if full else None,
            )
        )
    return SessionDigest(summary=summary, lines=lines, total_exchanges=total)
