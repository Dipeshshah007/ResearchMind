/* ResearchMind dashboard — vanilla JS, no build step. */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const state = { filters: null, feedTimer: null, paperId: null };

/* ---------- helpers ---------- */
async function api(path, opts = {}) {
  const o = { headers: {}, ...opts };
  if (o.body && !(o.body instanceof FormData)) { o.headers['Content-Type'] = 'application/json'; o.body = JSON.stringify(o.body); }
  const r = await fetch('/api' + path, o);
  if (!r.ok) { let m = r.statusText; try { m = (await r.json()).detail || m; } catch {} throw new Error(m); }
  return (r.headers.get('content-type') || '').includes('json') ? r.json() : r.text();
}
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const md = t => DOMPurify.sanitize(marked.parse(t || ''));
function toast(msg, bad = false) {
  const t = $('#toast'); t.textContent = msg; t.className = `fixed bottom-5 right-5 z-50 px-4 py-2 rounded-lg text-sm text-white shadow-lg ${bad ? 'bg-red-600' : 'bg-slate-900'}`;
  clearTimeout(t._h); t._h = setTimeout(() => t.classList.add('hidden'), 3500);
}
function fill(sel, items, anyLabel) {
  const el = typeof sel === 'string' ? $(sel) : sel; if (!el) return;
  el.innerHTML = (anyLabel !== undefined ? `<option value="">${esc(anyLabel)}</option>` : '') +
    items.map(i => typeof i === 'object' ? `<option value="${esc(i.value)}">${esc(i.label)}</option>` : `<option value="${esc(i)}">${esc(i)}</option>`).join('');
}
async function busy(btn, fn) {
  const label = btn.textContent; btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Working…';
  try { return await fn(); } catch (e) { toast(e.message, true); } finally { btn.disabled = false; btn.textContent = label; }
}
const num = v => (v ? parseInt(v, 10) : null);
const val = id => $(id).value || null;

/* ---------- navigation ---------- */
function show(view) {
  $$('.view').forEach(v => v.classList.toggle('hidden', v.id !== 'view-' + view));
  $$('[data-view]').forEach(b => b.classList.toggle('active', b.dataset.view === view));
  clearInterval(state.feedTimer);
  if (view === 'feed') { loadFeed(); state.feedTimer = setInterval(loadFeed, 60000); }
  if (view === 'library') loadLibrary();
  if (view === 'ask') loadAskList();
  location.hash = view;
}
$$('[data-view]').forEach(b => b.addEventListener('click', () => show(b.dataset.view)));

/* ---------- paper card ---------- */
function paperCard(p, { save = true } = {}) {
  const authors = Array.isArray(p.authors) ? p.authors.join(', ') : p.authors;
  const d = document.createElement('div'); d.className = 'card p-4';
  d.innerHTML = `
    <div class="flex items-start justify-between gap-3">
      <a href="${esc(p.url)}" target="_blank" rel="noopener" class="font-semibold text-slate-900 hover:text-brand-600 leading-snug">${esc(p.title)}</a>
      ${p.citations ? `<span class="text-xs text-slate-500 shrink-0">★ ${p.citations}</span>` : ''}
    </div>
    <div class="flex flex-wrap gap-1.5 mt-2 items-center">
      <span class="chip ${esc(p.venue_type)}">${esc(p.venue_type)}</span>
      ${p.year ? `<span class="chip">${p.year}</span>` : ''}
      <span class="chip">${esc(p.venue)}</span>
      <span class="chip">${esc(p.source)}</span>
    </div>
    ${authors ? `<div class="text-xs text-slate-500 mt-2">${esc(authors)}</div>` : ''}
    <p class="text-sm text-slate-600 mt-2 clamp3">${esc(p.abstract || 'No abstract available.')}</p>
    <div class="flex gap-2 mt-3">
      ${save ? '<button class="btn-ghost save">＋ Save to library</button>' : ''}
      ${p.pdf_url ? `<a class="btn-ghost" target="_blank" rel="noopener" href="${esc(p.pdf_url)}">PDF</a>` : ''}
    </div>`;
  const sb = $('.save', d);
  if (sb) sb.onclick = () => busy(sb, async () => {
    await api('/papers', { method: 'POST', body: {
      title: p.title, authors: Array.isArray(p.authors) ? p.authors.join(', ') : p.authors, year: p.year, venue: p.venue,
      venue_type: p.venue_type, abstract: p.abstract, url: p.url, source: 'search' } });
    toast('Saved to library'); sb.textContent = '✓ Saved'; sb.disabled = true;
  });
  return d;
}
const warns = (id, w) => { $(id).innerHTML = (w || []).map(x => `<div class="text-xs bg-amber-50 text-amber-800 border border-amber-200 rounded-lg px-3 py-1.5 mb-1">⚠ ${esc(x)}</div>`).join(''); };

