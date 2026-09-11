from __future__ import annotations

import gzip
import io
import tarfile
from pathlib import Path

from fastapi_app.services.research_arxiv_source_service import (
    _extract_archive,
    build_combined_source,
    extract_frontmatter_metadata,
)


def _tar(files: dict[str, str]) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        for name, content in files.items():
            data = content.encode()
            member = tarfile.TarInfo(name)
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
    return output.getvalue()


def test_archive_extraction_is_safe_and_keeps_only_research_text(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    archive = _tar(
        {
            "main.tex": "\\documentclass{article}\\begin{document}Paper\\end{document}",
            "sections/method.tex": "Method",
            "references.bib": "@article{test}",
            "figures/result.png": "not an image fixture",
            "../outside.tex": "must not escape",
        }
    )

    extracted = _extract_archive(archive, source_dir)

    assert {path.relative_to(source_dir).as_posix() for path in extracted} == {
        "main.tex",
        "sections/method.tex",
        "references.bib",
    }
    assert not (tmp_path / "outside.tex").exists()
    assert not (source_dir / "figures" / "result.png").exists()


def test_combined_source_selects_entrypoint_and_expands_nested_inputs(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    (source_dir / "sections").mkdir(parents=True)
    (source_dir / "main.tex").write_text(
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "\\input{sections/method}\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    (source_dir / "sections" / "method.tex").write_text(
        "\\section{Method}\n\\input{details}",
        encoding="utf-8",
    )
    (source_dir / "sections" / "details.tex").write_text(
        "\\begin{equation}y=f(x)\\end{equation}",
        encoding="utf-8",
    )
    (source_dir / "appendix.tex").write_text(
        "\\section{Unreferenced Appendix}",
        encoding="utf-8",
    )

    metadata = build_combined_source(source_dir, "Fixture Paper")
    combined = Path(metadata["source_text_path"]).read_text(encoding="utf-8")

    assert metadata["source_ingestion_status"] == "ready"
    assert metadata["source_entrypoint"] == "main.tex"
    assert metadata["source_file_count"] == 4
    assert "% BEGIN INCLUDED FILE: sections/method.tex" in combined
    assert "% BEGIN INCLUDED FILE: sections/details.tex" in combined
    assert "\\begin{equation}y=f(x)\\end{equation}" in combined
    assert "% BEGIN UNREFERENCED TEX FILE: appendix.tex" in combined


def test_plain_gzip_source_falls_back_to_main_tex(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    source = b"\\documentclass{article}\\begin{document}Single file\\end{document}"

    extracted = _extract_archive(gzip.compress(source), source_dir)

    assert extracted == [source_dir / "main.tex"]
    assert extracted[0].read_bytes() == source


def test_extract_frontmatter_metadata_reads_common_latex_affiliations() -> None:
    source = (
        r"\author{Ada\textsuperscript{1} Bob\textsuperscript{2}}" "\n"
        r"\textsuperscript{1}{Princeton University} \quad "
        r"\textsuperscript{2}{Research Lab}"
    )
    assert extract_frontmatter_metadata(source) == {
        "institutions": ["Princeton University", "Research Lab"]
    }


def test_extract_frontmatter_metadata_reads_numbered_author_block_affiliations() -> None:
    source = (
        r"\author{Ada$^{1}$ Bob$^{2}$ \\ "
        r"$^1$The Chinese University of Hong Kong \quad\quad "
        r"$^2$Independent \quad\quad $^3$ELLIS \\}"
    )

    assert extract_frontmatter_metadata(source) == {
        "institutions": [
            "The Chinese University of Hong Kong",
            "Independent",
            "ELLIS",
        ]
    }
