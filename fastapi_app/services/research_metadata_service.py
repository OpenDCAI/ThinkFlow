from __future__ import annotations

import asyncio
import html
import re
import uuid
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote, urljoin, urlparse
from xml.etree import ElementTree

import httpx

from fastapi_app.services.research_arxiv_source_service import extract_frontmatter_metadata, fetch_arxiv_source
from fastapi_app.services.research_paper_service import (
    extract_pdf_to_markdown,
    render_paper_visual_assets,
)
from fastapi_app.services.research_repository import ResearchRepository


USER_AGENT = "ThinkFlow Research Person/1.0 (paper metadata resolver)"
MAX_PDF_BYTES = 40 * 1024 * 1024
DOI_RE = re.compile(r"(?:https?://(?:dx\.)?doi\.org/)?(10\.\d{4,9}/[-._;()/:A-Z0-9]+)", re.I)
ARXIV_RE = re.compile(
    r"(?:arxiv:\s*)?((?:\d{4}\.\d{4,5})(?:v\d+)?|(?:[a-z][a-z0-9-]+\.)?[a-z-]+/\d{7}(?:v\d+)?)",
    re.I,
)
PUBLICATION_LINE_RE = re.compile(
    r"^(?:(Published as (?:a|an) (?:conference|journal) paper at)|(Accepted (?:at|to))|(To appear (?:at|in)))\s+(.{2,120})$",
    re.I | re.M,
)


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _date_from_crossref(item: dict[str, Any]) -> Optional[str]:
    for key in ("published-print", "published-online", "published", "issued", "created"):
        date_parts = ((item.get(key) or {}).get("date-parts") or [])
        if date_parts and date_parts[0]:
            parts = [str(part) for part in date_parts[0][:3]]
            return "-".join(parts + ["01"] * (3 - len(parts)))
    return None


def normalize_arxiv_id(value: str) -> Optional[str]:
    match = ARXIV_RE.search(value.strip())
    if not match:
        return None
    return match.group(1)


def normalize_doi(value: str) -> Optional[str]:
    match = DOI_RE.search(value.strip().rstrip(".,;)]}"))
    return match.group(1).rstrip(".") if match else None


def _author(name: str, affiliations: Optional[list[str]] = None) -> dict[str, Any]:
    return {"name": _clean(name), "affiliations": [_clean(item) for item in (affiliations or []) if _clean(item)]}


def _base_metadata(query: str) -> dict[str, Any]:
    return {
        "query": query,
        "source": "",
        "sources": [],
        "title": "",
        "authors": [],
        "institutions": [],
        "abstract": "",
        "doi": None,
        "arxiv_id": None,
        "paper_url": None,
        "pdf_url": None,
        "venue": None,
        "venue_short_name": None,
        "venue_url": None,
        "venue_type": None,
        "publication_status": "unknown",
        "is_preprint": False,
        "published_at": None,
        "updated_at": None,
        "version": None,
        "categories": [],
        "confidence": 0.0,
    }


class _MetaParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.meta_values: dict[str, list[str]] = {}
        self.links: list[tuple[str, str]] = []
        self.title = ""
        self._in_title = False
        self._title_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        values = {key.lower(): value or "" for key, value in attrs}
        if tag.lower() == "meta":
            key = values.get("name") or values.get("property") or values.get("citation_name")
            content = values.get("content", "")
            if key and content:
                normalized_key = key.lower()
                normalized_content = html.unescape(content).strip()
                self.meta.setdefault(normalized_key, normalized_content)
                self.meta_values.setdefault(normalized_key, []).append(normalized_content)
        elif tag.lower() == "link" and values.get("href"):
            self.links.append((values.get("rel", "").lower(), values["href"]))
        elif tag.lower() == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._in_title = False
            self.title = _clean("".join(self._title_parts))

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_parts.append(data)


async def _get(client: httpx.AsyncClient, url: str, *, accept: str = "") -> httpx.Response:
    headers = {"User-Agent": USER_AGENT}
    if accept:
        headers["Accept"] = accept
    return await client.get(url, headers=headers, follow_redirects=True)


