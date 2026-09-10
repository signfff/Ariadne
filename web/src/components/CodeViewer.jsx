import { useEffect, useRef } from 'react';
import { Loader2 } from 'lucide-react';

export default function CodeViewer({ path, file, loading, error, jumpLine }) {
  const bodyRef = useRef(null);

  // scroll the cited line into view once its file has loaded
  useEffect(() => {
    if (!jumpLine || !file || !bodyRef.current) return;
    const row = bodyRef.current.querySelector(`[data-line="${jumpLine}"]`);
    row?.scrollIntoView({ block: 'center' });
  }, [jumpLine, file]);

  if (!path) return <p className="empty">从左侧选一个文件，或在概览里点阅读路线。</p>;
  if (loading) {
    return (
      <p className="loading">
        <Loader2 size={14} className="spin" /> 读取 {path}
      </p>
    );
  }
  if (error) return <p className="error-text ov-pad">读取失败：{error}</p>;
  if (!file) return null;

  const lines = file.content.split('\n');

  return (
    <div className="code-viewer">
      <div className="code-head">
        <strong>{file.path}</strong>
        <span>{file.lines} 行</span>
      </div>
      <pre className="code-body" ref={bodyRef}>
        {lines.map((line, i) => (
          <div
            className={`code-line ${i + 1 === jumpLine ? 'is-cited' : ''}`}
            key={i}
            data-line={i + 1}
          >
            <span className="ln">{i + 1}</span>
            <code>{line || ' '}</code>
          </div>
        ))}
      </pre>
    </div>
  );
}
