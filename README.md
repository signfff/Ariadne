# CoreCoder

A minimal, read-first AI agent for **understanding codebases**.

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
export CORECODER_MODEL=deepseek-chat

# Ollama (local, no key needed)
export OPENAI_API_KEY=ollama OPENAI_BASE_URL=http://localhost:11434/v1
export CORECODER_MODEL=qwen2.5-coder
```

Claude Code style variables (`ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_BASE_URL`,
`ANTHROPIC_MODEL`) are also accepted.

| Variable | Default | Meaning |
|---|---|---|
| `CORECODER_API_KEY` / `OPENAI_API_KEY` | — | API key |
| `OPENAI_BASE_URL` | provider default | API endpoint |
| `CORECODER_MODEL` | `gpt-5.5` | Model name |
| `CORECODER_MAX_CONTEXT` | `128000` | Context budget before compression kicks in |
| `CORECODER_PROVIDER` | `openai` | Set to `litellm` for non-OpenAI-compatible providers |

## Use

Terminal:

```bash
corecoder                                    # interactive REPL
corecoder --profile learn                    # read-only, explain-this-project mode
corecoder -p "这个项目的入口在哪，主流程怎么走的"   # one-shot
corecoder -r <session-id>                    # resume a saved session
```

API server (FastAPI, streams over SSE):

```bash
pip install -e ".[server]"
python -m uvicorn server.main:app --reload    # http://127.0.0.1:8000
```

Interactive API docs at `http://127.0.0.1:8000/docs`.

Legacy browser UI (stdlib server, no streaming — being replaced by the React client):

```bash
corecoder-web        # then open http://127.0.0.1:8765
```

## Profiles

| Profile | Tools | For |
|---|---|---|
| `learn` | read / glob / grep | Explaining a project to someone picking it up |
| `ask` | read / glob / grep | Q&A about architecture and implementation |
| `review` | read / glob / grep | Finding bugs, risks, and missing tests |
| `full` | + write / edit / bash / sub-agent | When you also want it to change things |

The three read-only profiles answer in Chinese by default and cite the files they read.

## How it works

```
corecoder/
├── agent.py      # the loop: LLM → tool calls → execute → feed back → repeat
├── llm.py        # OpenAI-compatible + LiteLLM backends, streaming, retry, cost
├── context.py    # 3-layer compression: snip tool output → summarize → collapse
├── profiles.py   # named tool sets + behavior instructions
├── session.py    # save/resume conversations under ~/.corecoder/sessions
├── prompt.py     # system prompt
├── cli.py        # terminal REPL
├── web.py        # legacy stdlib server (superseded by server/)
└── tools/        # bash, read_file, write_file, edit_file, glob, grep, agent

server/
├── main.py         # FastAPI app
├── agent_stream.py # blocking agent loop -> SSE event stream
├── projects.py     # project scanning and file reads
└── schemas.py      # Pydantic request/response models
```

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
pip install -e ".[dev]"
pytest tests/ -q
ruff check corecoder tests
```

## License

MIT
