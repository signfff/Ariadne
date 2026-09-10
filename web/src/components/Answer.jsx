import { useMemo } from 'react';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

// A path the model cites, with an optional :line or :start-end suffix.
const CITATION = /^([\w./@-]+\.\w{1,6})(?::(\d+)(?:-\d+)?)?$/;

/**
 * Render an answer as Markdown, and turn any inline code that names a real
 * file in this project into a link that opens it.
 *
 * The agent is told to cite what it read, so those citations are the most
 * useful thing in the answer - leaving them as plain text means copying the
 * path into the file tree by hand.
 */
export default function Answer({ text, files, onOpenFile }) {
  const known = useMemo(() => new Set(files ?? []), [files]);

  const components = useMemo(
    () => ({
      code({ inline, className, children, ...props }) {
        const raw = String(children).replace(/\n$/, '');

        if (inline || (!className && !raw.includes('\n'))) {
          const match = CITATION.exec(raw.trim());
          const path = match?.[1];
          if (path && known.has(path)) {
            return (
              <button
                type="button"
                className="cite"
                onClick={() => onOpenFile(path, match[2] ? Number(match[2]) : undefined)}
                title={`打开 ${path}`}
              >
                {raw}
              </button>
            );
          }
          return <code className="inline-code" {...props}>{children}</code>;
        }

        return (
          <pre className="md-code">
            <code {...props}>{children}</code>
          </pre>
        );
      },
      // the model's headings should not outrank the page's own
      h1: ({ children }) => <h4 className="md-h">{children}</h4>,
      h2: ({ children }) => <h4 className="md-h">{children}</h4>,
      h3: ({ children }) => <h5 className="md-h">{children}</h5>,
      h4: ({ children }) => <h5 className="md-h">{children}</h5>,
      a: ({ children, href }) => (
        <a href={href} target="_blank" rel="noreferrer noopener">
          {children}
        </a>
      ),
      table: ({ children }) => (
        <div className="md-table-wrap">
          <table>{children}</table>
        </div>
      ),
    }),
    [known, onOpenFile],
  );

  return (
    <div className="answer-md">
      <Markdown remarkPlugins={[remarkGfm]} components={components}>
        {text}
      </Markdown>
    </div>
  );
}