async def _resolve_arxiv(client: httpx.AsyncClient, arxiv_id: str, query: str) -> Optional[dict[str, Any]]:
    response: Optional[httpx.Response] = None
    for host in ("https://export.arxiv.org", "https://arxiv.org"):
        url = f"{host}/api/query?id_list={quote(arxiv_id)}"
        try:
            candidate = await _get(client, url, accept="application/atom+xml")
            candidate.raise_for_status()
            response = candidate
            break
        except httpx.HTTPError:
            continue
    try:
        if response is None:
            return None
        root = ElementTree.fromstring(response.text)
        namespace = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
        entry = root.find("atom:entry", namespace)
        if entry is None:
            return None
        text = lambda path: _clean(entry.findtext(path, "", namespace))
        authors = []
        for author in entry.findall("atom:author", namespace):
            name = _clean(author.findtext("atom:name", "", namespace))
            affiliation = _clean(author.findtext("arxiv:affiliation", "", namespace))
            if name:
                authors.append(_author(name, [affiliation] if affiliation else []))
        links = {(link.attrib.get("rel", ""), link.attrib.get("href", "")) for link in entry.findall("atom:link", namespace)}
        paper_url = next((href for rel, href in links if rel == "alternate"), f"https://arxiv.org/abs/{arxiv_id}")
        pdf_url = next((href for rel, href in links if rel == "related" and "pdf" in href), f"https://arxiv.org/pdf/{arxiv_id}.pdf")
        categories = [item.attrib.get("term", "") for item in entry.findall("atom:category", namespace)]
        version_match = re.search(r"v(\d+)", arxiv_id, re.I)
        version = f"v{version_match.group(1)}" if version_match else None
        return {
            "query": query,
            "source": "arxiv",
            "sources": ["arxiv"],
            "title": text("atom:title"),
            "authors": authors,
            "institutions": sorted({aff for item in authors for aff in item.get("affiliations", [])}),
            "abstract": text("atom:summary"),
            "doi": None,
            "arxiv_id": arxiv_id,
            "paper_url": paper_url,
            "pdf_url": pdf_url,
            "venue": None,
            "venue_type": None,
            "publication_status": "preprint",
            "is_preprint": True,
            "published_at": text("atom:published") or None,
            "updated_at": text("atom:updated") or None,
            "version": version,
            "categories": [item for item in categories if item],
            "confidence": 0.99,
        }
    except (httpx.HTTPError, ElementTree.ParseError, ValueError):
        return None


async def _resolve_crossref(client: httpx.AsyncClient, doi: str, query: str) -> Optional[dict[str, Any]]:
    url = f"https://api.crossref.org/works/{quote(doi, safe='')}"
    try:
        response = await _get(client, url, accept="application/json")
        response.raise_for_status()
        item = response.json().get("message", {})
        title = _clean((item.get("title") or [""])[0])
        if not title:
            return None
        authors = []
        for person in item.get("author") or []:
            name = _clean(" ".join(part for part in (person.get("given"), person.get("family")) if part))
            affiliations = [_clean(aff.get("name")) for aff in person.get("affiliation") or []]
            if name:
                authors.append(_author(name, affiliations))
        resource = item.get("resource") or {}
        pdf_url = resource.get("primary.URL") or resource.get("primary.url")
        crossref_links = item.get("link") or []
        link = item.get("URL") or (crossref_links[0].get("URL") if crossref_links else None)
        type_value = _clean(item.get("type"))
        venue = _clean((item.get("container-title") or [""])[0]) or None
        venue_type = "journal" if "journal" in type_value else "conference" if "proceedings" in type_value or "conference" in type_value else type_value or None
        return {
            "query": query,
            "source": "crossref",
            "sources": ["crossref"],
            "title": title,
            "authors": authors,
            "institutions": sorted({aff for item in authors for aff in item.get("affiliations", [])}),
            "abstract": _clean(item.get("abstract")),
            "doi": doi,
            "arxiv_id": None,
            "paper_url": link,
            "pdf_url": pdf_url,
            "venue": venue,
            "venue_short_name": None,
            "venue_url": None,
            "venue_type": venue_type,
            "publication_status": "published" if _date_from_crossref(item) or venue else "unknown",
            "is_preprint": False,
            "published_at": _date_from_crossref(item),
            "updated_at": _clean(item.get("indexed", {}).get("date-time")) or None,
            "version": None,
            "categories": [str(value) for value in item.get("subject") or []],
            "confidence": 0.98,
        }
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
        return None


