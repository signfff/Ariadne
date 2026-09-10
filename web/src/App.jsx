import { useEffect, useRef, useState } from 'react';
import { AlertTriangle, FolderOpen, LayoutList, Loader2, RefreshCw, Server, FileCode2 } from 'lucide-react';

import { getHealth, getOverview, openProject, readFile, streamChat } from './api.js';
import ChatPanel from './components/ChatPanel.jsx';
import CodeViewer from './components/CodeViewer.jsx';
import FileTree from './components/FileTree.jsx';
import OverviewPanel from './components/OverviewPanel.jsx';

export default function App() {
  const [health, setHealth] = useState(null);
  const [pathInput, setPathInput] = useState('');
  const [project, setProject] = useState(null);
  const [projectError, setProjectError] = useState('');
  const [opening, setOpening] = useState(false);

  const [tab, setTab] = useState('overview');
  const [overview, setOverview] = useState(null);
  const [overviewError, setOverviewError] = useState('');
  const [overviewLoading, setOverviewLoading] = useState(false);

  const [selected, setSelected] = useState('');
  const [jumpLine, setJumpLine] = useState(null);
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
    setOverview(null);
    setOverviewError('');
    try {
      const data = await openProject(pathInput.trim());
      setProject(data);
      setSelected('');
      setFile(null);
      setMessages([]);
      setTab('overview');
      sessionRef.current = `web-${Date.now()}`;

      setOverviewLoading(true);
      getOverview(data.root)
        .then(setOverview)
        .catch((err) => setOverviewError(err.message))
        .finally(() => setOverviewLoading(false));
    } catch (err) {
      setProjectError(err.message);
      setProject(null);
    } finally {
      setOpening(false);
    }
  }

  function openFile(path, line) {
    setSelected(path);
    setJumpLine(line ?? null);
    setTab('code');
  }

  async function handleSend(preset) {
    const message = (typeof preset === 'string' ? preset : draft).trim();
    if (!message || !project || streaming) return;

    if (typeof preset !== 'string') setDraft('');
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

  const filePaths = project?.files?.map((f) => f.path);
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
            <AlertTriangle size={13} /> 没读到 API Key，概览可用，提问会失败。
          </p>
        )}

        {project && <FileTree files={project.files} selected={selected} onSelect={openFile} />}
      </aside>

      <main className="main-panel">
        <header className="reader-topbar">
          <div className="topbar-tabs">
            <button
              type="button"
              className={tab === 'overview' ? 'is-active' : ''}
              onClick={() => setTab('overview')}
              disabled={!project}
            >
              <LayoutList size={14} /> 项目概览
            </button>
            <button
              type="button"
              className={tab === 'code' ? 'is-active' : ''}
              onClick={() => setTab('code')}
              disabled={!project}
            >
              <FileCode2 size={14} /> {selected || '代码'}
            </button>
          </div>

          <div className="topbar-right">
            {truncated && <span className="badge">文件过多，已截断</span>}
            <button type="button" className="refresh" onClick={handleOpen} disabled={!project || opening}>
              <RefreshCw size={13} /> 重新扫描
            </button>
          </div>
        </header>

        <div className="reader-grid">
          <section className="preview">
            {tab === 'overview' ? (
              <OverviewPanel
                data={overview}
                loading={overviewLoading}
                error={overviewError}
                onOpenFile={openFile}
              />
            ) : (
              <CodeViewer
                path={selected}
                file={file}
                loading={fileLoading}
                error={fileError}
                jumpLine={jumpLine}
              />
            )}
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
              selectedFile={selected}
              files={filePaths}
              onOpenFile={openFile}
            />
          </section>
        </div>
      </main>
    </div>
  );
}
