# Research Person Skeleton

This branch turns ThinkFlow's first screen into a local, single-user research workspace.
The existing feature modules remain in the repository, while the new surface is organized
around research spaces, persistent Codex conversations, and durable research artifacts.

## Runtime shape

- One application conversation maps to one resumable Codex SDK thread.
- Every conversation has an isolated writable sandbox under
  `outputs/research_person/spaces/<space_id>/threads/<conversation_id>`.
- Papers, Wiki pages, Ideas, generated artifacts, and project Skills are shared within a
  research space.
- PDF uploads are extracted page by page into ignored Markdown artifacts. A conversation can bind
  an ordered set of papers and blogs. Their bounded content is supplied directly to Codex turns so
  paper chat does not depend on shell access, bwrap, or the legacy RAG pipeline.
- SQLite stores workspace metadata and message history. Wiki pages and Ideas are also
  materialized as Markdown so Codex and future tools can use them directly.
- Codex uses the machine's existing `~/.codex` provider and model configuration. No provider
  secret is copied into ThinkFlow storage.

## Global research functions

Global Codex conversations receive a project-local `thinkflow_research` STDIO MCP server. Space and
paper conversations do not receive these cross-space tools. The MCP server, REST routes, and action
confirmation endpoints share `ResearchToolExecutor`; repository mutations must not be duplicated in
an MCP-only implementation.

The first registry exposes ten functions covering space discovery and creation, resource metadata
resolution and import, conversation discovery and creation, and multi-resource bindings. Read tools
execute immediately. Write tools only persist a `pending_action`; the frontend must submit a separate
confirmation request before the executor performs the mutation. Completed, failed, and cancelled
actions remain attached to the global conversation as an audit-friendly history.

For compound setup, `import_research_resources` can create a new space, import multiple papers, create
one conversation, and bind successful imports in a single confirmed action. Imports remain deduplicated
by arXiv ID, DOI, or normalized exact title.

## Extension boundaries

Paper search, translation, calendar actions, and task actions are integrations rather than
core domain logic:

1. A provider accepts a job plus paths to local inputs.
2. It writes generated files below the space's `artifacts` directory.
3. It returns artifact metadata and updates job status and progress.
4. External side effects use an installed Skill, MCP server, command adapter, or HTTP adapter.
5. Side-effect adapters must write an audit entry and use an idempotency key before execution.

The current translation provider is intentionally `unconfigured`; translation jobs remain in
`waiting_provider` until a concrete adapter is installed.

## PDF translation candidates

No paper-translation Skill was found in the currently installed local Skill directories.
The following projects were reviewed on 2026-08-12. All are AGPL-3.0. A subprocess or service
adapter keeps the core architecture decoupled, but it does not by itself remove license
obligations; deployment and distribution terms must be reviewed before selecting a provider.

| Project | Interface and fit | Recommendation |
| --- | --- | --- |
| [PDFMathTranslate-next](https://github.com/PDFMathTranslate/PDFMathTranslate-next) | Current self-hosted PDFMathTranslate generation with CLI, GUI and Docker support | Best first service-provider proof of concept for a self-hosted deployment |
| [PDFMathTranslate](https://github.com/PDFMathTranslate/PDFMathTranslate) | CLI, Python API, HTTP API, MCP, formula/layout preservation, monolingual and bilingual PDF output | Best ready-made provider when broad service support or an HTTP boundary is preferred |
| [BabelDOC](https://github.com/funstory-ai/BabelDOC) | PyPI package, CLI and Python API, designed for embedding, bilingual comparison output | Best low-level library candidate for a dedicated translation worker |
| [zotero-pdf2zh](https://github.com/guaguastandup/zotero-pdf2zh) | Zotero plugin plus companion server built around PDF2zh | Useful for Zotero interoperability, not the primary ThinkFlow backend adapter |

No candidate is installed in the main ThinkFlow environment at this stage. A future adapter
should be selectable by provider ID and consume the existing `paper_translation` job schema,
without changing paper, conversation, Wiki, or Idea models.

## Current API surface

- `GET/POST /api/v1/research/spaces`
- `GET/POST /api/v1/research/spaces/{space_id}/conversations`
- `GET /api/v1/research/conversations/{conversation_id}/messages`
- `GET /api/v1/research/conversations/{conversation_id}/actions`
- `POST /api/v1/research/actions/{action_id}/confirm`
- `POST /api/v1/research/actions/{action_id}/cancel`
- `POST /api/v1/research/conversations/{conversation_id}/turns` (SSE)
- `POST /api/v1/research/conversations/{conversation_id}/cancel`
- `GET/POST /api/v1/research/spaces/{space_id}/papers/*`
- `GET/POST /api/v1/research/spaces/{space_id}/wiki`
- `GET/POST /api/v1/research/spaces/{space_id}/ideas`
- `GET /api/v1/research/spaces/{space_id}/jobs`
- `POST /api/v1/research/spaces/{space_id}/translations`
- `GET /api/v1/research/skills`
