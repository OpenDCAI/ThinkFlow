import { type CSSProperties, type FormEvent, type PointerEvent as ReactPointerEvent, useEffect, useMemo, useRef, useState } from 'react';
import {
  Archive,
  BookOpen,
  Bot,
  CalendarDays,
  Check,
  ChevronDown,
  Square,
  FileText,
  Home,
  Lightbulb,
  Link2,
  Loader2,
  MessageSquare,
  MoreHorizontal,
  PanelLeftClose,
  PanelLeftOpen,
  PanelRightOpen,
  Paperclip,
  Plus,
  RefreshCw,
  Search,
  Send,
  Settings,
  Sparkles,
  Trash2,
  Undo2,
  Upload,
  Wrench,
  X,
} from 'lucide-react';
import { researchApi, streamRegeneratedTurn, streamTurn } from './api';
import MarkdownPreview from './MarkdownPreview';
import PaperReader from './PaperReader';
import ResearchHome from './ResearchHome';
import GlobalResearchAssistant from './GlobalResearchAssistant';
import type {
  CodexEvent,
  CodexHarness,
  CodexHarnessPhase,
  ResearchConversation,
  ResearchIdea,
  ResearchJob,
  ResearchMessage,
  ResearchPaper,
  PaperNote,
  ResearchSpace,
  SkillSummary,
  WikiPage,
} from './types';
import './research-workspace.css';

type ResourceTab = 'papers' | 'wiki' | 'ideas' | 'jobs' | 'skills';

const eventLabels: Record<string, string> = {
  commandExecution: '运行命令',
  webSearch: '检索网页',
  mcpToolCall: '调用工具',
  fileChange: '更新研究文件',
  reasoning: '分析中',
};

const terminalHarnessPhases: CodexHarnessPhase[] = ['completed', 'cancelled', 'failed'];

function isHarnessPhase(value: unknown): value is CodexHarnessPhase {
  return typeof value === 'string' && [
    'queued', 'preparing_context', 'context_ready', 'starting_thread', 'starting_turn',
    'waiting_for_response', 'streaming', 'tool_running', 'retrying', 'cancelling',
    'completed', 'cancelled', 'failed',
  ].includes(value);
}

function harnessEventStatus(phase: CodexHarnessPhase): CodexEvent['status'] {
  if (phase === 'failed') return 'error';
  if (phase === 'completed' || phase === 'cancelled' || phase === 'context_ready') return 'done';
  return 'running';
}

function formatElapsed(milliseconds: number) {
  const seconds = Math.max(0, Math.floor(milliseconds / 1000));
  return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
}

function maximumReaderChatWidth(viewportWidth: number, navigationCollapsed: boolean) {
  const minimum = 340;
  if (navigationCollapsed) return Math.max(minimum, Math.floor((viewportWidth - 5) / 2));
  const navigationWidth = viewportWidth > 1180 ? 260 : 210;
  return Math.max(minimum, Math.min(560, viewportWidth - navigationWidth - 440));
}

function precedingUserMessageIndex(messages: ResearchMessage[], targetIndex: number) {
  for (let index = targetIndex - 1; index >= 0; index -= 1) {
    if (messages[index].role === 'user') return index;
  }
  return -1;
}

function stamp() {
  return new Date().toISOString();
}

function shortTime(value?: string) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
}

function publicationLabel(paper: ResearchPaper) {
  const status = paper.metadata?.publication_status;
  const label = status === 'preprint' ? '预印本' : status === 'published' ? '已发表' : status === 'accepted' ? '已接收' : '发表状态未知';
  return paper.metadata?.is_preprint && status !== 'preprint' ? `${label} · 有预印本` : label;
}

function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  return (
    <div className="research-modal-backdrop" onMouseDown={onClose}>
      <div className="research-modal" onMouseDown={(event) => event.stopPropagation()}>
        <header><h3>{title}</h3><button className="icon-button" onClick={onClose} title="关闭"><X size={18} /></button></header>
        {children}
      </div>
    </div>
  );
}

function EmptyState({ icon, title, action }: { icon: React.ReactNode; title: string; action?: React.ReactNode }) {
  return <div className="resource-empty"><span>{icon}</span><p>{title}</p>{action}</div>;
}

