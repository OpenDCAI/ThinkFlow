import React from 'react';
import '@testing-library/jest-dom/vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import ResearchWorkspace from '../ResearchWorkspace';
import { researchApi, streamRegeneratedTurn } from '../api';


vi.mock('../api', () => ({
  researchApi: {
    spaces: vi.fn(),
    status: vi.fn(),
    skills: vi.fn(),
    conversations: vi.fn(),
    papers: vi.fn(),
    wiki: vi.fn(),
    ideas: vi.fn(),
    jobs: vi.fn(),
    messages: vi.fn(),
    rollbackMessage: vi.fn(),
    createConversation: vi.fn(),
    deleteSpace: vi.fn(),
    uploadPaper: vi.fn(),
    importPaper: vi.fn(),
    bindPaper: vi.fn(),
  },
  streamTurn: vi.fn(),
  streamRegeneratedTurn: vi.fn(),
}));

vi.mock('react-pdf', () => ({
  Document: ({ children }: { children?: unknown }) => children,
  Page: () => null,
  pdfjs: { GlobalWorkerOptions: {} },
}));


const space = {
  id: 'space-1',
  title: 'Paper Lab',
  description: '',
  created_at: '2026-08-12T00:00:00Z',
  updated_at: '2026-08-12T00:00:00Z',
};

const conversation = {
  id: 'chat-1',
  space_id: space.id,
  title: '新对话',
  status: 'idle' as const,
  created_at: '2026-08-12T00:00:00Z',
  updated_at: '2026-08-12T00:00:00Z',
};

const paper = {
  id: 'paper-1',
  title: 'Reliable Paper Chat',
  availability: 'local_pdf',
  status: 'ready',
  metadata: {
    outputs_url: '/outputs/paper.pdf',
    extraction_status: 'ready' as const,
    page_count: 12,
    authors: [
      { name: 'Ada Lovelace', affiliations: ['Analytical Engine Lab'] },
      { name: 'Grace Hopper', affiliations: ['Research Navy'] },
    ],
    institutions: ['Analytical Engine Lab', 'Research Navy'],
    arxiv_id: '2501.00001',
    venue: 'International Conference on Learning Representations',
    venue_short_name: 'ICLR',
    publication_status: 'published',
    published_at: '2026-05-14T06:04:40Z',
  },
  created_at: '2026-08-12T00:00:00Z',
};

function deferred<T>() {
  let resolve!: (value: T | PromiseLike<T>) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}


