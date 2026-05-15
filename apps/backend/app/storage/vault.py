from __future__ import annotations

from pathlib import Path

from .markdown import ParsedMarkdown, read_markdown
from .paths import VaultPath, resolve_vault_path


class VaultStorage:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve(strict=False)

    def resolve_note(self, relative_path: str | Path, *, for_write: bool = False) -> VaultPath:
        return resolve_vault_path(self.root, relative_path, for_write=for_write)

    def read_note(self, relative_path: str | Path) -> ParsedMarkdown:
        vault_path = self.resolve_note(relative_path)
        return read_markdown(vault_path.absolute_path)

    def iter_markdown_files(self) -> list[VaultPath]:
        files: list[VaultPath] = []
        for path in self.root.rglob("*.md"):
            try:
                relative = path.relative_to(self.root).as_posix()
                files.append(self.resolve_note(relative))
            except ValueError:
                continue
        return sorted(files, key=lambda item: item.relative_path.casefold())
