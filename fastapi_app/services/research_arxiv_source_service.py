from __future__ import annotations

import gzip
import io
import re
import shutil
import tarfile
import uuid
from pathlib import Path
from typing import Any, Optional

import httpx


USER_AGENT = "ThinkFlow Research Person/1.0 (arXiv source resolver)"
MAX_ARCHIVE_BYTES = 25 * 1024 * 1024
MAX_SOURCE_BYTES = 30 * 1024 * 1024
MAX_SOURCE_FILES = 800
TEXT_SUFFIXES = {".tex", ".bib", ".bbl", ".sty", ".cls"}
INCLUDE_RE = re.compile(r"\\(?:input|include|subfile)\s*\{([^{}]+)\}")
AFFILIATION_RE = re.compile(
    r"\\(?:affil|affiliation|institute|institution)\s*(?:\[[^\]]*\])?\s*\{([^{}]{2,240})\}"
    r"|\\textsuperscript\s*\{[^{}]+\}\s*\{([^{}]{2,240})\}",
    re.I,
)
NUMBERED_AFFILIATION_RE = re.compile(
    r"\$\s*\^\s*\{?(\d{1,2})\}?\s*\$\s*(.+?)"
    r"(?=(?:\\(?:quad|qquad))+|\$\s*\^\s*\{?\d|\\\\|[\r\n])"
)


def _safe_source_path(root: Path, member_name: str) -> Optional[Path]:
    member = Path(member_name)
    if member.is_absolute() or ".." in member.parts or member.suffix.lower() not in TEXT_SUFFIXES:
        return None
    destination = (root / member).resolve()
    return destination if root.resolve() in destination.parents else None


def _extract_archive(content: bytes, source_dir: Path) -> list[Path]:
    extracted: list[Path] = []
    total_bytes = 0
    try:
        archive = tarfile.open(fileobj=io.BytesIO(content), mode="r:*")
    except tarfile.ReadError:
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(content)) as compressed:
                plain = compressed.read(MAX_SOURCE_BYTES + 1)
        except (gzip.BadGzipFile, EOFError, OSError) as exc:
            raise ValueError("arXiv 源码包不是支持的 tar 或 gzip 格式") from exc
        if len(plain) > MAX_SOURCE_BYTES:
            raise ValueError("arXiv 解压源码超过 30 MB 限制")
        destination = source_dir / "main.tex"
        destination.write_bytes(plain)
        return [destination]

    with archive:
        for member in archive.getmembers():
            if not member.isfile():
                continue
            destination = _safe_source_path(source_dir, member.name)
            if destination is None:
                continue
            if member.size < 0 or member.size > MAX_SOURCE_BYTES:
                continue
            total_bytes += member.size
            if total_bytes > MAX_SOURCE_BYTES:
                raise ValueError("arXiv 解压源码超过 30 MB 限制")
            if len(extracted) >= MAX_SOURCE_FILES:
                raise ValueError("arXiv 源码文件数量超过 800 个限制")
            source = archive.extractfile(member)
            if source is None:
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(source.read())
            extracted.append(destination)
    return extracted


def _entrypoint(tex_files: list[Path]) -> Path:
    if not tex_files:
        raise ValueError("arXiv 源码包中没有找到 TeX 文件")

    def score(path: Path) -> tuple[int, int]:
        text = path.read_text(encoding="utf-8", errors="replace")
        points = 0
        if "\\documentclass" in text:
            points += 100
        if "\\begin{document}" in text:
            points += 50
        if path.stem.lower() in {"main", "paper", "manuscript", "article"}:
            points += 25
        return points, len(text)

    return max(tex_files, key=score)


def _expand_tex(path: Path, root: Path, seen: set[Path], stack: set[Path]) -> str:
    resolved = path.resolve()
    if root.resolve() not in resolved.parents or resolved in stack or not resolved.is_file():
        return ""
    seen.add(resolved)
    stack.add(resolved)
    text = resolved.read_text(encoding="utf-8", errors="replace")

    def replace(match: re.Match[str]) -> str:
        raw = match.group(1).strip()
        if not raw or "\\" in raw or "#" in raw:
            return match.group(0)
        child = resolved.parent / raw
        if not child.suffix:
            child = child.with_suffix(".tex")
        child_resolved = child.resolve()
        if root.resolve() not in child_resolved.parents or not child_resolved.is_file():
            return match.group(0)
        expanded = _expand_tex(child_resolved, root, seen, stack)
        relative = child_resolved.relative_to(root.resolve()).as_posix()
        return f"\n% BEGIN INCLUDED FILE: {relative}\n{expanded}\n% END INCLUDED FILE: {relative}\n"

    expanded = INCLUDE_RE.sub(replace, text)
    stack.remove(resolved)
    return expanded


