// REST + WebSocket client.

async function req(method, url, body) {
  const opts = { method, headers: {} };
  if (body instanceof FormData) opts.body = body;
  else if (body !== undefined) { opts.headers['content-type'] = 'application/json'; opts.body = JSON.stringify(body); }
  const r = await fetch(url, opts);
  const ct = r.headers.get('content-type') || '';
  const data = ct.includes('json') ? await r.json() : await r.text();
  if (!r.ok) throw new Error((data && data.detail) ? (typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)) : `${r.status} ${r.statusText}`);
  return data;
}

export const api = {
  get: (u) => req('GET', u),
  post: (u, b = {}) => req('POST', u, b),
  put: (u, b) => req('PUT', u, b),
  del: (u) => req('DELETE', u),
};

// zlib-compressed base64 -> Uint8Array
export async function inflate(b64) {
  const bin = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
  const ds = new DecompressionStream('deflate');
  const buf = await new Response(new Blob([bin]).stream().pipeThrough(ds)).arrayBuffer();
  return new Uint8Array(buf);
}

export class Live {
  constructor(handlers) {
    this.h = handlers;
    this.open();
  }
  open() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    this.ws = new WebSocket(`${proto}://${location.host}/api/ws`);
    this.ws.onmessage = (ev) => {
      const m = JSON.parse(ev.data);
      const f = this.h[m.type];
      if (f) f(m);
    };
    this.ws.onclose = () => {
      this.h.disconnected && this.h.disconnected();
      setTimeout(() => this.open(), 1500);
    };
    this.ws.onopen = () => this.h.connected && this.h.connected();
  }
}
