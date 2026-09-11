import {
  type CSSProperties,
  type FormEvent,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import {
  BadgeCheck,
  BookOpen,
  Building2,
  CalendarDays,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  ExternalLink,
  Loader2,
  Maximize2,
  MessageSquare,
  Minimize2,
  Minus,
  PanelLeftOpen,
  PanelRightOpen,
  Plus,
  Search,
  Users,
  X,
} from 'lucide-react';
import { Document, Page, pdfjs } from 'react-pdf';
import type { PDFDocumentProxy } from 'pdfjs-dist';
import 'react-pdf/dist/Page/AnnotationLayer.css';
import 'react-pdf/dist/Page/TextLayer.css';

import { API_BASE_URL, getApiHeaders } from '../config/api';
import type { ResearchPaper } from './types';
import './paper-reader.css';


pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.min.mjs',
  import.meta.url,
).toString();


interface PaperReaderProps {
  paper: ResearchPaper;
  focused: boolean;
  navigationCollapsed: boolean;
  onToggleFocus: () => void;
  onOpenNavigation: () => void;
  onOpenResources: () => void;
  onOpenChat: () => void;
  onClose: () => void;
}

function clamp(value: number, minimum: number, maximum: number) {
  return Math.min(maximum, Math.max(minimum, value));
}

function documentRequest(paper: ResearchPaper) {
  const path = paper.metadata?.outputs_url || `/api/v1/research/papers/${paper.id}/file`;
  const url = path.startsWith('http') ? path : `${API_BASE_URL}${path}`;
  return {
    url,
    httpHeaders: getApiHeaders() as Record<string, string>,
  };
}

function summarize(values: string[], limit: number) {
  const normalized = values.map((value) => value.trim()).filter(Boolean);
  const visible = normalized.slice(0, limit).join('、');
  return normalized.length > limit ? `${visible} 等 ${normalized.length} 位` : visible;
}

function publicationLabel(status?: string) {
  if (status === 'published') return '已发表';
  if (status === 'accepted') return '已接收';
  if (status === 'preprint') return '预印本';
  return '';
}

function formatPublicationDate(value?: string) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value.slice(0, 10);
  return date.toISOString().slice(0, 10);
}

