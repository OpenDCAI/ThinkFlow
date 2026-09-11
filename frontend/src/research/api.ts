import { apiFetch, parseJson } from '../config/api';
import type {
  ResearchConversation,
  ResearchIdea,
  ResearchJob,
  ResearchMessage,
  ResearchAction,
  ResearchPaper,
  ResearchSpace,
  PaperBatchImportResult,
  PaperNote,
  SkillSummary,
  WikiPage,
} from './types';

async function json<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await apiFetch(path, options);
  return parseJson<T>(response);
}

function body(value: unknown): RequestInit {
  return {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(value),
  };
}

export const researchApi = {
  async status() {
    return json<{
      codex: {
        available: boolean;
        signed_in?: boolean;
        error?: string;
        models?: Array<{ id: string; displayName?: string; isDefault?: boolean }>;
        skills?: SkillSummary[];
        skills_error?: string | null;
        skills_root?: string;
      };
      translation_providers: Array<{ id: string; name: string; available: boolean; accepts: string[] }>;
      external_tools: Array<{ id: string; available: boolean; mode: string }>;
      research_functions?: Array<{ name: string; title: string; read_only: boolean }>;
    }>('/api/v1/research/status');
  },
  async spaces() {
    return (await json<{ spaces: ResearchSpace[] }>('/api/v1/research/spaces')).spaces;
  },
  async createSpace(title: string, description = '') {
    return (await json<{ space: ResearchSpace }>('/api/v1/research/spaces', body({ title, description }))).space;
  },
  async deleteSpace(spaceId: string) {
    return json<{ success: boolean }>(`/api/v1/research/spaces/${spaceId}`, { method: 'DELETE' });
  },
  async conversations(spaceId: string) {
    return (await json<{ conversations: ResearchConversation[] }>(`/api/v1/research/spaces/${spaceId}/conversations`)).conversations;
  },
  async resourceConversations(spaceId: string, resourceId: string) {
    return (await json<{ conversations: ResearchConversation[] }>(
      `/api/v1/research/spaces/${spaceId}/conversations?resource_id=${encodeURIComponent(resourceId)}`,
    )).conversations;
  },
  async createConversation(spaceId: string, title = '新对话', options?: { scope?: string; paper_ids?: string[] }) {
    return (await json<{ conversation: ResearchConversation }>(`/api/v1/research/spaces/${spaceId}/conversations`, body({ title, ...options }))).conversation;
  },
  async globalConversations() {
    return (await json<{ conversations: ResearchConversation[] }>('/api/v1/research/global/conversations')).conversations;
  },
  async createGlobalConversation(title = '全局研究对话') {
    return (await json<{ conversation: ResearchConversation }>('/api/v1/research/global/conversations', body({ title }))).conversation;
  },
  async messages(conversationId: string) {
    return (await json<{ messages: ResearchMessage[] }>(`/api/v1/research/conversations/${conversationId}/messages`)).messages;
  },
  async rollbackMessage(conversationId: string, messageId: string) {
    return json<{
      success: boolean;
      removed_count: number;
      messages: ResearchMessage[];
      conversation: ResearchConversation;
    }>(`/api/v1/research/conversations/${conversationId}/messages/${messageId}/rollback`, {
      method: 'POST',
    });
  },
  async actions(conversationId: string) {
    return (await json<{ actions: ResearchAction[] }>(
      `/api/v1/research/conversations/${conversationId}/actions`,
    )).actions;
  },
  async confirmAction(actionId: string) {
    return (await json<{ action: ResearchAction }>(
      `/api/v1/research/actions/${actionId}/confirm`,
      { method: 'POST' },
    )).action;
  },
  async cancelAction(actionId: string) {
    return (await json<{ action: ResearchAction }>(
      `/api/v1/research/actions/${actionId}/cancel`,
      { method: 'POST' },
    )).action;
  },
  async deleteConversation(conversationId: string) {
    return json<{ success: boolean }>(`/api/v1/research/conversations/${conversationId}`, { method: 'DELETE' });
  },
  async bindPaper(conversationId: string, paperId?: string) {
    return (await json<{ conversation: ResearchConversation }>(
      `/api/v1/research/conversations/${conversationId}/paper`,
      { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ paper_id: paperId || null }) },
    )).conversation;
  },
  async setConversationPapers(conversationId: string, paperIds: string[]) {
    return json<{ conversation: ResearchConversation; papers: ResearchPaper[] }>(
      `/api/v1/research/conversations/${conversationId}/papers`,
      { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ paper_ids: paperIds }) },
    );
  },
  async cancel(conversationId: string) {
    return json<{ cancelled: boolean }>(`/api/v1/research/conversations/${conversationId}/cancel`, { method: 'POST' });
  },
  async papers(spaceId: string) {
    return (await json<{ papers: ResearchPaper[] }>(`/api/v1/research/spaces/${spaceId}/papers`)).papers;
  },
  async resources(resourceType?: string) {
    const query = resourceType ? `?resource_type=${encodeURIComponent(resourceType)}` : '';
    return (await json<{ resources: ResearchPaper[] }>(`/api/v1/research/resources${query}`)).resources;
  },
  async resourceSpaces(resourceId: string) {
    return (await json<{ spaces: ResearchSpace[] }>(`/api/v1/research/resources/${resourceId}/spaces`)).spaces;
  },
  async linkResourceToSpace(spaceId: string, resourceId: string) {
    return (await json<{ resource: ResearchPaper; spaces: ResearchSpace[] }>(
      `/api/v1/research/spaces/${spaceId}/resources/${resourceId}`,
      { method: 'POST' },
    ));
  },
  async unlinkResourceFromSpace(spaceId: string, resourceId: string) {
    return (await json<{ resource: ResearchPaper; spaces: ResearchSpace[] }>(
      `/api/v1/research/spaces/${spaceId}/resources/${resourceId}`,
      { method: 'DELETE' },
    ));
  },
  async uploadPaper(spaceId: string, file: File) {
    const data = new FormData();
    data.set('file', file);
    data.set('title', file.name.replace(/\.pdf$/i, ''));
    return (await json<{ paper: ResearchPaper }>(`/api/v1/research/spaces/${spaceId}/papers/upload`, { method: 'POST', body: data })).paper;
  },
  async importPaper(spaceId: string, query: string, downloadPdf = true) {
    return (await json<{ success: boolean; paper: ResearchPaper; metadata: NonNullable<ResearchPaper['metadata']>; candidates: Array<NonNullable<ResearchPaper['metadata']>>; warnings: string[] }>(
      `/api/v1/research/spaces/${spaceId}/papers/import`,
      body({ query, download_pdf: downloadPdf, download_source: downloadPdf, resolve_metadata: true }),
    ));
  },
  async batchImportPapers(input: {
    queries: string[];
    space_id?: string;
    new_space_title?: string;
    new_space_description?: string;
    download_pdf?: boolean;
    conversation_id?: string;
    instruction?: string;
  }) {
    return json<PaperBatchImportResult>('/api/v1/research/papers/batch-import', body({
      ...input,
      download_pdf: input.download_pdf ?? true,
      download_source: input.download_pdf ?? true,
    }));
  },
  async paperNote(paperId: string) {
    return (await json<{ note: PaperNote | null }>(`/api/v1/research/papers/${paperId}/note`)).note;
  },
  async refreshPaperNote(paperId: string) {
    return (await json<{ note: PaperNote }>(`/api/v1/research/papers/${paperId}/note/refresh`, { method: 'POST' })).note;
  },
  async savePaperNote(paperId: string, note: Partial<PaperNote>) {
    return (await json<{ note: PaperNote }>(
      `/api/v1/research/papers/${paperId}/note`,
      { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(note) },
    )).note;
  },
  async addBlog(spaceId: string, sourceUrl: string, title = '', fetchContent = true) {
    return (await json<{ resource: ResearchPaper }>(
      `/api/v1/research/spaces/${spaceId}/resources/blog`,
      body({ source_url: sourceUrl, title, fetch_content: fetchContent }),
    )).resource;
  },
  async wiki(spaceId: string) {
    return (await json<{ pages: WikiPage[] }>(`/api/v1/research/spaces/${spaceId}/wiki`)).pages;
  },
  async saveWiki(spaceId: string, page: Partial<WikiPage> & { title: string; content: string }) {
    return (await json<{ page: WikiPage }>(`/api/v1/research/spaces/${spaceId}/wiki`, body(page))).page;
  },
  async ideas(spaceId: string) {
    return (await json<{ ideas: ResearchIdea[] }>(`/api/v1/research/spaces/${spaceId}/ideas`)).ideas;
  },
  async saveIdea(spaceId: string, idea: Partial<ResearchIdea> & { title: string }) {
    return (await json<{ idea: ResearchIdea }>(`/api/v1/research/spaces/${spaceId}/ideas`, body(idea))).idea;
  },
  async jobs(spaceId: string) {
    return (await json<{ jobs: ResearchJob[] }>(`/api/v1/research/spaces/${spaceId}/jobs`)).jobs;
  },
  async createTranslation(spaceId: string, paperId: string, conversationId?: string) {
    return json<{ job: ResearchJob; message: string }>(`/api/v1/research/spaces/${spaceId}/translations`, body({
      paper_id: paperId,
      provider: 'unconfigured',
      conversation_id: conversationId,
    }));
  },
  async skills() {
    return (await json<{ skills: SkillSummary[] }>('/api/v1/research/skills')).skills;
  },
};

