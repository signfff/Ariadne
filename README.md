# Ariadne

> A thread through an unfamiliar codebase.

Developed on top of [CoreCoder](https://github.com/he-yufeng/CoreCoder) (MIT),
whose minimal agent loop is the engine underneath. Ariadne builds it out into a
full-stack tool for reading code: a FastAPI backend that streams a run over SSE,
a React client that shows each tool call as the agent makes it, semantic search
over a locally built index, and a structural overview of any project computed
without a model call.

Point it at a project and ask questions. It reads files, searches, and explains —
in read-only modes it cannot write, edit, or run commands, so it is safe to aim at
code you do not want touched.

Works with any OpenAI-compatible LLM (OpenAI, DeepSeek, Qwen, Kimi, GLM, Ollama…),
or 100+ providers through LiteLLM.

## Install

```bash
pip install -e .
```

## Configure

Set an API key via env vars or a `.env` file:

```bash
# OpenAI
export OPENAI_API_KEY=sk-...

# DeepSeek
export OPENAI_API_KEY=sk-... OPENAI_BASE_URL=https://api.deepseek.com
export ARIADNE_MODEL=deepseek-chat

# Ollama (local, no key needed)
export OPENAI_API_KEY=ollama OPENAI_BASE_URL=http://localhost:11434/v1
export ARIADNE_MODEL=qwen2.5-coder
```

Claude Code style variables (`ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_BASE_URL`,
`ANTHROPIC_MODEL`) are also accepted.

| Variable | Default | Meaning |
|---|---|---|
| `ARIADNE_API_KEY` / `OPENAI_API_KEY` | — | API key |
| `OPENAI_BASE_URL` | provider default | API endpoint |
| `ARIADNE_MODEL` | `gpt-5.5` | Model name |
| `ARIADNE_MAX_CONTEXT` | `128000` | Context budget before compression kicks in |
| `ARIADNE_PROVIDER` | `openai` | Set to `litellm` for non-OpenAI-compatible providers |
| `ARIADNE_PRICING` | — | Token rates for models the built-in table does not know, e.g. `model-a:0.55,2.19; model-b:0.1,0.4` (USD per million in,out) |

## Use

Terminal:

```bash
ariadne                                    # interactive REPL
ariadne --profile learn                    # read-only, explain-this-project mode
ariadne -p "这个项目的入口在哪，主流程怎么走的"   # one-shot
ariadne -r <session-id>                    # resume a saved session
```

Browser — build once, then one command serves the API and the UI on one port:

```bash
pip install -e ".[server]"
cd web && npm install && npm run build && cd ..
ariadne-server                  # http://127.0.0.1:8000
```

Interactive API docs at `http://127.0.0.1:8000/docs`.

Developing the client instead? Run Vite for hot reload — it proxies `/api` back
to the server, so the browser still sees a single origin:

```bash
ariadne-server                  # terminal 1
cd web && npm run dev             # terminal 2 -> http://127.0.0.1:5173
```

## Semantic search

`grep` answers "where does this string appear". The index answers "where is the
code that does X" - the question you actually have in an unfamiliar repo.

```bash
pip install -e ".[rag]"
ariadne-index            # index the current folder
ariadne-index --rebuild  # start over
```

Indexing runs **entirely on your machine** - a small ONNX embedding model on the
CPU. No API key, no per-token cost, and your chat provider's quota is untouched.
The index is one SQLite file under `.ariadne_index/`, and re-running only
re-embeds files whose contents changed.

The model weights download from HuggingFace on first use. If that is blocked:

```bash
export HF_ENDPOINT=https://hf-mirror.com
export HF_HUB_DISABLE_XET=1
```

Retrieval fuses two arms with Reciprocal Rank Fusion: dense vectors find the
concept, SQLite FTS5 BM25 pins the exact identifier. The agent reaches it
through the `search_code` tool, which every read-only profile has.

| Variable | Default | Meaning |
|---|---|---|
| `ARIADNE_EMBED_MODEL` | `BAAI/bge-small-zh-v1.5` | Embedding model |
| `HF_ENDPOINT` | HuggingFace | Mirror for weight downloads |

## Project overview

Opening a project first shows a structural read of it, computed from the files
alone - no model call, so it is instant, free, and works before a key is set:

- what it is written in, and how much of each
- where execution starts, including console scripts declared in `pyproject.toml`
- **which modules everything else is built on**, ranked by how many other files
  import them - a better guide to what matters than size or commit count
- a **reading route** derived from that graph: docs, then config, then entry
  points, then the load-bearing modules, each with the reason it is there
- files nothing imports and that import nothing, which can wait

Every row opens that file. Because the route comes from the import graph rather
than the model, it cannot cite a file that does not exist.

## Profiles

| Profile | Tools | For |
|---|---|---|
| `learn` | read / glob / grep / search_code | Explaining a project to someone picking it up |
| `ask` | read / glob / grep / search_code | Q&A about architecture and implementation |
| `review` | read / glob / grep / search_code | Finding bugs, risks, and missing tests |
| `full` | + write / edit / bash / sub-agent | When you also want it to change things |

The three read-only profiles answer in Chinese by default and cite the files
they read. Each one carries its own openers - reading route, concept glossary,
explain this file, review this file - so the difference between them is visible
rather than buried in a system prompt.

## How it works

```
ariadne/
├── agent.py      # the loop: LLM → tool calls → execute → feed back → repeat
├── llm.py        # OpenAI-compatible + LiteLLM backends, streaming, retry, cost
├── context.py    # 3-layer compression: snip tool output → summarize → collapse
├── profiles.py   # named tool sets + behavior instructions
├── session.py    # save/resume conversations under ~/.ariadne/sessions
├── prompt.py     # system prompt
├── cli.py        # terminal REPL
├── web.py        # legacy stdlib server (superseded by server/)
├── index_cli.py  # `ariadne-index`
├── rag/
│   ├── chunker.py  # split by AST, embed a prose card rather than raw source
│   ├── embedder.py # local ONNX embeddings
│   ├── store.py    # SQLite chunks + vectors + FTS5
│   └── indexer.py  # incremental build, RRF fusion
└── tools/        # bash, read, write, edit, glob, grep, search_code, agent

server/
├── main.py         # FastAPI app
├── agent_stream.py # blocking agent loop -> SSE event stream
├── projects.py     # project scanning and file reads
└── schemas.py      # Pydantic request/response models

web/
├── src/api.js      # fetch + ReadableStream SSE client
├── src/App.jsx     # project, file viewer, and chat state
└── src/components/ # FileTree, CodeViewer, ChatPanel, ToolTimeline
```

The browser's `EventSource` only issues GET requests, but `/api/chat` is a POST
carrying a JSON body, so `web/src/api.js` reads the response with
`fetch` + `ReadableStream` and parses the SSE frames itself.

`Agent.chat()` is the whole thing: ask the model, run whatever tools it asks for,
append the results, ask again — until it replies with plain text.

## Web API

| Endpoint | Purpose |
|---|---|
| `GET /api/config`, `GET /api/health` | Metadata, cwd, supported profiles |
| `POST /api/open` | Scan a project folder, return file metadata |
| `POST /api/file` | Read one project-relative text file |
| `POST /api/analyze` | Run the agent in `learn` / `ask` / `review` mode |
| `POST /api/pick-folder` | Native folder picker, when available |

## Develop

```bash
pip install -e ".[dev]"     # pulls in the server and rag extras too
pytest tests/ -q
ruff check ariadne_code server tests
```

## License

MIT
