from __future__ import annotations

from pathlib import Path
import re
from typing import Any

import pymupdf

from fastapi_app.services.research_repository import ResearchRepository


MAX_PAPER_CONTEXT_CHARS = 180_000
MAX_SOURCE_CONTEXT_CHARS = 120_000
MAX_PDF_SUPPLEMENT_CHARS = 80_000
MAX_VISUAL_ASSETS = 8
VISUAL_RENDER_SCALE = 1.35
VISUAL_ASSET_VERSION = 1


def _visual_page_labels(text: str) -> list[str]:
    labels: list[str] = []
    for kind, pattern in (
        ("figure", r"\b(?:figure|fig\.?)\s*([0-9]+[a-z]?)"),
        ("table", r"\btable\s*([0-9]+[a-z]?)"),
    ):
        for label in re.findall(pattern, text, flags=re.IGNORECASE):
            normalized = f"{kind}:{str(label).casefold()}"
            if normalized not in labels:
                labels.append(normalized)
    return labels


def _visual_page_score(page: Any) -> tuple[int, str]:
    """Rank pages likely to contain figures or tables without OCR or model calls."""
    text = page.get_text("text") or ""
    lowered = text.casefold()
    image_count = len(page.get_images(full=True))
    drawing_count = len(page.get_drawings())
    has_figure = bool(re.search(r"\b(?:figure|fig\.?|图)\s*\d*", lowered))
    has_table = bool(re.search(r"\btable\s*\d*|表\s*\d*", lowered))
    score = image_count * 5 + min(drawing_count, 8)
    if has_figure:
        score += 12
    if has_table:
        score += 9
    if not score:
        return 0, ""
    if has_table and not has_figure:
        kind = "table_page"
    elif has_figure or image_count or drawing_count:
        kind = "figure_page"
    else:
        kind = "visual_page"
    return score, kind


