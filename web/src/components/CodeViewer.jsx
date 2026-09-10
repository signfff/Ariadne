import { Loader2 } from 'lucide-react';

export default function CodeViewer({ path, file, loading, error }) {
  if (!path) return <p className="empty">从左侧选一个文件查看内容。</p>;
  if (loading) {
    return (
      <p className="loading">
        <Loader2 size={14} className="spin" /> 读取 {path}
      </p>
    );
  }
  if (error) return <p className="error-text">读取失败：{error}</p>;
  if (!file) return null;

  const lines = file.content.split('\n');

  return (
    <div className="code-viewer">
      <div className="code-head">
        <strong>{file.path}</strong>
        <span>{file.lines} 行</span>
      </div>
      <pre className="code-body">
        {lines.map((line, i) => (
          <div className="code-line" key={i}>
            <span className="ln">{i + 1}</span>
            <code>{line || ' '}</code>
          </div>
        ))}
      </pre>
    </div>
  );
}
