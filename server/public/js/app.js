// XephyGuard UI v2 · interactive & backend-wired runtime

window.xgCsrf = () => document.querySelector('meta[name="csrf-token"]')?.content || '';

window.xgApi = async function (url, opts = {}) {
  const method = (opts.method || 'GET').toUpperCase();
  const headers = {
    Accept: 'application/json',
    ...(method !== 'GET' ? { 'Content-Type': 'application/json', 'X-CSRF-TOKEN': window.xgCsrf() } : {}),
    ...(opts.headers || {})
  };
  const res = await fetch(url, { credentials: 'same-origin', ...opts, method, headers });
  if (!res.ok) {
    let msg = res.statusText || ('HTTP ' + res.status);
    try { const j = await res.json(); if (j && j.message) msg = j.message; } catch (e) {}
    throw new Error(msg);
  }
  const ct = res.headers.get('content-type') || '';
  return ct.includes('application/json') ? res.json() : res.text();
};

/* ---------- Binary Screen Protocol (0x5847) & TileCanvas ---------- */
(function () {
  const TILE_SIZE = 64;
  const MAGIC = 0x5847;
  const VERSION = 1;
  const HEADER_SIZE = 28;
  const TILE_HEADER_SIZE = 10;
  const MAX_TILES = 4096;
  const MAX_PAYLOAD = 64 * 64 * 4;
  const MsgType = { Frame: 1, Cursor: 2, Ack: 3, KeyframeReq: 4, Status: 5 };
  const Flags = { KEY: 1, FULL: 2, DELTA: 4, MASKED: 8, SECURE: 16, CURSOR_F: 32 };
  const Codec = { Raw: 0, Webp: 1, Jpeg: 2 };

  class TileCanvas {
    constructor(canvas) {
      this.canvas = canvas;
      this.ctx = (canvas && typeof canvas.getContext === 'function') ? canvas.getContext('2d') : null;
      this.width = 0;
      this.height = 0;
      this.pendingTiles = [];
      this.rafId = null;
      this.banner = null;
    }
    setSize(w, h) {
      if (this.width !== w || this.height !== h) {
        this.width = w;
        this.height = h;
        if (this.canvas) { this.canvas.width = w; this.canvas.height = h; }
      }
    }
    setBanner(b) { this.banner = b; this.scheduleRender(); }
    drawTiles(tiles) {
      if (!tiles || !tiles.length) return;
      this.pendingTiles.push(...tiles);
      this.scheduleRender();
    }
    scheduleRender() {
      if (this.rafId !== null) return;
      if (typeof requestAnimationFrame === 'function') this.rafId = requestAnimationFrame(() => this.flush());
      else this.flush();
    }
    flush() {
      this.rafId = null;
      if (!this.ctx) return;
      while (this.pendingTiles.length > 0) {
        const tile = this.pendingTiles.shift();
        if (tile && tile.bitmap) {
          this.ctx.drawImage(tile.bitmap, tile.tileX * TILE_SIZE, tile.tileY * TILE_SIZE);
          if (typeof tile.bitmap.close === 'function') tile.bitmap.close();
        }
      }
      if (this.banner) {
        this.ctx.save();
        this.ctx.fillStyle = 'rgba(0, 0, 0, 0.75)';
        this.ctx.fillRect(0, 0, this.width, this.height);
        this.ctx.fillStyle = '#FFFFFF';
        this.ctx.font = 'bold 24px sans-serif';
        this.ctx.textAlign = 'center';
        this.ctx.textBaseline = 'middle';
        this.ctx.fillText(this.banner, this.width / 2, this.height / 2);
        this.ctx.restore();
      }
    }
    clear() {
      this.pendingTiles = [];
      if (this.ctx && this.width > 0 && this.height > 0) this.ctx.clearRect(0, 0, this.width, this.height);
    }
  }

  function parseMessage(input) {
    try {
      let buffer, byteOffset = 0, byteLength = 0;
      if (input instanceof ArrayBuffer) { buffer = input; byteLength = input.byteLength; }
      else if (ArrayBuffer.isView(input)) { buffer = input.buffer; byteOffset = input.byteOffset; byteLength = input.byteLength; }
      else return null;
      if (byteLength < HEADER_SIZE) return null;
      const view = new DataView(buffer, byteOffset, byteLength);
      if (view.getUint16(0, true) !== MAGIC || view.getUint8(2) !== VERSION) return null;
      const type = view.getUint8(3), flags = view.getUint16(4, true), monitorId = view.getUint16(6, true);
      const streamId = view.getUint32(8, true), seq = view.getUint32(12, true), baseSeq = view.getUint32(16, true);
      const width = view.getUint16(20, true), height = view.getUint16(22, true), tileCount = view.getUint16(24, true);
      if (tileCount > MAX_TILES) return null;
      let offset = HEADER_SIZE;
      const tiles = [];
      for (let i = 0; i < tileCount; ++i) {
        if (offset + TILE_HEADER_SIZE > byteLength) return null;
        const tileX = view.getUint16(offset, true), tileY = view.getUint16(offset + 2, true);
        const codec = view.getUint8(offset + 4), payloadLen = view.getUint32(offset + 6, true);
        if (payloadLen > MAX_PAYLOAD || offset + TILE_HEADER_SIZE + payloadLen > byteLength) return null;
        tiles.push({ tileX, tileY, codec, payload: new Uint8Array(buffer, byteOffset + offset + TILE_HEADER_SIZE, payloadLen) });
        offset += TILE_HEADER_SIZE + payloadLen;
      }
      return { type, flags, monitorId, streamId, seq, baseSeq, width, height, tiles };
    } catch (e) { return null; }
  }

  function encodeAck(streamId, monitorId, seq) {
    const buffer = new ArrayBuffer(HEADER_SIZE), view = new DataView(buffer);
    view.setUint16(0, MAGIC, true); view.setUint8(2, VERSION); view.setUint8(3, MsgType.Ack);
    view.setUint16(6, monitorId, true); view.setUint32(8, streamId, true); view.setUint32(12, seq, true);
    return buffer;
  }

  function encodeKeyframeReq(streamId, monitorId) {
    const buffer = new ArrayBuffer(HEADER_SIZE), view = new DataView(buffer);
    view.setUint16(0, MAGIC, true); view.setUint8(2, VERSION); view.setUint8(3, MsgType.KeyframeReq);
    view.setUint16(6, monitorId, true); view.setUint32(8, streamId, true);
    return buffer;
  }

  class ScreenViewer {
    constructor(canvas, options = {}) {
      this.canvas = canvas;
      this.options = options || {};
      this.tileCanvas = canvas && typeof canvas.getContext === 'function' ? new TileCanvas(canvas) : null;
      this.ws = null;
      this.lastAppliedSeq = 0;
      this.waitingForKeyframe = true;
    }
    connect(url) {
      if (this.ws) this.disconnect();
      this.waitingForKeyframe = true;
      this.ws = new WebSocket(url);
      this.ws.binaryType = 'arraybuffer';
      this.ws.onopen = () => {
        this.waitingForKeyframe = true;
        this.requestKeyframe(0, 0);
        if (this.options.onOpen) this.options.onOpen();
      };
      this.ws.onclose = () => { if (this.options.onClose) this.options.onClose(); };
      this.ws.onerror = err => { if (this.options.onError) this.options.onError(err); };
      this.ws.onmessage = async event => {
        if (typeof event.data === 'string') {
          try { const j = JSON.parse(event.data); if (this.options.onControlMessage) this.options.onControlMessage(j); } catch (e) {}
          return;
        }
        await this.handleBinaryFrame(event.data);
      };
    }
    async handleBinaryFrame(data) {
      const msg = parseMessage(data);
      if (!msg || msg.type !== MsgType.Frame || !this.tileCanvas) return;
      if (msg.flags & Flags.MASKED) this.tileCanvas.setBanner('PRIVACY MASKED');
      else if (msg.flags & Flags.SECURE) this.tileCanvas.setBanner('SECURE DESKTOP');
      else this.tileCanvas.setBanner(null);

      if ((msg.flags & Flags.KEY) !== 0 || (msg.flags & Flags.FULL) !== 0) {
        this.tileCanvas.setSize(msg.width, msg.height);
        this.lastAppliedSeq = msg.seq;
        this.waitingForKeyframe = false;
      } else if ((msg.flags & Flags.DELTA) !== 0) {
        if (this.waitingForKeyframe || msg.baseSeq !== this.lastAppliedSeq) {
          this.requestKeyframe(msg.streamId, msg.monitorId);
          this.waitingForKeyframe = true;
          return;
        }
        this.lastAppliedSeq = msg.seq;
      }

      const decodedTiles = [];
      for (const tile of msg.tiles) {
        try {
          let bitmap = null;
          if (tile.codec === Codec.Webp) bitmap = await createImageBitmap(new Blob([tile.payload], { type: 'image/webp' }));
          else if (tile.codec === Codec.Jpeg) bitmap = await createImageBitmap(new Blob([tile.payload], { type: 'image/jpeg' }));
          else if (tile.codec === Codec.Raw) {
            const tileW = Math.min(TILE_SIZE, msg.width - tile.tileX * TILE_SIZE);
            const tileH = Math.min(TILE_SIZE, msg.height - tile.tileY * TILE_SIZE);
            const rgba = new Uint8ClampedArray(tileW * tileH * 4);
            for (let p = 0; p < tileW * tileH; ++p) {
              rgba[p * 4 + 0] = tile.payload[p * 4 + 2];
              rgba[p * 4 + 1] = tile.payload[p * 4 + 1];
              rgba[p * 4 + 2] = tile.payload[p * 4 + 0];
              rgba[p * 4 + 3] = tile.payload[p * 4 + 3];
            }
            bitmap = await createImageBitmap(new ImageData(rgba, tileW, tileH));
          }
          if (bitmap) decodedTiles.push({ tileX: tile.tileX, tileY: tile.tileY, bitmap });
        } catch (e) {}
      }
      this.tileCanvas.drawTiles(decodedTiles);
      if (this.options.onFrame) this.options.onFrame(msg);
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        this.ws.send(encodeAck(msg.streamId, msg.monitorId, msg.seq));
      }
    }
    requestKeyframe(streamId, monitorId) {
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        this.ws.send(encodeKeyframeReq(streamId, monitorId));
      }
    }
    disconnect() {
      if (this.ws) { this.ws.close(); this.ws = null; }
    }
  }

  window.TileCanvas = TileCanvas;
  window.ScreenViewer = ScreenViewer;
})();

