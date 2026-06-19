from pathlib import Path

import pytest

from app.storage.paths import VaultPathError, resolve_vault_path


def test_resolve_vault_path_accepts_markdown_inside_root(tmp_path: Path) -> None:
    note = tmp_path / "Inbox" / "Memory.md"
    note.parent.mkdir()
    note.write_text("# Memory\n", encoding="utf-8")

    resolved = resolve_vault_path(tmp_path, "Inbox/Memory.md")

    assert resolved.relative_path == "Inbox/Memory.md"
    assert resolved.absolute_path == note.resolve()


@pytest.mark.parametrize(
    "relative_path",
    [
        "../outside.md",
        "/absolute.md",
        "C:" + "/Users/test/outside.md",
        ".obsidian/config.md",
        ".hidden/note.md",
        "Folder/SHORT~1.md",
        "not-markdown.txt",
    ],
)
def test_resolve_vault_path_rejects_unsafe_paths(tmp_path: Path, relative_path: str) -> None:
    with pytest.raises(VaultPathError):
        resolve_vault_path(tmp_path, relative_path, for_write=True)


def test_resolve_vault_path_rejects_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (outside / "Secret.md").write_text("secret", encoding="utf-8")
    link = tmp_path / "Link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Symlink creation is unavailable")

    with pytest.raises(VaultPathError):
        resolve_vault_path(tmp_path, "Link/Secret.md")
