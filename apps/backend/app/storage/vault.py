from __future__ import annotations

import os
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
        # 用 os.walk(followlinks=False) 而不是 Path.rglob：Python 3.10 的
        # rglob 会跟随符号链接目录，恶意 Vault 可用 symlink 环/越界把外部
        # 文件拉进索引。符号链接目录与文件一律跳过。
        files: list[VaultPath] = []
        for dirpath, dirnames, filenames in os.walk(self.root, followlinks=False):
            dirnames[:] = sorted(
                name
                for name in dirnames
                if not (Path(dirpath) / name).is_symlink()
            )
            for filename in filenames:
                if not filename.endswith(".md"):
                    continue
                path = Path(dirpath) / filename
                if path.is_symlink():
                    continue
                try:
                    relative = path.relative_to(self.root).as_posix()
                    files.append(self.resolve_note(relative))
                except ValueError:
                    continue
        return sorted(files, key=lambda item: item.relative_path.casefold())