/* ---------- discover ---------- */
$('#d-go').onclick = () => busy($('#d-go'), async () => {
  const q = $('#d-query').value.trim(); if (!q) return toast('Enter a search query', true);
  const r = await api('/search', { method: 'POST', body: {
    query: q, source: $('#d-source').value, venue_type: val('#d-vtype'), venue: val('#d-venue'), sort: $('#d-sort').value,
    year_from: num($('#d-yfrom').value), year_to: num($('#d-yto').value), limit: num($('#d-limit').value) } });
  warns('#d-warn', r.warnings);
  const box = $('#d-results'); box.innerHTML = '';
  if (!r.results.length) box.innerHTML = '<div class="text-slate-500 text-sm">No results. Try broader keywords or relax filters.</div>';
  r.results.forEach(p => box.appendChild(paperCard(p)));
});
$('#d-query').addEventListener('keydown', e => { if (e.key === 'Enter') $('#d-go').click(); });

/* ---------- live feed ---------- */
async function loadFeed() {
  try {
    const r = await api(`/feed?category=${$('#f-cat').value}&venue_type=${encodeURIComponent($('#f-vtype').value)}`);
    warns('#f-warn', r.warnings);
    const box = $('#f-results'); box.innerHTML = '';
    r.items.forEach(p => box.appendChild(paperCard(p)));
    if (!r.items.length) box.innerHTML = '<div class="text-slate-500 text-sm">Nothing to show right now.</div>';
    $('#f-updated').textContent = 'Updated ' + new Date().toLocaleTimeString() + ' · server cache ' + r.ttl + 's';
  } catch (e) { toast(e.message, true); }
}
$('#f-refresh').onclick = loadFeed; $('#f-cat').onchange = loadFeed; $('#f-vtype').onchange = loadFeed;

/* ---------- agent ---------- */
$('#a-go').onclick = () => busy($('#a-go'), async () => {
  const goal = $('#a-goal').value.trim(); if (!goal) return toast('Describe your research goal', true);
  $('#a-out').innerHTML = '<div class="card p-5 text-sm text-slate-600"><span class="spinner"></span> Agent is planning, searching, reading and verifying… this can take 20–60 seconds.</div>';
  const r = await api('/agent/run', { method: 'POST', body: {
    goal, source: $('#a-source').value, venue_type: val('#a-vtype'), year_from: num($('#a-yfrom').value),
    year_to: num($('#a-yto').value), depth: num($('#a-depth').value) } });
  const out = $('#a-out');
  out.innerHTML = `
    <div class="grid lg:grid-cols-3 gap-4">
      <div class="card p-5 lg:col-span-1"><div class="font-semibold mb-3">Agent trace</div>
        ${r.trace.map(s => `<div class="step"><div class="text-sm font-medium">${esc(s.agent)} <span class="text-xs text-slate-400">+${s.t}s</span></div>
          <div class="text-xs text-slate-600">${esc(s.action)}</div>${s.detail ? `<div class="text-xs text-slate-400 mt-0.5">${esc(s.detail)}</div>` : ''}</div>`).join('')}
      </div>
      <div class="card p-5 lg:col-span-2"><div class="flex justify-between items-center"><div class="font-semibold">Literature brief</div>
        <button id="a-save" class="btn-ghost">＋ Save to library</button></div>
        <div class="md mt-2 text-sm">${md(r.report)}</div></div>
    </div>
    <div class="font-semibold mt-6 mb-2">References</div><div id="a-refs" class="space-y-3"></div>`;
  r.papers.forEach((p, i) => { const c = paperCard(p); c.insertAdjacentHTML('afterbegin', `<div class="text-xs font-bold text-brand-600 mb-1">[${i + 1}]</div>`); $('#a-refs').appendChild(c); });
  $('#a-save').onclick = () => busy($('#a-save'), async () => {
    await api('/papers', { method: 'POST', body: { title: 'Agent brief: ' + goal.slice(0, 80), venue: 'ResearchMind Agent',
      venue_type: 'Article', year: new Date().getFullYear(), content: r.report, abstract: r.report.slice(0, 500), source: 'agent-report' } });
    toast('Saved — open it in Library to edit');
  });
});

