import '@testing-library/jest-dom';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import MarkdownPreview, { normalizeMathDelimiters } from '../MarkdownPreview';


describe('MarkdownPreview', () => {
  it('renders GFM structure used by Codex research answers', () => {
    const { container } = render(
      <MarkdownPreview>{`# Research summary

- First finding
- Second finding

1. Validate
2. Compare

---

> Evidence note

| Model | Score |
| --- | ---: |
| Codex | 92 |

- [x] Read paper

~~superseded~~ and https://example.com`}</MarkdownPreview>,
    );

    expect(screen.getByRole('heading', { name: 'Research summary' })).toBeInTheDocument();
    expect(container.querySelector('ul > li')).toHaveTextContent('First finding');
    expect(container.querySelector('ol > li')).toHaveTextContent('Validate');
    expect(container.querySelector('hr')).toBeInTheDocument();
    expect(container.querySelector('blockquote')).toHaveTextContent('Evidence note');
    expect(screen.getByRole('table')).toHaveTextContent('Codex');
    expect(container.querySelector('.contains-task-list input[type="checkbox"]')).toBeChecked();
    expect(container.querySelector('del')).toHaveTextContent('superseded');
    expect(screen.getByRole('link', { name: 'https://example.com' })).toHaveAttribute('target', '_blank');
    expect(container.firstElementChild).toHaveClass('research-markdown');
  });

  it('normalizes bracketed LaTeX without changing fenced code', () => {
    const markdown = String.raw`公式：
\[
\text{Solved}(i)=\mathbf{1}[\forall t,\ \text{status}(t)=\text{pass}]
\]

` + '```latex\n\\\\[not math in code\\\\]\n```\n\n`\\[inline code\\]`';
    const normalized = normalizeMathDelimiters(markdown);

    expect(normalized).toContain('$$\n\\text{Solved}(i)');
    expect(normalized).toContain('\\\\[not math in code\\\\]');
    expect(normalized).toContain('`\\[inline code\\]`');
    expect(normalized).not.toContain('\\\n\\text{Solved');
  });

  it('hands bracketed display math to KaTeX', () => {
    const { container } = render(
      <MarkdownPreview>{String.raw`\[
\text{Resolved Rate}=\frac{1}{N}\sum_{i=1}^{N}\text{Solved}(i)
\]`}</MarkdownPreview>,
    );

    expect(container.querySelector('.katex-display')).toBeInTheDocument();
    expect(container.querySelector('.katex')).toBeInTheDocument();
    expect(container.textContent).not.toContain('\\[');
  });
});