describe('ResearchWorkspace paper chat workflow', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(researchApi.spaces).mockResolvedValue([space]);
    vi.mocked(researchApi.status).mockResolvedValue({
      codex: { available: true },
      translation_providers: [],
      external_tools: [],
    });
    vi.mocked(researchApi.skills).mockResolvedValue([]);
    vi.mocked(researchApi.conversations).mockResolvedValue([]);
    vi.mocked(researchApi.papers).mockResolvedValue([]);
    vi.mocked(researchApi.wiki).mockResolvedValue([]);
    vi.mocked(researchApi.ideas).mockResolvedValue([]);
    vi.mocked(researchApi.jobs).mockResolvedValue([]);
    vi.mocked(researchApi.messages).mockResolvedValue([]);
  });

  it('deletes a research space from the homepage after destructive confirmation', async () => {
    const anotherSpace = { ...space, id: 'space-2', title: 'SWE Evolution' };
    vi.mocked(researchApi.spaces).mockResolvedValue([space, anotherSpace]);
    vi.mocked(researchApi.deleteSpace).mockResolvedValue({ success: true });
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
    render(<ResearchWorkspace />);

    fireEvent.click(await screen.findByRole('button', { name: `删除研究空间 ${space.title}` }));

    expect(confirm).toHaveBeenCalledWith(expect.stringContaining(space.title));
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('论文、Blog、对话、Wiki、Idea、笔记和本地产物'));
    await waitFor(() => expect(researchApi.deleteSpace).toHaveBeenCalledWith(space.id));
    await waitFor(() => expect(screen.queryByText(space.title)).not.toBeInTheDocument());
    expect(screen.getByText(anotherSpace.title)).toBeInTheDocument();
    confirm.mockRestore();
  });

  it('keeps a research space when deletion confirmation is cancelled', async () => {
    const anotherSpace = { ...space, id: 'space-2', title: 'SWE Evolution' };
    vi.mocked(researchApi.spaces).mockResolvedValue([space, anotherSpace]);
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    render(<ResearchWorkspace />);

    fireEvent.click(await screen.findByRole('button', { name: `删除研究空间 ${space.title}` }));

    expect(researchApi.deleteSpace).not.toHaveBeenCalled();
    expect(screen.getByText(space.title)).toBeInTheDocument();
    confirm.mockRestore();
  });

  it('creates and selects a new conversation from the visible command', async () => {
    vi.mocked(researchApi.createConversation).mockResolvedValue(conversation);
    render(<ResearchWorkspace />);

    const create = (await screen.findAllByRole('button', { name: '新建对话' }))[0];
    fireEvent.click(create);

    await waitFor(() => expect(researchApi.createConversation).toHaveBeenCalledWith(space.id));
    expect((await screen.findAllByText('新对话')).length).toBeGreaterThan(0);
    expect(screen.getByPlaceholderText('询问论文、检索研究、整理 Idea 或沉淀 Wiki...')).toBeEnabled();
  });

  it('creates an Idea conversation without opening a structured form', async () => {
    const ideaConversation = { ...conversation, id: 'chat-idea', title: 'Idea 讨论', scope: 'idea' as const };
    vi.mocked(researchApi.createConversation).mockResolvedValue(ideaConversation);
    render(<ResearchWorkspace />);

    fireEvent.click(await screen.findByRole('button', { name: 'Idea' }));
    fireEvent.click(await screen.findByRole('button', { name: '新建 Idea 对话' }));

    await waitFor(() => expect(researchApi.createConversation).toHaveBeenCalledWith(space.id, 'Idea 讨论', { scope: 'idea', paper_ids: [] }));
    expect(screen.queryByText('研究问题')).not.toBeInTheDocument();
    expect(screen.getByPlaceholderText('写下你的想法，Codex 会结合当前空间资料并按需检索最新工作...')).toBeEnabled();
  });

  it('collapses and expands the research navigation rail', async () => {
    render(<ResearchWorkspace />);
    const main = (await screen.findByRole('button', { name: '收起侧栏' })).closest('main');
    expect(main).toHaveClass('research-shell');
    fireEvent.click(screen.getByRole('button', { name: '收起侧栏' }));
    expect(main).toHaveClass('nav-collapsed');
    fireEvent.click(screen.getByRole('button', { name: '展开侧栏' }));
    expect(main).not.toHaveClass('nav-collapsed');
  });

  it('opens an active PDF in the immersive reader beside the Codex conversation', async () => {
    const paperConversation = { ...conversation, active_paper_id: paper.id };
    vi.mocked(researchApi.conversations).mockResolvedValue([paperConversation]);
    vi.mocked(researchApi.papers).mockResolvedValue([paper]);
    render(<ResearchWorkspace />);

    const reader = await screen.findByLabelText('论文阅读器');
    expect(reader).toBeInTheDocument();
    expect(screen.getByRole('separator', { name: '调整 PDF 和对话窗口宽度' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '与 Codex 对话' })).toBeInTheDocument();
    expect(screen.getByLabelText('当前页码')).toHaveValue('1');
    expect(screen.getByLabelText('论文元数据')).toHaveTextContent('Ada Lovelace');
    expect(screen.getByLabelText('论文元数据')).toHaveTextContent('Analytical Engine Lab');
    expect(screen.getByLabelText('论文元数据')).toHaveTextContent('第一单位 Analytical Engine Lab');
    expect(screen.getByLabelText('论文元数据')).toHaveTextContent('第二单位 Research Navy');
    expect(screen.getByLabelText('论文元数据')).toHaveTextContent('ICLR · 已发表');
    expect(screen.getByLabelText('论文元数据')).toHaveTextContent('发表 2026-05-14');
    expect(screen.getByLabelText('论文元数据')).toHaveTextContent('arXiv 2501.00001');

    fireEvent.click(screen.getByTitle('专注阅读'));
    expect(reader.closest('main')).toHaveClass('reader-focus');
    fireEvent.click(screen.getByTitle('退出专注模式'));
    expect(reader.closest('main')).not.toHaveClass('reader-focus');

    fireEvent.click(screen.getByTitle('打开 AI 对话'));
    expect(reader.closest('main')).toHaveClass('reader-pane-chat');

    fireEvent.click(screen.getByTitle('退出论文阅读'));
    await waitFor(() => expect(screen.queryByLabelText('论文阅读器')).not.toBeInTheDocument());
    expect(screen.getByText('当前论文')).toBeInTheDocument();
    expect(researchApi.bindPaper).not.toHaveBeenCalled();
  });

  it('extracts and binds an uploaded PDF as the active conversation paper', async () => {
    vi.mocked(researchApi.conversations).mockResolvedValue([conversation]);
    vi.mocked(researchApi.uploadPaper).mockResolvedValue(paper);
    vi.mocked(researchApi.bindPaper).mockResolvedValue({
      ...conversation,
      active_paper_id: paper.id,
    });
    render(<ResearchWorkspace />);

    expect((await screen.findAllByText('新对话')).length).toBeGreaterThan(0);
    const input = document.querySelector<HTMLInputElement>('input[type="file"]');
    expect(input).not.toBeNull();
    fireEvent.change(input!, {
      target: { files: [new File(['%PDF-1.4'], 'paper.pdf', { type: 'application/pdf' })] },
    });

    await waitFor(() => expect(researchApi.uploadPaper).toHaveBeenCalled());
    await waitFor(() => expect(researchApi.bindPaper).toHaveBeenCalledWith(conversation.id, paper.id));
    expect(await screen.findByText('当前论文')).toBeInTheDocument();
    expect(screen.getAllByText(paper.title).length).toBeGreaterThan(0);
    const defaultPrompt = screen.getByDisplayValue(/请先概括/) as HTMLTextAreaElement;
    expect(defaultPrompt).toBeInTheDocument();
    expect(defaultPrompt.value).not.toContain('引用页码');
  });

  it('labels an extraction failure and does not bind the broken PDF', async () => {
    vi.mocked(researchApi.conversations).mockResolvedValue([conversation]);
    vi.mocked(researchApi.papers).mockResolvedValue([{
      ...paper,
      status: 'extract_error',
      metadata: {
        ...paper.metadata,
        extraction_status: 'error',
        extraction_error: '/host/private/path/broken.pdf could not be opened',
      },
    }]);
    render(<ResearchWorkspace />);

    expect(await screen.findByText(/解析失败 · 暂不可对话/)).toBeInTheDocument();
    fireEvent.click(screen.getByText(paper.title));

    expect(await screen.findByText('这份 PDF 解析失败，暂时无法进行论文对话；请重新上传有效 PDF。')).toBeInTheDocument();
    expect(researchApi.bindPaper).not.toHaveBeenCalled();
    expect(screen.queryByText('/host/private/path/broken.pdf could not be opened')).not.toBeInTheDocument();
  });

  it('imports paper metadata from an identifier without pretending a missing PDF is readable', async () => {
    const metadataPaper = {
      ...paper,
      id: 'paper-metadata',
      title: 'Metadata Paper',
      availability: 'metadata_only',
      status: 'metadata_only',
      metadata: {
        source: 'arxiv',
        authors: [{ name: 'Ada Lovelace', affiliations: ['Research Lab'] }],
        institutions: ['Research Lab'],
        arxiv_id: '2501.00001',
        publication_status: 'preprint',
      },
    };
    vi.mocked(researchApi.importPaper).mockResolvedValue({
      success: true,
      paper: metadataPaper,
      metadata: metadataPaper.metadata,
      candidates: [metadataPaper.metadata],
      warnings: [],
    });
    render(<ResearchWorkspace />);

    fireEvent.click((await screen.findAllByRole('button', { name: '导入论文' }))[0]);
    fireEvent.change(screen.getByRole('textbox', { name: 'arXiv ID、DOI、论文标题或链接' }), { target: { value: '2501.00001' } });
    fireEvent.click(screen.getByRole('button', { name: '查找并导入' }));

    await waitFor(() => expect(researchApi.importPaper).toHaveBeenCalledWith(space.id, '2501.00001', true));
    expect((await screen.findAllByText('Metadata Paper')).length).toBeGreaterThan(0);
    expect(screen.getByText('Ada Lovelace')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '开始阅读' })).not.toBeInTheDocument();
    expect(researchApi.bindPaper).not.toHaveBeenCalled();
  });

  it('shows the Codex Harness immediately before the stream has produced output', async () => {
    vi.mocked(researchApi.conversations).mockResolvedValue([conversation]);
    const pending = deferred<void>();
    vi.mocked((await import('../api')).streamTurn).mockImplementation(() => pending.promise);
    render(<ResearchWorkspace />);

    const textarea = await screen.findByPlaceholderText('询问论文、检索研究、整理 Idea 或沉淀 Wiki...');
    fireEvent.change(textarea, { target: { value: '请概括研究工作台的核心能力' } });
    fireEvent.keyDown(textarea, { key: 'Enter' });

    expect(await screen.findByText('Codex Harness')).toBeInTheDocument();
    expect(screen.getAllByText('请求已提交').length).toBeGreaterThan(0);
    expect(screen.getAllByText('正在连接 Codex sandbox').length).toBeGreaterThan(0);
    expect(screen.getByTitle('停止')).toBeInTheDocument();

    pending.resolve();
  });

  it('keeps the execution timeline visible while Codex streams and marks completion', async () => {
    vi.mocked(researchApi.conversations).mockResolvedValue([conversation]);
    vi.mocked(researchApi.messages).mockResolvedValue([
      {
        id: 'message-1',
        conversation_id: conversation.id,
        role: 'assistant',
        content: '已完成回答',
        event_type: 'message',
        created_at: '2026-08-13T00:00:00Z',
      },
    ]);
    vi.mocked((await import('../api')).streamTurn).mockImplementation(async (_id, _prompt, _paperId, _signal, onEvent) => {
      onEvent('turn.harness', {
        phase: 'starting_thread',
        title: '正在建立 Codex sandbox',
        detail: '正在恢复独立研究线程',
        attempt: 1,
        maxAttempts: 3,
      });
      onEvent('item/agentMessage/delta', { delta: '正在流式输出' });
      onEvent('turn.harness', {
        phase: 'completed',
        title: '回复已完成',
        detail: '本次执行的对话内容已保存',
        attempt: 1,
        maxAttempts: 3,
        threadId: 'thread-test',
        turnId: 'turn-test',
      });
    });
    render(<ResearchWorkspace />);

    const textarea = await screen.findByPlaceholderText('询问论文、检索研究、整理 Idea 或沉淀 Wiki...');
    fireEvent.change(textarea, { target: { value: '回答一个问题' } });
    fireEvent.keyDown(textarea, { key: 'Enter' });

    expect((await screen.findAllByText('回复已完成')).length).toBeGreaterThan(0);
    expect(screen.getByText('已完成回答')).toBeInTheDocument();
    expect(screen.getByText('独立研究 sandbox')).toBeInTheDocument();
    expect(screen.getByText(/线程 thread-tes/)).toBeInTheDocument();
    expect(document.querySelectorAll('.event-row.running')).toHaveLength(0);
  });

  it('rolls a paper conversation back to before the selected Codex answer', async () => {
    const userMessage = {
      id: 'message-user', conversation_id: conversation.id, role: 'user' as const,
      content: 'Original question', event_type: 'message', created_at: '2026-08-13T00:00:00Z',
    };
    const answerMessage = {
      id: 'message-answer', conversation_id: conversation.id, role: 'assistant' as const,
      content: 'Broken answer', event_type: 'message', created_at: '2026-08-13T00:00:01Z',
    };
    vi.mocked(researchApi.conversations).mockResolvedValue([conversation]);
    vi.mocked(researchApi.messages).mockResolvedValue([userMessage, answerMessage]);
    vi.mocked(researchApi.rollbackMessage).mockResolvedValue({
      success: true, removed_count: 2, messages: [], conversation,
    });
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
    render(<ResearchWorkspace />);

    fireEvent.click(await screen.findByRole('button', { name: '回滚' }));

    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('删除对应提问和这条回答'));
    await waitFor(() => expect(researchApi.rollbackMessage).toHaveBeenCalledWith(conversation.id, answerMessage.id));
    await waitFor(() => expect(screen.queryByText('Broken answer')).not.toBeInTheDocument());
    confirm.mockRestore();
  });

  it('regenerates a Codex answer through the replay stream', async () => {
    const userMessage = {
      id: 'message-user', conversation_id: conversation.id, role: 'user' as const,
      content: 'Explain the method', event_type: 'message', created_at: '2026-08-13T00:00:00Z',
    };
    const answerMessage = {
      id: 'message-answer', conversation_id: conversation.id, role: 'assistant' as const,
      content: 'Broken answer', event_type: 'message', created_at: '2026-08-13T00:00:01Z',
    };
    const replacementMessage = {
      ...answerMessage, id: 'message-replacement', content: 'Regenerated answer',
    };
    vi.mocked(researchApi.conversations).mockResolvedValue([conversation]);
    vi.mocked(researchApi.messages)
      .mockResolvedValueOnce([userMessage, answerMessage])
      .mockResolvedValueOnce([userMessage, replacementMessage]);
    vi.mocked(streamRegeneratedTurn).mockImplementation(async (_id, _messageId, _signal, onEvent) => {
      onEvent('turn.harness', {
        phase: 'starting_thread', title: '正在重建 Codex sandbox', detail: '正在回放保留历史',
        attempt: 1, maxAttempts: 3,
      });
      onEvent('item/agentMessage/delta', { delta: 'Regenerated answer' });
      onEvent('turn.harness', {
        phase: 'completed', title: '回复已完成', detail: '替换回答已保存',
        attempt: 1, maxAttempts: 3,
      });
    });
    render(<ResearchWorkspace />);

    fireEvent.click(await screen.findByRole('button', { name: '重新生成' }));

    await waitFor(() => expect(streamRegeneratedTurn).toHaveBeenCalledWith(
      conversation.id, answerMessage.id, expect.any(AbortSignal), expect.any(Function),
    ));
    expect(await screen.findByText('Regenerated answer')).toBeInTheDocument();
    expect(screen.queryByText('Broken answer')).not.toBeInTheDocument();
  });

  it('shows a skill only when the Codex runtime reports that it loaded one', async () => {
    vi.mocked(researchApi.conversations).mockResolvedValue([{ ...conversation, active_paper_id: paper.id }]);
    vi.mocked(researchApi.papers).mockResolvedValue([paper]);
    vi.mocked((await import('../api')).streamTurn).mockImplementation(async (_id, _prompt, _paperId, _signal, onEvent) => {
      onEvent('turn.skill', {
        status: 'loaded',
        name: 'read-paper',
        detail: 'Codex 自主选择并载入 Skill',
      });
      onEvent('item/agentMessage/delta', { delta: '已使用读论文 Skill' });
      onEvent('turn/completed', { status: 'completed' });
    });
    render(<ResearchWorkspace />);

    const textarea = await screen.findByPlaceholderText('询问论文、检索研究、整理 Idea 或沉淀 Wiki...');
    fireEvent.change(textarea, { target: { value: '请读懂这篇论文' } });
    fireEvent.keyDown(textarea, { key: 'Enter' });

    expect(await screen.findByText('Skill · read-paper')).toBeInTheDocument();
    expect(screen.getAllByText('已载入 read-paper Skill').length).toBeGreaterThan(0);
  });
});