/* ---------- library ---------- */
async function loadLibrary() {
  const qs = new URLSearchParams();
  for (const [key, value] of Object.entries({
    q: $('#l-q').value,
    year: $('#l-year').value,
    venue_type: $('#l-vtype').value,
    source: $('#l-source').value,
  })) {
    if (value) qs.set(key, value);
  }
  const rows = await api('/papers?' + qs);
  const box = $('#l-list');
  if (!rows.length) { box.innerHTML = '<div class="p-6 text-sm text-slate-500">Your library is empty. Drop a PDF above or save papers from Discover.</div>'; return; }
  box.innerHTML = rows.map(p => `
    <div class="p-4 flex items-center justify-between gap-3 hover:bg-slate-50">
      <div class="min-w-0"><div class="font-medium truncate">${esc(p.title)}</div>
        <div class="flex gap-1.5 mt-1 flex-wrap"><span class="chip ${esc(p.venue_type)}">${esc(p.venue_type)}</span>
        ${p.year ? `<span class="chip">${p.year}</span>` : ''}${p.venue ? `<span class="chip">${esc(p.venue)}</span>` : ''}
        <span class="chip">${esc(p.source)}</span><span class="text-xs text-slate-400 ml-1">${(p.content_len || 0).toLocaleString()} chars</span></div></div>
      <button class="btn-ghost shrink-0" data-open="${p.id}">Open</button>
    </div>`).join('');
  $$('[data-open]', box).forEach(b => b.onclick = () => openEditor(+b.dataset.open));
}
['l-q', 'l-year', 'l-vtype', 'l-source'].forEach(id => $('#' + id).addEventListener(id === 'l-q' ? 'input' : 'change', () => { clearTimeout(loadLibrary._t); loadLibrary._t = setTimeout(loadLibrary, 250); }));

/* upload (drag & drop) */
const dz = $('#dropzone'), fi = $('#file-input');
$('#browse').onclick = () => fi.click();
fi.onchange = () => uploadFiles(fi.files);
['dragenter', 'dragover'].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.add('over'); }));
['dragleave', 'drop'].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.remove('over'); }));
dz.addEventListener('drop', e => uploadFiles(e.dataTransfer.files));
async function uploadFiles(files) {
  const st = $('#upload-status');
  for (const f of files) {
    if (!f.name.toLowerCase().endsWith('.pdf')) { toast(`${f.name}: only PDFs`, true); continue; }
    st.innerHTML = `<span class="spinner"></span> Ingesting ${esc(f.name)} (extract → detect metadata → index)…`;
    const fd = new FormData(); fd.append('file', f);
    try { const p = await api('/papers/upload', { method: 'POST', body: fd }); toast('Ingested: ' + p.title.slice(0, 60)); }
    catch (e) { toast(f.name + ': ' + e.message, true); }
  }
  st.textContent = ''; fi.value = ''; loadLibrary();
}

