export type ResearchSpace = {
  id: string;
  title: string;
  description: string;
  created_at: string;
  updated_at: string;
  resource_count?: number;
  conversation_count?: number;
  scope?: 'user' | 'system' | string;
};

export type ResearchConversation = {
  id: string;
  space_id: string;
  title: string;
  codex_thread_id?: string;
  active_paper_id?: string;
  paper_ids?: string[];
  resource_count?: number;
  scope?: 'global' | 'space' | 'paper' | 'idea' | string;
  status: 'idle' | 'running' | 'error';
  created_at: string;
  updated_at: string;
};

export type ResearchMessage = {
  id: string;
  conversation_id: string;
  turn_id?: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  event_type: string;
  metadata?: Record<string, unknown>;
  created_at: string;
};

export type ResearchAction = {
  id: string;
  conversation_id: string;
  tool_name: string;
  summary: string;
  arguments: Record<string, unknown>;
  result: {
    success?: boolean;
    imported_count?: number;
    failed_count?: number;
    space?: ResearchSpace;
    conversation?: ResearchConversation;
    [key: string]: unknown;
  };
  status: 'pending' | 'executing' | 'completed' | 'failed' | 'cancelled';
  error?: string;
  created_at: string;
  updated_at: string;
  confirmed_at?: string;
  completed_at?: string;
};

export type ResearchPaper = {
  id: string;
  resource_id?: string;
  space_ids?: string[];
  resource_type?: 'paper' | 'blog' | string;
  title: string;
  original_name?: string;
  stored_path?: string;
  source_url?: string;
  availability: string;
  status: string;
  metadata?: {
    size?: number;
    outputs_url?: string;
    text_path?: string;
    page_count?: number;
    extracted_chars?: number;
    extraction_status?: 'ready' | 'error';
    extraction_error?: string;
    query?: string;
    source?: string;
    sources?: string[];
    authors?: Array<{ name: string; affiliations?: string[] }>;
    institutions?: string[];
    abstract?: string;
    doi?: string | null;
    arxiv_id?: string | null;
    paper_url?: string | null;
    pdf_url?: string | null;
    venue?: string | null;
    venue_short_name?: string | null;
    venue_url?: string | null;
    venue_type?: string | null;
    publication_status?: 'preprint' | 'published' | 'accepted' | 'unknown' | string;
    is_preprint?: boolean;
    published_at?: string | null;
    updated_at?: string | null;
    version?: string | null;
    categories?: string[];
    confidence?: number;
    import_warnings?: string[];
    resolved_at?: string;
    source_ingestion_status?: 'ready' | 'error';
    source_text_path?: string;
    source_entrypoint?: string;
    source_file_count?: number;
    source_chars?: number;
    source_archive_url?: string;
    visual_assets?: Array<{ path: string; page: number; kind?: string; labels?: string[] }>;
    visual_asset_count?: number;
    visual_ingestion_status?: 'ready' | 'none_detected' | 'error' | string;
    visual_ingestion_error?: string;
    resource_type?: string;
    page_title?: string;
    content?: string;
    content_chars?: number;
    content_status?: 'ready' | 'empty' | 'error' | string;
    content_error?: string;
  };
  created_at: string;
};

export type PaperImportResult = {
  paper: ResearchPaper;
  metadata: NonNullable<ResearchPaper['metadata']>;
  candidates: Array<NonNullable<ResearchPaper['metadata']>>;
  warnings: string[];
};

export type PaperBatchImportResult = {
  success: boolean;
  space: ResearchSpace;
  imported_count: number;
  failed_count: number;
  results: Array<{
    query: string;
    status: 'success' | 'error';
    paper?: ResearchPaper;
    warnings?: string[];
    error?: string;
  }>;
};

export type PaperNote = {
  paper_id: string;
  short_summary: string;
  qa_summary: string;
  open_questions: string;
  key_takeaways: string;
  personal_notes: string;
  source_message_ids: string[];
  generated_at: string;
  revision: number;
};

export type WikiPage = {
  id: string;
  title: string;
  slug: string;
  content: string;
  tags: string[];
  revision: number;
  updated_at: string;
};

export type ResearchIdea = {
  id: string;
  title: string;
  problem: string;
  hypothesis: string;
  method: string;
  evidence: string;
  risks: string;
  next_steps: string;
  status: string;
  tags: string[];
  updated_at: string;
};

export type ResearchJob = {
  id: string;
  kind: string;
  provider: string;
  status: string;
  progress: number;
  input: Record<string, unknown>;
  output: Record<string, unknown>;
  error?: string;
  updated_at: string;
};

export type SkillSummary = {
  name: string;
  path: string;
  description: string;
  enabled?: boolean;
  scope?: string;
  source?: 'filesystem' | 'codex-runtime' | string;
  runtime_cwd?: string;
  interface?: {
    displayName?: string;
    shortDescription?: string;
  } | null;
};

export type CodexEvent = {
  id: string;
  type: string;
  title: string;
  detail?: string;
  status: 'running' | 'done' | 'error';
};

export type CodexHarnessPhase =
  | 'queued'
  | 'preparing_context'
  | 'context_ready'
  | 'starting_thread'
  | 'starting_turn'
  | 'waiting_for_response'
  | 'streaming'
  | 'tool_running'
  | 'retrying'
  | 'cancelling'
  | 'completed'
  | 'cancelled'
  | 'failed';

export type CodexHarness = {
  phase: CodexHarnessPhase;
  title: string;
  detail?: string;
  startedAt: number;
  updatedAt: number;
  endedAt?: number;
  attempt: number;
  maxAttempts: number;
  threadId?: string;
  turnId?: string;
};