/* ---------- Synthetic student desktops (stand-in when no live agent frame is active) ---------- */
(function () {
  const rng = seed => () => { seed |= 0; seed = seed + 0x6D2B79F5 | 0; let t = Math.imul(seed ^ seed >>> 15, 1 | seed); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; };
  const rr = (x, ctx, a, b, w, h, rad, col) => { ctx.fillStyle = col; ctx.beginPath(); ctx.roundRect(a, b, w, h, rad); ctx.fill(); };
  const palette = ['#7aa2f7', '#9ece6a', '#e0af68', '#bb9af7', '#c0caf5', '#7dcfff'];

  window.xgDraw = function (c, pc, t, monitor) {
    if (!c || !pc) return;
    const ctx = c.getContext('2d'), w = c.width, h = c.height, u = w / 320;
    const r = rng((pc.id || 1) * 977 + (monitor || 0) * 131);
    const hue = ((pc.id || 1) * 53 + (monitor || 0) * 40) % 360;
    const g = ctx.createLinearGradient(0, 0, w, h);
    g.addColorStop(0, `hsl(${hue},45%,28%)`); g.addColorStop(1, `hsl(${(hue + 50) % 360},50%,18%)`);
    ctx.fillStyle = g; ctx.fillRect(0, 0, w, h);

    const down = pc.status === 'offline' || pc.kind === 'lock';
    if (!down) {
      const X = w * .05, Y = h * .07, W = w * .9, H = h * .82;
      const kind = (monitor || 0) === 1 ? 'browser' : (pc.kind || 'code');
      if (kind === 'code') {
        rr(0, ctx, X, Y, W, H, 4 * u, '#1e2128');
        rr(0, ctx, X, Y, W, 9 * u, 4 * u, '#2a2e37');
        ctx.fillStyle = '#16181d'; ctx.fillRect(X, Y + 9 * u, W * .17, H - 9 * u);
        for (let i = 0; i < 9; i++) rr(0, ctx, X + 6 * u, Y + 18 * u + i * 9 * u, W * .17 * (.4 + r() * .45), 3 * u, 1.5 * u, '#3a3f4b');
        const lines = Math.floor((H - 22 * u) / (8 * u));
        for (let k = 0; k < lines; k++) {
          const ind = Math.floor(r() * 3) * 10 * u, len = (.12 + r() * .5) * W * .7;
          const live = k === Math.floor(lines * .6);
          const L = live ? len * (.55 + .45 * Math.abs(Math.sin(t / 900))) : len;
          rr(0, ctx, X + W * .2 + ind, Y + 17 * u + k * 8 * u, L, 3.2 * u, 1.6 * u, palette[Math.floor(r() * palette.length)]);
          if (live && Math.floor(t / 500) % 2 === 0) { ctx.fillStyle = '#fff'; ctx.fillRect(X + W * .2 + ind + L + 2 * u, Y + 15.5 * u + k * 8 * u, 1.2 * u, 6 * u); }
        }
      } else if (kind === 'terminal') {
        rr(0, ctx, X + W * .08, Y + H * .06, W * .84, H * .86, 4 * u, '#0e1013');
        rr(0, ctx, X + W * .08, Y + H * .06, W * .84, 8 * u, 4 * u, '#23262d');
        const lines = Math.floor((H * .8) / (8 * u));
        for (let k = 0; k < lines; k++) { const len = (.1 + r() * .6) * W * .7; rr(0, ctx, X + W * .11, Y + H * .06 + 14 * u + k * 8 * u, k % 4 === 0 ? len * .5 : len, 3 * u, 1.5 * u, k % 4 === 0 ? '#58d68d' : '#7b8494'); }
      } else if (kind === 'chat') {
        rr(0, ctx, X, Y, W, H, 4 * u, '#14161a'); rr(0, ctx, X, Y, W, 9 * u, 4 * u, '#23262d');
        ctx.fillStyle = '#101216'; ctx.fillRect(X, Y + 9 * u, W * .14, H - 9 * u);
        for (let i = 0; i < 6; i++) rr(0, ctx, X + 5 * u, Y + 18 * u + i * 10 * u, W * .14 - 10 * u, 4 * u, 2 * u, '#2c303a');
        for (let k = 0; k < 5; k++) { const me = k % 2 === 0, bw = (.25 + r() * .3) * W * .6; rr(0, ctx, me ? X + W * .95 - bw : X + W * .2, Y + 16 * u + k * 17 * u, bw, 12 * u, 5 * u, me ? '#2b5cd6' : '#262a33'); }
        rr(0, ctx, X + W * .2, Y + H - 18 * u, W * .7, 10 * u, 5 * u, '#262a33');
        if (Math.floor(t / 600) % 2 === 0) { ctx.fillStyle = '#fff'; ctx.fillRect(X + W * .22, Y + H - 15.5 * u, 1.2 * u, 5 * u); }
      } else {
        rr(0, ctx, X, Y, W, H, 4 * u, '#f3f4f6'); rr(0, ctx, X, Y, W, 9 * u, 4 * u, '#d9dce1');
        rr(0, ctx, X + W * .14, Y + 11 * u, W * .6, 7 * u, 3.5 * u, '#fff');
        rr(0, ctx, X + 8 * u, Y + 24 * u, W * .5, 7 * u, 2 * u, '#bfc5ce');
        for (let k = 0; k < 4; k++) rr(0, ctx, X + 8 * u, Y + 36 * u + k * 9 * u, W * (.5 + r() * .35), 3 * u, 1.5 * u, '#cdd2d9');
        for (let k = 0; k < 3; k++) rr(0, ctx, X + 8 * u + k * (W * .3), Y + H - 46 * u, W * .27, 38 * u, 4 * u, '#fff');
      }
    } else {
      ctx.fillStyle = 'rgba(0,0,0,.28)'; ctx.fillRect(0, 0, w, h);
      ctx.fillStyle = 'rgba(255,255,255,.9)'; ctx.font = `600 ${22 * u}px Inter, sans-serif`; ctx.textAlign = 'center';
      if (pc.status !== 'offline') ctx.fillText('12:08', w / 2, h * .46);
      ctx.fillStyle = 'rgba(255,255,255,.5)'; ctx.font = `${8 * u}px Inter, sans-serif`;
      ctx.fillText(pc.status === 'offline' ? 'No signal' : 'Locked', w / 2, h * .46 + 14 * u);
    }
    ctx.fillStyle = 'rgba(14,16,20,.88)'; ctx.fillRect(0, h - 11 * u, w, 11 * u);
    for (let i = 0; i < 6; i++) rr(0, ctx, w * .36 + i * 9 * u, h - 8.5 * u, 6 * u, 6 * u, 1.5 * u, i === 1 ? '#5b9bff' : '#59606c');
    rr(0, ctx, w - 30 * u, h - 8 * u, 24 * u, 5 * u, 2 * u, '#59606c');
    if (!down) {
      const cx = w * (.5 + .28 * Math.sin(t / 2300 + (pc.id || 1))), cy = h * (.5 + .2 * Math.cos(t / 1900 + (pc.id || 1)));
      ctx.fillStyle = '#fff'; ctx.strokeStyle = '#000'; ctx.lineWidth = .8 * u; ctx.beginPath();
      ctx.moveTo(cx, cy); ctx.lineTo(cx, cy + 10 * u); ctx.lineTo(cx + 3 * u, cy + 7.5 * u); ctx.lineTo(cx + 7 * u, cy + 7 * u); ctx.closePath(); ctx.fill(); ctx.stroke();
    }
  };

  setInterval(() => {
    if (document.hidden || !window.XG) return;
    const pool = (window.XG_LIVE && window.XG_LIVE.pcs && window.XG_LIVE.pcs.length) ? window.XG_LIVE.pcs : XG.pcs;
    document.querySelectorAll('canvas[data-pc]').forEach(c => {
      const p = pool.find(x => x.id == c.dataset.pc) || XG.pcs.find(x => x.id == c.dataset.pc);
      if (p) xgDraw(c, p, performance.now());
    });
  }, 1000);
})();

