from pathlib import Path

import pymupdf
import pytest

from fastapi_app.services.research_paper_service import (
    build_paper_context,
    ensure_paper_text,
    extract_pdf_to_markdown,
    render_paper_visual_assets,
)
from fastapi_app.services.research_repository import ResearchRepository


def _make_pdf(path: Path) -> None:
    document = pymupdf.open()
    first = document.new_page()
    first.insert_text((72, 72), "First page finding")
    second = document.new_page()
    second.insert_text((72, 72), "Second page limitation")
    document.save(path)
    document.close()


def test_pdf_is_extracted_with_page_markers_for_codex(tmp_path: Path) -> None:
    repository = ResearchRepository(tmp_path / "research")
    space = repository.create_space("Paper chat")
    pdf_path = repository.space_dir(space["id"]) / "papers" / "paper.pdf"
    markdown_path = pdf_path.with_name("paper.extracted.md")
    _make_pdf(pdf_path)

    extraction = extract_pdf_to_markdown(pdf_path, markdown_path, "Test Paper")
    paper = repository.add_paper(
        space["id"],
        title="Test Paper",
        stored_path=str(pdf_path),
        metadata=extraction,
    )
    context = build_paper_context(repository, paper)

    assert extraction["page_count"] == 2
    assert "## Page 1" in context
    assert "First page finding" in context
    assert "## Page 2" in context
    assert "Second page limitation" in context
    assert "Do not use shell commands" in context
    assert "Do not include page citations" in context
    assert "Cite evidence as" not in context


def test_latex_source_is_primary_with_page_marked_pdf_supplement(tmp_path: Path) -> None:
    repository = ResearchRepository(tmp_path / "research")
    space = repository.create_space("Source paper chat")
    papers_dir = repository.space_dir(space["id"]) / "papers"
    pdf_path = papers_dir / "paper.pdf"
    markdown_path = papers_dir / "paper.extracted.md"
    source_path = papers_dir / "paper.source" / "source.combined.tex"
    source_path.parent.mkdir()
    _make_pdf(pdf_path)
    extraction = extract_pdf_to_markdown(pdf_path, markdown_path, "Source Paper")
    source_path.write_text(
        "\\section{Method}\n\\begin{equation}z = Wx + b\\end{equation}",
        encoding="utf-8",
    )
    paper = repository.add_paper(
        space["id"],
        title="Source Paper",
        stored_path=str(pdf_path),
        metadata={**extraction, "source_text_path": str(source_path)},
    )

    context = build_paper_context(repository, paper)

    assert "[LATEX_SOURCE_PRIMARY]" in context
    assert "\\section{Method}" in context
    assert "\\begin{equation}z = Wx + b\\end{equation}" in context
    assert "[PDF_TEXT_WITH_PAGE_MARKERS]" in context
    assert "## Page 2" in context
    assert "Second page limitation" in context


def test_runtime_extraction_failure_is_persisted_on_the_paper(tmp_path: Path) -> None:
    repository = ResearchRepository(tmp_path / "research")
    space = repository.create_space("Broken paper")
    pdf_path = repository.space_dir(space["id"]) / "papers" / "broken.pdf"
    pdf_path.write_bytes(b"%PDF-this-is-not-a-complete-document")
    paper = repository.add_paper(
        space["id"],
        title="Broken Paper",
        stored_path=str(pdf_path),
        metadata={"size": pdf_path.stat().st_size},
    )

    with pytest.raises(ValueError, match="could not be parsed"):
        ensure_paper_text(repository, paper)

    updated = repository.get_paper(paper["id"])
    assert updated["status"] == "extract_error"
    assert updated["metadata"]["extraction_status"] == "error"
    assert updated["metadata"]["extraction_error"]


def test_visual_pages_are_ranked_rendered_and_bounded(tmp_path: Path) -> None:
    pdf_path = tmp_path / "visual-paper.pdf"
    document = pymupdf.open()
    text_page = document.new_page()
    text_page.insert_text((72, 72), "Introduction without visual evidence")
    figure_page = document.new_page()
    figure_page.insert_text((72, 72), "Figure 1: Method architecture")
    figure_page.draw_rect(pymupdf.Rect(80, 110, 300, 260), color=(0, 0, 0))
    table_page = document.new_page()
    table_page.insert_text((72, 72), "Table 1: Main results")
    table_page.draw_line((80, 110), (360, 110))
    document.save(pdf_path)
    document.close()

    rendered = render_paper_visual_assets(pdf_path)

    assert rendered["visual_ingestion_status"] == "ready"
    assert rendered["visual_asset_count"] == 2
    assert [asset["page"] for asset in rendered["visual_assets"]] == [2, 3]
    assert {asset["kind"] for asset in rendered["visual_assets"]} == {
        "figure_page",
        "table_page",
    }
    assert all(Path(asset["path"]).is_file() for asset in rendered["visual_assets"])