async def _resolve_semantic_scholar(
    client: httpx.AsyncClient,
    identifier: str,
    query: str,
) -> Optional[dict[str, Any]]:
    fields = "title,authors,venue,publicationVenue,publicationDate,journal,externalIds"
    url = f"https://api.semanticscholar.org/graph/v1/paper/{quote(identifier, safe=':')}?fields={fields}"
    try:
        response = await _get(client, url, accept="application/json")
        response.raise_for_status()
        item = response.json()
        title = _clean(item.get("title"))
        if not title:
            return None
        publication_venue = item.get("publicationVenue") or {}
        journal = item.get("journal") or {}
        journal_name = _clean(journal.get("name"))
        if journal_name.lower() in {"arxiv", "corr"}:
            journal_name = ""
        venue = _clean(publication_venue.get("name") or item.get("venue") or journal_name) or None
        alternate_names = [_clean(value) for value in publication_venue.get("alternate_names") or [] if _clean(value)]
        short_names = [value for value in alternate_names if len(value) <= 20]
        venue_short_name = min(short_names, key=len) if short_names else None
        external_ids = item.get("externalIds") or {}
        arxiv_id = _clean(external_ids.get("ArXiv")) or None
        doi = normalize_doi(_clean(external_ids.get("DOI")))
        authors = [
            _author(person.get("name"))
            for person in item.get("authors") or []
            if _clean(person.get("name"))
        ]
        return {
            "query": query,
            "source": "semantic_scholar",
            "sources": ["semantic_scholar"],
            "title": title,
            "authors": authors,
            "institutions": [],
            "abstract": "",
            "doi": doi,
            "arxiv_id": arxiv_id,
            "paper_url": None,
            "pdf_url": None,
            "venue": venue,
            "venue_short_name": venue_short_name,
            "venue_url": publication_venue.get("url"),
            "venue_type": _clean(publication_venue.get("type")) or ("journal" if journal_name else None),
            "publication_status": "published" if venue else "preprint" if arxiv_id else "unknown",
            "is_preprint": bool(arxiv_id),
            "published_at": item.get("publicationDate"),
            "updated_at": None,
            "version": None,
            "categories": [],
            "confidence": 0.97,
        }
    except (httpx.HTTPError, ValueError, TypeError):
        return None


def _resolve_document_hints(markdown_path: Path, query: str) -> Optional[dict[str, Any]]:
    try:
        frontmatter = markdown_path.read_text(encoding="utf-8", errors="replace")[:20_000]
    except OSError:
        return None
    match = PUBLICATION_LINE_RE.search(frontmatter)
    if not match:
        return None
    venue = _clean(match.group(4)).rstrip(".")
    status = "published" if match.group(1) else "accepted"
    venue_type = "journal" if match.group(1) and "journal" in match.group(1).lower() else "conference"
    return {
        "query": query,
        "source": "document_frontmatter",
        "sources": ["document_frontmatter"],
        "venue": venue,
        "venue_short_name": venue,
        "venue_type": venue_type,
        "publication_status": status,
        "confidence": 0.92,
    }


async def _resolve_openalex_title(client: httpx.AsyncClient, title: str, query: str) -> list[dict[str, Any]]:
    url = f"https://api.openalex.org/works?search={quote(title)}&per_page=5"
    try:
        response = await _get(client, url, accept="application/json")
        response.raise_for_status()
        results = response.json().get("results") or []
    except (httpx.HTTPError, ValueError, TypeError):
        return []
    candidates: list[dict[str, Any]] = []
    normalized_title = re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()
    for item in results:
        candidate_title = _clean(item.get("title"))
        if not candidate_title:
            continue
        candidate_normalized = re.sub(r"[^a-z0-9]+", " ", candidate_title.lower()).strip()
        score = 0.85 if candidate_normalized == normalized_title else 0.55
        authors = []
        for authorship in item.get("authorships") or []:
            person = authorship.get("author") or {}
            name = _clean(person.get("display_name"))
            affiliations = [_clean(org.get("display_name")) for org in authorship.get("institutions") or []]
            if name:
                authors.append(_author(name, affiliations))
        primary = item.get("primary_location") or {}
        source = primary.get("source") or {}
        source_type = _clean(source.get("type")) or None
        doi = normalize_doi(item.get("doi") or "")
        arxiv_id = normalize_arxiv_id(item.get("id") or "")
        if not arxiv_id:
            for location in item.get("locations") or []:
                arxiv_id = normalize_arxiv_id((location.get("landing_page_url") or ""))
                if arxiv_id:
                    break
        published_year = item.get("publication_year")
        item_type = _clean(item.get("type"))
        if primary.get("is_published") or (source and source_type != "repository" and item_type != "preprint"):
            publication_status = "published"
        elif primary.get("is_accepted"):
            publication_status = "accepted"
        elif item_type == "preprint" or arxiv_id:
            publication_status = "preprint"
        else:
            publication_status = "unknown"
        venue = _clean(source.get("display_name")) if source_type != "repository" else ""
        candidates.append({
            "query": query,
            "source": "openalex",
            "sources": ["openalex"],
            "title": candidate_title,
            "authors": authors,
            "institutions": sorted({aff for value in authors for aff in value.get("affiliations", [])}),
            "abstract": "",
            "doi": doi,
            "arxiv_id": arxiv_id,
            "paper_url": primary.get("landing_page_url") or item.get("id"),
            "pdf_url": primary.get("pdf_url"),
            "venue": venue or None,
            "venue_short_name": None,
            "venue_url": None,
            "venue_type": "journal" if source_type == "journal" else source_type,
            "publication_status": publication_status,
            "is_preprint": item_type == "preprint" or bool(arxiv_id),
            "published_at": item.get("publication_date") or (str(published_year) if published_year else None),
            "updated_at": None,
            "version": None,
            "categories": [_clean(concept.get("display_name")) for concept in item.get("concepts") or [] if _clean(concept.get("display_name"))],
            "confidence": score,
        })
    return sorted(candidates, key=lambda item: item["confidence"], reverse=True)