async function consumeTurnStream(
  path: string,
  options: RequestInit,
  signal: AbortSignal,
  onEvent: (type: string, data: Record<string, any>) => void,
) {
  const response = await apiFetch(path, { ...options, signal });
  if (!response.ok || !response.body) {
    throw new Error((await response.text()) || `Request failed: ${response.status}`);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let eventName = 'message';
  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    const chunks = buffer.split('\n\n');
    buffer = chunks.pop() || '';
    for (const chunk of chunks) {
      let data = '';
      for (const line of chunk.split('\n')) {
        if (line.startsWith('event:')) eventName = line.slice(6).trim();
        if (line.startsWith('data:')) data += line.slice(5).trim();
      }
      if (data) onEvent(eventName, JSON.parse(data));
      eventName = 'message';
    }
    if (done) break;
  }
}

export async function streamTurn(
  conversationId: string,
  prompt: string,
  paperId: string | undefined,
  signal: AbortSignal,
  onEvent: (type: string, data: Record<string, any>) => void,
) {
  return consumeTurnStream(
    `/api/v1/research/conversations/${conversationId}/turns`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt, paper_id: paperId || null }),
    },
    signal,
    onEvent,
  );
}

export async function streamRegeneratedTurn(
  conversationId: string,
  messageId: string,
  signal: AbortSignal,
  onEvent: (type: string, data: Record<string, any>) => void,
) {
  return consumeTurnStream(
    `/api/v1/research/conversations/${conversationId}/messages/${messageId}/regenerate`,
    { method: 'POST' },
    signal,
    onEvent,
  );
}