/* ---------- Alert grouping ---------- */
window.xgGroup = function (list) {
  const rank = { critical: 4, high: 3, medium: 2, low: 1, info: 0 };
  const map = new Map();
  list.forEach(a => {
    const k = a.pcId + '|' + a.rule;
    if (!map.has(k)) map.set(k, { key: k, pcId: a.pcId, pc: a.pc, user: a.user, rule: a.rule, sev: a.sev, title: a.title, at: a.at, ago: a.ago, items: [] });
    const g = map.get(k); g.items.push(a);
    if ((rank[a.sev] || 0) > (rank[g.sev] || 0)) g.sev = a.sev;
    if (a.ago < g.ago) { g.ago = a.ago; g.at = a.at; g.title = a.title; }
  });
  const arr = [...map.values()].map(g => ({ ...g, count: g.items.length, acked: g.items.every(i => i.acked), by: (g.items.find(i => i.acked) || {}).by, note: (g.items.find(i => i.note) || {}).note }));
  return arr.sort((a, b) => (a.acked - b.acked) || ((rank[b.sev] || 0) - (rank[a.sev] || 0)) || (a.ago - b.ago));
};
window.xgAgo = m => m < 60 ? m + ' min ago' : Math.floor(m / 60) + ' h ago';

document.addEventListener('alpine:init', () => {

  /* ---------- Theme ---------- */
  const apply = mode => {
    const dark = mode === 'dark' || (mode === 'system' && matchMedia('(prefers-color-scheme: dark)').matches);
    document.documentElement.dataset.theme = dark ? 'dark' : 'light';
  };
  Alpine.store('theme', {
    mode: localStorage.getItem('xg-theme') || 'system',
    get dark() { return document.documentElement.dataset.theme === 'dark'; },
    set(m) { this.mode = m; try { localStorage.setItem('xg-theme', m); } catch (e) {} apply(m); },
    toggle() { this.set(this.dark ? 'light' : 'dark'); }
  });
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => { if (Alpine.store('theme').mode === 'system') apply('system'); });

  /* ---------- Toasts & copy ---------- */
  Alpine.store('toasts', {
    items: [],
    add(title, severity = 'info') { const id = Date.now() + Math.random(); this.items.push({ id, title, severity }); setTimeout(() => this.remove(id), 4200); },
    push(t) { this.add(t.title || '', t.severity || 'info'); },
    remove(id) { this.items = this.items.filter(t => t.id !== id); }
  });
  window.xgCopy = (text, label = 'Copied to clipboard') => {
    const done = () => Alpine.store('toasts').add(label, 'ok');
    if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(text).then(done, done);
    else { const t = document.createElement('textarea'); t.value = text; document.body.appendChild(t); t.select(); try { document.execCommand('copy'); } catch (e) {} t.remove(); done(); }
  };

  /* ---------- Command palette ---------- */
  Alpine.data('palette', () => ({
    open: false, q: '', idx: 0,
    base: [
      { g: 'Go to', t: 'Live lab', icon: 'live', href: 'index.html', k: 'Alt+1' },
      { g: 'Go to', t: 'Alerts', icon: 'bell', href: 'alerts.html', k: 'Alt+2' },
      { g: 'Go to', t: 'Sessions', icon: 'clock', href: 'sessions.html', k: 'Alt+3' },
      { g: 'Go to', t: 'Timetable and profiles', icon: 'calendar', href: 'profiles.html', k: 'Alt+4' },
      { g: 'Go to', t: 'Roster', icon: 'users', href: 'roster.html', k: 'Alt+5' },
      { g: 'Go to', t: 'Blocklists and rules', icon: 'shield', href: 'signatures.html', k: 'Alt+6' },
      { g: 'Go to', t: 'Reports', icon: 'report', href: 'reports.html', k: 'Alt+7' },
      { g: 'Go to', t: 'Add a PC', icon: 'addpc', href: 'enroll.html', k: 'Alt+8' },
      { g: 'Go to', t: 'Health', icon: 'pulse', href: 'admin-health.html', k: 'Alt+9' },
      { g: 'Go to', t: 'Settings', icon: 'sliders', href: 'admin-settings.html' },
      { g: 'Go to', t: 'Staff accounts', icon: 'badge', href: 'admin-users.html' },
      { g: 'Go to', t: 'Audit log', icon: 'list', href: 'admin-audit.html' },
      { g: 'Go to', t: 'Shared clipboard', icon: 'clipboard', href: 'share.html' },
      { g: 'Go to', t: 'Downloads', icon: 'download', href: 'downloads.html' },
      { g: 'Actions', t: 'Open the screen wall', icon: 'grid', href: 'index.html#wall' },
      { g: 'Actions', t: 'Start a session', icon: 'plus', href: 'sessions.html#start' },
      { g: 'Actions', t: 'Switch theme', icon: 'sun', run: () => Alpine.store('theme').toggle() }
    ],
    get items() {
      const pool = (window.XG_LIVE && window.XG_LIVE.pcs && window.XG_LIVE.pcs.length) ? window.XG_LIVE.pcs : (window.XG ? XG.pcs : []);
      const pcs = pool.map(p => ({ g: 'PCs', t: p.name, icon: 'live', href: 'index.html#pc=' + p.id, k: p.user }));
      const q = this.q.trim().toLowerCase();
      const all = this.base.concat(pcs);
      return q ? all.filter(i => (i.t + ' ' + (i.k || '')).toLowerCase().includes(q)).slice(0, 12) : this.base.slice(0, 8);
    },
    show() { this.open = true; this.q = ''; this.idx = 0; this.$nextTick(() => this.$refs.q && this.$refs.q.focus()); },
    go(i) { const it = this.items[i]; if (!it) return; this.open = false; if (it.run) it.run(); else location.href = it.href; },
    move(d) { const n = this.items.length; this.idx = (this.idx + d + n) % n; }
  }));

  /* ---------- Live lab ---------- */
  Alpine.data('labView', () => ({
    view: 'map',
    cols: (window.XG_LIVE && window.XG_LIVE.cols) || 6,
    rows: (window.XG_LIVE && window.XG_LIVE.rows) || 3,
    editing: false, dragId: null, dropKey: null,
    pcs: (window.XG_LIVE && window.XG_LIVE.pcs && window.XG_LIVE.pcs.length) ? structuredClone(window.XG_LIVE.pcs) : structuredClone(XG.pcs),
    alerts: (window.XG_LIVE && window.XG_LIVE.alerts && window.XG_LIVE.alerts.length) ? structuredClone(window.XG_LIVE.alerts) : structuredClone(XG.alerts),
    serverDetails: {},
    activePcId: null, inspector: false, tab: 'screen', screenMode: 'snapshot', monitor: 0, snapT: 4200, snapAt: '12:07:41',
    screenStreaming: false, screenHasFrame: false, screenStatus: '', screenAuditId: null, screenViewer: null, screenRenewTimer: null,
    tile: 240, flagged: false, blur: false, pinned: [1], dock: { att: true, props: true, list: true }, pcFilter: 'all',
    messageModal: false, messageTarget: null, messageText: '', showDone: false, closeModal: false, closeName: '', closePid: null,

    init() {
      if (this.pcs.length && !this.pcs.some(p => p.id === 1)) {
        this.pinned = [this.pcs[0].id];
      }
      const h = location.hash;
      if (h.includes('wall')) this.view = 'wall';
      const m = h.match(/pc=(\d+)/); if (m) this.select(+m[1]);
      this._timer = setInterval(() => {
        if (document.hidden || !this.inspector || this.tab !== 'screen' || !this.$refs.live) return;
        if (!this.screenHasFrame) {
          xgDraw(this.$refs.live, this.active, this.screenMode === 'live' ? performance.now() : this.snapT, this.monitor);
        }
      }, 110);
      this.$watch('inspector', v => {
        if (v) {
          this.$nextTick(() => this.paintLive());
          if (this.activePcId) this.fetchDetail(this.activePcId);
        } else {
          this.stopScreen();
        }
      });
      this.$watch('tab', t => {
        this.$nextTick(() => this.paintLive());
        if (t !== 'screen' && this.screenStreaming) this.stopScreen();
      });
      this.$watch('monitor', () => this.paintLive());
    },
    paintLive() {
      if (this.$refs.live && !this.screenHasFrame) {
        xgDraw(this.$refs.live, this.active, this.screenMode === 'live' ? performance.now() : this.snapT, this.monitor);
      }
    },

    async fetchDetail(id) {
      try {
        const d = await window.xgApi(`/pcs/${id}`);
        if (!d || !d.pc) return;
        const base = XG.detail(this.active);
        const mapped = {
          events: (d.timeline && d.timeline.length)
            ? d.timeline.map(e => ({ time: e.at, sev: e.type === 'rule_hit' || e.type === 'tamper' ? 'high' : 'info', label: e.summary }))
            : base.events,
          processes: (d.running_processes && d.running_processes.length)
            ? d.running_processes.map(p => ({ pid: p.pid || 0, name: p.exe || p.name || 'process', title: p.title || p.cmdline || '', cpu: Number(p.cpu || 0), mem: Math.round(Number(p.rss_mb || p.mem || 0)), net: Number(p.net_mbps || 0), threat: p.rule_id || '' }))
            : ((d.processes && d.processes.length)
              ? d.processes.map(p => ({ pid: p.pid || 0, name: p.exe || 'process', title: p.type || '', cpu: 0, mem: 0, net: 0, threat: p.rule || '' }))
              : base.processes),
          aiTraffic: (d.ai_traffic && d.ai_traffic.length)
            ? d.ai_traffic.map(r => ({ service: r.description || r.rule_id, host: r.domain || r.remote_ip, proc: r.process || 'browser', count: 1, last: r.at, mode: 'Observed' }))
            : base.aiTraffic,
          tabs: (d.browser_tabs && d.browser_tabs.length)
            ? d.browser_tabs.map(t => ({ browser: t.app || 'Browser', title: t.title || t.app, host: t.ai_site || t.user || '', ai: !!t.ai_site }))
            : base.tabs,
          extensions: (d.extensions && d.extensions.length)
            ? d.extensions.map(e => ({ browser: e.browser || 'Browser', name: e.name || e.id, id: e.id || '' }))
            : base.extensions,
          artifacts: (d.artifacts && d.artifacts.length)
            ? d.artifacts.map(a => ({ kind: a.kind || 'File', path: a.path || '', note: a.rule_id || 'Local AI file' }))
            : base.artifacts,
          adapters: (d.adapters && d.adapters.length)
            ? d.adapters.map(a => ({ name: a.name || 'adapter', type: (a.description || a.kind || (a.wireless ? 'Wi-Fi' : 'Ethernet')) + (a.default_route ? ' · default route' : ''), ip: (a.addresses || [])[0] || '', mac: a.driver || '' }))
            : base.adapters,
          ports: (d.listening_ports && d.listening_ports.length)
            ? d.listening_ports.map(p => ({ port: p.port, proto: 'TCP', proc: (p.process || 'unknown') + (p.pid ? ` (PID ${p.pid})` : ''), pid: p.pid || null, exe: p.process || '', rule: p.rule_id || 'Local AI port' }))
            : base.ports,
          devices: (d.devices && d.devices.length)
            ? d.devices.map(dv => ({ vidpid: (dv.vendor && dv.product) ? `${dv.vendor}:${dv.product}` : (dv.class || 'USB'), name: dv.model || dv.action || 'USB device', time: dv.at }))
            : base.devices,
          netEvents: d.network || [],
          keyrate: (d.keyrate && d.keyrate.series && d.keyrate.series.length)
            ? d.keyrate.series.map(s => s.keys || 0)
            : base.keyrate,
          pastes: (d.pastes && d.pastes.length)
            ? d.pastes.map(p => ({ time: p.occurred_at, chars: p.chars, lines: p.lines, from: p.source_app || '?', to: p.target_app || '?', code: !!p.looks_like_code }))
            : base.pastes,
        };
        this.serverDetails[id] = mapped;
      } catch (e) {}
    },

    /* derived */
    get active() { return this.pcs.find(p => p.id === this.activePcId) || {}; },
    get det() { return this.activePcId ? (this.serverDetails[this.activePcId] || XG.detail(this.active)) : null; },
    get counts() { const c = { ok: 0, idle: 0, watch: 0, alert: 0, off: 0 }; this.pcs.filter(p => p.seat).forEach(p => c[this.kind(p)]++); return c; },
    get total() { return this.pcs.filter(p => p.seat).length; },
    get online() { return this.pcs.filter(p => p.seat && p.status !== 'offline').length; },
    get groups() { return xgGroup(this.alerts.filter(a => !a.acked)); },
    get doneGroups() { return xgGroup(this.alerts.filter(a => a.acked)); },
    get half() { return Math.floor(this.cols / 2); },
    get gridStyle() { const h = this.half; return `grid-template-columns: repeat(${h}, minmax(0,1fr)) 18px repeat(${this.cols - h}, minmax(0,1fr))`; },
    get cells() {
      const out = [];
      for (let y = 0; y < this.rows; y++) for (let x = 0; x < this.cols; x++)
        out.push({ key: x + ':' + y, x, y, pc: this.pcs.find(p => p.seat && p.seat.x === x && p.seat.y === y) || null, col: x + 1 + (x >= this.half ? 1 : 0) });
      return out;
    },
    get unplaced() { return this.pcs.filter(p => !p.seat); },
    get listed() { return this.pcs.filter(p => p.seat && (this.pcFilter === 'all' || !['ok', 'idle'].includes(this.kind(p)))); },
    get wallPcs() { return this.pcs.filter(p => p.seat && !this.pinned.includes(p.id) && (!this.flagged || !['ok', 'idle'].includes(this.kind(p)))); },
    get pinnedPcs() { return this.pinned.map(id => this.pcs.find(p => p.id === id)).filter(Boolean); },
    get screenOk() { return !!(this.active.caps && this.active.caps.snapshot && this.active.status !== 'offline'); },
    get pcAlerts() { return this.alerts.filter(a => a.pcId === this.activePcId); },
    get tabs() {
      const d = this.det; if (!d) return [];
      return [['screen', 'Screen', 'monitor', ''], ['timeline', 'Timeline', 'clock', ''], ['alerts', 'Alerts', 'bell', this.pcAlerts.length || ''],
        ['programs', 'Programs', 'terminal', d.processes.length], ['browser', 'Browser', 'globe', d.aiTraffic.length || ''],
        ['installed', 'Installed AI', 'shield', (d.extensions.length + d.artifacts.length) || ''], ['network', 'Network', 'wifi', ''],
        ['typing', 'Typing', 'keyboard', ''], ['pastes', 'Pastes', 'clipboard', d.pastes.length || '']];
    },
    pct(n) { return Math.max(0, n / Math.max(1, this.total) * 100); },
    kind(p) { if (p.isolated || p.status === 'alert') return 'alert'; return ({ active: 'ok', clean: 'ok', idle: 'idle', warning: 'watch', offline: 'off' })[p.status] || 'ok'; },
    seatClass(p) { if (!p) return 'empty'; const k = p.isolated ? 'iso' : this.kind(p); return 's-' + k + (this.editing ? ' editing' : ''); },
    tileClass(p) { const k = p.isolated ? 'iso' : this.kind(p); return { alert: 't-alert', watch: 't-watch', iso: 't-iso', off: 't-off' }[k] || ''; },
    dotOf(p) { if (p.isolated) return 'iso'; return ({ ok: 'ok', idle: '', watch: 'watch', alert: 'alert', off: 'off' })[this.kind(p)] || ''; },
    scoreClass(p) { return typeof p.score !== 'number' ? '' : (p.score < 70 ? 'low' : (p.score < 95 ? 'mid' : '')); },
    ringColor(p) { return typeof p.score !== 'number' ? 'var(--off)' : (p.score < 70 ? 'var(--alert)' : (p.score < 95 ? 'var(--watch)' : 'var(--ok)')); },
    statusText(p) { return p.isolated ? 'Isolated' : ({ active: 'Online', clean: 'Online', idle: 'Not in use', warning: 'Needs a look', alert: 'Alert', offline: 'Offline' })[p.status]; },
    pc(id) { return this.pcs.find(p => p.id === id) || XG.pcs.find(p => p.id === id); },

    /* selection / inspector */
    select(id) { if (this.editing) return; this.activePcId = id; this.fetchDetail(id); },
    openInspector(id, tab) { if (this.editing) return; this.activePcId = id; this.tab = tab || 'screen'; this.screenMode = 'snapshot'; this.monitor = 0; this.inspector = true; this.fetchDetail(id); },
    closeInspector() { this.stopScreen(); this.inspector = false; },
    clear() { this.stopScreen(); this.inspector = false; this.messageModal = false; this.closeModal = false; },

    async toggleIsolate(pc) {
      if (!pc || !pc.id) return;
      const next = !pc.isolated;
      pc.isolated = next;
      try {
        await window.xgApi(`/pcs/${pc.id}/isolate`, { method: 'POST', body: JSON.stringify({ isolated: next, reason: 'dashboard' }) });
      } catch (e) {}
      Alpine.store('toasts').add(pc.isolated ? `${pc.name} is cut off from the lab network.` : `${pc.name} is back on the network.`, pc.isolated ? 'alert' : 'ok');
    },
    async rescan(pcOrKind, kindArg) {
      const targetPc = (typeof pcOrKind === 'object' && pcOrKind) ? pcOrKind : this.active;
      const kind = (typeof pcOrKind === 'string') ? pcOrKind : (kindArg || 'all');
      if (!targetPc || !targetPc.id) return;
      Alpine.store('toasts').add(`Rescanning ${targetPc.name} (${kind})…`, 'info');
      try {
        await window.xgApi(`/pcs/${targetPc.id}/rescan`, { method: 'POST', body: JSON.stringify({ kind }) });
        setTimeout(() => this.fetchDetail(targetPc.id), 800);
      } catch (e) {}
    },
    promptCloseProgram(name = '', pid = null) {
      this.closeName = name;
      this.closePid = pid;
      this.closeModal = true;
    },
    async closeProgram() {
      const exe = (this.closeName || '').trim();
      if (!exe && !this.closePid) return;
      const target = this.active;
      this.closeModal = false;
      try {
        if (target && target.id) {
          await window.xgApi(`/pcs/${target.id}/kill`, { method: 'POST', body: JSON.stringify({ exe: exe || null, pid: this.closePid || null }) });
        }
      } catch (e) {}
      Alpine.store('toasts').add(`Asked ${target.name} to close ${exe || ('PID ' + this.closePid)}.`, 'watch');
      this.closeName = '';
      this.closePid = null;
    },
    async startScreenStream(mode = 'live') {
      const pcId = this.activePcId;
      if (!pcId) return;
      this.screenMode = mode;
      await this.stopScreen();
      this.screenStreaming = true;
      try {
        const data = await window.xgApi(`/api/screen/pc/${pcId}/token`, { method: 'POST', body: JSON.stringify({ mode }) });
        this.screenAuditId = data.audit_id;
        let gwUrl = String(data.gateway_url || '').trim();
        const wsProto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        if (!gwUrl) gwUrl = `${wsProto}//${window.location.host}/screen-gw`;
        else if (gwUrl.startsWith('/')) gwUrl = `${wsProto}//${window.location.host}${gwUrl.replace(/\/$/, '')}`;
        const wsUrl = `${gwUrl.replace(/\/$/, '')}/view?token=${data.token}`;
        const canvas = this.$refs.live;
        if (canvas && window.ScreenViewer) {
          this.screenViewer = new window.ScreenViewer(canvas, {
            onFrame: () => { this.screenHasFrame = true; },
            onClose: () => { this.screenStreaming = false; }
          });
          this.screenViewer.connect(wsUrl);
          if (mode === 'live' && this.screenAuditId) {
            this.screenRenewTimer = setInterval(() => {
              if (this.screenAuditId && this.screenStreaming) {
                window.xgApi(`/api/screen/${this.screenAuditId}/renew`, { method: 'POST' }).catch(() => {});
              }
            }, 20000);
          }
        }
      } catch (e) {
        this.screenStreaming = false;
      }
    },
    async stopScreen() {
      if (this.screenRenewTimer) { clearInterval(this.screenRenewTimer); this.screenRenewTimer = null; }
      if (this.screenViewer) { this.screenViewer.disconnect(); this.screenViewer = null; }
      if (this.screenAuditId) {
        const aid = this.screenAuditId;
        this.screenAuditId = null;
        window.xgApi(`/api/screen/${aid}/stop`, { method: 'POST' }).catch(() => {});
      }
      this.screenStreaming = false;
      this.screenHasFrame = false;
    },
    snapshot() {
      this.snapT = performance.now();
      this.snapAt = new Date().toTimeString().slice(0, 8);
      this.screenMode = 'snapshot';
      this.startScreenStream('snapshot');
      this.paintLive();
      Alpine.store('toasts').add('Snapshot taken.', 'ok');
    },
    goLive() {
      this.screenMode = 'live';
      this.startScreenStream('live');
    },
    evidence() { Alpine.store('toasts').add('Snapshot saved to the PC’s alert as evidence.', 'ok'); },

    /* wall */
    togglePin(id) { const i = this.pinned.indexOf(id); if (i >= 0) this.pinned.splice(i, 1); else if (this.pinned.length < 4) this.pinned.push(id); else Alpine.store('toasts').add('You can pin up to 4 PCs.', 'watch'); },
    tileSize(s) { this.tile = s; },

    /* messages & alerts */
    message(id) { this.messageTarget = id ? this.pcs.find(p => p.id === id) : null; this.messageText = ''; this.messageModal = true; },
    async sendMessage() {
      const txt = this.messageText.trim();
      if (!txt) return;
      const target = this.messageTarget;
      this.messageModal = false;
      this.messageText = '';
      try {
        await window.xgApi('/sessions/message', { method: 'POST', body: JSON.stringify({ text: txt, pc_ids: target ? [target.id] : [] }) });
      } catch (e) {}
      Alpine.store('toasts').add(`Message sent to ${target ? target.name : 'every student screen'}.`, 'ok');
    },
    async ackGroup(g) {
      g.items.forEach(a => {
        const x = this.alerts.find(y => y.id === a.id);
        if (x) { x.acked = true; x.by = 'KUET admin'; }
        window.xgApi(`/alerts/${a.id}/ack`, { method: 'POST', body: JSON.stringify({}) }).catch(() => {});
      });
      Alpine.store('toasts').add(`${g.pc}: ${g.count > 1 ? g.count + ' alerts' : 'alert'} marked as reviewed.`, 'ok');
    },

    /* seat map editing */
    startDrag(pc) { if (this.editing) this.dragId = pc.id; },
    dropOn(cell) {
      this.dropKey = null; const mv = this.pcs.find(p => p.id === this.dragId); this.dragId = null; if (!mv) return;
      const other = cell.pc, from = mv.seat; if (other && other.id === mv.id) return;
      if (other) other.seat = from ? { ...from } : null; mv.seat = { x: cell.x, y: cell.y };
    },
    dropShelf() { const mv = this.pcs.find(p => p.id === this.dragId); this.dragId = null; this.dropKey = null; if (mv) mv.seat = null; },
    async saveLayout() {
      this.editing = false;
      const tiles = this.pcs.filter(p => p.seat).map(p => ({ pc_id: p.id, x: p.seat.x, y: p.seat.y }));
      try {
        await window.xgApi('/lab/layout', { method: 'POST', body: JSON.stringify({ cols: this.cols, rows: this.rows, tiles }) });
      } catch (e) {}
      Alpine.store('toasts').add('Seat map saved.', 'ok');
    }
  }));
});

/* ---------- Shortcuts ---------- */
document.addEventListener('keydown', e => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); window.dispatchEvent(new CustomEvent('xg-palette')); return; }
  if (!e.altKey || e.ctrlKey || e.metaKey) return;
  const map = { 1: 'index', 2: 'alerts', 3: 'sessions', 4: 'profiles', 5: 'roster', 6: 'signatures', 7: 'reports', 8: 'enroll', 9: 'admin-health' };
  const code = e.code && e.code.startsWith('Digit') ? e.code.slice(5) : e.key;
  if (map[code]) { e.preventDefault(); location.href = map[code] + '.html'; }
});
