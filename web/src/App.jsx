import { useEffect, useRef, useState } from 'react';
import { AlertTriangle, FolderOpen, Loader2, RefreshCw, Server } from 'lucide-react';

import { getHealth, openProject, readFile, streamChat } from './api.js';
import ChatPanel from './components/ChatPanel.jsx';
import CodeViewer from './components/CodeViewer.jsx';
import FileTree from './components/FileTree.jsx';

export default function App() {
  const [health, setHealth] = useState(null);
  const [pathInput, setPathInput] = useState('');
  const [project, setProject] = useState(null);
  const [projectError, setProjectError] = useState('');
  const [opening, setOpening] = useState(false);

  const [selected, setSelected] = useState('');
  const [file, setFile] = useState(null);
  const [fileLoading, setFileLoading] = useState(false);
  const [fileError, setFileError] = useState('');

  const [messages, setMessages] = useState([]);
  const [draft, setDraft] = useState('');
  const [profile, setProfile] = useState('learn');
  const [streaming, setStreaming] = useState(false);
  const abortRef = useRef(null);
  const sessionRef = useRef(`web-${Date.now()}`);

  useEffect(() => {
    getHealth()
      .then((h) => {
        setHealth(h);
        setPathInput((prev) => prev || h.cwd);
      })
      .catch(() => setHealth(null));
  }, []);

  useEffect(() => {
    if (!selected || !project) return;
    setFileLoading(true);
    setFileError('');
    readFile(project.root, selected)
      .then(setFile)
      .catch((e) => setFileError(e.message))
      .finally(() => setFileLoading(false));
  }, [selected, project]);

  async function handleOpen(e) {
    e?.preventDefault();
    if (!pathInput.trim() || opening) return;
    setOpening(true);
    setProjectError('');
    try {
      const data = await openProject(pathInput.trim());
      setProject(data);
      setSelected(data.files.find((f) => f.previewable)?.path || '');
      setMessages([]);
      sessionRef.current = `web-${Date.now()}`;
    } catch (err) {
      setProjectError(err.message);
      setProject(null);
    } finally {
      setOpening(false);
    }
  }

  async function handleSend() {
    const message = draft.trim();
    if (!message || !project || streaming) return;

    setDraft('');
    setStreaming(true);
    setMessages((prev) => [
      ...prev,
      { role: 'user', text: message },
      { role: 'assistant', text: '', tools: [] },
    ]);

    const controller = new AbortController();
    abortRef.current = controller;

    // only the trailing assistant bubble changes as events arrive
    const patchLast = (fn) =>
      setMessages((prev) => {
        const next = prev.slice();
        next[next.length - 1] = fn(next[next.length - 1]);
        return next;
      });

    try {
      const body = { path: project.root, message, profile, session_id: sessionRef.current };
      for await (const event of streamChat(body, controller.signal)) {
        if (event.type === 'token') {
          patchLast((m) => ({ ...m, text: m.text + event.data.text }));
        } else if (event.type === 'tool_start') {
          patchLast((m) => ({
            ...m,
            tools: [...m.tools, { name: event.data.name, arguments: event.data.arguments }],
          }));
        } else if (event.type === 'tool_result') {
          patchLast((m) => {
            const tools = m.tools.slice();
            // fill in the newest still-running call with this name
            for (let i = tools.length - 1; i >= 0; i -= 1) {
              if (tools[i].name === event.data.name && tools[i].preview === undefined) {
                tools[i] = { ...tools[i], preview: event.data.preview, size: event.data.size };
                break;
              }
            }
            return { ...m, tools };
          });
        } else if (event.type === 'done') {
          patchLast((m) => ({ ...m, text: m.text || event.data.report, usage: event.data.usage }));
        } else if (event.type === 'error') {
          patchLast((m) => ({ ...m, error: `${event.data.kind}: ${event.data.message}` }));
        }
      }
    } catch (err) {
      const note = err.name === 'AbortError' ? '已停止' : err.message;
      patchLast((m) => ({ ...m, error: note }));
    } finally {
      setStreaming(false);
      abortRef.current = null;
    }
  }

  function handleStop() {
    abortRef.current?.abort();
  }

  const runtime = health?.runtime;
  const truncated = project?.files?.[0]?.truncated_listing;

  return (
    <div className="reader-shell">
      <aside className="left-rail">
        <div className="brand">
          <Server size={18} />
          <div>
            <div className="eyebrow">CoreCoder</div>
            <strong>代码阅读助手</strong>
          </div>
        </div>

        <form className="path-form" onSubmit={handleOpen}>
          <label htmlFor="project-path">项目路径</label>
          <div className="path-row">
            <input
              id="project-path"
              value={pathInput}
              onChange={(e) => setPathInput(e.target.value)}
              placeholder="D:\your\project"
            />
            <button type="submit" disabled={opening}>
              {opening ? <Loader2 size={14} className="spin" /> : <FolderOpen size={14} />}
            </button>
          </div>
          {projectError && <p className="error-text">{projectError}</p>}
        </form>

        {runtime && (
          <div className="metric-row">
            <div className="metric">
              <span>模型</span>
              <strong>{runtime.model}</strong>
            </div>
            <div className="metric">
              <span>API Key</span>
              <strong className={runtime.api_key_present ? '' : 'warn'}>
                {runtime.api_key_present ? '已读取' : '未读取'}
              </strong>
            </div>
          </div>
        )}

        {runtime && !runtime.api_key_present && (
          <p className="notice">
            <AlertTriangle size={13} /> 服务端没读到 API Key，提问会失败。设好环境变量后重启服务器。
          </p>
        )}

        {project && (
          <>
            <div className="metric-row">
              <div className="metric">
                <span>文件</span>
                <strong>{project.stats.file_count}</strong>
              </div>
              <div className="metric">
                <span>主要类型</span>
                <strong>{project.stats.top_exts.slice(0, 2).map((t) => t.ext).join(' ')}</strong>
              </div>
            </div>
            <FileTree files={project.files} selected={selected} onSelect={setSelected} />
          </>
        )}
      </aside>

      <main className="main-panel">
        <header className="reader-topbar">
          <div>
            <strong>{project ? project.root : '未打开项目'}</strong>
            {truncated && <span className="badge">文件过多，已截断</span>}
          </div>
          <button type="button" className="refresh" onClick={handleOpen} disabled={!project || opening}>
            <RefreshCw size={13} /> 重新扫描
          </button>
        </header>

        <div className="reader-grid">
          <section className="preview">
            <CodeViewer path={selected} file={file} loading={fileLoading} error={fileError} />
          </section>
          <section className="chat-section">
            <ChatPanel
              messages={messages}
              streaming={streaming}
              profile={profile}
              onProfileChange={setProfile}
              draft={draft}
              onDraftChange={setDraft}
              onSend={handleSend}
              onStop={handleStop}
              disabled={!project}
            />
          </section>
        </div>
      </main>
    </div>
  );
}
