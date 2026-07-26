from .common import *
from .utility import _asset_markdown, _base_import_metadata, _is_binary_asset, _is_hidden_relative, _read_text_file, _resolve_import_path, _supplied_web_content, _title_from_url, _unique

def _import_preview_request(request: WikiSourceImportPreviewRequest) -> WikiIngestPreviewRequest:
    if request.source_kind == "file":
        return _file_import_preview_request(request)
    if request.source_kind == "folder":
        return _folder_import_preview_request(request)
    if request.source_kind == "url":
        return _url_import_preview_request(request)
    if request.source_kind == "webpage_text":
        return _webpage_text_import_preview_request(request)
    if request.source_kind == "image_asset":
        return _image_asset_import_preview_request(request)
    raise WikiSourceImportRejectedError(f"unsupported_source_kind:{request.source_kind}")


def _file_import_preview_request(request: WikiSourceImportPreviewRequest) -> WikiIngestPreviewRequest:
    path = _resolve_import_path(request.import_root, request.source_path)
    if not path.is_file():
        raise WikiSourceImportRejectedError("source_file_not_found")
    if _is_binary_asset(path):
        return _asset_preview_request(request, path, content=None)
    content = _read_text_file(path)
    title = request.title or path.stem
    metadata = _base_import_metadata(request, source_uri=str(path))
    metadata.update(
        {
            "resolved_path": str(path),
            "file_name": path.name,
            "file_size_bytes": path.stat().st_size,
        }
    )
    return WikiIngestPreviewRequest(
        title=title,
        content=content,
        source_type="file",
        source_uri=str(path),
        tags=_unique(["import/file", *request.tags]),
        links=request.links,
        max_pages=request.max_pages,
        source_metadata=metadata,
    )


def _folder_import_preview_request(request: WikiSourceImportPreviewRequest) -> WikiIngestPreviewRequest:
    folder = _resolve_import_path(request.import_root, request.source_path)
    if not folder.is_dir():
        raise WikiSourceImportRejectedError("source_folder_not_found")
    files = [
        path
        for path in sorted(folder.rglob("*"))
        if path.is_file() and not _is_hidden_relative(folder, path)
    ][: request.max_files]
    if not files:
        raise WikiSourceImportRejectedError("source_folder_empty")
    sections: list[str] = []
    file_metadata: list[dict[str, object]] = []
    for path in files:
        relative = path.relative_to(folder).as_posix()
        if _is_binary_asset(path):
            text = _asset_markdown(path, title=relative)
            kind = "asset"
        else:
            text = _read_text_file(path)
            kind = "text"
        sections.extend([f"## {relative}", "", text.strip(), ""])
        file_metadata.append(
            {
                "relative_path": relative,
                "file_name": path.name,
                "file_size_bytes": path.stat().st_size,
                "kind": kind,
            }
        )
    title = request.title or folder.name
    metadata = _base_import_metadata(request, source_uri=str(folder))
    metadata.update(
        {
            "resolved_path": str(folder),
            "file_count": len(files),
            "files": file_metadata,
        }
    )
    return WikiIngestPreviewRequest(
        title=title,
        content="\n".join(sections).strip(),
        source_type="folder",
        source_uri=str(folder),
        tags=_unique(["import/folder", *request.tags]),
        links=request.links,
        max_pages=request.max_pages,
        source_metadata=metadata,
    )


def _url_import_preview_request(request: WikiSourceImportPreviewRequest) -> WikiIngestPreviewRequest:
    if not request.url:
        raise WikiSourceImportRejectedError("url_required")
    content = _supplied_web_content(request)
    if not content:
        raise WikiSourceImportRejectedError("url_import_requires_supplied_text_or_html")
    title = request.title or _title_from_url(request.url)
    metadata = _base_import_metadata(request, source_uri=request.url)
    metadata.update({"url": request.url, "network_fetch": False})
    return WikiIngestPreviewRequest(
        title=title,
        content=content,
        source_type="url",
        source_uri=request.url,
        tags=_unique(["import/url", *request.tags]),
        links=request.links,
        max_pages=request.max_pages,
        source_metadata=metadata,
    )


def _webpage_text_import_preview_request(request: WikiSourceImportPreviewRequest) -> WikiIngestPreviewRequest:
    content = _supplied_web_content(request)
    if not content:
        raise WikiSourceImportRejectedError("webpage_text_required")
    title = request.title or (request.url and _title_from_url(request.url)) or "导入的网页"
    metadata = _base_import_metadata(request, source_uri=request.url)
    if request.url:
        metadata["url"] = request.url
    return WikiIngestPreviewRequest(
        title=title,
        content=content,
        source_type="webpage_text",
        source_uri=request.url,
        tags=_unique(["import/webpage", *request.tags]),
        links=request.links,
        max_pages=request.max_pages,
        source_metadata=metadata,
    )


def _image_asset_import_preview_request(request: WikiSourceImportPreviewRequest) -> WikiIngestPreviewRequest:
    if request.source_path:
        path = _resolve_import_path(request.import_root, request.source_path)
        if not path.is_file():
            raise WikiSourceImportRejectedError("source_asset_not_found")
        return _asset_preview_request(request, path, content=request.text)
    if not request.url:
        raise WikiSourceImportRejectedError("asset_source_required")
    title = request.title or _title_from_url(request.url)
    metadata = _base_import_metadata(request, source_uri=request.url)
    metadata.update({"url": request.url, "asset_kind": "remote"})
    content = request.text.strip() if request.text and request.text.strip() else _asset_markdown(None, title=title)
    return WikiIngestPreviewRequest(
        title=title,
        content=content,
        source_type="image_asset",
        source_uri=request.url,
        tags=_unique(["import/asset", *request.tags]),
        links=request.links,
        max_pages=request.max_pages,
        source_metadata=metadata,
    )


def _asset_preview_request(
    request: WikiSourceImportPreviewRequest,
    path: Path,
    *,
    content: str | None,
) -> WikiIngestPreviewRequest:
    title = request.title or path.stem
    metadata = _base_import_metadata(request, source_uri=str(path))
    metadata.update(
        {
            "resolved_path": str(path),
            "file_name": path.name,
            "file_size_bytes": path.stat().st_size,
            "asset_kind": "local",
        }
    )
    return WikiIngestPreviewRequest(
        title=title,
        content=content.strip() if content and content.strip() else _asset_markdown(path, title=title),
        source_type="image_asset" if request.source_kind == "image_asset" else "file",
        source_uri=str(path),
        tags=_unique(["import/asset", *request.tags]),
        links=request.links,
        max_pages=request.max_pages,
        source_metadata=metadata,
    )
