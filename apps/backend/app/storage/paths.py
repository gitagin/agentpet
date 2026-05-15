from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath


class VaultPathError(ValueError):
    pass


DENIED_DIRS = {".obsidian", ".git"}


@dataclass(frozen=True)
class VaultPath:
    root: Path
    relative_path: str
    absolute_path: Path


def canonical_root(root: str | Path) -> Path:
    resolved = Path(root).expanduser().resolve(strict=False)
    if _is_unc_or_extended_windows_path(str(root)):
        raise VaultPathError("知识库根目录不支持 UNC 或扩展 Windows 路径")
    return resolved


def resolve_vault_path(root: str | Path, relative_path: str | Path, *, for_write: bool = False) -> VaultPath:
    root_path = canonical_root(root)
    rel = _validate_relative(relative_path)
    target = root_path / rel
    resolved = target.resolve(strict=not for_write)
    if for_write:
        resolved.parent.resolve(strict=True)
    _ensure_inside(root_path, resolved)
    _reject_reparse_ancestors(root_path, resolved if resolved.exists() else resolved.parent)
    return VaultPath(root=root_path, relative_path=_as_posix_relative(root_path, resolved), absolute_path=resolved)


def _validate_relative(relative_path: str | Path) -> Path:
    raw = str(relative_path).replace("\\", "/")
    if not raw or raw.strip() != raw:
        raise VaultPathError("路径必须是非空的知识库相对路径")
    if raw.startswith(("/", "//")) or _is_unc_or_extended_windows_path(raw):
        raise VaultPathError("不支持绝对路径")
    win = PureWindowsPath(raw)
    if win.drive or win.root:
        raise VaultPathError("不支持带盘符的路径")
    path = Path(raw)
    if path.is_absolute():
        raise VaultPathError("不支持绝对路径")
    parts = path.parts
    if any(part in {"", ".", ".."} for part in parts):
        raise VaultPathError("不支持路径穿越")
    for part in parts:
        lowered = part.lower()
        if lowered in DENIED_DIRS or lowered.startswith(".") or "~" in part:
            raise VaultPathError("不支持隐藏目录、应用配置目录、Git 目录或短文件名样式路径")
    if path.suffix.lower() != ".md":
        raise VaultPathError("只支持 Markdown 文件")
    return path


def _ensure_inside(root: Path, target: Path) -> None:
    root_cmp = _casefold_path(root)
    target_cmp = _casefold_path(target)
    try:
        if os.path.commonpath([root_cmp, target_cmp]) != root_cmp:
            raise VaultPathError("路径不能超出知识库根目录")
    except ValueError as exc:
        raise VaultPathError("路径不能超出知识库根目录") from exc


def _reject_reparse_ancestors(root: Path, target: Path) -> None:
    current = target
    candidates: list[Path] = []
    while True:
        candidates.append(current)
        if _casefold_path(current) == _casefold_path(root):
            break
        if current.parent == current:
            raise VaultPathError("路径不能超出知识库根目录")
        current = current.parent
    for candidate in candidates:
        if candidate.exists() and (_is_symlink(candidate) or _is_windows_reparse_point(candidate)):
            raise VaultPathError("不支持符号链接或重解析点路径")


def _is_symlink(path: Path) -> bool:
    try:
        return path.is_symlink()
    except OSError:
        return True


def _is_windows_reparse_point(path: Path) -> bool:
    attrs = getattr(path.stat(follow_symlinks=False), "st_file_attributes", 0)
    return bool(attrs & 0x400)


def _casefold_path(path: Path) -> str:
    return os.path.normcase(str(path.resolve(strict=False))).rstrip("\\/").casefold()


def _as_posix_relative(root: Path, target: Path) -> str:
    return target.relative_to(root).as_posix()


def _is_unc_or_extended_windows_path(value: str) -> bool:
    normalized = value.replace("/", "\\")
    return normalized.startswith("\\\\") or normalized.startswith("\\\\?\\")