export default function PaperReader({
  paper,
  focused,
  navigationCollapsed,
  onToggleFocus,
  onOpenNavigation,
  onOpenResources,
  onOpenChat,
  onClose,
}: PaperReaderProps) {
  const viewerRef = useRef<HTMLDivElement | null>(null);
  const pageRefs = useRef<Record<number, HTMLDivElement | null>>({});
  const searchInputRef = useRef<HTMLInputElement | null>(null);
  const [pdfDocument, setPdfDocument] = useState<PDFDocumentProxy | null>(null);
  const [numPages, setNumPages] = useState(Number(paper.metadata?.page_count || 0));
  const [currentPage, setCurrentPage] = useState(1);
  const [pageInput, setPageInput] = useState('1');
  const [viewerWidth, setViewerWidth] = useState(860);
  const [zoom, setZoom] = useState(1);
  const [loadingError, setLoadingError] = useState('');
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [searching, setSearching] = useState(false);
  const [searchMatches, setSearchMatches] = useState<number[]>([]);
  const [searchMatchIndex, setSearchMatchIndex] = useState(0);

  const file = useMemo(() => documentRequest(paper), [paper.id, paper.metadata?.outputs_url]);
  const basePageWidth = Math.min(920, Math.max(300, viewerWidth - 72));
  const pageWidth = Math.round(basePageWidth * zoom);
  const visibleWindow = 2;

  useEffect(() => {
    setPdfDocument(null);
    setNumPages(Number(paper.metadata?.page_count || 0));
    setCurrentPage(1);
    setPageInput('1');
    setZoom(1);
    setLoadingError('');
    setSearchQuery('');
    setSearchMatches([]);
    setSearchMatchIndex(0);
    pageRefs.current = {};
    const viewer = viewerRef.current;
    if (viewer && typeof viewer.scrollTo === 'function') viewer.scrollTo({ top: 0 });
  }, [paper.id]);

  useEffect(() => {
    setPageInput(String(currentPage));
  }, [currentPage]);

  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer) return;
    const updateWidth = () => setViewerWidth(viewer.clientWidth);
    updateWidth();
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(updateWidth);
    observer.observe(viewer);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const viewer = viewerRef.current;
    if (!viewer || !numPages || typeof IntersectionObserver === 'undefined') return;
    const observer = new IntersectionObserver((entries) => {
      const visible = entries
        .filter((entry) => entry.isIntersecting)
        .sort((left, right) => right.intersectionRatio - left.intersectionRatio)[0];
      if (!visible) return;
      const page = Number((visible.target as HTMLElement).dataset.page || 1);
      if (page) setCurrentPage(page);
    }, {
      root: viewer,
      rootMargin: '-18% 0px -52% 0px',
      threshold: [0.01, 0.2, 0.5, 0.8],
    });
    Object.values(pageRefs.current).forEach((element) => {
      if (element) observer.observe(element);
    });
    return () => observer.disconnect();
  }, [numPages, paper.id]);

  useEffect(() => {
    const handleShortcut = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'f') {
        event.preventDefault();
        setSearchOpen(true);
        window.setTimeout(() => searchInputRef.current?.focus(), 0);
      }
      if (event.key === 'Escape' && searchOpen) {
        setSearchOpen(false);
      }
    };
    window.addEventListener('keydown', handleShortcut);
    return () => window.removeEventListener('keydown', handleShortcut);
  }, [searchOpen]);

  function scrollToPage(page: number, behavior: ScrollBehavior = 'smooth') {
    const nextPage = clamp(page, 1, Math.max(1, numPages));
    setCurrentPage(nextPage);
    pageRefs.current[nextPage]?.scrollIntoView({ behavior, block: 'start' });
  }

  function submitPage(event: FormEvent) {
    event.preventDefault();
    const requested = Number.parseInt(pageInput, 10);
    if (Number.isFinite(requested)) scrollToPage(requested);
    else setPageInput(String(currentPage));
  }

  async function runSearch(event: FormEvent) {
    event.preventDefault();
    const query = searchQuery.trim().toLocaleLowerCase();
    if (!query || !pdfDocument || searching) return;
    setSearching(true);
    setSearchMatches([]);
    try {
      const matches: number[] = [];
      for (let pageNumber = 1; pageNumber <= pdfDocument.numPages; pageNumber += 1) {
        const page = await pdfDocument.getPage(pageNumber);
        const text = await page.getTextContent();
        const content = text.items
          .map((item) => ('str' in item ? item.str : ''))
          .join(' ')
          .toLocaleLowerCase();
        if (content.includes(query)) matches.push(pageNumber);
      }
      setSearchMatches(matches);
      setSearchMatchIndex(0);
      if (matches[0]) scrollToPage(matches[0]);
    } finally {
      setSearching(false);
    }
  }

  function moveSearchMatch(direction: -1 | 1) {
    if (!searchMatches.length) return;
    const nextIndex = (searchMatchIndex + direction + searchMatches.length) % searchMatches.length;
    setSearchMatchIndex(nextIndex);
    scrollToPage(searchMatches[nextIndex]);
  }

  const pageNumbers = Array.from({ length: numPages }, (_, index) => index + 1);
  const authors = paper.metadata?.authors?.map((author) => author.name).filter(Boolean) || [];
  const institutions = Array.from(new Set([
    ...(paper.metadata?.institutions || []),
    ...(paper.metadata?.authors || []).flatMap((author) => author.affiliations || []),
  ].map((value) => value.trim()).filter(Boolean)));
  const authorSummary = summarize(authors, 3);
  const primaryInstitution = institutions[0] || '';
  const secondaryInstitution = institutions[1] || '';
  const venue = paper.metadata?.venue_short_name || paper.metadata?.venue || '';
  const status = publicationLabel(paper.metadata?.publication_status);
  const publicationSummary = [venue, status].filter(Boolean).join(' · ');
  const publicationDate = formatPublicationDate(paper.metadata?.published_at);
  const publicationDateLabel = paper.metadata?.publication_status === 'preprint' ? '提交' : '发表';
  const identifier = paper.metadata?.arxiv_id
    ? `arXiv ${paper.metadata.arxiv_id}`
    : paper.metadata?.doi
      ? `DOI ${paper.metadata.doi}`
      : '';

  return (
    <section className="paper-reader" aria-label="论文阅读器">
      <header className="paper-reader-header">
        <button className="icon-button paper-nav-button" type="button" onClick={onOpenNavigation} title={navigationCollapsed ? '展开侧栏' : '打开对话导航'} aria-label={navigationCollapsed ? '展开侧栏' : '打开对话导航'}>
          <PanelLeftOpen size={17} />
        </button>
        <div className="paper-reader-title">
          <span className="paper-reader-kicker"><BookOpen size={14} />正在阅读</span>
          <strong title={paper.title}>{paper.title}</strong>
          <div className="paper-reader-metadata" aria-label="论文元数据">
            {authorSummary && (
              <span className="paper-meta-item paper-meta-authors" title={authors.join('、')}>
                <Users size={11} />{authorSummary}
              </span>
            )}
            {primaryInstitution && (
              <span className="paper-meta-item paper-meta-institutions paper-meta-primary-institution" title={`第一单位：${primaryInstitution}`}>
                <Building2 size={11} />第一单位 {primaryInstitution}
              </span>
            )}
            {secondaryInstitution && <span className="paper-meta-item paper-meta-institutions paper-meta-secondary-institution" title={`第二单位：${secondaryInstitution}`}>第二单位 {secondaryInstitution}</span>}
            {publicationSummary && (
              <span className="paper-meta-item paper-meta-publication" title={[paper.metadata?.venue, status].filter(Boolean).join(' · ')}>
                <BadgeCheck size={11} />{publicationSummary}
              </span>
            )}
            {publicationDate && <span className="paper-meta-item paper-meta-date" title={`${publicationDateLabel}日期：${publicationDate}`}><CalendarDays size={11} />{publicationDateLabel} {publicationDate}</span>}
            {identifier && <span className="paper-meta-item paper-meta-identifier" title={identifier}>{identifier}</span>}
          </div>
        </div>
        <div className="paper-reader-actions">
          <span className="paper-ready-state"><span />{numPages || paper.metadata?.page_count || '?'} 页</span>
          <button className="icon-button reader-mobile-chat" type="button" onClick={onOpenChat} title="打开 AI 对话">
            <MessageSquare size={17} />
          </button>
          <button className="icon-button" type="button" onClick={onOpenResources} title="打开论文库">
            <PanelRightOpen size={17} />
          </button>
          <a className="icon-button" href={file.url} target="_blank" rel="noreferrer" title="在新窗口打开 PDF">
            <ExternalLink size={16} />
          </a>
          <button className="icon-button" type="button" onClick={onClose} title="退出论文阅读">
            <X size={17} />
          </button>
        </div>
      </header>

      <div className="paper-toolbar">
        <div className="paper-toolbar-group page-controls">
          <button className="icon-button" type="button" onClick={() => scrollToPage(currentPage - 1)} disabled={currentPage <= 1} title="上一页">
            <ChevronLeft size={17} />
          </button>
          <form className="paper-page-form" onSubmit={submitPage}>
            <input aria-label="当前页码" value={pageInput} onChange={(event) => setPageInput(event.target.value.replace(/[^0-9]/g, ''))} inputMode="numeric" />
            <span>/ {numPages || '?'}</span>
          </form>
          <button className="icon-button" type="button" onClick={() => scrollToPage(currentPage + 1)} disabled={!numPages || currentPage >= numPages} title="下一页">
            <ChevronRight size={17} />
          </button>
        </div>

        <div className="paper-toolbar-divider" />

        <div className="paper-toolbar-group search-controls">
          {searchOpen ? (
            <form className="paper-search-form" onSubmit={runSearch}>
              <Search size={14} />
              <input ref={searchInputRef} value={searchQuery} onChange={(event) => setSearchQuery(event.target.value)} placeholder="搜索论文" aria-label="搜索论文" />
              {searching ? <Loader2 className="spin" size={14} /> : searchMatches.length > 0 ? <span>{searchMatchIndex + 1}/{searchMatches.length}</span> : searchQuery ? <span>0</span> : null}
              {searchMatches.length > 0 && <>
                <button type="button" onClick={() => moveSearchMatch(-1)} title="上一个结果"><ChevronUp size={14} /></button>
                <button type="button" onClick={() => moveSearchMatch(1)} title="下一个结果"><ChevronDown size={14} /></button>
              </>}
              <button type="button" onClick={() => { setSearchOpen(false); setSearchMatches([]); }} title="关闭搜索"><X size={14} /></button>
            </form>
          ) : (
            <button className="icon-button" type="button" onClick={() => { setSearchOpen(true); window.setTimeout(() => searchInputRef.current?.focus(), 0); }} title="搜索论文">
              <Search size={16} />
            </button>
          )}
        </div>

        <div className="paper-toolbar-spacer" />

        <div className="paper-toolbar-group zoom-controls">
          <button className="icon-button" type="button" onClick={() => setZoom((value) => clamp(Number((value - 0.1).toFixed(2)), 0.6, 1.8))} disabled={zoom <= 0.6} title="缩小">
            <Minus size={16} />
          </button>
          <button className="zoom-value" type="button" onClick={() => setZoom(1)} title="适合宽度">{Math.round(zoom * 100)}%</button>
          <button className="icon-button" type="button" onClick={() => setZoom((value) => clamp(Number((value + 0.1).toFixed(2)), 0.6, 1.8))} disabled={zoom >= 1.8} title="放大">
            <Plus size={16} />
          </button>
          <button className="icon-button focus-button" type="button" onClick={onToggleFocus} title={focused ? '退出专注模式' : '专注阅读'}>
            {focused ? <Minimize2 size={16} /> : <Maximize2 size={16} />}
          </button>
        </div>
      </div>

      <div ref={viewerRef} className="paper-document-scroll scrollbar-thin">
        <Document
          key={paper.id}
          file={file}
          loading={<div className="paper-loading"><Loader2 className="spin" size={22} /><span>正在载入 PDF</span></div>}
          error={<div className="paper-loading error"><BookOpen size={22} /><span>{loadingError || 'PDF 载入失败'}</span><a href={file.url} target="_blank" rel="noreferrer">在新窗口打开</a></div>}
          onLoadSuccess={(document) => {
            setPdfDocument(document);
            setNumPages(document.numPages);
            setLoadingError('');
          }}
          onLoadError={(reason) => setLoadingError(reason.message || 'PDF 载入失败')}
        >
          <div className="paper-pages" style={{ '--paper-page-width': `${pageWidth}px` } as CSSProperties}>
            {pageNumbers.map((pageNumber) => {
              const shouldRender = Math.abs(pageNumber - currentPage) <= visibleWindow;
              return (
                <div
                  key={pageNumber}
                  ref={(element) => { pageRefs.current[pageNumber] = element; }}
                  className={`paper-page-shell ${searchMatches.includes(pageNumber) ? 'search-match' : ''}`}
                  data-page={pageNumber}
                  style={{ minHeight: `${Math.round(pageWidth * 1.414)}px` }}
                >
                  {shouldRender ? <Page
                    pageNumber={pageNumber}
                    width={pageWidth}
                    renderAnnotationLayer
                    renderTextLayer
                    loading={<div className="paper-page-placeholder"><span>第 {pageNumber} 页</span></div>}
                  /> : <div className="paper-page-placeholder"><span>第 {pageNumber} 页</span></div>}
                  <span className="paper-page-number">{pageNumber}</span>
                </div>
              );
            })}
          </div>
        </Document>
      </div>
    </section>
  );
}