async def _resolve_url(client: httpx.AsyncClient, url: str, query: str) -> Optional[dict[str, Any]]:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("论文链接必须使用 http 或 https")
    try:
        response = await _get(client, url, accept="text/html,application/xhtml+xml,application/pdf")
        response.raise_for_status()
    except httpx.HTTPError:
        return None
    if response.content[:5] == b"%PDF-" or "application/pdf" in response.headers.get("content-type", "").lower():
        return {
            **_base_metadata(query),
            "source": "url",
            "sources": ["url"],
            "title": Path(parsed.path).stem.replace("_", " ") or parsed.netloc,
            "paper_url": url,
            "pdf_url": url,
            "confidence": 0.65,
        }
    parser = _MetaParser()
    parser.feed(response.text[:2_000_000])
    meta = parser.meta
    title = meta.get("citation_title") or meta.get("og:title") or parser.title
    author_values = parser.meta_values.get("citation_author", []) + parser.meta_values.get("author", [])
    authors = [{"name": value, "affiliations": []} for value in author_values if value]
    doi = normalize_doi(meta.get("citation_doi", "") or meta.get("dc.identifier", ""))
    pdf_url = next((urljoin(url, href) for rel, href in parser.links if "pdf" in rel or "alternate" in rel and href.lower().endswith(".pdf")), None)
    return {
        **_base_metadata(query),
        "source": "url",
        "sources": ["url"],
        "title": _clean(title) or url,
        "authors": authors,
        "institutions": [],
        "abstract": meta.get("citation_abstract") or meta.get("description") or meta.get("og:description", ""),
        "doi": doi,
        "paper_url": url,
        "pdf_url": pdf_url,
        "venue": meta.get("citation_journal_title") or meta.get("citation_conference"),
        "venue_short_name": None,
        "venue_url": None,
        "venue_type": "journal" if meta.get("citation_journal_title") else "conference" if meta.get("citation_conference") else None,
        "publication_status": "published" if meta.get("citation_publication_date") else "unknown",
        "is_preprint": False,
        "published_at": meta.get("citation_publication_date"),
        "updated_at": None,
        "version": None,
        "categories": [],
        "confidence": 0.7 if title else 0.35,
    }


def _merge(primary: dict[str, Any], secondary: dict[str, Any]) -> dict[str, Any]:
    merged = dict(primary)
    for key, value in secondary.items():
        if key in {"query", "source", "confidence"}:
            continue
        if value and (not merged.get(key) or merged.get(key) in ([], {}, None)):
            merged[key] = value
    merged["sources"] = sorted(set((primary.get("sources") or []) + (secondary.get("sources") or [])))
    if primary.get("doi") is None and secondary.get("doi"):
        merged["doi"] = secondary["doi"]
    status_rank = {"unknown": 0, "preprint": 1, "accepted": 2, "published": 3}
    primary_status = str(primary.get("publication_status") or "unknown")
    secondary_status = str(secondary.get("publication_status") or "unknown")
    if status_rank.get(secondary_status, 0) > status_rank.get(primary_status, 0):
        merged["publication_status"] = secondary_status
    if status_rank.get(secondary_status, 0) >= status_rank.get(primary_status, 0) and status_rank.get(secondary_status, 0) >= 2:
        for key in ("venue", "venue_short_name", "venue_url", "venue_type"):
            if secondary.get(key):
                merged[key] = secondary[key]
    merged["confidence"] = max(float(primary.get("confidence") or 0), float(secondary.get("confidence") or 0))
    return merged


