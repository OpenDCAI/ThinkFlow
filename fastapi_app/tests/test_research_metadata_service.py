from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from fastapi_app.services.research_metadata_service import (
    _resolve_document_hints,
    _merge,
    _resolve_arxiv,
    _resolve_crossref,
    _resolve_openalex_title,
    _resolve_semantic_scholar,
    _resolve_url,
    normalize_arxiv_id,
    normalize_doi,
    import_paper,
)
from fastapi_app.services.research_repository import ResearchRepository


ARXIV_XML = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
<entry><title> A Test Paper </title><summary> A concise abstract. </summary><published>2025-01-02T00:00:00Z</published><updated>2025-01-03T00:00:00Z</updated>
<author><name>Ada Lovelace</name><arxiv:affiliation>Analytical Engine Lab</arxiv:affiliation></author>
<link rel="alternate" href="https://arxiv.org/abs/2501.00001"/><link rel="related" href="https://arxiv.org/pdf/2501.00001.pdf"/><category term="cs.AI"/></entry></feed>"""


def _client(routes: dict[str, tuple[int, str, str]]) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        status, content, content_type = routes.get(str(request.url), (404, "", "text/plain"))
        return httpx.Response(status, request=request, content=content.encode(), headers={"content-type": content_type})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_identifier_normalization_and_arxiv_resolution() -> None:
    assert normalize_arxiv_id("https://arxiv.org/abs/2501.00001v2") == "2501.00001v2"
    assert normalize_doi("https://doi.org/10.1234/Test.1.") == "10.1234/Test.1"
    async with _client({"https://export.arxiv.org/api/query?id_list=2501.00001v2": (200, ARXIV_XML, "application/atom+xml")}) as client:
        metadata = await _resolve_arxiv(client, "2501.00001v2", "2501.00001v2")
    assert metadata is not None
    assert metadata["title"] == "A Test Paper"
    assert metadata["authors"][0]["affiliations"] == ["Analytical Engine Lab"]
    assert metadata["publication_status"] == "preprint"


@pytest.mark.asyncio
async def test_crossref_and_openalex_resolution() -> None:
    crossref_url = "https://api.crossref.org/works/10.1234%2Ftest"
    crossref = {"message": {"title": ["Published Paper"], "author": [{"given": "Ada", "family": "Lovelace", "affiliation": [{"name": "Lab"}]}], "container-title": ["Test Journal"], "type": "journal-article", "published": {"date-parts": [[2024, 5, 1]]}, "URL": "https://doi.org/10.1234/test"}}
    openalex_url = "https://api.openalex.org/works?search=Published%20Paper&per_page=5"
    openalex = {"results": [{"title": "Published Paper", "publication_year": 2024, "doi": "https://doi.org/10.1234/test", "primary_location": {"landing_page_url": "https://doi.org/10.1234/test", "source": {"display_name": "Test Journal", "type": "journal"}}, "authorships": []}]}
    async with _client({crossref_url: (200, json.dumps(crossref), "application/json"), openalex_url: (200, json.dumps(openalex), "application/json")}) as client:
        crossref_metadata = await _resolve_crossref(client, "10.1234/test", "10.1234/test")
        candidates = await _resolve_openalex_title(client, "Published Paper", "Published Paper")
    assert crossref_metadata is not None
    assert crossref_metadata["publication_status"] == "published"
    assert crossref_metadata["institutions"] == ["Lab"]
    assert candidates[0]["confidence"] == 0.85


@pytest.mark.asyncio
async def test_semantic_scholar_recovers_published_venue_from_arxiv_id() -> None:
    fields = "title,authors,venue,publicationVenue,publicationDate,journal,externalIds"
    url = f"https://api.semanticscholar.org/graph/v1/paper/ARXIV:2310.06770?fields={fields}"
    payload = {
        "title": "SWE-bench",
        "authors": [{"name": "Carlos Jimenez"}],
        "venue": "International Conference on Learning Representations",
        "publicationVenue": {
            "name": "International Conference on Learning Representations",
            "type": "conference",
            "alternate_names": ["Int Conf Learn Represent", "ICLR"],
            "url": "https://iclr.cc/",
        },
        "publicationDate": "2023-10-10",
        "externalIds": {"ArXiv": "2310.06770"},
    }
    async with _client({url: (200, json.dumps(payload), "application/json")}) as client:
        metadata = await _resolve_semantic_scholar(client, "ARXIV:2310.06770", "2310.06770")
    assert metadata is not None
    assert metadata["venue_short_name"] == "ICLR"
    assert metadata["venue_type"] == "conference"
    assert metadata["publication_status"] == "published"
    assert metadata["venue_url"] == "https://iclr.cc/"


def test_document_frontmatter_recovers_publication_status(tmp_path: Path) -> None:
    markdown = tmp_path / "paper.md"
    markdown.write_text(
        "# Paper\n\n## Page 1\n\nPublished as a conference paper at ICLR 2024\nTitle",
        encoding="utf-8",
    )
    metadata = _resolve_document_hints(markdown, "Paper")
    assert metadata is not None
    assert metadata["venue"] == "ICLR 2024"
    assert metadata["publication_status"] == "published"


def test_published_metadata_replaces_repository_venue_type() -> None:
    merged = _merge(
        {"publication_status": "preprint", "venue_type": "repository", "sources": ["arxiv"]},
        {
            "publication_status": "published",
            "venue": "ICLR 2024",
            "venue_short_name": "ICLR",
            "venue_type": "conference",
            "sources": ["document_frontmatter"],
        },
    )
    assert merged["publication_status"] == "published"
    assert merged["venue_type"] == "conference"
    assert merged["venue_short_name"] == "ICLR"


@pytest.mark.asyncio
async def test_generic_paper_page_keeps_multiple_authors() -> None:
    url = "https://papers.example.test/item"
    page = """<html><head><title>Paper page</title><meta name="citation_title" content="A Web Paper"><meta name="citation_author" content="First Author"><meta name="citation_author" content="Second Author"><meta name="citation_doi" content="10.1234/web"><link rel="alternate" href="/paper.pdf"></head></html>"""
    async with _client({url: (200, page, "text/html")}) as client:
        metadata = await _resolve_url(client, url, url)
    assert metadata is not None
    assert [author["name"] for author in metadata["authors"]] == ["First Author", "Second Author"]
    assert metadata["pdf_url"] == "https://papers.example.test/paper.pdf"


@pytest.mark.asyncio
async def test_import_reuses_existing_arxiv_paper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = ResearchRepository(tmp_path / "research")
    space = repository.create_space("Deduplication")
    existing = repository.add_paper(
        space["id"],
        title="Existing Paper",
        metadata={"arxiv_id": "2501.00001"},
    )

    async def fake_resolve(_query: str):
        return {
            "title": "A newer title",
            "arxiv_id": "2501.00001",
            "pdf_url": "https://example.test/paper.pdf",
        }, []

    monkeypatch.setattr(
        "fastapi_app.services.research_metadata_service.resolve_metadata", fake_resolve
    )
    result = await import_paper(
        repository,
        space["id"],
        "2501.00001",
        download_pdf=True,
        download_source=True,
    )

    assert result["paper"]["id"] == existing["id"]
    assert result["deduplicated"] is True
    assert len(repository.list_papers(space["id"])) == 1
