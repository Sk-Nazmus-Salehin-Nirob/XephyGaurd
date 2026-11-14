// XephyGuard UI v2 · interactive preview logic (static demo, no backend)

/* ---------- Synthetic student desktops (stand-in for real screen frames) ---------- */
(function () {
  const rng = seed => () => { seed |= 0; seed = seed + 0x6D2B79F5 | 0; let t = Math.imul(seed ^ seed >>> 15, 1 | seed); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; };
  const rr = (x, ctx, a, b, w, h, rad, col) => { ctx.fillStyle = col; ctx.beginPath(); ctx.roundRect(a, b, w, h, rad); ctx.fill(); };
  const palette = ['#7aa2f7', '#9ece6a', '#e0af68', '#bb9af7', '#c0caf5', '#7dcfff'];

  window.xgDraw = function (c, pc, t, monitor) {
    if (!c || !pc) return;
    const ctx = c.getContext('2d'), w = c.width, h = c.height, u = w / 320;
    const r = rng(pc.id * 977 + (monitor || 0) * 131);
    const hue = (pc.id * 53 + (monitor || 0) * 40) % 360;
    // wallpaper
    const g = ctx.createLinearGradient(0, 0, w, h);
    g.addColorStop(0, `hsl(${hue},45%,28%)`); g.addColorStop(1, `hsl(${(hue + 50) % 360},50%,18%)`);
    ctx.fillStyle = g; ctx.fillRect(0, 0, w, h);

    const down = pc.status === 'offline' || pc.kind === 'lock';
    if (!down) {
      const X = w * .05, Y = h * .07, W = w * .9, H = h * .82;
      const kind = (monitor || 0) === 1 ? 'browser' : pc.kind;
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
      } else { // browser
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
    // taskbar
    ctx.fillStyle = 'rgba(14,16,20,.88)'; ctx.fillRect(0, h - 11 * u, w, 11 * u);
    for (let i = 0; i < 6; i++) rr(0, ctx, w * .36 + i * 9 * u, h - 8.5 * u, 6 * u, 6 * u, 1.5 * u, i === 1 ? '#5b9bff' : '#59606c');
    rr(0, ctx, w - 30 * u, h - 8 * u, 24 * u, 5 * u, 2 * u, '#59606c');
    // cursor
    if (!down) {
      const cx = w * (.5 + .28 * Math.sin(t / 2300 + pc.id)), cy = h * (.5 + .2 * Math.cos(t / 1900 + pc.id));
      ctx.fillStyle = '#fff'; ctx.strokeStyle = '#000'; ctx.lineWidth = .8 * u; ctx.beginPath();
      ctx.moveTo(cx, cy); ctx.lineTo(cx, cy + 10 * u); ctx.lineTo(cx + 3 * u, cy + 7.5 * u); ctx.lineTo(cx + 7 * u, cy + 7 * u); ctx.closePath(); ctx.fill(); ctx.stroke();
    }
  };

  // keep wall thumbnails moving (1 fps keeps CPU low, like the real thumbnails would)
  setInterval(() => {
    if (document.hidden || !window.XG) return;
    document.querySelectorAll('canvas[data-pc]').forEach(c => {
      const p = XG.pcs.find(x => x.id == c.dataset.pc); xgDraw(c, p, performance.now());
    });
  }, 1000);
})();

/* ---------- Alert grouping (repeats of the same rule on one PC collapse into one row) ---------- */
window.xgGroup = function (list) {
  const rank = { critical: 4, high: 3, medium: 2, low: 1, info: 0 };
  const map = new Map();
  list.forEach(a => {
    const k = a.pcId + '|' + a.rule;
    if (!map.has(k)) map.set(k, { key: k, pcId: a.pcId, pc: a.pc, user: a.user, rule: a.rule, sev: a.sev, title: a.title, at: a.at, ago: a.ago, items: [] });
    const g = map.get(k); g.items.push(a);
    if (rank[a.sev] > rank[g.sev]) g.sev = a.sev;
    if (a.ago < g.ago) { g.ago = a.ago; g.at = a.at; g.title = a.title; }
  });
  const arr = [...map.values()].map(g => ({ ...g, count: g.items.length, acked: g.items.every(i => i.acked), by: (g.items.find(i => i.acked) || {}).by, note: (g.items.find(i => i.note) || {}).note }));
  return arr.sort((a, b) => (a.acked - b.acked) || (rank[b.sev] - rank[a.sev]) || (a.ago - b.ago));
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
      const pcs = (window.XG ? XG.pcs : []).map(p => ({ g: 'PCs', t: p.name, icon: 'live', href: 'index.html#pc=' + p.id, k: p.user }));
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
    view: 'map', cols: 6, rows: 3, editing: false, dragId: null, dropKey: null,
    pcs: structuredClone(XG.pcs), alerts: structuredClone(XG.alerts),
    activePcId: null, inspector: false, tab: 'screen', screenMode: 'snapshot', monitor: 0, snapT: 4200, snapAt: '12:07:41',
    tile: 240, flagged: false, blur: false, pinned: [1], dock: { att: true, props: true, list: true }, pcFilter: 'all',
    messageModal: false, messageTarget: null, messageText: '', showDone: false, closeModal: false, closeName: '',

    init() {
      const h = location.hash;
      if (h.includes('wall')) this.view = 'wall';
      const m = h.match(/pc=(\d+)/); if (m) this.activePcId = +m[1];
      this._timer = setInterval(() => {
        if (document.hidden || !this.inspector || this.tab !== 'screen' || !this.$refs.live) return;
        xgDraw(this.$refs.live, this.active, this.screenMode === 'live' ? performance.now() : this.snapT, this.monitor);
      }, 110);
      this.$watch('inspector', v => v && this.$nextTick(() => this.paintLive()));
      this.$watch('tab', () => this.$nextTick(() => this.paintLive()));
      this.$watch('monitor', () => this.paintLive());
    },
    paintLive() { if (this.$refs.live) xgDraw(this.$refs.live, this.active, this.screenMode === 'live' ? performance.now() : this.snapT, this.monitor); },

    /* derived */
    get active() { return this.pcs.find(p => p.id === this.activePcId) || {}; },
    get det() { return this.activePcId ? XG.detail(this.active) : null; },
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
    kind(p) { if (p.isolated || p.status === 'alert') return 'alert'; return ({ active: 'ok', idle: 'idle', warning: 'watch', offline: 'off' })[p.status] || 'ok'; },
    seatClass(p) { if (!p) return 'empty'; const k = p.isolated ? 'iso' : this.kind(p); return 's-' + k + (this.editing ? ' editing' : ''); },
    tileClass(p) { const k = p.isolated ? 'iso' : this.kind(p); return { alert: 't-alert', watch: 't-watch', iso: 't-iso', off: 't-off' }[k] || ''; },
    dotOf(p) { if (p.isolated) return 'iso'; return ({ ok: 'ok', idle: '', watch: 'watch', alert: 'alert', off: 'off' })[this.kind(p)] || ''; },
    scoreClass(p) { return typeof p.score !== 'number' ? '' : (p.score < 70 ? 'low' : (p.score < 95 ? 'mid' : '')); },
    ringColor(p) { return typeof p.score !== 'number' ? 'var(--off)' : (p.score < 70 ? 'var(--alert)' : (p.score < 95 ? 'var(--watch)' : 'var(--ok)')); },
    statusText(p) { return p.isolated ? 'Isolated' : ({ active: 'Online', idle: 'Not in use', warning: 'Needs a look', alert: 'Alert', offline: 'Offline' })[p.status]; },
    pc(id) { return XG.pcs.find(p => p.id === id); },

    /* selection / inspector */
    select(id) { if (this.editing) return; this.activePcId = id; },
    openInspector(id, tab) { if (this.editing) return; this.activePcId = id; this.tab = tab || 'screen'; this.screenMode = 'snapshot'; this.monitor = 0; this.inspector = true; },
    closeInspector() { this.inspector = false; },
    clear() { this.inspector = false; this.messageModal = false; this.closeModal = false; },
    toggleIsolate(pc) { pc.isolated = !pc.isolated; Alpine.store('toasts').add(pc.isolated ? `${pc.name} is cut off from the lab network.` : `${pc.name} is back on the network.`, pc.isolated ? 'alert' : 'ok'); },
    rescan(pc) { Alpine.store('toasts').add(`Rescanning ${pc.name}…`, 'info'); },
    closeProgram() { if (!this.closeName.trim()) return; Alpine.store('toasts').add(`Asked ${this.active.name} to close ${this.closeName}.`, 'watch'); this.closeModal = false; this.closeName = ''; },
    snapshot() { this.snapT = performance.now(); this.snapAt = new Date().toTimeString().slice(0, 8); this.screenMode = 'snapshot'; this.paintLive(); Alpine.store('toasts').add('Snapshot taken.', 'ok'); },
    goLive() { this.screenMode = 'live'; },
    evidence() { Alpine.store('toasts').add('Snapshot saved to the PC’s alert as evidence.', 'ok'); },

    /* wall */
    togglePin(id) { const i = this.pinned.indexOf(id); if (i >= 0) this.pinned.splice(i, 1); else if (this.pinned.length < 4) this.pinned.push(id); else Alpine.store('toasts').add('You can pin up to 4 PCs.', 'watch'); },
    tileSize(s) { this.tile = s; },

    /* messages & alerts */
    message(id) { this.messageTarget = id ? this.pcs.find(p => p.id === id) : null; this.messageText = ''; this.messageModal = true; },
    sendMessage() { if (!this.messageText.trim()) return; Alpine.store('toasts').add(`Message sent to ${this.messageTarget ? this.messageTarget.name : 'every student screen'}.`, 'ok'); this.messageModal = false; this.messageText = ''; },
    ackGroup(g) { g.items.forEach(a => { const x = this.alerts.find(y => y.id === a.id); if (x) { x.acked = true; x.by = 'KUET admin'; } }); Alpine.store('toasts').add(`${g.pc}: ${g.count > 1 ? g.count + ' alerts' : 'alert'} marked as reviewed.`, 'ok'); },

    /* seat map editing */
    startDrag(pc) { if (this.editing) this.dragId = pc.id; },
    dropOn(cell) {
      this.dropKey = null; const mv = this.pcs.find(p => p.id === this.dragId); this.dragId = null; if (!mv) return;
      const other = cell.pc, from = mv.seat; if (other && other.id === mv.id) return;
      if (other) other.seat = from ? { ...from } : null; mv.seat = { x: cell.x, y: cell.y };
    },
    dropShelf() { const mv = this.pcs.find(p => p.id === this.dragId); this.dragId = null; this.dropKey = null; if (mv) mv.seat = null; },
    saveLayout() { this.editing = false; Alpine.store('toasts').add('Seat map saved.', 'ok'); }
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
