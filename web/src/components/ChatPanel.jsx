import { useEffect, useRef } from 'react';
import { Bot, Loader2, Send, Square, User } from 'lucide-react';
import ToolTimeline from './ToolTimeline.jsx';

/**
 * Each profile carries the questions it is actually for. On their own the
 * profiles only swap a system prompt, which is invisible - pairing them with
 * concrete openers is what makes the difference show.
 */
const PROFILES = [
  {
    id: 'learn',
    label: '教学导读',
    blurb: '第一次接触这个项目',
    actions: [
      { label: '项目导读', prompt: '请给我一份这个项目的导读：它解决什么问题、整体architecture怎么划分、主执行流程是怎么走的。引用你看过的文件。' },
      { label: '分阶段路线', prompt: '请给一份分阶段的源码阅读路线：5 分钟速览、30 分钟主线、2 小时深入。每一步说明读哪个文件、为什么读、读完应该理解什么。' },
      { label: '核心概念', prompt: '请提炼这个项目的核心概念词典。每个概念给出：通俗解释、涉及哪些文件、为什么重要、读代码时怎么识别它。' },
      { label: '讲解当前文件', prompt: '请讲解我正在看的这个文件：它在项目里处于什么位置、依赖谁、谁调用它、主要的类和函数各做什么、阅读时该抓住哪几条线。不要逐行翻译。', needsFile: true },
    ],
  },
  {
    id: 'ask',
    label: '项目问答',
    blurb: '带着具体问题来找答案',
    actions: [
      { label: '数据怎么流动', prompt: '一次完整的请求或调用，数据是怎么在这个项目里流动的？从入口到出口，经过哪些模块，每一步做了什么转换？' },
      { label: '配置从哪来', prompt: '这个项目的配置是怎么加载的？有哪些环境变量和配置文件，优先级是什么，默认值在哪里定义？' },
      { label: '错误怎么处理', prompt: '这个项目的错误处理策略是什么？异常在哪里被捕获，怎么向上传播，最终怎么呈现给用户？' },
    ],
  },
  {
    id: 'review',
    label: '代码审查',
    blurb: '找问题和风险',
    actions: [
      { label: '整体风险', prompt: '请审查这个项目，按严重程度列出问题：bug、行为回归、安全风险、边界条件、错误处理缺口。每条给出文件路径和行号。' },
      { label: '测试缺口', prompt: '这个项目的测试覆盖了什么、漏掉了什么？哪些关键路径没有测试？请给出具体的文件和函数。' },
      { label: '审查当前文件', prompt: '请审查我正在看的这个文件，找出其中的 bug、边界条件问题和可以简化的地方。', needsFile: true },
    ],
  },
];

export default function ChatPanel({
  messages,
  streaming,
  profile,
  onProfileChange,
  draft,
  onDraftChange,
  onSend,
  onStop,
  disabled,
  selectedFile,
}) {
  const endRef = useRef(null);
  const active = PROFILES.find((p) => p.id === profile) ?? PROFILES[0];

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages, streaming]);

  function runAction(action) {
    const suffix = action.needsFile && selectedFile ? `\n\n当前文件：${selectedFile}` : '';
    onSend(action.prompt + suffix);
  }

  return (
    <div className="chat-panel">
      <div className="chat-log">
        {messages.length === 0 && (
          <div className="chat-intro">
            <p className="empty">
              {disabled ? '先在左侧打开一个项目。' : `当前模式：${active.label} · ${active.blurb}`}
            </p>
            {!disabled && (
              <div className="starter-grid">
                {active.actions.map((a) => (
                  <button
                    key={a.label}
                    type="button"
                    onClick={() => runAction(a)}
                    disabled={a.needsFile && !selectedFile}
                    title={a.needsFile && !selectedFile ? '先在左侧选一个文件' : a.prompt}
                  >
                    {a.label}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        {messages.map((msg, i) => (
          <div key={i} className={`bubble is-${msg.role}`}>
            <div className="bubble-icon">{msg.role === 'user' ? <User size={14} /> : <Bot size={14} />}</div>
            <div className="bubble-body">
              {msg.role === 'assistant' && <ToolTimeline tools={msg.tools || []} />}
              {msg.text && <div className="bubble-text">{msg.text}</div>}
              {msg.error && <div className="error-text">{msg.error}</div>}
              {msg.usage && (
                <div className="usage">
                  {msg.usage.total_tokens} tokens
                  {msg.usage.cost_usd != null && ` · $${msg.usage.cost_usd.toFixed(4)}`}
                </div>
              )}
              {msg.role === 'assistant' && !msg.text && !msg.error && streaming && i === messages.length - 1 && (
                <span className="cursor" />
              )}
            </div>
          </div>
        ))}
        <div ref={endRef} />
      </div>

      <form
        className="ask-box"
        onSubmit={(e) => {
          e.preventDefault();
          onSend();
        }}
      >
        <div className="profile-tabs">
          {PROFILES.map((p) => (
            <button
              key={p.id}
              type="button"
              className={profile === p.id ? 'is-active' : ''}
              onClick={() => onProfileChange(p.id)}
              disabled={streaming}
              title={p.blurb}
            >
              {p.label}
            </button>
          ))}
        </div>

        {messages.length > 0 && !streaming && (
          <div className="starter-row">
            {active.actions.map((a) => (
              <button
                key={a.label}
                type="button"
                onClick={() => runAction(a)}
                disabled={disabled || (a.needsFile && !selectedFile)}
              >
                {a.label}
              </button>
            ))}
          </div>
        )}

        <div className="ask-row">
          <input
            value={draft}
            onChange={(e) => onDraftChange(e.target.value)}
            placeholder={disabled ? '先打开一个项目' : `以「${active.label}」提问…`}
            disabled={disabled || streaming}
            aria-label="提问"
          />
          {streaming ? (
            <button type="button" className="stop" onClick={onStop} title="停止">
              <Square size={14} /> 停止
            </button>
          ) : (
            <button type="submit" disabled={disabled || !draft.trim()}>
              <Send size={14} /> 发送
            </button>
          )}
        </div>
      </form>

      {streaming && (
        <p className="stream-hint">
          <Loader2 size={12} className="spin" /> agent 正在读代码…
        </p>
      )}
    </div>
  );
}
