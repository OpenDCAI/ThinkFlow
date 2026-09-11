import React from 'react';
import '@testing-library/jest-dom/vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import GlobalResearchAssistant from '../GlobalResearchAssistant';
import { researchApi, streamTurn } from '../api';

vi.mock('../api', () => ({
  researchApi: {
    globalConversations: vi.fn(),
    createGlobalConversation: vi.fn(),
    messages: vi.fn(),
    actions: vi.fn(),
    spaces: vi.fn(),
    deleteConversation: vi.fn(),
    cancel: vi.fn(),
    confirmAction: vi.fn(),
    cancelAction: vi.fn(),
  },
  streamTurn: vi.fn(),
}));

const conversation = {
  id: 'global-chat-1',
  space_id: '__global__',
  title: '全局研究对话',
  scope: 'global',
  status: 'idle' as const,
  created_at: '2026-08-15T00:00:00Z',
  updated_at: '2026-08-15T00:00:00Z',
};

const space = {
  id: 'space-1',
  title: 'SWE 演进',
  description: '',
  created_at: '2026-08-15T00:00:00Z',
  updated_at: '2026-08-15T00:00:00Z',
};

describe('GlobalResearchAssistant natural-language orchestration', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(researchApi.globalConversations)
      .mockResolvedValueOnce([])
      .mockResolvedValue([conversation]);
    vi.mocked(researchApi.createGlobalConversation).mockResolvedValue(conversation);
    vi.mocked(researchApi.messages).mockResolvedValue([]);
    vi.mocked(researchApi.actions).mockResolvedValue([]);
    vi.mocked(researchApi.spaces).mockResolvedValue([space]);
    vi.mocked(streamTurn).mockResolvedValue(undefined);
  });

  it('creates the first conversation and submits the same command without a manual mode', async () => {
    const onSpacesChanged = vi.fn();
    render(
      <GlobalResearchAssistant
        codexAvailable
        onBack={vi.fn()}
        onSpacesChanged={onSpacesChanged}
      />,
    );

    expect(screen.queryByRole('button', { name: '普通研究' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '批量入库' })).not.toBeInTheDocument();
    const composer = screen.getByPlaceholderText(/直接告诉 Codex/);
    expect(composer).toBeEnabled();

    fireEvent.change(composer, { target: { value: '新建一个 SWE 演进空间，并把这批论文导进去' } });
    fireEvent.keyDown(composer, { key: 'Enter' });

    await waitFor(() => expect(researchApi.createGlobalConversation).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(streamTurn).toHaveBeenCalledWith(
      conversation.id,
      '新建一个 SWE 演进空间，并把这批论文导进去',
      undefined,
      expect.any(AbortSignal),
      expect.any(Function),
    ));
    await waitFor(() => expect(onSpacesChanged).toHaveBeenCalledWith([space]));
  });
});