async def resolve_metadata(query: str, client: Optional[httpx.AsyncClient] = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    cleaned = _clean(query)
    if not cleaned:
        raise ValueError("请输入论文标题、arXiv ID、DOI 或论文链接")
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=8.0), headers={"User-Agent": USER_AGENT})
    try:
        arxiv_id = normalize_arxiv_id(cleaned)
        doi = normalize_doi(cleaned)
        parsed = urlparse(cleaned)
        if arxiv_id:
            result = await _resolve_arxiv(client, arxiv_id, cleaned)
            if result:
                semantic_scholar = await _resolve_semantic_scholar(client, f"ARXIV:{arxiv_id}", cleaned)
                if semantic_scholar:
                    result = _merge(result, semantic_scholar)
                return result, [result]
        if doi:
            result = await _resolve_crossref(client, doi, cleaned)
            if result:
                semantic_scholar = await _resolve_semantic_scholar(client, f"DOI:{doi}", cleaned)
                if semantic_scholar:
                    result = _merge(result, semantic_scholar)
                return result, [result]
        if parsed.scheme in {"http", "https"}:
            result = await _resolve_url(client, cleaned, cleaned)
            if result:
                if result.get("doi"):
                    crossref = await _resolve_crossref(client, result["doi"], cleaned)
                    if crossref:
                        result = _merge(crossref, result)
                return result, [result]
        candidates = await _resolve_openalex_title(client, cleaned, cleaned)
        if candidates:
            selected = candidates[0]
            if selected.get("arxiv_id"):
                arxiv = await _resolve_arxiv(client, selected["arxiv_id"], cleaned)
                if arxiv:
                    selected = _merge(arxiv, selected)
            elif selected.get("doi"):
                crossref = await _resolve_crossref(client, selected["doi"], cleaned)
                if crossref:
                    selected = _merge(crossref, selected)
            candidates[0] = selected
            return selected, candidates
        raise LookupError("没有找到匹配的论文元数据")
    finally:
        if owns_client:
            await client.aclose()


