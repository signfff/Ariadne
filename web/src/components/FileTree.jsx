import { useMemo, useState } from 'react';
import { FileCode2, Search } from 'lucide-react';

const KB = 1024;

function humanSize(bytes) {
  if (bytes < KB) return `${bytes} B`;
  if (bytes < KB * KB) return `${(bytes / KB).toFixed(1)} KB`;
  return `${(bytes / KB / KB).toFixed(1)} MB`;
}

export default function FileTree({ files, selected, onSelect }) {
  const [filter, setFilter] = useState('');

  const visible = useMemo(() => {
    const keyword = filter.trim().toLowerCase();
    if (!keyword) return files;
    return files.filter((f) => f.path.toLowerCase().includes(keyword));
  }, [files, filter]);

  return (
    <div className="section-block file-panel">
      <div className="search-box">
        <Search size={14} />
        <input
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder={`过滤 ${files.length} 个文件`}
          aria-label="过滤文件"
        />
      </div>

      <div className="file-list">
        {visible.length === 0 && <p className="empty">没有匹配的文件</p>}
        {visible.map((file) => (
          <button
            key={file.path}
            type="button"
            className={`file-item ${file.path === selected ? 'is-active' : ''}`}
            onClick={() => file.previewable && onSelect(file.path)}
            disabled={!file.previewable}
            title={file.previewable ? file.path : `${file.path}（不可预览）`}
          >
            <FileCode2 size={13} />
            <span className="file-name">{file.path}</span>
            <span className="file-size">{humanSize(file.size)}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
