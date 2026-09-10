import { useState } from 'react';
import { ChevronRight, Loader2, Terminal } from 'lucide-react';

/** The tool calls the agent made, in order, with their results. */
export default function ToolTimeline({ tools }) {
  if (!tools.length) return null;
  return (
    <div className="tool-timeline">
      {tools.map((tool, i) => (
        <ToolRow key={i} tool={tool} />
      ))}
    </div>
  );
}

function ToolRow({ tool }) {
  const [open, setOpen] = useState(false);
  const done = tool.preview !== undefined;

  return (
    <div className={`tool-row ${done ? 'is-done' : 'is-running'}`}>
      <button type="button" className="tool-head" onClick={() => setOpen(!open)} disabled={!done}>
        {done ? <Terminal size={12} /> : <Loader2 size={12} className="spin" />}
        <span className="tool-name">{tool.name}</span>
        <span className="tool-args">{summarise(tool.arguments)}</span>
        {done && <span className="tool-size">{tool.size} 字符</span>}
        {done && <ChevronRight size={12} className={`chev ${open ? 'is-open' : ''}`} />}
      </button>
      {open && done && <pre className="tool-output">{tool.preview}</pre>}
    </div>
  );
}

function summarise(args) {
  if (!args) return '';
  const parts = Object.entries(args).map(([k, v]) => `${k}=${String(v).slice(0, 40)}`);
  return parts.join(' ');
}