export default function ResearchWorkspace() {
  const [spaces, setSpaces] = useState<ResearchSpace[]>([]);
  const [globalResources, setGlobalResources] = useState<ResearchPaper[]>([]);
  const [showHome, setShowHome] = useState(false);
  const [globalAssistantOpen, setGlobalAssistantOpen] = useState(false);
  const [selectedSpaceId, setSelectedSpaceId] = useState('');
  const [conversations, setConversations] = useState<ResearchConversation[]>([]);
  const [selectedConversationId, setSelectedConversationId] = useState('');
  const [messages, setMessages] = useState<ResearchMessage[]>([]);
  const [papers, setPapers] = useState<ResearchPaper[]>([]);
  const [wiki, setWiki] = useState<WikiPage[]>([]);
  const [ideas, setIdeas] = useState<ResearchIdea[]>([]);
  const [jobs, setJobs] = useState<ResearchJob[]>([]);
  const [skills, setSkills] = useState<SkillSummary[]>([]);
  const [resourceTab, setResourceTab] = useState<ResourceTab>('papers');
  const [prompt, setPrompt] = useState('');
  const [assistantDraft, setAssistantDraft] = useState('');
  const [events, setEvents] = useState<CodexEvent[]>([]);
  const [harness, setHarness] = useState<CodexHarness | null>(null);
  const [harnessNow, setHarnessNow] = useState(0);
  const [harnessExpanded, setHarnessExpanded] = useState(true);
  const [recentSkill, setRecentSkill] = useState<{ name: string; detail: string; status: 'loaded' | 'provided' } | null>(null);
  const [running, setRunning] = useState(false);
  const [messageActionId, setMessageActionId] = useState('');
  const [creatingConversation, setCreatingConversation] = useState(false);
  const [deletingSpaceId, setDeletingSpaceId] = useState('');
  const [deletingConversationId, setDeletingConversationId] = useState('');
  const [uploadingPaper, setUploadingPaper] = useState(false);
  const [importingPaper, setImportingPaper] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [codexStatus, setCodexStatus] = useState<{
    available: boolean;
    signed_in?: boolean;
    error?: string;
    skills?: SkillSummary[];
    skills_error?: string | null;
    skills_root?: string;
  }>({ available: false });
  const [modal, setModal] = useState<'space' | 'wiki' | 'paper-import' | 'blog' | 'paper-note' | null>(null);
  const [resourceSearch, setResourceSearch] = useState('');
  const [mobilePanel, setMobilePanel] = useState<'nav' | 'resources' | null>(null);
  const [readerFocus, setReaderFocus] = useState(false);
  const [navCollapsed, setNavCollapsed] = useState(false);
  const [readerOpen, setReaderOpen] = useState(true);
  const [readerChatWidth, setReaderChatWidth] = useState(420);
  const [readerMobileView, setReaderMobileView] = useState<'paper' | 'chat'>('paper');
  const [newSpaceTitle, setNewSpaceTitle] = useState('');
  const [newSpaceDescription, setNewSpaceDescription] = useState('');
  const [wikiDraft, setWikiDraft] = useState({ title: '', content: '', tags: '' });
  const [paperImportQuery, setPaperImportQuery] = useState('');
  const [paperImportDownload, setPaperImportDownload] = useState(true);
  const [paperImportResult, setPaperImportResult] = useState<{ paper: ResearchPaper; warnings: string[] } | null>(null);
  const [blogDraft, setBlogDraft] = useState({ title: '', url: '' });
  const [paperNoteTarget, setPaperNoteTarget] = useState<ResearchPaper | null>(null);
  const [paperNote, setPaperNote] = useState<PaperNote | null>(null);
  const [loadingPaperNote, setLoadingPaperNote] = useState(false);
  const [refreshingPaperNote, setRefreshingPaperNote] = useState(false);
  const [savingPaperNote, setSavingPaperNote] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const messageScrollRef = useRef<HTMLDivElement | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);
  const promptRef = useRef<HTMLTextAreaElement | null>(null);
  const loadSpaceRef = useRef(0);
  const loadMessagesRef = useRef(0);
  const stickToBottomRef = useRef(true);
  const pendingDeltaRef = useRef('');
  const deltaFrameRef = useRef<number | null>(null);
  const readerResizeRef = useRef(false);

  const selectedSpace = spaces.find((item) => item.id === selectedSpaceId);
  const selectedConversation = conversations.find((item) => item.id === selectedConversationId);
  const activePaperIds = selectedConversation?.paper_ids?.length
    ? selectedConversation.paper_ids
    : selectedConversation?.active_paper_id ? [selectedConversation.active_paper_id] : [];
  const activePapers = activePaperIds.map((paperId) => papers.find((item) => item.id === paperId)).filter((paper): paper is ResearchPaper => Boolean(paper));
  const activePaper = activePapers[0];
  const readingPaper = readerOpen && activePaper?.resource_type !== 'blog' ? activePaper : undefined;

  useEffect(() => {
    void initialize();
  }, []);

  useEffect(() => {
    if (!selectedSpaceId) return;
    void loadSpace(selectedSpaceId);
  }, [selectedSpaceId]);

  useEffect(() => {
    if (!selectedConversationId) {
      loadMessagesRef.current += 1;
      setMessages([]);
      return;
    }
    const conversationId = selectedConversationId;
    const requestId = ++loadMessagesRef.current;
    void researchApi.messages(conversationId).then((rows) => {
      if (requestId === loadMessagesRef.current) setMessages(rows);
    }).catch((reason) => {
      if (requestId === loadMessagesRef.current) setError(reason.message);
    });
  }, [selectedConversationId]);

  useEffect(() => () => {
    if (deltaFrameRef.current !== null) cancelAnimationFrame(deltaFrameRef.current);
  }, []);

  useEffect(() => () => {
    readerResizeRef.current = false;
    document.body.classList.remove('reader-resizing');
  }, []);

  useEffect(() => {
    if (!harness || terminalHarnessPhases.includes(harness.phase)) return;
    setHarnessNow(Date.now());
    const timer = window.setInterval(() => setHarnessNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [harness?.phase, harness?.startedAt]);

  useEffect(() => {
    if (!stickToBottomRef.current) return;
    const container = messageScrollRef.current;
    if (container) container.scrollTop = container.scrollHeight;
  }, [assistantDraft, events, harness, messages]);

  async function initialize() {
    setLoading(true);
    setError('');
    try {
      const resourceLoader = (researchApi as typeof researchApi & {
        resources?: () => Promise<ResearchPaper[]>;
      }).resources;
      const [spaceRows, status, skillRows, resourceRows] = await Promise.all([
        researchApi.spaces(),
        researchApi.status(),
        researchApi.skills(),
        resourceLoader ? resourceLoader().catch(() => []) : Promise.resolve([]),
      ]);
      setSpaces(spaceRows);
      setGlobalResources(resourceRows);
      setSkills(skillRows.length ? skillRows : (status.codex.skills || []));
      setCodexStatus(status.codex);
      if (spaceRows.length !== 1) {
        setShowHome(true);
      } else if (spaceRows[0]) {
        setSelectedSpaceId(spaceRows[0].id);
      }
    } catch (reason: any) {
      setError(reason.message || '研究工作台初始化失败');
    } finally {
      setLoading(false);
    }
  }

  async function refreshGlobalResources() {
    const resourceLoader = (researchApi as typeof researchApi & {
      resources?: () => Promise<ResearchPaper[]>;
    }).resources;
    if (!resourceLoader) return;
    try {
      setGlobalResources(await resourceLoader());
    } catch {
      // The space workflow remains usable when the optional library refresh fails.
    }
  }

  async function loadSpace(spaceId: string) {
    const requestId = ++loadSpaceRef.current;
    setError('');
    try {
      const [chatRows, paperRows, wikiRows, ideaRows, jobRows] = await Promise.all([
        researchApi.conversations(spaceId),
        researchApi.papers(spaceId),
        researchApi.wiki(spaceId),
        researchApi.ideas(spaceId),
        researchApi.jobs(spaceId),
      ]);
      if (requestId !== loadSpaceRef.current || spaceId !== selectedSpaceId) return;
      setConversations(chatRows);
      setPapers(paperRows);
      setWiki(wikiRows);
      setIdeas(ideaRows);
      setJobs(jobRows);
      setSelectedConversationId((current) => chatRows.some((item) => item.id === current) ? current : chatRows[0]?.id || '');
    } catch (reason: any) {
      setError(reason.message || '加载研究空间失败');
    }
  }

  function openGlobalResource(resource: ResearchPaper) {
    const linkedSpaceId = resource.space_ids?.find((spaceId) => spaces.some((space) => space.id === spaceId));
    if (linkedSpaceId) {
      enterSpace(linkedSpaceId);
      return;
    }
    setGlobalAssistantOpen(true);
  }

  async function createSpace(event: FormEvent) {
    event.preventDefault();
    if (!newSpaceTitle.trim()) return;
    const space = await researchApi.createSpace(newSpaceTitle.trim(), newSpaceDescription.trim());
    setSpaces((current) => [{ ...space, resource_count: 0, conversation_count: 0 }, ...current]);
    setNewSpaceTitle('');
    setNewSpaceDescription('');
    setModal(null);
    setSelectedSpaceId(space.id);
    setShowHome(false);
  }

  function enterSpace(spaceId: string) {
    setGlobalAssistantOpen(false);
    setSelectedSpaceId(spaceId);
    setShowHome(false);
    setMobilePanel(null);
  }

  async function quickChat(spaceId: string) {
    setError('');
    try {
      const conversation = await researchApi.createConversation(spaceId);
      setSelectedSpaceId(spaceId);
      setShowHome(false);
      setSpaces((current) => current.map((space) => space.id === spaceId ? { ...space, conversation_count: (space.conversation_count || 0) + 1 } : space));
      setConversations([conversation]);
      setSelectedConversationId(conversation.id);
      setMessages([]);
    } catch (reason: any) {
      setError(reason.message || '新建对话失败');
    }
  }

  async function deleteSpace(space: ResearchSpace) {
    if (deletingSpaceId || !window.confirm(
      `删除研究空间“${space.title}”？\n\n空间内的论文、Blog、对话、Wiki、Idea、笔记和本地产物都会被永久删除。`,
    )) return;
    setDeletingSpaceId(space.id);
    setError('');
    try {
      await researchApi.deleteSpace(space.id);
      setSpaces((current) => current.filter((item) => item.id !== space.id));
      if (selectedSpaceId === space.id) {
        loadSpaceRef.current += 1;
        loadMessagesRef.current += 1;
        setSelectedSpaceId('');
        setSelectedConversationId('');
        setConversations([]);
        setMessages([]);
        setPapers([]);
        setWiki([]);
        setIdeas([]);
        setJobs([]);
        setReaderFocus(false);
        setReaderOpen(false);
        setShowHome(true);
      }
    } catch (reason: any) {
      setError(reason.message || '删除研究空间失败');
    } finally {
      setDeletingSpaceId('');
    }
  }

  function goHome() {
    if (running) return;
    setReaderFocus(false);
    setReaderOpen(false);
    setShowHome(true);
    setGlobalAssistantOpen(false);
    setMobilePanel(null);
  }

  async function createConversation() {
    if (!selectedSpaceId || creatingConversation) return;
    setCreatingConversation(true);
    setError('');
    try {
      let conversation = await researchApi.createConversation(selectedSpaceId);
      if (activePaperIds.length === 1) {
        conversation = await researchApi.bindPaper(conversation.id, activePaperIds[0]);
      } else if (activePaperIds.length > 1) {
        conversation = (await researchApi.setConversationPapers(conversation.id, activePaperIds)).conversation;
      }
      setSpaces((current) => current.map((space) => space.id === selectedSpaceId ? { ...space, conversation_count: (space.conversation_count || 0) + 1 } : space));
      loadSpaceRef.current += 1;
      loadMessagesRef.current += 1;
      setConversations((current) => [conversation, ...current]);
      setSelectedConversationId(conversation.id);
      setMessages([]);
      setAssistantDraft('');
      setEvents([]);
      setHarness(null);
      setHarnessExpanded(true);
      stickToBottomRef.current = true;
      setMobilePanel(null);
    } catch (reason: any) {
      setError(reason.message || '新建对话失败');
    } finally {
      setCreatingConversation(false);
    }
  }

  async function createIdeaConversation() {
    if (!selectedSpaceId || creatingConversation) return;
    setCreatingConversation(true);
    setError('');
    try {
      const conversation = await researchApi.createConversation(selectedSpaceId, 'Idea 讨论', {
        scope: 'idea',
        paper_ids: papers.slice(0, 12).map((paper) => paper.id),
      });
      setSpaces((current) => current.map((space) => space.id === selectedSpaceId
        ? { ...space, conversation_count: (space.conversation_count || 0) + 1 }
        : space));
      setConversations((current) => [conversation, ...current]);
      setSelectedConversationId(conversation.id);
      setMessages([]);
      setAssistantDraft('');
      setEvents([]);
      setHarness(null);
      setReaderOpen(false);
      setReaderFocus(false);
      setResourceTab('ideas');
      setMobilePanel(null);
      window.requestAnimationFrame(() => promptRef.current?.focus());
    } catch (reason: any) {
      setError(reason.message || '新建 Idea 对话失败');
    } finally {
      setCreatingConversation(false);
    }
  }

  async function deleteConversation(conversation: ResearchConversation) {
    if (deletingConversationId || !window.confirm(`删除“${conversation.title}”及其全部消息？`)) return;
    setDeletingConversationId(conversation.id);
    setError('');
    try {
      await researchApi.deleteConversation(conversation.id);
      const remaining = conversations.filter((item) => item.id !== conversation.id);
      setConversations(remaining);
      setSpaces((current) => current.map((space) => space.id === conversation.space_id ? { ...space, conversation_count: Math.max(0, (space.conversation_count || 0) - 1) } : space));
      if (selectedConversationId === conversation.id) {
        setSelectedConversationId(remaining[0]?.id || '');
        setMessages([]);
        setReaderOpen(Boolean(remaining[0]?.active_paper_id));
      }
    } catch (reason: any) {
      setError(reason.message || '删除对话失败');
    } finally {
      setDeletingConversationId('');
    }
  }

  function flushAssistantDelta() {
    deltaFrameRef.current = null;
    const next = pendingDeltaRef.current;
    pendingDeltaRef.current = '';
    if (next) setAssistantDraft((current) => current + next);
  }

  function recordHarness(data: Record<string, any>) {
    const phase: CodexHarnessPhase = isHarnessPhase(data.phase) ? data.phase : 'waiting_for_response';
    const now = Date.now();
    const terminal = terminalHarnessPhases.includes(phase);
    setHarness((current) => {
      const startedAt = current?.startedAt || now;
      return {
        phase,
        title: String(data.title || current?.title || 'Codex 正在执行'),
        detail: String(data.detail || ''),
        startedAt,
        updatedAt: now,
        endedAt: terminal ? now : undefined,
        attempt: Number(data.attempt || current?.attempt || 1),
        maxAttempts: Number(data.maxAttempts || current?.maxAttempts || 3),
        threadId: typeof data.threadId === 'string' ? data.threadId : current?.threadId,
        turnId: typeof data.turnId === 'string' ? data.turnId : current?.turnId,
      };
    });
    setEvents((current) => {
      const next: CodexEvent = {
        id: `harness-${phase}`,
        type: 'harness',
        title: String(data.title || 'Codex 正在执行'),
        detail: String(data.detail || ''),
        status: harnessEventStatus(phase),
      };
      const found = current.findIndex((entry) => entry.id === next.id);
      // Lifecycle rows are checkpoints, not concurrent jobs. Once a newer
      // checkpoint arrives, every previous harness row is complete. Terminal
      // states also close any raw tool row still marked as running.
      const settled = current.map((entry) => {
        if (entry.id === next.id) return entry;
        if (entry.type === 'harness' || terminal) {
          return entry.status === 'running' ? { ...entry, status: 'done' as const } : entry;
        }
        return entry;
      });
      if (found === -1) return [...settled.slice(-7), next];
      return settled.map((entry, index) => index === found ? next : entry);
    });
  }

  function startHarness(title = '请求已提交', detail = '正在连接 Codex sandbox') {
    const now = Date.now();
    setHarness({
      phase: 'queued',
      title,
      detail,
      startedAt: now,
      updatedAt: now,
      attempt: 1,
      maxAttempts: 3,
    });
    setHarnessNow(now);
    setHarnessExpanded(true);
    setEvents([{
      id: 'harness-queued',
      type: 'harness',
      title,
      detail,
      status: 'running',
    }]);
  }

  function addOrUpdateEvent(type: string, data: Record<string, any>) {
    if (type === 'turn.harness') {
      recordHarness(data);
      return;
    }
    if (type === 'turn.skill') {
      const name = typeof data.name === 'string' && data.name.trim() ? data.name : 'research skill';
      const status = data.status === 'provided' ? 'provided' : 'loaded';
      const detail = String(data.detail || (status === 'provided' ? '已作为本次执行输入提供，是否采用由 Codex 决定' : 'Codex 自主选择并载入 Skill'));
      setRecentSkill({ name, detail, status });
      setEvents((current) => [
        ...current.filter((item) => item.type !== 'skill'),
        {
          id: 'skill-current',
          type: 'skill',
          title: status === 'provided' ? `已提供 ${name} Skill` : `已载入 ${name} Skill`,
          detail,
          status: 'done',
        },
      ]);
      return;
    }
    if (type === 'item/agentMessage/delta') {
      setHarness((current) => current?.phase === 'streaming' ? current : current ? {
        ...current,
        phase: 'streaming',
        title: 'Codex 正在生成回复',
        detail: '回复内容会持续显示在下方',
        updatedAt: Date.now(),
      } : current);
      pendingDeltaRef.current += String(data.delta || '');
      if (deltaFrameRef.current === null) {
        deltaFrameRef.current = requestAnimationFrame(flushAssistantDelta);
      }
      return;
    }
    if (type === 'error') {
      const message = String(data.message || data.error?.message || 'Codex 执行失败');
      recordHarness({ phase: 'failed', title: 'Codex 执行失败', detail: message });
      setError(message);
      return;
    }
    if (type === 'turn.retrying') {
      if (data.reset) {
        pendingDeltaRef.current = '';
        if (deltaFrameRef.current !== null) {
          cancelAnimationFrame(deltaFrameRef.current);
          deltaFrameRef.current = null;
        }
        setAssistantDraft('');
      }
      recordHarness({
        phase: 'retrying',
        title: '连接中断，正在重试',
        detail: String(data.message || ''),
        attempt: data.attempt,
        maxAttempts: data.maxAttempts,
      });
      return;
    }
    if (type === 'turn.started') {
      recordHarness({
        phase: 'waiting_for_response',
        title: 'Codex 已开始执行',
        detail: '正在等待模型生成第一个响应',
        attempt: data.attempt,
        maxAttempts: data.maxAttempts,
        threadId: data.threadId,
        turnId: data.turnId,
      });
      return;
    }
    if (type === 'turn/completed') {
      const status = data.turn?.status || data.status;
      recordHarness({
        phase: status === 'interrupted' ? 'cancelled' : 'completed',
        title: status === 'interrupted' ? 'Codex 已停止' : '回复已完成',
        detail: '本次执行的对话内容已保存',
      });
      return;
    }
    const item = data.item?.root || data.item;
    if (!item?.type || item.type === 'agentMessage' || item.type === 'userMessage') return;
    const id = item.id || `${type}-${Date.now()}`;
    const detail = item.command || item.query || item.tool || item.server || '';
    const status: CodexEvent['status'] = type === 'item/completed'
      ? (item.status === 'failed' ? 'error' : 'done')
      : 'running';
    setEvents((current) => {
      const next: CodexEvent = { id, type: item.type, title: eventLabels[item.type] || item.type, detail, status };
      const found = current.findIndex((entry) => entry.id === id);
      if (found === -1) return [...current.slice(-7), next];
      return current.map((entry, index) => index === found ? next : entry);
    });
  }

  async function submitPrompt(event: FormEvent) {
    event.preventDefault();
    const value = prompt.trim();
    if (!value || running || !selectedConversationId) return;
    setPrompt('');
    setError('');
    setAssistantDraft('');
    setRecentSkill(null);
    setRunning(true);
    startHarness();
    stickToBottomRef.current = true;
    setMessages((current) => [...current, {
      id: `local-${Date.now()}`,
      conversation_id: selectedConversationId,
      role: 'user',
      content: value,
      event_type: 'message',
      created_at: stamp(),
    }]);
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      await streamTurn(
        selectedConversationId,
        value,
        activePaper?.id,
        controller.signal,
        addOrUpdateEvent,
      );
      flushAssistantDelta();
      const [nextMessages, nextChats] = await Promise.all([
        researchApi.messages(selectedConversationId),
        researchApi.conversations(selectedSpaceId),
      ]);
      setMessages(nextMessages);
      setConversations(nextChats);
      setAssistantDraft('');
    } catch (reason: any) {
      if (reason.name !== 'AbortError') {
        const message = reason.message || '发送失败';
        recordHarness({ phase: 'failed', title: 'Codex 连接失败', detail: message });
        setError(message);
      }
    } finally {
      abortRef.current = null;
      setRunning(false);
    }
  }

  async function rollbackMessage(message: ResearchMessage) {
    if (running || messageActionId || !selectedConversationId) return;
    const targetIndex = messages.findIndex((item) => item.id === message.id);
    const userIndex = precedingUserMessageIndex(messages, targetIndex);
    if (targetIndex < 0 || userIndex < 0) return;
    const laterTurns = messages.slice(targetIndex + 1).some((item) => item.role === 'user');
    const detail = laterTurns
      ? '这会删除对应提问、这条回答以及后续全部对话。'
      : '这会删除对应提问和这条回答。';
    if (!window.confirm(`回滚到这轮之前？\n\n${detail}`)) return;
    setMessageActionId(message.id);
    setError('');
    try {
      const result = await researchApi.rollbackMessage(selectedConversationId, message.id);
      setMessages(result.messages);
      setConversations((current) => current.map((item) => item.id === result.conversation.id ? result.conversation : item));
      setAssistantDraft('');
      setEvents([]);
      setHarness(null);
      setRecentSkill(null);
    } catch (reason: any) {
      setError(reason.message || '回滚失败');
    } finally {
      setMessageActionId('');
    }
  }

  async function regenerateMessage(message: ResearchMessage) {
    if (running || messageActionId || !selectedConversationId || !selectedSpaceId) return;
    const conversationId = selectedConversationId;
    const targetIndex = messages.findIndex((item) => item.id === message.id);
    const userIndex = precedingUserMessageIndex(messages, targetIndex);
    if (targetIndex < 0 || userIndex < 0) return;
    if (
      messages.slice(targetIndex + 1).some((item) => item.role === 'user')
      && !window.confirm('重新生成这条回答会回滚并删除它后面的对话分支。继续吗？')
    ) return;
    setMessageActionId(message.id);
    setError('');
    setAssistantDraft('');
    setRecentSkill(null);
    setRunning(true);
    startHarness('正在重新生成', '正在回滚错误分支并重建 Codex sandbox');
    stickToBottomRef.current = true;
    setMessages((current) => current.slice(0, userIndex + 1));
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      await streamRegeneratedTurn(conversationId, message.id, controller.signal, addOrUpdateEvent);
      flushAssistantDelta();
      const [nextMessages, nextChats] = await Promise.all([
        researchApi.messages(conversationId),
        researchApi.conversations(selectedSpaceId),
      ]);
      setMessages(nextMessages);
      setConversations(nextChats);
      setAssistantDraft('');
    } catch (reason: any) {
      const nextMessages = await researchApi.messages(conversationId).catch(() => messages);
      setMessages(nextMessages);
      if (reason.name !== 'AbortError') {
        const detail = reason.message || '重新生成失败，原回答已恢复';
        recordHarness({ phase: 'failed', title: '重新生成失败', detail });
        setError(detail);
      }
    } finally {
      abortRef.current = null;
      setRunning(false);
      setMessageActionId('');
    }
  }

  async function stopTurn() {
    if (!selectedConversationId) return;
    recordHarness({
      phase: 'cancelling',
      title: '正在请求停止',
      detail: '正在向 Codex sandbox 发送中断请求',
    });
    setHarnessExpanded(true);
    await researchApi.cancel(selectedConversationId).catch(() => undefined);
    abortRef.current?.abort();
    recordHarness({
      phase: 'cancelled',
      title: 'Codex 已停止',
      detail: '停止请求已发送，本次输出已保留',
    });
    setRunning(false);
  }

  async function uploadPaper(file?: File) {
    if (!file || !selectedSpaceId || uploadingPaper) return;
    setUploadingPaper(true);
    setError('');
    try {
      const paper = await researchApi.uploadPaper(selectedSpaceId, file);
      setPapers((current) => [paper, ...current]);
      void refreshGlobalResources();
      let conversation = selectedConversation;
      if (!conversation) {
        conversation = await researchApi.createConversation(selectedSpaceId, `阅读 ${paper.title}`);
        setSpaces((current) => current.map((space) => space.id === selectedSpaceId ? { ...space, conversation_count: (space.conversation_count || 0) + 1 } : space));
      }
      conversation = await researchApi.bindPaper(conversation.id, paper.id);
      setConversations((current) => [conversation!, ...current.filter((item) => item.id !== conversation!.id)]);
      setSelectedConversationId(conversation.id);
      setPrompt(`请先概括《${paper.title}》的研究问题、核心方法、关键实验结论和主要局限。`);
      setResourceTab('papers');
      setReaderFocus(false);
      setReaderOpen(true);
      setReaderMobileView('paper');
      setMobilePanel(null);
    } catch (reason: any) {
      setError(reason.message || '上传论文失败');
    } finally {
      setUploadingPaper(false);
      if (fileRef.current) fileRef.current.value = '';
    }
  }

  async function openPaperConversation(paper: ResearchPaper, prepareSummary = false, createNew = false) {
    if (!selectedSpaceId) return;
    let conversation = createNew ? undefined : selectedConversation;
    if (!conversation) {
      conversation = await researchApi.createConversation(selectedSpaceId, `阅读 ${paper.title}`);
      setSpaces((current) => current.map((space) => space.id === selectedSpaceId ? { ...space, conversation_count: (space.conversation_count || 0) + 1 } : space));
    }
    const existingIds = conversation.paper_ids?.length
      ? conversation.paper_ids
      : conversation.active_paper_id ? [conversation.active_paper_id] : [];
    const nextPaperIds = [paper.id, ...existingIds.filter((paperId) => paperId !== paper.id)];
    conversation = nextPaperIds.length === 1
      ? await researchApi.bindPaper(conversation.id, paper.id)
      : (await researchApi.setConversationPapers(conversation.id, nextPaperIds)).conversation;
    setConversations((current) => [conversation!, ...current.filter((item) => item.id !== conversation!.id)]);
    setSelectedConversationId(conversation.id);
    if (prepareSummary) setPrompt(`请先概括《${paper.title}》的研究问题、核心方法、关键实验结论和主要局限。`);
    setResourceTab('papers');
    setReaderFocus(false);
    setReaderOpen(true);
    setReaderMobileView('paper');
    setMobilePanel(null);
  }

  async function importPaperFromQuery(event: FormEvent) {
    event.preventDefault();
    const query = paperImportQuery.trim();
    if (!query || !selectedSpaceId || importingPaper) return;
    setImportingPaper(true);
    setError('');
    setPaperImportResult(null);
    try {
      const result = await researchApi.importPaper(selectedSpaceId, query, paperImportDownload);
      setPapers((current) => [result.paper, ...current.filter((item) => item.id !== result.paper.id)]);
      void refreshGlobalResources();
      setPaperImportResult({ paper: result.paper, warnings: result.warnings || [] });
      setPaperImportQuery('');
    } catch (reason: any) {
      setError(reason.message || '论文导入失败');
    } finally {
      setImportingPaper(false);
    }
  }

  async function selectPaper(paper: ResearchPaper, prepareSummary = false) {
    if (!selectedSpaceId) return;
    if (paper.status === 'extract_error' || paper.metadata?.extraction_status === 'error') {
      setError('这份 PDF 解析失败，暂时无法进行论文对话；请重新上传有效 PDF。');
      return;
    }
    if (paper.resource_type !== 'blog' && (!paper.stored_path || paper.metadata?.extraction_status !== 'ready')) {
      setError('这篇论文目前只有元数据或 PDF 尚未解析，无法开启全文对话。请先下载 PDF 或上传本地文件。');
      return;
    }
    setError('');
    try {
      await openPaperConversation(paper, prepareSummary);
    } catch (reason: any) {
      setError(reason.message || '绑定论文失败');
    }
  }

  async function removeConversationPaper(paperId: string) {
    if (!selectedConversationId) return;
    const remaining = activePaperIds.filter((id) => id !== paperId);
    try {
      const conversation = remaining.length <= 1
        ? await researchApi.bindPaper(selectedConversationId, remaining[0])
        : (await researchApi.setConversationPapers(selectedConversationId, remaining)).conversation;
      setConversations((current) => current.map((item) => item.id === conversation.id ? conversation : item));
      if (!remaining.length) setReaderOpen(false);
    } catch (reason: any) {
      setError(reason.message || '移除论文上下文失败');
    }
  }

  async function openPaperNote(paper: ResearchPaper) {
    setPaperNoteTarget(paper);
    setPaperNote(null);
    setModal('paper-note');
    setLoadingPaperNote(true);
    setError('');
    try {
      setPaperNote(await researchApi.paperNote(paper.id));
    } catch (reason: any) {
      setError(reason.message || 'Paper 记忆卡加载失败');
    } finally {
      setLoadingPaperNote(false);
    }
  }

  async function refreshPaperNote() {
    if (!paperNoteTarget || refreshingPaperNote) return;
    setRefreshingPaperNote(true);
    setError('');
    try {
      setPaperNote(await researchApi.refreshPaperNote(paperNoteTarget.id));
    } catch (reason: any) {
      setError(reason.message || 'Paper 记忆卡生成失败');
    } finally {
      setRefreshingPaperNote(false);
    }
  }

  async function saveCurrentPaperNote() {
    if (!paperNoteTarget || !paperNote || savingPaperNote) return;
    setSavingPaperNote(true);
    try {
      setPaperNote(await researchApi.savePaperNote(paperNoteTarget.id, paperNote));
    } catch (reason: any) {
      setError(reason.message || 'Paper 记忆卡保存失败');
    } finally {
      setSavingPaperNote(false);
    }
  }

  async function addBlog(event: FormEvent) {
    event.preventDefault();
    if (!selectedSpaceId || !blogDraft.url.trim()) return;
    setError('');
    try {
      const resource = await researchApi.addBlog(selectedSpaceId, blogDraft.url.trim(), blogDraft.title.trim());
      setPapers((current) => [resource, ...current.filter((item) => item.id !== resource.id)]);
      void refreshGlobalResources();
      setSpaces((current) => current.map((space) => space.id === selectedSpaceId ? { ...space, resource_count: (space.resource_count || 0) + 1 } : space));
      setBlogDraft({ title: '', url: '' });
      setModal(null);
      setResourceTab('papers');
    } catch (reason: any) {
      setError(reason.message || '添加 Blog 失败');
    }
  }

  function handleMessageScroll() {
    const container = messageScrollRef.current;
    if (!container) return;
    stickToBottomRef.current = container.scrollHeight - container.scrollTop - container.clientHeight < 80;
  }

  function startReaderResize(event: ReactPointerEvent<HTMLDivElement>) {
    if (!readingPaper || readerFocus || event.button !== 0) return;
    event.preventDefault();
    readerResizeRef.current = true;
    document.body.classList.add('reader-resizing');
    const updateWidth = (pointer: PointerEvent) => {
      if (!readerResizeRef.current) return;
      const viewportWidth = document.documentElement.clientWidth;
      const maximum = maximumReaderChatWidth(viewportWidth, navCollapsed);
      setReaderChatWidth(Math.round(Math.min(maximum, Math.max(340, viewportWidth - pointer.clientX))));
    };
    const stopResize = () => {
      readerResizeRef.current = false;
      document.body.classList.remove('reader-resizing');
      window.removeEventListener('pointermove', updateWidth);
      window.removeEventListener('pointerup', stopResize);
    };
    window.addEventListener('pointermove', updateWidth);
    window.addEventListener('pointerup', stopResize, { once: true });
  }

  function closePaperReader() {
    setReaderFocus(false);
    setReaderOpen(false);
  }

  async function saveWiki(event: FormEvent) {
    event.preventDefault();
    if (!selectedSpaceId || !wikiDraft.title.trim()) return;
    const page = await researchApi.saveWiki(selectedSpaceId, {
      title: wikiDraft.title,
      content: wikiDraft.content,
      tags: wikiDraft.tags.split(',').map((item) => item.trim()).filter(Boolean),
      source_conversation_id: selectedConversationId || undefined,
    });
    setWiki((current) => [page, ...current.filter((item) => item.id !== page.id)]);
    setWikiDraft({ title: '', content: '', tags: '' });
    setModal(null);
    setResourceTab('wiki');
  }

  async function queueTranslation(paperId: string) {
    if (!selectedSpaceId) return;
    const response = await researchApi.createTranslation(selectedSpaceId, paperId, selectedConversationId || undefined);
    setJobs((current) => [response.job, ...current]);
    setResourceTab('jobs');
  }

  const filteredResources = useMemo(() => {
    const query = resourceSearch.trim().toLowerCase();
    if (!query) return { papers, wiki, ideas, skills };
    return {
      papers: papers.filter((item) => item.title.toLowerCase().includes(query)),
      wiki: wiki.filter((item) => `${item.title} ${item.content} ${item.tags.join(' ')}`.toLowerCase().includes(query)),
      ideas: ideas.filter((item) => `${item.title} ${item.problem} ${item.tags.join(' ')}`.toLowerCase().includes(query)),
      skills: skills.filter((item) => `${item.name} ${item.description}`.toLowerCase().includes(query)),
    };
  }, [ideas, papers, resourceSearch, skills, wiki]);

  if (loading) {
    return <div className="research-loading"><Loader2 className="spin" size={24} /><span>正在连接研究工作台</span></div>;
  }

  if (globalAssistantOpen) {
    return <GlobalResearchAssistant
      codexAvailable={codexStatus.available}
      onBack={() => { setGlobalAssistantOpen(false); setShowHome(true); }}
      onSpacesChanged={setSpaces}
    />;
  }

  if (showHome) {
    return <>
      <ResearchHome spaces={spaces} resources={globalResources} onOpenResource={openGlobalResource} onEnter={enterSpace} onCreateSpace={() => setModal('space')} onQuickChat={(spaceId) => void quickChat(spaceId)} onDelete={(space) => void deleteSpace(space)} deletingSpaceId={deletingSpaceId} onOpenGlobalAssistant={() => setGlobalAssistantOpen(true)} />
      {error && <div className="home-error" role="alert">{error}</div>}
      {modal === 'space' && <Modal title="新建研究空间" onClose={() => setModal(null)}><form className="modal-form" onSubmit={createSpace}><label>空间名称<input autoFocus value={newSpaceTitle} onChange={(event) => setNewSpaceTitle(event.target.value)} placeholder="例如：SWE 的演进" /></label><label>研究目标<textarea rows={3} value={newSpaceDescription} onChange={(event) => setNewSpaceDescription(event.target.value)} placeholder="例如：梳理从自动补全到自主软件工程的演进" /></label><div className="modal-actions"><button type="button" onClick={() => setModal(null)}>取消</button><button className="primary-button" type="submit">创建空间</button></div></form></Modal>}
    </>;
  }

  return (
    <main
      className={`research-shell ${readingPaper ? 'paper-reading' : ''} ${readerFocus ? 'reader-focus' : ''} ${navCollapsed ? 'nav-collapsed' : ''} reader-pane-${readerMobileView}`}
      style={readingPaper ? { '--reader-chat-width': `${readerChatWidth}px` } as CSSProperties : undefined}
    >
      {mobilePanel && <button className="mobile-backdrop" aria-label="关闭侧栏" onClick={() => setMobilePanel(null)} />}
      <aside className={`research-nav ${mobilePanel === 'nav' ? 'mobile-open' : ''}`}>
        <header className="brand-row">
          <div className="brand-mark">TF</div>
          <div><strong>ThinkFlow</strong><span>Research</span></div>
          {!navCollapsed && <button
            className="icon-button subtle nav-collapse-button"
            onClick={() => {
              if (window.innerWidth <= 900) {
                setMobilePanel(null);
              } else {
                setNavCollapsed(true);
              }
            }}
            title="收起侧栏"
            aria-label="收起侧栏"
          >
            <PanelLeftClose size={17} />
          </button>}
        </header>

        <div className="space-context">
          <span className="space-icon"><Archive size={16} /></span>
          <span><small>当前研究空间</small><strong>{selectedSpace?.title || '研究空间'}</strong></span>
        </div>
        <button className="text-action home-nav-action" onClick={goHome}><Home size={14} />返回研究空间首页</button>

        <div className="conversation-heading"><span>对话</span></div>
        <button className="new-conversation-button" onClick={() => void createConversation()} disabled={!selectedSpaceId || creatingConversation}>{creatingConversation ? <Loader2 className="spin" size={15} /> : <Plus size={15} />}{creatingConversation ? '正在创建对话' : '新建对话'}</button>
        <div className="conversation-list scrollbar-thin">
          {conversations.map((conversation) => (
            <div key={conversation.id} className={`conversation-row ${conversation.id === selectedConversationId ? 'active' : ''}`}>
            <button className="conversation-item" onClick={() => { setSelectedConversationId(conversation.id); setReaderOpen(Boolean(conversation.active_paper_id || conversation.paper_ids?.length)); setReaderFocus(false); setReaderMobileView('paper'); setMobilePanel(null); }}>
              <MessageSquare size={15} />
              <span><strong>{conversation.title}</strong><small>{conversation.status === 'running' ? 'Codex 执行中' : `${conversation.resource_count || conversation.paper_ids?.length || (conversation.active_paper_id ? 1 : 0) ? `${conversation.resource_count || conversation.paper_ids?.length || 1} 项资料 · ` : ''}${shortTime(conversation.updated_at)}`}</small></span>
              {conversation.status === 'running' && <Loader2 className="spin" size={13} />}
            </button>
            <button className="conversation-delete" title="删除对话" aria-label={`删除对话 ${conversation.title}`} disabled={deletingConversationId === conversation.id} onClick={() => void deleteConversation(conversation)}>{deletingConversationId === conversation.id ? <Loader2 className="spin" size={13} /> : <Trash2 size={13} />}</button>
            </div>
          ))}
          {selectedSpaceId && conversations.length === 0 && <button className="empty-conversation" onClick={() => void createConversation()} disabled={creatingConversation}>{creatingConversation ? <Loader2 className="spin" size={15} /> : <Plus size={16} />}{creatingConversation ? '正在创建' : '创建第一个对话'}</button>}
        </div>

        <footer className="nav-footer">
          <div className={`runtime-status ${codexStatus.available ? 'online' : 'offline'}`}><span /><div><strong>Codex SDK</strong><small>{codexStatus.available ? `本机配置已连接 · ${codexStatus.skills?.filter((skill) => skill.enabled !== false).length || 0} 个 Skill 可用` : '连接不可用'}</small></div></div>
          <button className="icon-button" title="设置"><Settings size={17} /></button>
        </footer>
      </aside>

      {readingPaper && <PaperReader
        paper={readingPaper}
        focused={readerFocus}
        navigationCollapsed={navCollapsed}
        onToggleFocus={() => setReaderFocus((current) => !current)}
        onOpenNavigation={() => {
          if (window.innerWidth <= 900) {
            setMobilePanel('nav');
          } else {
            setReaderChatWidth((current) => Math.min(current, maximumReaderChatWidth(window.innerWidth, false)));
            setNavCollapsed(false);
          }
        }}
        onOpenResources={() => setMobilePanel('resources')}
        onOpenChat={() => setReaderMobileView('chat')}
        onClose={closePaperReader}
      />}

      {readingPaper && <div
        className="reader-splitter"
        role="separator"
        aria-label="调整 PDF 和对话窗口宽度"
        aria-orientation="vertical"
        onPointerDown={startReaderResize}
      />}

      <section className={`research-chat ${readingPaper ? 'reader-chat' : ''}`}>
        <header className="chat-header">
          {navCollapsed && !readingPaper && <button className="icon-button nav-restore-button" type="button" onClick={() => setNavCollapsed(false)} title="展开侧栏" aria-label="展开侧栏"><PanelLeftOpen size={18} /></button>}
          <button className="icon-button mobile-panel-button" onClick={() => setMobilePanel('nav')} title="打开对话导航"><PanelLeftOpen size={18} /></button>
          {readingPaper && <button className="icon-button reader-mobile-paper" type="button" onClick={() => setReaderMobileView('paper')} title="阅读论文"><BookOpen size={18} /></button>}
          <div className="chat-heading"><h1>{readingPaper ? '与 Codex 对话' : selectedConversation?.title || selectedSpace?.title || 'Research Workspace'}</h1><p>{readingPaper ? `${readingPaper.title}${activePapers.length > 1 ? ` · 共 ${activePapers.length} 项资料` : ''}` : selectedSpace ? `${selectedSpace.title} · 独立 Codex sandbox` : '创建研究空间后开始'}</p></div>
          <div className="chat-runtime"><span className={codexStatus.available ? 'online-dot' : 'offline-dot'} />{codexStatus.available ? 'Codex online' : 'Codex offline'}{codexStatus.skills?.length ? <span className="skill-runtime">{codexStatus.skills.filter((skill) => skill.enabled !== false).length} Skills ready</span> : null}{readingPaper && recentSkill && <span className="skill-runtime">Skill · {recentSkill.name}</span>}<button className="icon-button"><MoreHorizontal size={18} /></button></div>
          <button className="icon-button mobile-panel-button" onClick={() => setMobilePanel('resources')} title="打开研究资源"><PanelRightOpen size={18} /></button>
        </header>

        {error && <div className="research-error"><span>{error}</span><button onClick={() => setError('')}><X size={15} /></button></div>}

        <div ref={messageScrollRef} className="message-scroll scrollbar-thin" onScroll={handleMessageScroll}>
          {!selectedSpaceId ? (
            <div className="chat-empty"><div className="empty-symbol"><Sparkles size={25} /></div><h2>返回研究空间首页</h2><p>请从首页选择一个研究空间后开始对话。</p><button className="primary-button" onClick={goHome}><Home size={16} />返回首页</button></div>
          ) : !selectedConversationId ? (
            <div className="chat-empty"><div className="empty-symbol"><MessageSquare size={25} /></div><h2>开始一次研究对话</h2><p>每个对话会启动独立且可恢复的 Codex thread。</p><button className="primary-button" onClick={() => void createConversation()}><Plus size={16} />新建对话</button></div>
          ) : messages.length === 0 && !assistantDraft && !harness ? (
            <div className="chat-empty chat-prompts">
              <div className="empty-symbol"><Bot size={25} /></div><h2>从论文和问题出发</h2><p>Codex 可以直接读取空间中的完整 PDF，并将长期内容整理到 Wiki 或 Idea。</p>
              <div className="prompt-grid">
                {['总结论文库中的研究脉络', '搜索这个方向近两年的代表论文', '把这次讨论整理为 Research Idea', '检查 Wiki 中还缺哪些关键证据'].map((item) => <button key={item} onClick={() => setPrompt(item)}>{item}</button>)}
              </div>
            </div>
          ) : (
            <div className="message-column">
              {messages.map((message) => {
                const replayable = (message.role === 'assistant' && message.event_type === 'message') || message.event_type === 'error';
                return (
                <article key={message.id} className={`message ${message.role}`}>
                  <div className="message-avatar">{message.role === 'user' ? '你' : message.role === 'assistant' ? <Sparkles size={15} /> : '!'}</div>
                  <div className="message-body"><div className="message-meta">{message.role === 'user' ? '你' : message.role === 'assistant' ? 'Codex' : '系统'}<span>{shortTime(message.created_at)}</span></div>
                    {message.role === 'assistant' ? <MarkdownPreview>{message.content}</MarkdownPreview> : <p>{message.content}</p>}
                    {replayable && <div className="message-actions">
                      <button type="button" onClick={() => void regenerateMessage(message)} disabled={running || Boolean(messageActionId)} title={message.event_type === 'error' ? '重新执行这次 Codex 请求' : '重新生成这条回答'}>
                        <RefreshCw className={messageActionId === message.id && running ? 'spin' : ''} size={13} />{message.event_type === 'error' ? '重新执行' : '重新生成'}
                      </button>
                      <button type="button" onClick={() => void rollbackMessage(message)} disabled={running || Boolean(messageActionId)} title="删除对应提问、回答及后续分支">
                        <Undo2 size={13} />回滚
                      </button>
                    </div>}
                  </div>
                </article>
                );
              })}
              {(running || harness || events.length > 0 || assistantDraft) && <article className="message assistant streaming">
                <div className="message-avatar"><Sparkles size={15} /></div>
                <div className="message-body"><div className="message-meta">Codex<span>{running ? '执行中' : harness?.phase === 'failed' ? '执行失败' : '执行完成'}</span></div>
                  {harness && <section className={`codex-harness ${harness.phase} ${harnessExpanded ? 'expanded' : 'collapsed'}`} aria-live="polite">
                    <button type="button" className="codex-harness-header" onClick={() => setHarnessExpanded((current) => !current)} aria-expanded={harnessExpanded}>
                      <span className="codex-harness-status">{harness.phase === 'failed' ? <X size={14} /> : terminalHarnessPhases.includes(harness.phase) ? <Check size={14} /> : <Loader2 className="spin" size={14} />}</span>
                      <span className="codex-harness-title"><strong>Codex Harness</strong><small>{harness.title}</small></span>
                      <span className="codex-harness-elapsed">{formatElapsed((harness.endedAt || harnessNow || Date.now()) - harness.startedAt)}</span>
                      <ChevronDown className={harnessExpanded ? 'harness-chevron open' : 'harness-chevron'} size={15} />
                    </button>
                    {harnessExpanded && <div className="codex-harness-body">
                      <div className="harness-current"><strong>{harness.title}</strong>{harness.detail && <span>{harness.detail}</span>}</div>
                      <div className="harness-meta"><span>独立研究 sandbox</span>{codexStatus.skills?.length ? <span title={codexStatus.skills_root}>可用 Skills · {codexStatus.skills.filter((skill) => skill.enabled !== false).map((skill) => skill.name).join('、')}</span> : null}{recentSkill ? <span className="harness-skill">{recentSkill.status === 'provided' ? '已提供' : '已载入'} {recentSkill.name} Skill</span> : <span>本轮未收到 Skill 事件</span>}<span>第 {harness.attempt}/{harness.maxAttempts} 次</span>{harness.threadId && <span title={harness.threadId}>线程 {harness.threadId.slice(0, 10)}</span>}{harness.turnId && <span title={harness.turnId}>执行 {harness.turnId.slice(0, 10)}</span>}</div>
                      {events.length > 0 && <div className="event-list">{events.map((item) => <div key={item.id} className={`event-row ${item.status}`}><span>{item.status === 'running' ? <Loader2 className="spin" size={14} /> : item.status === 'done' ? <Check size={14} /> : <X size={14} />}</span><div><strong>{item.title}</strong>{item.detail && <code title={String(item.detail)}>{String(item.detail).slice(0, 180)}</code>}</div></div>)}</div>}
                    </div>}
                  </section>}
                  {assistantDraft && <MarkdownPreview>{assistantDraft}</MarkdownPreview>}
                </div>
              </article>}
            </div>
          )}
        </div>

        <form className="composer" onSubmit={submitPrompt}>
          {activePapers.length > 0 && <div className="composer-context-list"><span className="composer-context-label"><FileText size={14} />{activePapers.length > 1 ? `多论文上下文 · ${activePapers.length}` : '当前论文'}</span><div>{activePapers.map((paper) => <span className="composer-context-chip" key={paper.id} title={paper.title}><strong>{paper.title}</strong><button type="button" title={`移除 ${paper.title}`} onClick={() => void removeConversationPaper(paper.id)}><X size={12} /></button></span>)}</div></div>}
          <textarea ref={promptRef} value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder={selectedConversation?.scope === 'idea' ? '写下你的想法，Codex 会结合当前空间资料并按需检索最新工作...' : selectedConversationId ? '询问论文、检索研究、整理 Idea 或沉淀 Wiki...' : '先创建一个研究对话'} disabled={!selectedConversationId || running} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }} />
          <div className="composer-footer">
            <div><button type="button" className="composer-tool" onClick={() => fileRef.current?.click()} disabled={!selectedSpaceId || uploadingPaper} title="上传论文">{uploadingPaper ? <Loader2 className="spin" size={16} /> : <Paperclip size={17} />}</button><button type="button" className="composer-model"><Bot size={15} />本机默认模型<ChevronDown size={13} /></button></div>
            {running ? <button type="button" className="stop-button" onClick={() => void stopTurn()} title="停止"><Square size={16} /></button> : <button type="submit" className="send-button" disabled={!prompt.trim() || !selectedConversationId} title="发送"><Send size={18} /></button>}
          </div>
          <input ref={fileRef} type="file" accept="application/pdf" hidden onChange={(event) => void uploadPaper(event.target.files?.[0])} />
        </form>
      </section>

      <aside className={`resource-panel ${mobilePanel === 'resources' ? 'mobile-open' : ''} ${readingPaper ? 'reader-resource-panel' : ''}`}>
        <header className="resource-header"><div><strong>研究资源</strong><span>{papers.length + wiki.length + ideas.length} 项</span></div><button className="icon-button" title="更多"><MoreHorizontal size={18} /></button></header>
        <nav className="resource-tabs">
          {([
            ['papers', BookOpen, '论文'], ['wiki', FileText, 'Wiki'], ['ideas', Lightbulb, 'Idea'], ['jobs', CalendarDays, '任务'], ['skills', Wrench, 'Skills'],
          ] as const).map(([id, Icon, label]) => <button key={id} className={resourceTab === id ? 'active' : ''} onClick={() => setResourceTab(id)}><Icon size={15} /><span>{label}</span></button>)}
        </nav>
        <div className="resource-search"><Search size={15} /><input value={resourceSearch} onChange={(event) => setResourceSearch(event.target.value)} placeholder="搜索当前资源" /></div>
        <div className="resource-actions">
          {resourceTab === 'papers' && <><button className="secondary-button" onClick={() => fileRef.current?.click()} disabled={uploadingPaper}>{uploadingPaper ? <Loader2 className="spin" size={15} /> : <Upload size={15} />}{uploadingPaper ? '正在解析 PDF' : '上传 PDF'}</button><button className="secondary-button" onClick={() => { setPaperImportResult(null); setModal('paper-import'); }} disabled={!selectedSpaceId || importingPaper}><Link2 size={15} />导入论文</button><button className="secondary-button" onClick={() => setModal('blog')} disabled={!selectedSpaceId}><Link2 size={15} />添加 Blog</button></>}
          {resourceTab === 'wiki' && <button className="secondary-button" onClick={() => setModal('wiki')}><Plus size={15} />新建 Wiki</button>}
          {resourceTab === 'ideas' && <button className="secondary-button" onClick={() => void createIdeaConversation()} disabled={!selectedSpaceId || creatingConversation}><Plus size={15} />新建 Idea 对话</button>}
        </div>
        <div className="resource-list scrollbar-thin">
          {resourceTab === 'papers' && (filteredResources.papers.length ? filteredResources.papers.map((paper) => {
            const isBlog = paper.resource_type === 'blog';
            const extractionFailed = !isBlog && (paper.status === 'extract_error' || paper.metadata?.extraction_status === 'error');
            const metadataOnly = !isBlog && (!paper.stored_path || paper.metadata?.extraction_status !== 'ready');
            const linkedChats = conversations.filter((item) => item.paper_ids?.includes(paper.id) || item.active_paper_id === paper.id).length;
            const attached = activePaperIds.includes(paper.id);
            return <article className={`resource-item paper-item ${attached ? 'active' : ''} ${extractionFailed || metadataOnly ? 'paper-unavailable' : ''}`} key={paper.id} onClick={() => void selectPaper(paper)}>
              <div className={`resource-icon ${isBlog ? 'blog' : 'pdf'}`}>{isBlog ? 'WEB' : 'PDF'}</div>
              <div className="resource-copy"><strong>{paper.title}</strong><small>{isBlog ? (paper.metadata?.content_status === 'ready' ? 'Blog 内容已抓取' : 'Blog 链接 · Codex 可按需检索') : extractionFailed ? '解析失败 · 暂不可对话' : paper.metadata?.extraction_status === 'ready' ? `${paper.metadata.page_count || 0} 页 · 已可对话` : '仅元数据'}{!isBlog && paper.metadata?.visual_ingestion_status === 'ready' ? ` · ${paper.metadata.visual_asset_count || 0} 个视觉页` : ''} · {linkedChats} 个对话{!isBlog && ` · ${publicationLabel(paper)}`}{paper.metadata?.venue ? ` · ${paper.metadata.venue}` : ''}</small>
                <div className="paper-identifiers">{paper.metadata?.arxiv_id && <span>arXiv:{paper.metadata.arxiv_id}</span>}{paper.metadata?.doi && <span>DOI:{paper.metadata.doi}</span>}{isBlog && paper.source_url && <span>{paper.source_url}</span>}</div>
                <div className="inline-actions">{paper.metadata?.outputs_url && <a href={paper.metadata.outputs_url} target="_blank" rel="noreferrer" onClick={(event) => event.stopPropagation()}>打开</a>}{!paper.metadata?.outputs_url && paper.source_url && <a href={paper.source_url} target="_blank" rel="noreferrer" onClick={(event) => event.stopPropagation()}>来源</a>}{!extractionFailed && !metadataOnly && <button onClick={(event) => { event.stopPropagation(); void openPaperConversation(paper, true, true); }}>新对话</button>}{!extractionFailed && !metadataOnly && selectedConversationId && !attached && <button onClick={(event) => { event.stopPropagation(); void openPaperConversation(paper); }}>加入当前对话</button>}{!isBlog && <button onClick={(event) => { event.stopPropagation(); void openPaperNote(paper); }}>记忆卡</button>}{!isBlog && <button onClick={(event) => { event.stopPropagation(); void queueTranslation(paper.id); }}>翻译</button>}</div>
              </div>{attached && <Check className="paper-selected" size={15} />}</article>;
          }) : <EmptyState icon={<BookOpen size={22} />} title="导入论文或添加 Blog 后开始研究" action={<div className="empty-actions"><button className="secondary-button" onClick={() => fileRef.current?.click()}><Upload size={15} />上传 PDF</button><button className="secondary-button" onClick={() => setModal('paper-import')}><Link2 size={15} />导入论文</button><button className="secondary-button" onClick={() => setModal('blog')}><Link2 size={15} />添加 Blog</button></div>} />)}
          {resourceTab === 'wiki' && (filteredResources.wiki.length ? filteredResources.wiki.map((page) => <article className="resource-item" key={page.id}><div className="resource-icon wiki"><FileText size={16} /></div><div className="resource-copy"><strong>{page.title}</strong><small>v{page.revision} · {page.tags.join(' · ') || '无标签'}</small><p>{page.content.slice(0, 100)}</p></div></article>) : <EmptyState icon={<FileText size={22} />} title="尚无 Wiki 页面" />)}
          {resourceTab === 'ideas' && (filteredResources.ideas.length ? filteredResources.ideas.map((idea) => <article className="resource-item" key={idea.id}><div className="resource-icon idea"><Lightbulb size={16} /></div><div className="resource-copy"><strong>{idea.title}</strong><small>{idea.status} · {idea.tags.join(' · ') || '无标签'}</small><p>{idea.problem || idea.hypothesis || '等待补充研究问题'}</p></div></article>) : <EmptyState icon={<Lightbulb size={22} />} title="尚无 Research Idea" />)}
          {resourceTab === 'jobs' && (jobs.length ? jobs.map((job) => <article className="resource-item" key={job.id}><div className="resource-icon job"><CalendarDays size={16} /></div><div className="resource-copy"><strong>{job.kind === 'paper_translation' ? '论文翻译' : job.kind}</strong><small>{job.status === 'waiting_provider' ? '等待翻译 Provider' : job.status} · {job.provider}</small><div className="job-track"><span style={{ width: `${job.progress * 100}%` }} /></div></div></article>) : <EmptyState icon={<CalendarDays size={22} />} title="尚无后台任务" />)}
          {resourceTab === 'skills' && (filteredResources.skills.length ? filteredResources.skills.map((skill) => <article className="resource-item" key={skill.path}><div className="resource-icon skill"><Wrench size={16} /></div><div className="resource-copy"><strong>{skill.name}</strong><small>{skill.source === 'codex-runtime' ? `Codex 运行时已发现 · ${skill.enabled === false ? '已禁用' : '已启用'}` : '本地 Skill 文件'}</small><p>{skill.description || '本机已发现 Skill'}</p></div></article>) : <EmptyState icon={<Wrench size={22} />} title="未发现 Skills" />)}
        </div>
      </aside>

      {modal === 'paper-import' && <Modal title="导入论文" onClose={() => { if (!importingPaper) setModal(null); }}><form className="modal-form" onSubmit={importPaperFromQuery}><label>arXiv ID、DOI、论文标题或链接<input autoFocus value={paperImportQuery} onChange={(event) => setPaperImportQuery(event.target.value)} placeholder="例如 2401.12345、10.1145/... 或论文标题" disabled={importingPaper} /></label><label className="check-row"><input type="checkbox" checked={paperImportDownload} onChange={(event) => setPaperImportDownload(event.target.checked)} disabled={importingPaper} />自动下载 PDF；arXiv 同时解析 LaTeX 源码</label>{importingPaper && <div className="import-progress"><Loader2 className="spin" size={16} /><span>正在查询元数据、作者机构和发表状态…</span></div>}{paperImportResult && <section className="import-result"><div className="import-result-title"><strong>{paperImportResult.paper.title}</strong><span>{publicationLabel(paperImportResult.paper)}</span></div><p>{(paperImportResult.paper.metadata?.authors || []).slice(0, 8).map((author) => author.name).join('、') || '作者信息未返回'}</p>{paperImportResult.paper.metadata?.institutions?.length ? <p>{paperImportResult.paper.metadata.institutions.slice(0, 4).join(' · ')}</p> : null}<p>{paperImportResult.paper.metadata?.venue || '未识别 venue'}{paperImportResult.paper.metadata?.published_at ? ` · ${paperImportResult.paper.metadata.published_at.slice(0, 10)}` : ''}</p>{paperImportResult.paper.metadata?.abstract && <p className="import-abstract">{paperImportResult.paper.metadata.abstract.slice(0, 420)}</p>}<div className="paper-identifiers">{paperImportResult.paper.metadata?.arxiv_id && <span>arXiv:{paperImportResult.paper.metadata.arxiv_id}</span>}{paperImportResult.paper.metadata?.doi && <span>DOI:{paperImportResult.paper.metadata.doi}</span>}{paperImportResult.paper.metadata?.source_ingestion_status === 'ready' && <span>LaTeX 源码已解析</span>}</div>{paperImportResult.warnings.map((warning) => <p className="import-warning" key={warning}>{warning}</p>)}<div className="modal-actions"><button type="button" onClick={() => setModal(null)}>关闭</button>{paperImportResult.paper.metadata?.extraction_status === 'ready' && <button type="button" className="primary-button" onClick={() => { void openPaperConversation(paperImportResult.paper, true); setModal(null); }}>开始阅读</button>}</div></section>}<div className="modal-actions"><button type="button" onClick={() => setModal(null)} disabled={importingPaper}>取消</button><button className="primary-button" type="submit" disabled={!paperImportQuery.trim() || importingPaper}>{importingPaper ? <><Loader2 className="spin" size={15} />正在导入</> : '查找并导入'}</button></div></form></Modal>}
      {modal === 'blog' && <Modal title="添加 Blog 资源" onClose={() => setModal(null)}><form className="modal-form" onSubmit={addBlog}><label>Blog 标题（可选）<input autoFocus value={blogDraft.title} onChange={(event) => setBlogDraft({ ...blogDraft, title: event.target.value })} placeholder="留空则使用网页标题" /></label><label>网页链接<input type="url" value={blogDraft.url} onChange={(event) => setBlogDraft({ ...blogDraft, url: event.target.value })} placeholder="https://..." /></label><p className="modal-hint">会尝试抓取正文，抓取失败时仍保留链接，Codex 可在对话中按需检索。</p><div className="modal-actions"><button type="button" onClick={() => setModal(null)}>取消</button><button className="primary-button" type="submit" disabled={!blogDraft.url.trim()}><Link2 size={15} />添加 Blog</button></div></form></Modal>}
      {modal === 'paper-note' && paperNoteTarget && <Modal title="Paper 记忆卡" onClose={() => { if (!refreshingPaperNote && !savingPaperNote) setModal(null); }}><section className="paper-note-modal">
        <header><div><strong>{paperNoteTarget.title}</strong><small>{paperNote ? `v${paperNote.revision} · ${new Date(paperNote.generated_at).toLocaleString('zh-CN')}` : '尚未生成'}</small></div><button className="secondary-button" type="button" onClick={() => void refreshPaperNote()} disabled={refreshingPaperNote || loadingPaperNote}>{refreshingPaperNote ? <Loader2 className="spin" size={14} /> : <RefreshCw size={14} />}{paperNote ? '根据最新 QA 刷新' : '生成记忆卡'}</button></header>
        {loadingPaperNote ? <div className="paper-note-loading"><Loader2 className="spin" size={17} />正在读取记忆卡</div> : paperNote ? <div className="paper-note-content">
          <section><h4>简短摘要</h4><MarkdownPreview>{paperNote.short_summary || '暂无'}</MarkdownPreview></section>
          <section><h4>QA 摘要</h4><MarkdownPreview>{paperNote.qa_summary || '暂无相关对话'}</MarkdownPreview></section>
          <section><h4>未决问题</h4><MarkdownPreview>{paperNote.open_questions || '暂无'}</MarkdownPreview></section>
          <section><h4>关键结论</h4><MarkdownPreview>{paperNote.key_takeaways || '暂无'}</MarkdownPreview></section>
          <label>个人记录与研究启发<textarea rows={5} value={paperNote.personal_notes || ''} onChange={(event) => setPaperNote({ ...paperNote, personal_notes: event.target.value })} placeholder="Codex 会基于 QA 生成，也可以在这里补充自己的记录。" /></label>
          <footer><span>依据 {paperNote.source_message_ids.length} 条相关消息</span><button className="primary-button" type="button" onClick={() => void saveCurrentPaperNote()} disabled={savingPaperNote}>{savingPaperNote ? <Loader2 className="spin" size={14} /> : <Check size={14} />}{savingPaperNote ? '保存中' : '保存记录'}</button></footer>
        </div> : <div className="paper-note-empty"><FileText size={22} /><p>生成后会把论文短摘要、你问过的问题、已确认结论和仍未解决的疑问保存在这里。</p></div>}
      </section></Modal>}
      {modal === 'wiki' && <Modal title="新建 Wiki 页面" onClose={() => setModal(null)}><form className="modal-form" onSubmit={saveWiki}><label>标题<input autoFocus value={wikiDraft.title} onChange={(event) => setWikiDraft({ ...wikiDraft, title: event.target.value })} /></label><label>正文<textarea rows={9} value={wikiDraft.content} onChange={(event) => setWikiDraft({ ...wikiDraft, content: event.target.value })} placeholder="支持 Markdown" /></label><label>标签<input value={wikiDraft.tags} onChange={(event) => setWikiDraft({ ...wikiDraft, tags: event.target.value })} placeholder="逗号分隔" /></label><div className="modal-actions"><button type="button" onClick={() => setModal(null)}>取消</button><button className="primary-button" type="submit">保存页面</button></div></form></Modal>}
    </main>
  );
}