async def import_paper(
    repository: ResearchRepository,
    space_id: str,
    query: str,
    *,
    download_pdf: bool = True,
    download_source: bool = True,
) -> dict[str, Any]:
    metadata, candidates = await resolve_metadata(query)
    metadata = {**_base_metadata(query), **metadata, "resolved_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    arxiv_id = str(metadata.get("arxiv_id") or "").strip().casefold()
    doi = str(metadata.get("doi") or "").strip().casefold().removeprefix("https://doi.org/")
    title_key = " ".join(str(metadata.get("title") or "").split()).casefold()
    for existing in repository.list_papers(space_id):
        if existing.get("resource_type") != "paper":
            continue
        existing_metadata = existing.get("metadata") or {}
        existing_arxiv = str(existing_metadata.get("arxiv_id") or "").strip().casefold()
        existing_doi = str(existing_metadata.get("doi") or "").strip().casefold().removeprefix("https://doi.org/")
        existing_title = " ".join(str(existing.get("title") or "").split()).casefold()
        same_identifier = bool(
            (arxiv_id and existing_arxiv == arxiv_id)
            or (doi and existing_doi == doi)
        )
        same_title_without_identifier = bool(
            not arxiv_id and not doi and title_key and existing_title == title_key
        )
        if same_identifier or same_title_without_identifier:
            warning = "论文已存在于目标研究空间，本次复用已有记录"
            return {
                "paper": existing,
                "metadata": existing_metadata,
                "candidates": candidates,
                "warnings": [warning],
                "deduplicated": True,
            }
    errors: list[str] = []
    stored_path: Optional[Path] = None
    if download_pdf and metadata.get("pdf_url"):
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0), follow_redirects=True) as client:
                response = await _get(client, str(metadata["pdf_url"]), accept="application/pdf")
                response.raise_for_status()
                content = response.content
                if len(content) > MAX_PDF_BYTES:
                    raise ValueError("PDF 超过 40 MB 限制")
                if content[:5] != b"%PDF-":
                    raise ValueError("下载地址未返回有效 PDF")
            name = re.sub(r"[^A-Za-z0-9._\-\u4e00-\u9fff]+", "_", metadata.get("title") or "paper").strip("_")[:150] or "paper"
            destination = repository.space_dir(space_id) / "papers" / f"{name}.pdf"
            if destination.exists():
                destination = destination.with_name(f"{destination.stem}_{uuid.uuid4().hex[:8]}{destination.suffix}")
            destination.write_bytes(content)
            stored_path = destination
            relative = destination.relative_to(repository.root.parent).as_posix()
            metadata.update({"size": len(content), "outputs_url": f"/outputs/{relative}"})
            markdown_path = destination.with_name(f"{destination.stem}.extracted.md")
            try:
                extraction = await asyncio.to_thread(extract_pdf_to_markdown, destination, markdown_path, metadata.get("title") or "Paper")
                metadata.update(extraction)
                try:
                    metadata.update(await asyncio.to_thread(render_paper_visual_assets, destination))
                except Exception as exc:
                    metadata.update(
                        {
                            "visual_ingestion_status": "error",
                            "visual_ingestion_error": str(exc)[:500],
                        }
                    )
                document_hints = _resolve_document_hints(markdown_path, query)
                if document_hints:
                    metadata = _merge(metadata, document_hints)
            except Exception as exc:
                errors.append(f"PDF 解析失败: {str(exc)[:300]}")
                metadata.update({"extraction_status": "error", "extraction_error": str(exc)[:500]})
        except (httpx.HTTPError, ValueError) as exc:
            errors.append(f"PDF 下载失败: {str(exc)[:300]}")
    if download_source and metadata.get("arxiv_id"):
        try:
            source_metadata = await fetch_arxiv_source(
                str(metadata["arxiv_id"]),
                repository.space_dir(space_id) / "papers",
                metadata.get("title") or _clean(query),
            )
            metadata.update(source_metadata)
        except (httpx.HTTPError, ValueError, OSError) as exc:
            errors.append(f"arXiv 源码获取失败: {str(exc)[:300]}")
    if errors:
        metadata["import_warnings"] = errors
    availability = "local_pdf" if stored_path else "metadata_only"
    status = "ready" if stored_path and metadata.get("extraction_status") == "ready" else "extract_error" if stored_path else "metadata_only"
    paper = repository.add_paper(
        space_id,
        title=metadata.get("title") or _clean(query),
        original_name=stored_path.name if stored_path else None,
        stored_path=str(stored_path) if stored_path else None,
        source_url=metadata.get("paper_url") or metadata.get("pdf_url"),
        availability=availability,
        status=status,
        metadata=metadata,
    )
    return {"paper": paper, "metadata": metadata, "candidates": candidates, "warnings": errors}


async def refresh_paper_metadata(
    repository: ResearchRepository,
    paper_id: str,
) -> dict[str, Any]:
    paper = repository.get_paper(paper_id)
    if not paper:
        raise LookupError("Paper not found")
    existing = dict(paper.get("metadata") or {})
    query = str(
        existing.get("arxiv_id")
        or existing.get("doi")
        or existing.get("paper_url")
        or paper.get("source_url")
        or paper.get("title")
        or ""
    )
    refreshed = existing
    try:
        resolved, _ = await resolve_metadata(query)
        refreshed = _merge(refreshed, resolved)
    except (LookupError, ValueError):
        pass

    text_path_value = refreshed.get("text_path")
    if text_path_value:
        document_hints = _resolve_document_hints(Path(str(text_path_value)), query)
        if document_hints:
            refreshed = _merge(refreshed, document_hints)

    source_path_value = refreshed.get("source_text_path")
    if source_path_value:
        try:
            source_text = Path(str(source_path_value)).read_text(encoding="utf-8", errors="replace")
        except OSError:
            source_text = ""
        if source_text:
            source_hints = extract_frontmatter_metadata(source_text)
            if source_hints:
                refreshed = _merge(refreshed, source_hints)

    refreshed["resolved_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    updated = repository.update_paper_metadata(paper_id, refreshed)
    if not updated:
        raise LookupError("Paper not found")
    return updated