def render_paper_visual_assets(
    pdf_path: Path,
    *,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """Render a bounded set of figure/table pages for Codex visual input."""
    document = pymupdf.open(pdf_path)
    try:
        candidates: list[tuple[int, int, str]] = []
        for page_index, page in enumerate(document):
            score, kind = _visual_page_score(page)
            if score:
                candidates.append((score, page_index, kind))
        # Keep document order in the metadata and in the eventual visual prompt.
        selected = sorted(
            sorted(candidates, key=lambda item: (-item[0], item[1]))[:MAX_VISUAL_ASSETS],
            key=lambda item: item[1],
        )
        target_dir = output_dir or pdf_path.with_name(f"{pdf_path.stem}.visuals")
        target_dir.mkdir(parents=True, exist_ok=True)
        assets: list[dict[str, Any]] = []
        matrix = pymupdf.Matrix(VISUAL_RENDER_SCALE, VISUAL_RENDER_SCALE)
        for score, page_index, kind in selected:
            page = document[page_index]
            labels = _visual_page_labels(page.get_text("text") or "")
            pixmap = page.get_pixmap(matrix=matrix, alpha=False, colorspace=pymupdf.csRGB)
            destination = target_dir / f"page-{page_index + 1:03d}.png"
            pixmap.save(destination)
            assets.append(
                {
                    "path": str(destination.resolve()),
                    "page": page_index + 1,
                    "kind": kind,
                    "labels": labels,
                    "score": score,
                    "width": pixmap.width,
                    "height": pixmap.height,
                }
            )
        return {
            "visual_assets": assets,
            "visual_asset_count": len(assets),
            "visual_ingestion_status": "ready" if assets else "none_detected",
            "visual_asset_version": VISUAL_ASSET_VERSION,
        }
    finally:
        document.close()


def ensure_paper_visual_assets(
    repository: ResearchRepository,
    paper: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Lazily create visual page renders and return only paths inside the repository."""
    metadata = dict(paper.get("metadata") or {})
    root = repository.root.resolve()
    existing = metadata.get("visual_assets")
    if isinstance(existing, list):
        valid = [
            item
            for item in existing
            if isinstance(item, dict)
            and isinstance(item.get("path"), str)
            and (lambda path: path.is_file() and root in path.parents)(Path(item["path"]).resolve())
        ]
        if metadata.get("visual_asset_version") == VISUAL_ASSET_VERSION and (
            valid or metadata.get("visual_ingestion_status") == "none_detected"
        ):
            return paper, valid

    stored_path = paper.get("stored_path")
    if not stored_path:
        return paper, []
    pdf_path = Path(str(stored_path)).resolve()
    if not pdf_path.is_file() or root not in pdf_path.parents:
        return paper, []
    try:
        rendered = render_paper_visual_assets(pdf_path)
    except Exception as exc:
        metadata.update({"visual_ingestion_status": "error", "visual_ingestion_error": str(exc)[:500]})
        refreshed = repository.update_paper_metadata(paper["id"], metadata) or paper
        return refreshed, []
    metadata.update(rendered)
    refreshed = repository.update_paper_metadata(paper["id"], metadata) or paper
    return refreshed, list(rendered.get("visual_assets") or [])


def extract_pdf_to_markdown(pdf_path: Path, markdown_path: Path, title: str) -> dict[str, Any]:
    """Extract a local PDF page by page so Codex does not need shell access to read it."""
    document = pymupdf.open(pdf_path)
    try:
        parts = [f"# {title}\n"]
        extracted_chars = 0
        for page_number, page in enumerate(document, start=1):
            text = page.get_text("text").strip()
            parts.append(f"\n## Page {page_number}\n\n{text or '[No extractable text on this page]'}\n")
            extracted_chars += len(text)
        markdown_path.write_text("".join(parts), encoding="utf-8")
        return {
            "extraction_status": "ready",
            "text_path": str(markdown_path),
            "page_count": document.page_count,
            "extracted_chars": extracted_chars,
        }
    finally:
        document.close()


def ensure_paper_text(
    repository: ResearchRepository,
    paper: dict[str, Any],
) -> tuple[dict[str, Any], Path]:
    metadata = dict(paper.get("metadata") or {})
    existing_path = metadata.get("text_path")
    if existing_path:
        path = Path(str(existing_path)).resolve()
        if path.is_file() and repository.root.resolve() in path.parents:
            return paper, path

    stored_path = paper.get("stored_path")
    if not stored_path:
        raise ValueError("This paper has no local PDF")
    pdf_path = Path(str(stored_path)).resolve()
    if not pdf_path.is_file() or repository.root.resolve() not in pdf_path.parents:
        raise ValueError("The local PDF is missing")

    markdown_path = pdf_path.with_name(f"{pdf_path.stem}.extracted.md")
    try:
        extraction = extract_pdf_to_markdown(pdf_path, markdown_path, paper["title"])
    except Exception as exc:
        metadata.update(
            {
                "extraction_status": "error",
                "extraction_error": str(exc)[:500],
            }
        )
        repository.update_paper_metadata(paper["id"], metadata, status="extract_error")
        raise ValueError("The selected PDF could not be parsed; upload a valid PDF and try again") from exc
    metadata.update(extraction)
    repository.update_paper_metadata(paper["id"], metadata, status="ready")
    refreshed = repository.get_paper(paper["id"]) or paper
    return refreshed, markdown_path


def build_paper_context(repository: ResearchRepository, paper: dict[str, Any]) -> str:
    paper, text_path = ensure_paper_text(repository, paper)
    # Generate bounded page renders alongside text so a later visual question can
    # attach them without blocking on a full PDF conversion.
    paper, _ = ensure_paper_visual_assets(repository, paper)
    metadata = paper.get("metadata") or {}
    pdf_content = text_path.read_text(encoding="utf-8", errors="replace")
    source_content = ""
    source_path_value = metadata.get("source_text_path")
    if source_path_value:
        source_path = Path(str(source_path_value)).resolve()
        if source_path.is_file() and repository.root.resolve() in source_path.parents:
            source_content = source_path.read_text(encoding="utf-8", errors="replace")
    if source_content:
        source_truncated = len(source_content) > MAX_SOURCE_CONTEXT_CHARS
        pdf_truncated = len(pdf_content) > MAX_PDF_SUPPLEMENT_CHARS
        source_suffix = "\n[LaTeX source truncated at the context limit.]" if source_truncated else ""
        pdf_suffix = "\n[PDF extraction truncated at the context limit.]" if pdf_truncated else ""
        content = (
            "[LATEX_SOURCE_PRIMARY]\n"
            f"{source_content[:MAX_SOURCE_CONTEXT_CHARS]}"
            f"{source_suffix}\n"
            "[/LATEX_SOURCE_PRIMARY]\n\n"
            "[PDF_TEXT_WITH_PAGE_MARKERS]\n"
            f"{pdf_content[:MAX_PDF_SUPPLEMENT_CHARS]}"
            f"{pdf_suffix}\n"
            "[/PDF_TEXT_WITH_PAGE_MARKERS]"
        )
        source_description = (
            "The paper includes normalized LaTeX source as the primary structured text and "
            "page-marked PDF extraction as a supplement."
        )
    else:
        truncated = len(pdf_content) > MAX_PAPER_CONTEXT_CHARS
        content = pdf_content[:MAX_PAPER_CONTEXT_CHARS]
        if truncated:
            content += "\n\n[The extracted paper exceeded the context limit and was truncated.]"
        source_description = "The paper includes page-marked PDF extraction."
    page_count = metadata.get("page_count")
    return (
        "[THINKFLOW_ATTACHED_PAPER]\n"
        f"Title: {paper['title']}\n"
        f"Paper ID: {paper['id']}\n"
        f"Pages: {page_count or 'unknown'}\n"
        f"{source_description} Answer from this "
        "content directly. Do not use shell commands to locate or read the attached paper. "
        "Do not include page citations or source annotations unless the user explicitly asks "
        "for evidence locations or page numbers.\n\n"
        f"{content}\n"
        "[/THINKFLOW_ATTACHED_PAPER]"
    )
