import ReactMarkdown from 'react-markdown';
import rehypeKatex from 'rehype-katex';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';

import './markdown-preview.css';


interface MarkdownPreviewProps {
  children: string;
  className?: string;
}

const CODE_BLOCK_OR_SPAN = /(```[\s\S]*?```|~~~[\s\S]*?~~~|``[^\n]*?``|`[^`\n]*`)/g;

/** Normalize LaTeX delimiters commonly emitted by Codex before remark-math parses Markdown. */
export function normalizeMathDelimiters(markdown: string): string {
  return markdown
    .split(CODE_BLOCK_OR_SPAN)
    .map((part, index) => {
      if (index % 2 === 1) return part;
      return part
        .replace(/\\\[([\s\S]*?)\\\]/g, (_, body: string) => `$$\n${body.trim()}\n$$`)
        .replace(/\\\(([\s\S]*?)\\\)/g, (_, body: string) => `$${body}$`)
        .replace(/\\begin\{equation\*?\}([\s\S]*?)\\end\{equation\*?\}/g, (_, body: string) => `$$\n${body.trim()}\n$$`);
    })
    .join('');
}

export default function MarkdownPreview({ children, className = '' }: MarkdownPreviewProps) {
  return (
    <div className={`research-markdown ${className}`.trim()}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeKatex]}
        components={{
          a: ({ children: linkChildren, ...props }) => (
            <a {...props} target="_blank" rel="noreferrer">
              {linkChildren}
            </a>
          ),
        }}
      >
        {normalizeMathDelimiters(children)}
      </ReactMarkdown>
    </div>
  );
}