def _clean_latex_text(value: str) -> str:
    cleaned = value
    for _ in range(3):
        cleaned = re.sub(r"\\[A-Za-z]+\*?(?:\[[^\]]*\])?\{([^{}]*)\}", r"\1", cleaned)
    cleaned = re.sub(r"\\(?:quad|qquad|and|\\)", " ", cleaned)
    cleaned = re.sub(r"[{}~]", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip(" ,;.-")


def extract_frontmatter_metadata(source: str) -> dict[str, Any]:
    institutions: list[str] = []
    for match in AFFILIATION_RE.finditer(source[:80_000]):
        value = _clean_latex_text(match.group(1) or match.group(2) or "")
        if value and value not in institutions:
            institutions.append(value)
    numbered: dict[int, str] = {}
    for match in NUMBERED_AFFILIATION_RE.finditer(source[:80_000]):
        value = _clean_latex_text(match.group(2) or "")
        if value:
            # Author superscripts appear before the affiliation block and can
            # look identical. The later value for an index is the address.
            numbered[int(match.group(1))] = value
    for _, value in sorted(numbered.items()):
        if value not in institutions:
            institutions.append(value)
    return {"institutions": institutions} if institutions else {}


def build_combined_source(source_dir: Path, title: str) -> dict[str, Any]:
    tex_files = sorted(path for path in source_dir.rglob("*.tex") if path.is_file())
    entrypoint = _entrypoint(tex_files)
    seen: set[Path] = set()
    combined = _expand_tex(entrypoint, source_dir, seen, set())
    for path in tex_files:
        resolved = path.resolve()
        if resolved in seen:
            continue
        relative = resolved.relative_to(source_dir.resolve()).as_posix()
        combined += f"\n\n% BEGIN UNREFERENCED TEX FILE: {relative}\n{path.read_text(encoding='utf-8', errors='replace')}\n% END UNREFERENCED TEX FILE: {relative}\n"
    output = source_dir / "source.combined.tex"
    output.write_text(f"% ThinkFlow combined LaTeX source for: {title}\n{combined}", encoding="utf-8")
    return {
        "source_ingestion_status": "ready",
        "source_text_path": str(output),
        "source_entrypoint": entrypoint.relative_to(source_dir).as_posix(),
        "source_file_count": len(tex_files),
        "source_chars": len(combined),
        **extract_frontmatter_metadata(combined),
    }


async def fetch_arxiv_source(
    arxiv_id: str,
    papers_dir: Path,
    title: str,
    *,
    client: Optional[httpx.AsyncClient] = None,
) -> dict[str, Any]:
    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0), follow_redirects=True)
    response: Optional[httpx.Response] = None
    source_url = ""
    source_dir: Optional[Path] = None
    try:
        for host in ("https://export.arxiv.org", "https://arxiv.org"):
            source_url = f"{host}/e-print/{arxiv_id}"
            try:
                candidate = await client.get(source_url, headers={"User-Agent": USER_AGENT})
                candidate.raise_for_status()
                if int(candidate.headers.get("content-length") or 0) > MAX_ARCHIVE_BYTES:
                    raise ValueError("arXiv 源码包超过 25 MB 限制")
                response = candidate
                break
            except httpx.HTTPError:
                continue
        if response is None:
            raise ValueError("arXiv 未返回可下载的 LaTeX 源码")
        if len(response.content) > MAX_ARCHIVE_BYTES:
            raise ValueError("arXiv 源码包超过 25 MB 限制")
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", title).strip("_")[:120] or "paper"
        source_dir = papers_dir / f"{safe_name}.source"
        if source_dir.exists():
            source_dir = papers_dir / f"{safe_name}_{uuid.uuid4().hex[:8]}.source"
        source_dir.mkdir(parents=True, exist_ok=False)
        extracted = _extract_archive(response.content, source_dir)
        metadata = build_combined_source(source_dir, title)
        metadata.update({"source_archive_url": source_url, "source_extracted_files": len(extracted)})
        return metadata
    except Exception:
        if source_dir is not None and source_dir.exists():
            shutil.rmtree(source_dir, ignore_errors=True)
        raise
    finally:
        if owns_client:
            await client.aclose()