/* ---------- editor ---------- */
async function openEditor(id) {
  const p = await api('/papers/' + id); state.paperId = id;
  $('#e-title').value = p.title; $('#e-authors').value = p.authors; $('#e-venue').value = p.venue;
  $('#e-year').value = p.year || ''; $('#e-vtype').value = p.venue_type; $('#e-abstract').value = p.abstract;
  $('#e-notes').value = p.notes; $('#e-content').value = p.content;
  $('#e-review-out').innerHTML = ''; $('#e-edit-out').innerHTML = ''; $('#e-versions').innerHTML = '';
  $('#editor').classList.remove('hidden');
}
const closeEditor = () => { $('#editor').classList.add('hidden'); loadLibrary(); };
$('#e-close').onclick = closeEditor;
$('#e-save').onclick = () => busy($('#e-save'), async () => {
  await api('/papers/' + state.paperId, { method: 'PUT', body: {
    title: $('#e-title').value, authors: $('#e-authors').value, venue: $('#e-venue').value, year: num($('#e-year').value),
    venue_type: $('#e-vtype').value, abstract: $('#e-abstract').value, notes: $('#e-notes').value, content: $('#e-content').value } });
  toast('Saved (previous text kept in Versions)');
});
$('#e-delete').onclick = async () => { if (!confirm('Delete this paper permanently?')) return; await api('/papers/' + state.paperId, { method: 'DELETE' }); closeEditor(); toast('Deleted'); };
$('#e-export').onclick = () => { window.location = `/api/papers/${state.paperId}/export`; };

$$('.tab').forEach(t => t.onclick = () => {
  $$('.tab').forEach(x => x.classList.toggle('tab-on', x === t));
  $$('.tabp').forEach(p => p.classList.toggle('hidden', p.id !== 'tab-' + t.dataset.tab));
  if (t.dataset.tab === 'versions') loadVersions();
});

$('#e-review').onclick = () => busy($('#e-review'), async () => {
  const r = await api(`/papers/${state.paperId}/review`, { method: 'POST' });
  const list = a => (a || []).length ? `<ul class="list-disc pl-5 text-sm space-y-1">${a.map(x => `<li>${esc(x)}</li>`).join('')}</ul>` : '<div class="text-sm text-slate-400">—</div>';
  const score = (n, v) => v ? `<div class="card px-3 py-2 text-center"><div class="text-lg font-bold text-brand-600">${esc(v)}/10</div><div class="text-xs text-slate-500">${n}</div></div>` : '';
  $('#e-review-out').innerHTML = `
    ${r.recommendation ? `<div class="mb-3"><span class="chip">Recommendation</span> <b class="ml-1">${esc(r.recommendation)}</b></div>` : ''}
    <div class="grid grid-cols-3 gap-2 mb-3">${score('Novelty', r.novelty)}${score('Rigor', r.rigor)}${score('Clarity', r.clarity)}</div>
    <div class="text-sm md">${md(r.summary)}</div>
    <div class="font-semibold mt-3 mb-1 text-sm">Strengths</div>${list(r.strengths)}
    <div class="font-semibold mt-3 mb-1 text-sm">Weaknesses</div>${list(r.weaknesses)}
    <div class="font-semibold mt-3 mb-1 text-sm">Suggestions</div>${list(r.suggestions)}`;
});
$('#e-summ').onclick = () => busy($('#e-summ'), async () => {
  const r = await api(`/papers/${state.paperId}/summarize`, { method: 'POST' });
  $('#e-review-out').innerHTML = `<div class="md text-sm">${md(r.summary)}</div>`;
});
$('#e-preset').onchange = e => { if (e.target.value) $('#e-instr').value = e.target.value; };
$('#e-aiedit').onclick = () => busy($('#e-aiedit'), async () => {
  const ta = $('#e-content'); const s = ta.selectionStart, e = ta.selectionEnd; const sel = s !== e ? ta.value.slice(s, e) : '';
  const instr = $('#e-instr').value.trim(); if (!instr) return toast('Write an instruction first', true);
  const r = await api(`/papers/${state.paperId}/ai-edit`, { method: 'POST', body: { instruction: instr, selection: sel || null } });
  $('#e-edit-out').innerHTML = `<div class="text-xs text-slate-500 mb-1">Scope: ${r.scope === 'selection' ? 'selected text' : 'whole document (truncated to model limit)'}</div>
    <textarea id="e-revised" rows="12" class="input text-xs font-mono">${esc(r.revised)}</textarea>
    <button id="e-apply" class="btn-primary mt-2">Apply to editor</button>`;
  $('#e-apply').onclick = () => {
    const rev = $('#e-revised').value;
    ta.value = sel ? ta.value.slice(0, s) + rev + ta.value.slice(e) : rev;
    toast('Applied — click “Save changes” to keep it');
  };
});
async function loadVersions() {
  const v = await api(`/papers/${state.paperId}/versions`);
  $('#e-versions').innerHTML = v.length ? v.map(x => `<div class="card p-3 mb-2 text-sm flex justify-between items-center">
      <div><div class="font-medium">${esc(x.label)}</div><div class="text-xs text-slate-500">${esc(x.saved_at)} · ${x.content.length.toLocaleString()} chars</div></div>
      <button class="btn-ghost" data-restore="${x.id}">Restore</button></div>`).join('') : '<div class="text-sm text-slate-500">No earlier versions yet.</div>';
  $$('[data-restore]').forEach(b => b.onclick = () => { $('#e-content').value = v.find(x => x.id == b.dataset.restore).content; toast('Restored into editor — save to keep'); });
}

