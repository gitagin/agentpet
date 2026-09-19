from pathlib import Path

from app.models.api import MemorySearchResult
from app.repositories.storage import NoteRepository, VaultRepository
from app.services.memory import SafeMarkdownWriter
from app.services.memory_entity_graph import MemoryEntityGraphStore
from app.services.retrieval import _classify_source_scope
from app.services.wiki_reconciler import bind_authoritative_wiki_page
from app.storage.database import Database
from app.storage.markdown import read_markdown


def indexed_citation(
    database: Database, vault_root: Path, relative_path: str,
    *, content: str = "# Source\n\nRelevant snippet.\n", reviewed: bool = True,
) -> MemorySearchResult:
    path = SafeMarkdownWriter(vault_root).resolve_markdown_path(relative_path)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    parsed = read_markdown(path)
    with database.session() as conn:
        vault_id = VaultRepository(conn).upsert(vault_root)
        conn.commit()
        note_id = NoteRepository(conn).replace_note(
            vault_id=vault_id, relative_path=relative_path, markdown=parsed,
            modified_at=path.stat().st_mtime,
        )
        if relative_path.startswith("Wiki/") and reviewed:
            graph = MemoryEntityGraphStore(conn)
            if graph.get_wiki_binding(vault_id=vault_id, wiki_relative_path=relative_path) is None:
                bind_authoritative_wiki_page(graph, vault_id=vault_id,
                    relative_path=relative_path, parsed=parsed)
        row = conn.execute(
            "SELECT * FROM note_chunks WHERE note_id = ? ORDER BY chunk_index LIMIT 1",
            (note_id,),
        ).fetchone()
    return MemorySearchResult(
        note_id=note_id, chunk_id=row["id"], relative_path=relative_path,
        title=parsed.title, heading=row["heading"], snippet=row["content"], score=1.0,
        content_hash=row["content_hash"], source_scope=_classify_source_scope(relative_path),
    )
