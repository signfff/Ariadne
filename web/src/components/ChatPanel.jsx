import { useEffect, useRef } from 'react';
import { Bot, Loader2, Send, Square, User } from 'lucide-react';
import ToolTimeline from './ToolTimeline.jsx';

const PROFILES = [
  { id: 'learn', label: '教学导读' },
  { id: 'ask', label: '项目问答' },
  { id: 'review', label: '代码审查' },
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
}) {
  const endRef = useRef(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages, streaming]);

  return (
    <div className="chat-panel">
      <div className="chat-log">
        {messages.length === 0 && (
          <p className="empty">
            打开一个项目后提问，比如「这个项目的入口在哪，主流程怎么走」。
          </p>
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
            >
              {p.label}
            </button>
          ))}
        </div>

        <div className="ask-row">
          <input
            value={draft}
            onChange={(e) => onDraftChange(e.target.value)}
            placeholder={disabled ? '先打开一个项目' : '问点什么…'}
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