/* ---------- ask ---------- */
async function loadAskList() {
  const rows = await api('/papers');
  $('#ask-list').innerHTML = rows.length ? '<div class="text-xs font-semibold text-slate-500 mb-2">SCOPE (none selected = all)</div>' +
    rows.map(p => `<label class="flex gap-2 items-start text-sm py-1"><input type="checkbox" class="mt-1 ask-cb" value="${p.id}"><span>${esc(p.title.slice(0, 90))}</span></label>`).join('')
    : '<div class="text-sm text-slate-500">No papers yet.</div>';
}
$('#ask-go').onclick = () => busy($('#ask-go'), async () => {
  const q = $('#ask-q').value.trim(); if (!q) return toast('Type a question', true);
  const ids = $$('.ask-cb:checked').map(c => +c.value);
  const r = await api('/ask', { method: 'POST', body: { question: q, paper_ids: ids.length ? ids : null } });
  $('#ask-out').innerHTML = `<div class="card p-5"><div class="md text-sm">${md(r.answer)}</div></div>
    ${r.sources.length ? '<div class="font-semibold mt-4 mb-2 text-sm">Sources</div>' + r.sources.map(s => `<div class="card p-3 mb-2 text-xs"><b>[${s.n}] ${esc(s.title)}</b><div class="text-slate-500 mt-1">${esc(s.snippet)}…</div></div>`).join('') : ''}`;
});

/* ---------- init ---------- */
(async function init() {
  try {
    const [f, h] = await Promise.all([api('/filters'), api('/health')]);
    state.filters = f;
    const years = f.years.map(String);
    fill('#d-source', f.sources); fill('#a-source', f.sources);
    fill('#d-vtype', f.venue_types, 'Any'); fill('#a-vtype', f.venue_types, 'Any'); fill('#l-vtype', f.venue_types, 'Any');
    fill('#f-vtype', f.venue_types, 'All types'); fill('#e-vtype', [...f.venue_types, 'Other']);
    fill('#d-venue', f.venues, 'Any'); fill('#d-sort', f.sorts);
    ['#d-yfrom', '#d-yto', '#a-yfrom', '#a-yto', '#l-year'].forEach(s => fill(s, years, 'Any'));
    fill('#e-year', years, '—');
    const ok = h.llm_provider !== 'mock';
    $('#llm-status').innerHTML = `<div class="flex items-center gap-2"><span class="h-2 w-2 rounded-full ${ok ? 'bg-emerald-400' : 'bg-amber-400'}"></span>${esc(h.llm_provider)} · ${esc(h.llm_model)}</div>` +
      (ok ? '' : '<div class="mt-1 text-amber-300">Mock mode — add a free API key in .env</div>');
  } catch (e) { toast('Backend not reachable: ' + e.message, true); }
  show(location.hash.slice(1) || 'discover');
})();
