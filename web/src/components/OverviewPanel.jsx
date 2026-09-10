import { ArrowRight, Boxes, FileCode2, Layers, Loader2, PlayCircle, Route } from 'lucide-react';

/**
 * What the project is made of, computed on the server without a model call.
 * Every row is clickable and opens that file in the code view.
 */
export default function OverviewPanel({ data, loading, error, onOpenFile }) {
  if (loading) {
    return (
      <p className="loading">
        <Loader2 size={14} className="spin" /> 正在分析项目结构…
      </p>
    );
  }
  if (error) return <p className="error-text ov-pad">分析失败：{error}</p>;
  if (!data) return <p className="empty">打开一个项目后这里会显示结构概览。</p>;

  const { languages, totals, entry_points: entries, core_modules: core, reading_route: route } = data;

  return (
    <div className="overview-panel">
      <section className="ov-block">
        <div className="ov-totals">
          <div>
            <span>文件</span>
            <strong>{totals.files}</strong>
          </div>
          <div>
            <span>代码行</span>
            <strong>{totals.lines.toLocaleString()}</strong>
          </div>
          <div>
            <span>函数/类</span>
            <strong>{totals.definitions}</strong>
          </div>
        </div>

        <div className="lang-bar" role="img" aria-label="语言构成">
          {languages.map((l) => (
            <div
              key={l.language}
              className="lang-seg"
              style={{ width: `${l.percent}%` }}
              title={`${l.language} ${l.percent}% · ${l.files} 个文件`}
            />
          ))}
        </div>
        <div className="lang-legend">
          {languages.slice(0, 5).map((l) => (
            <span key={l.language}>
              <i /> {l.language} {l.percent}%
            </span>
          ))}
        </div>
      </section>

      <Group icon={<Route size={14} />} title="推荐阅读顺序" hint="按依赖结构推导，不是模型猜的">
        <ol className="route-steps">
          {route.map((step, i) => (
            <li key={step.path}>
              <button type="button" onClick={() => onOpenFile(step.path)}>
                <span className="step-no">{i + 1}</span>
                <span className="step-body">
                  <code>{step.path}</code>
                  <em>{step.why}</em>
                  {step.summary && <small>{step.summary}</small>}
                </span>
                <ArrowRight size={13} />
              </button>
            </li>
          ))}
        </ol>
      </Group>

      <Group icon={<PlayCircle size={14} />} title="入口文件" hint="程序从这些地方开始执行">
        <ModuleList rows={entries} onOpenFile={onOpenFile} />
      </Group>

      <Group icon={<Layers size={14} />} title="核心模块" hint="被其他模块依赖最多，改动它影响面最大">
        <ModuleList rows={core} onOpenFile={onOpenFile} showDeps />
      </Group>

      {data.largest?.length > 0 && (
        <Group icon={<Boxes size={14} />} title="最大的文件" hint="通常也是最难读的">
          <ModuleList rows={data.largest} onOpenFile={onOpenFile} />
        </Group>
      )}

      {data.orphans?.length > 0 && (
        <Group icon={<FileCode2 size={14} />} title="孤立文件" hint="不导入别人，也没人导入，可以最后再看">
          <ul className="orphan-list">
            {data.orphans.map((p) => (
              <li key={p}>
                <button type="button" onClick={() => onOpenFile(p)}>
                  <code>{p}</code>
                </button>
              </li>
            ))}
          </ul>
        </Group>
      )}
    </div>
  );
}

function Group({ icon, title, hint, children }) {
  return (
    <section className="ov-block">
      <h3>
        {icon}
        {title}
        <small>{hint}</small>
      </h3>
      {children}
    </section>
  );
}

function ModuleList({ rows, onOpenFile, showDeps = false }) {
  if (!rows?.length) return <p className="empty ov-pad">没有识别到。</p>;
  return (
    <ul className="module-list">
      {rows.map((row) => (
        <li key={row.path}>
          <button type="button" onClick={() => onOpenFile(row.path)}>
            <code>{row.path}</code>
            <span className="mod-meta">
              {showDeps && <b>{row.imported_by} 处依赖</b>}
              {row.lines} 行
              {row.definitions > 0 && ` · ${row.definitions} 个定义`}
            </span>
            {row.summary && <em>{row.summary}</em>}
          </button>
        </li>
      ))}
    </ul>
  );
}
