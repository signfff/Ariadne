// API client.
//
// The browser's EventSource only speaks GET, but /api/chat is a POST carrying
// a JSON body, so the stream is read with fetch + ReadableStream and the SSE
// frames are parsed here by hand.

const JSON_HEADERS = { 'Content-Type': 'application/json' };

async function post(path, body, signal) {
  const res = await fetch(path, {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail || `${res.status} ${res.statusText}`);
  }
  return res.json();
}

export const getHealth = () => fetch('/api/health').then((r) => r.json());
export const openProject = (path) => post('/api/project', { path });
export const readFile = (path, file) => post('/api/file', { path, file });
export const getOverview = (path) => post('/api/overview', { path });

/**
 * Split an SSE frame into its event name and parsed payload.
 * Returns null for heartbeats and frames with no data line.
 */
function parseFrame(frame) {
  let type = 'message';
  const dataLines = [];

  for (const line of frame.split('\n')) {
    if (line.startsWith(':')) continue; // comment / keep-alive
    if (line.startsWith('event:')) type = line.slice(6).trim();
    else if (line.startsWith('data:')) dataLines.push(line.slice(5).replace(/^ /, ''));
  }

  if (dataLines.length === 0) return null;
  const raw = dataLines.join('\n');
  try {
    return { type, data: JSON.parse(raw) };
  } catch {
    return { type, data: { raw } };
  }
}

/**
 * POST to /api/chat and yield each server-sent event as it arrives.
 *
 * Frames are separated by a blank line, and a chunk can split one anywhere,
 * so partial text is buffered until a full frame is available.
 */
export async function* streamChat(body, signal) {
  const res = await fetch('/api/chat', {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify(body),
    signal,
  });

  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail || `${res.status} ${res.statusText}`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      // normalise CRLF so a frame boundary is always exactly '\n\n', including
      // when a \r and its \n land in different chunks
      buffer = (buffer + decoder.decode(value, { stream: true })).replace(/\r\n/g, '\n');

      let split;
      while ((split = buffer.indexOf('\n\n')) !== -1) {
        const event = parseFrame(buffer.slice(0, split));
        buffer = buffer.slice(split + 2);
        if (event) yield event;
      }
    }

    const tail = parseFrame(buffer);
    if (tail) yield tail;
  } finally {
    reader.cancel().catch(() => {});
  }
}
