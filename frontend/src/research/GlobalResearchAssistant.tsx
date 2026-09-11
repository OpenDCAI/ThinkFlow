import { type FormEvent, useEffect, useRef, useState } from 'react';
import {
  ArrowLeft,
  Bot,
  Check,
  AlertCircle,
  Clock3,
  Database,
  Loader2,
  MessageSquare,
  Plus,
  Send,
  Square,
  Trash2,
  Wrench,
  X,
} from 'lucide-react';
import { researchApi, streamTurn } from './api';
import MarkdownPreview from './MarkdownPreview';
import type { ResearchAction, ResearchConversation, ResearchMessage, ResearchSpace } from './types';
import './global-research-assistant.css';

type Props = {
  codexAvailable: boolean;
  onBack: () => void;
  onSpacesChanged: (spaces: ResearchSpace[]) => void;
};

function shortTime(value?: string) {
  if (!value) return '';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

const TOOL_LABELS: Record<string, string> = {
  list_research_spaces: '获取研究空间',
  search_research_spaces: '搜索研究空间',
  create_research_space: '新建研究空间',
  list_space_resources: '获取空间资料',
  resolve_research_resources: '查找论文',
  import_research_resources: '批量导入论文',
  list_research_conversations: '获取研究对话',
  create_research_conversation: '新建研究对话',
  get_conversation_resources: '获取对话资料',
  set_conversation_resources: '更新资料绑定',
};

function actionState(action: ResearchAction) {
  if (action.status === 'pending') return { label: '等待确认', icon: Clock3 };
  if (action.status === 'executing') return { label: '正在执行', icon: Loader2 };
  if (action.status === 'completed') return { label: '执行完成', icon: Check };
  if (action.status === 'cancelled') return { label: '已取消', icon: X };
  return { label: '执行失败', icon: AlertCircle };
}

export default function GlobalResearchAssistant({ codexAvailable, onBack, onSpacesChanged }: Props) {
  const [conversations, setConversations] = useState<ResearchConversation[]>([]);
  const [selectedId, setSelectedId] = useState('');
  const [messages, setMessages] = useState<ResearchMessage[]>([]);
  const [actions, setActions] = useState<ResearchAction[]>([]);
  const [prompt, setPrompt] = useState('');
  const [draft, setDraft] = useState('');
  const [running, setRunning] = useState(false);
  const [creating, setCreating] = useState(false);
  const [status, setStatus] = useState('');
  const [error, setError] = useState('');
  const [actionBusyId, setActionBusyId] = useState('');
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => { void loadConversations(); }, []);
  useEffect(() => {
    if (!selectedId) { setMessages([]); setActions([]); return; }
    void Promise.all([researchApi.messages(selectedId), researchApi.actions(selectedId)])
      .then(([nextMessages, nextActions]) => { setMessages(nextMessages); setActions(nextActions); })
      .catch((reason) => setError(reason.message));
  }, [selectedId]);
  useEffect(() => {
    const node = scrollRef.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [messages, draft, status]);

  async function loadConversations() {
    try {
      const rows = await researchApi.globalConversations();
      setConversations(rows);
      setSelectedId((current) => rows.some((row) => row.id === current) ? current : rows[0]?.id || '');
    } catch (reason: any) {
      setError(reason.message || '全局对话加载失败');
    }
  }

  async function createConversation(): Promise<ResearchConversation | null> {
    if (creating) return null;
    setCreating(true);
    setError('');
    try {
      const conversation = await researchApi.createGlobalConversation();
      setConversations((current) => [conversation, ...current]);
      setSelectedId(conversation.id);
      setMessages([]);
      setActions([]);
      setDraft('');
      setStatus('');
      return conversation;
    } catch (reason: any) {
      setError(reason.message || '创建全局对话失败');
      return null;
    } finally {
      setCreating(false);
    }
  }

  async function deleteConversation(conversation: ResearchConversation) {
    if (running || !window.confirm(`删除“${conversation.title}”及其全部记录？`)) return;
    await researchApi.deleteConversation(conversation.id);
    const remaining = conversations.filter((row) => row.id !== conversation.id);
    setConversations(remaining);
    if (selectedId === conversation.id) setSelectedId(remaining[0]?.id || '');
  }

  function handleStreamEvent(type: string, data: Record<string, any>) {
    if (type === 'item/agentMessage/delta') {
      setDraft((current) => current + String(data.delta || ''));
    } else if (type === 'turn.harness') {
      setStatus([data.title, data.detail].filter(Boolean).join(' · '));
    } else if (type === 'turn.skill') {
      setStatus(`${data.status === 'loaded' ? '已载入' : '已提供'} ${data.name} Skill`);
    } else if (type === 'turn.tool' && data.server === 'thinkflow_research') {
      const label = TOOL_LABELS[String(data.name)] || String(data.name || 'Research Function');
      setStatus(`${label} · ${data.status === 'completed' ? '已完成' : data.status === 'failed' ? '失败' : '执行中'}`);
      if (data.status === 'completed' || data.status === 'failed') void loadActions();
    } else if (type === 'error') {
      setError(String(data.message || 'Codex 执行失败'));
    }
  }

  async function loadActions() {
    if (!selectedId) return;
    setActions(await researchApi.actions(selectedId));
  }

  async function runChat(value: string, conversationId = selectedId) {
    if (!conversationId) return;
    const controller = new AbortController();
    abortRef.current = controller;
    setMessages((current) => [...current, {
      id: `local-${Date.now()}`,
      conversation_id: conversationId,
      role: 'user',
      content: value,
      event_type: 'message',
      created_at: new Date().toISOString(),
    }]);
    setDraft('');
    setStatus('正在提交给 Codex');
    await streamTurn(conversationId, value, undefined, controller.signal, handleStreamEvent);
    const [nextMessages, nextConversations, nextActions, nextSpaces] = await Promise.all([
      researchApi.messages(conversationId),
      researchApi.globalConversations(),
      researchApi.actions(conversationId),
      researchApi.spaces(),
    ]);
    setMessages(nextMessages);
    setConversations(nextConversations);
    setActions(nextActions);
    onSpacesChanged(nextSpaces);
    setDraft('');
    setStatus('');
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    const value = prompt.trim();
    if (!value || running) return;
    setRunning(true);
    setError('');
    setPrompt('');
    try {
      const conversation = selectedId ? null : await createConversation();
      const conversationId = selectedId || conversation?.id;
      if (!conversationId) return;
      await runChat(value, conversationId);
    } catch (reason: any) {
      if (reason.name !== 'AbortError') setError(reason.message || '请求执行失败');
      setPrompt(value);
    } finally {
      abortRef.current = null;
      setRunning(false);
    }
  }

  function stop() {
    abortRef.current?.abort();
    if (selectedId) void researchApi.cancel(selectedId).catch(() => undefined);
    setRunning(false);
    setStatus('本次执行已停止');
  }

  async function confirmAction(action: ResearchAction) {
    if (actionBusyId || action.status !== 'pending') return;
    setActionBusyId(action.id);
    setError('');
    setActions((current) => current.map((item) => item.id === action.id ? { ...item, status: 'executing' } : item));
    try {
      await researchApi.confirmAction(action.id);
      const [nextActions, nextMessages, nextSpaces] = await Promise.all([
        researchApi.actions(action.conversation_id),
        researchApi.messages(action.conversation_id),
        researchApi.spaces(),
      ]);
      setActions(nextActions);
      setMessages(nextMessages);
      onSpacesChanged(nextSpaces);
    } catch (reason: any) {
      setError(reason.message || '操作执行失败');
      await loadActions().catch(() => undefined);
    } finally {
      setActionBusyId('');
    }
  }

  async function cancelAction(action: ResearchAction) {
    if (actionBusyId || action.status !== 'pending') return;
    setActionBusyId(action.id);
    setError('');
    try {
      await researchApi.cancelAction(action.id);
      await loadActions();
    } catch (reason: any) {
      setError(reason.message || '取消操作失败');
    } finally {
      setActionBusyId('');
    }
  }

  return (
    <main className="global-assistant">
      <aside className="global-nav">
        <header><button className="icon-button" onClick={onBack} title="返回首页"><ArrowLeft size={18} /></button><span><strong>全局研究助理</strong><small>跨空间研究与资料编排</small></span></header>
        <button className="global-new-chat" onClick={() => void createConversation()} disabled={creating}>{creating ? <Loader2 className="spin" size={15} /> : <Plus size={15} />}新建全局对话</button>
        <div className="global-conversation-list scrollbar-thin">
          {conversations.map((conversation) => <div className={conversation.id === selectedId ? 'active' : ''} key={conversation.id}>
            <button onClick={() => setSelectedId(conversation.id)}><MessageSquare size={14} /><span><strong>{conversation.title}</strong><small>{shortTime(conversation.updated_at)}</small></span></button>
            <button className="global-delete" onClick={() => void deleteConversation(conversation)} title="删除对话"><Trash2 size={13} /></button>
          </div>)}
          {!conversations.length && <p>新建对话后，可以跨空间讨论研究方向或批量导入论文。</p>}
        </div>
        <footer><span className={codexAvailable ? 'online' : ''} /><div><strong>Codex SDK</strong><small>{codexAvailable ? '运行环境已连接' : '连接不可用'}</small></div></footer>
      </aside>

      <section className="global-chat">
        <header className="global-chat-header"><button className="icon-button global-mobile-back" onClick={onBack} title="返回首页"><ArrowLeft size={18} /></button><div><h1>研究与规划</h1><p>由 Codex 自主检索、规划并操作研究空间与资料</p></div><span>{running ? <><Loader2 className="spin" size={14} />执行中</> : status || '就绪'}</span></header>
        {error && <div className="global-error"><span>{error}</span><button onClick={() => setError('')}><X size={14} /></button></div>}
        <div ref={scrollRef} className="global-message-scroll scrollbar-thin">
          {!selectedId ? <div className="global-empty"><Bot size={28} /><h2>直接描述你的研究目标</h2><p>Codex 会自动建立全局对话，并按需检索、规划或调用 Research Functions。</p></div> : messages.length === 0 && !draft ? <div className="global-empty"><Database size={28} /><h2>从跨空间问题开始</h2><p>直接说明要研究、查找或整理什么，Codex 会自主选择工具并执行。</p></div> : <div className="global-message-column">
            {messages.map((message) => <article className={`global-message ${message.role}`} key={message.id}><span>{message.role === 'user' ? '你' : <Bot size={15} />}</span><div><header>{message.role === 'user' ? '你' : 'Codex'}<small>{shortTime(message.created_at)}</small></header>{message.role === 'assistant' ? <MarkdownPreview>{message.content}</MarkdownPreview> : <p>{message.content}</p>}</div></article>)}
            {actions.length > 0 && <section className="research-action-list" aria-label="Research Functions 操作">
              {actions.slice(0, 12).map((action) => {
                const state = actionState(action);
                const StateIcon = state.icon;
                const resultSpace = action.result?.space;
                return <article className={`research-action ${action.status}`} key={action.id}>
                  <header><span><Wrench size={14} /><strong>{TOOL_LABELS[action.tool_name] || action.tool_name}</strong></span><small><StateIcon className={action.status === 'executing' ? 'spin' : ''} size={13} />{state.label}</small></header>
                  <p>{action.summary}</p>
                  {action.status === 'completed' && <div className="action-result">
                    {resultSpace && <span>研究空间：{resultSpace.title}</span>}
                    {typeof action.result?.imported_count === 'number' && <span>成功 {action.result.imported_count} 项 · 失败 {action.result.failed_count || 0} 项</span>}
                  </div>}
                  {action.error && <div className="action-error">{action.error}</div>}
                  {action.status === 'pending' && <footer><button type="button" className="action-cancel" onClick={() => void cancelAction(action)} disabled={Boolean(actionBusyId)}><X size={14} />取消</button><button type="button" className="action-confirm" onClick={() => void confirmAction(action)} disabled={Boolean(actionBusyId)}>{actionBusyId === action.id ? <Loader2 className="spin" size={14} /> : <Check size={14} />}确认执行</button></footer>}
                </article>;
              })}
            </section>}
            {(running || draft) && <article className="global-message assistant"><span><Bot size={15} /></span><div><header>Codex<small>{status || '执行中'}</small></header>{draft ? <MarkdownPreview>{draft}</MarkdownPreview> : <div className="global-running"><Loader2 className="spin" size={15} />{status || '正在执行'}</div>}</div></article>}
          </div>}
        </div>
        <form className="global-composer" onSubmit={submit}>
          <textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} disabled={running} placeholder="直接告诉 Codex 你要研究什么，或让它查找论文、创建空间、导入资料、整理对话…" onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }} />
          <footer><small>Codex sandbox · 10 个 Research Functions · 自动规划</small>{running ? <button type="button" className="global-send stop" onClick={stop} title="停止"><Square size={15} /></button> : <button className="global-send" type="submit" disabled={!prompt.trim()} title="发送"><Send size={17} /></button>}</footer>
        </form>
      </section>
    </main>
  );
}
