// ── State ─────────────────────────────────────────────────────────────────
const fileLists = { followers: null, following: null };
let lists = { a: [], b: [], mutual: [] };
let profileData = {};   // username → {followers, following, posts, verified} | null
let sortState   = { key: null, dir: -1 };   // dir: -1 desc, 1 asc
let pollInterval     = null;
let sessionUsername  = null;
let currentJobId     = null;
let fetchPaused      = false;
let changes          = null;   // diff vs. la comparación anterior

const SNAP_KEY = 'cf_snapshot';

// ── Helpers ───────────────────────────────────────────────────────────────

function fmtNum(n) {
  if (n === null || n === undefined) return '—';
  if (n < 0) return 'N/D';
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1).replace(/\.0$/, '') + 'M';
  if (n >= 1_000)     return (n / 1_000).toFixed(1).replace(/\.0$/, '') + 'K';
  return n.toString();
}

function fmtRatio(followers, following) {
  if (following == null || following === 0) return followers > 0 ? '∞' : '—';
  const r = followers / following;
  return r >= 10 ? r.toFixed(0) + 'x' : r.toFixed(1) + 'x';
}

function ratioClass(followers, following) {
  if (!following) return following === 0 && followers > 0 ? 'ratio-high' : '';
  const r = followers / following;
  if (r >= 1)   return 'ratio-high';
  if (r >= 0.3) return 'ratio-mid';
  return 'ratio-low';
}

function pct(n, total) {
  if (!total) return '';
  return Math.round(n / total * 100) + '% del total';
}

function fileLabel(fl) {
  return fl.length === 1 ? `✓ ${fl[0].name}` : `✓ ${fl.length} archivos`;
}

function showError(msg) {
  const el = document.getElementById('error-msg');
  el.textContent = msg;
  el.style.display = msg ? 'block' : 'none';
}

function setLoading(on) {
  document.getElementById('compare-btn').style.display = on ? 'none' : '';
  document.getElementById('spinner').style.display = on ? 'block' : 'none';
}

// ── File parser (parseContent vive en lib.js) ─────────────────────────────

async function readFileList(fl) {
  const merged = new Set();
  for (const f of fl) {
    const text = await f.text();
    parseContent(text, f.name).forEach(u => merged.add(u));
  }
  return merged;
}

// ── Compare ───────────────────────────────────────────────────────────────

async function compare() {
  showError('');
  setLoading(true);
  try {
    const followers = await readFileList(fileLists.followers);
    const following = await readFileList(fileLists.following);
    if (!followers.size && !following.size) {
      showError('No se pudieron leer los archivos. Verificá el formato.');
      return;
    }
    updateChanges(followers, following);

    lists.a      = [...following].filter(u => !followers.has(u)).sort();
    lists.b      = [...followers].filter(u => !following.has(u)).sort();
    lists.mutual = [...following].filter(u =>  followers.has(u)).sort();

    document.getElementById('count-followers').textContent = followers.size;
    document.getElementById('count-following').textContent = following.size;
    document.getElementById('count-a').textContent      = lists.a.length;
    document.getElementById('count-mutual').textContent  = lists.mutual.length;
    document.getElementById('badge-a').textContent      = lists.a.length;
    document.getElementById('badge-b').textContent      = lists.b.length;
    document.getElementById('badge-mutual').textContent  = lists.mutual.length;
    document.getElementById('pct-a').textContent        = pct(lists.a.length, following.size);
    document.getElementById('pct-mutual').textContent   = pct(lists.mutual.length, following.size);

    profileData = {};
    sortState   = { key: null, dir: -1 };
    document.getElementById('sort-btn').disabled    = true;
    document.getElementById('sort-btn').textContent = '↓ Más followers';
    document.getElementById('mutual-sort-bar').style.display = 'none';

    renderList('list-a', lists.a, false);
    renderList('list-b', lists.b, false);
    renderMutualList(lists.mutual);

    saveState();

    const resultsEl = document.getElementById('results');
    resultsEl.classList.add('visible');
    resultsEl.scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (e) {
    showError('Error al procesar los archivos: ' + e.message);
  } finally {
    setLoading(false);
  }
}

// ── Cambios desde la última comparación ───────────────────────────────────

function readSnapshot() {
  try { return JSON.parse(localStorage.getItem(SNAP_KEY)); } catch { return null; }
}

function updateChanges(followers, following) {
  const cur  = { followers: [...followers].sort(), following: [...following].sort() };
  const prev = readSnapshot();
  changes = null;
  if (prev && Array.isArray(prev.followers) && Array.isArray(prev.following)) {
    const diff = diffSnapshots(prev, cur);
    changes = { since: prev.date, ...diff };
    if (Object.values(diff).every(a => !a.length)) return renderChanges();   // sin cambios: se conserva la fecha original
  }
  try { localStorage.setItem(SNAP_KEY, JSON.stringify({ date: new Date().toISOString(), ...cur })); } catch { /* almacenamiento lleno o bloqueado */ }
  renderChanges();
}

function renderChanges() {
  const box = document.getElementById('changes');
  const grid = document.getElementById('changes-grid');
  grid.replaceChildren();
  if (!changes) { box.hidden = true; return; }
  box.hidden = false;
  document.getElementById('changes-date').textContent = new Date(changes.since).toLocaleDateString('es');

  const cards = [
    ['lostFollowers', 'Dejaron de seguirte', 'bad'],
    ['newFollowers',  'Nuevos seguidores',   'good'],
    ['unfollowed',    'Dejaste de seguir',   ''],
    ['newFollowing',  'Empezaste a seguir',  ''],
  ];
  for (const [key, label, cls] of cards) {
    const users = changes[key] || [];
    const card = document.createElement('details');
    card.className = `change-card ${cls}`;
    const sum = document.createElement('summary');
    const n = document.createElement('span'); n.className = 'n'; n.textContent = users.length;
    sum.append(n, label);
    card.append(sum);
    if (users.length) {
      const ul = document.createElement('ul');
      for (const u of users) {
        const li = document.createElement('li');
        const a  = document.createElement('a');
        a.href = `https://www.instagram.com/${u}`; a.target = '_blank'; a.rel = 'noopener';
        a.textContent = u;
        li.append(a); ul.append(li);
      }
      card.append(ul);
    }
    grid.append(card);
  }
}

// ── Render ────────────────────────────────────────────────────────────────

function renderList(containerId, items) {
  const el = document.getElementById(containerId);
  if (!items.length) {
    el.innerHTML = '<div class="empty-msg">¡Todo en orden! 🎉</div>';
    return;
  }
  el.innerHTML = items.map(u => `
    <div class="list-item" data-name="${u}">
      <div class="avatar" aria-hidden="true">${u.charAt(0)}</div>
      <span class="name"><a href="https://www.instagram.com/${u}" target="_blank" rel="noopener">${u}</a></span>
    </div>`).join('');
}

function renderMutualList(items) {
  const el = document.getElementById('list-mutual');
  if (!items.length) {
    el.innerHTML = '<div class="empty-msg">No hay mutuos 🤔</div>';
    return;
  }
  el.innerHTML = items.map(u => {
    const p   = profileData[u];
    const pending = !p;
    const nd  = p && p.followers === -1;
    const cls = pending ? 'pending' : 'loaded';
    const verifiedHtml = p?.verified ? '<span class="verified-icon" title="Verificado">✓</span>' : '';
    return `
      <div class="mutual-row" data-name="${u}">
        <div class="mutual-name">
          <div class="avatar" aria-hidden="true" style="background:rgba(76,175,125,.2);color:var(--green);width:24px;height:24px;font-size:.68rem;flex-shrink:0">${u.charAt(0)}</div>
          <a href="https://www.instagram.com/${u}" target="_blank" rel="noopener">${u}</a>
          ${verifiedHtml}
        </div>
        <span class="mcell ${cls}" id="m-fl-${u}">${pending ? '—' : nd ? 'N/D' : fmtNum(p.followers)}</span>
        <span class="mcell ${cls}" id="m-fw-${u}">${pending ? '—' : nd ? 'N/D' : fmtNum(p.following)}</span>
        <span class="mcell ${cls} ${pending || nd ? '' : ratioClass(p.followers, p.following)}" id="m-rt-${u}">${pending ? '—' : nd ? 'N/D' : fmtRatio(p.followers, p.following)}</span>
        <span class="mcell ${cls}" id="m-po-${u}">${pending ? '—' : nd ? 'N/D' : fmtNum(p.posts)}</span>
      </div>`;
  }).join('');
}

function updateMutualRow(username, profile) {
  if (!profile) return;
  const nd = profile.followers === -1;
  const setText = (id, val) => { const e = document.getElementById(id); if (e) { e.textContent = val; e.classList.replace('pending', 'loaded'); } };
  setText(`m-fl-${username}`, nd ? 'N/D' : fmtNum(profile.followers));
  setText(`m-fw-${username}`, nd ? 'N/D' : fmtNum(profile.following));
  const rtEl = document.getElementById(`m-rt-${username}`);
  if (rtEl) {
    rtEl.textContent = nd ? 'N/D' : fmtRatio(profile.followers, profile.following);
    rtEl.classList.replace('pending', 'loaded');
    if (!nd) rtEl.classList.add(ratioClass(profile.followers, profile.following));
  }
  setText(`m-po-${username}`, nd ? 'N/D' : fmtNum(profile.posts));
  if (profile.verified) {
    const nameEl = document.querySelector(`[data-name="${username}"] .mutual-name`);
    if (nameEl && !nameEl.querySelector('.verified-icon')) {
      nameEl.insertAdjacentHTML('beforeend', '<span class="verified-icon" title="Verificado">✓</span>');
    }
  }
}

function sortMutualBy(key) {
  if (sortState.key === key) {
    sortState.dir *= -1;
  } else {
    sortState.key = key;
    sortState.dir = -1; // default desc
  }

  // Update header indicators
  document.querySelectorAll('.sort-col[data-sort]').forEach(el => {
    const k   = el.dataset.sort;
    const arr = sortState.key === k ? (sortState.dir === -1 ? ' ↓' : ' ↑') : ' ↕';
    el.textContent = { followers: 'Followers', following: 'Following', ratio: 'Ratio', posts: 'Posts' }[k] + arr;
    el.classList.toggle('active', k === sortState.key);
  });

  const val = (u) => {
    const p = profileData[u];
    if (!p || p.followers === -1) return -Infinity;
    if (key === 'ratio') return p.following > 0 ? p.followers / p.following : Infinity;
    return p[key] ?? 0;
  };

  const sorted = [...lists.mutual].sort((a, b) => (val(b) - val(a)) * sortState.dir * -1);
  renderMutualList(sorted);

  // Restore search filter
  const q = document.getElementById('search-mutual').value.toLowerCase();
  if (q) document.getElementById('list-mutual').querySelectorAll('.mutual-row')
    .forEach(row => row.style.display = row.dataset.name.includes(q) ? '' : 'none');
}

// Legacy sort button (now delegates to sortMutualBy)
function sortMutual() { sortMutualBy('followers'); }

// ── Session & fetch ───────────────────────────────────────────────────────

function getSavedSessionId() {
  return localStorage.getItem('cf_sessionid') || null;
}

function checkSession() {
  const sid = getSavedSessionId();
  sessionUsername = sid ? 'conectado' : null;
  updateSessionUI();
}

function updateSessionUI() {
  const btn = document.getElementById('session-btn');
  if (sessionUsername) {
    btn.style.display = '';
    btn.textContent   = 'Instagram: conectado';
  } else {
    btn.style.display = 'none';
  }
}

let modalOpener = null;

function openModal() {
  modalOpener = document.activeElement;
  document.getElementById('modal-overlay').classList.add('open');
  document.getElementById('ig-sessionid').focus();
  document.getElementById('modal-error').style.display = 'none';
  document.getElementById('ig-sessionid').value = '';
  const submitBtn = document.getElementById('modal-submit');
  submitBtn.textContent = 'Conectar';
  submitBtn.disabled    = false;
  submitBtn.onclick     = submitLogin;
}

function closeModal() {
  document.getElementById('modal-overlay').classList.remove('open');
  if (modalOpener && modalOpener.focus) modalOpener.focus();
}

async function submitLogin() {
  const sessionid = document.getElementById('ig-sessionid').value.trim();
  const errEl     = document.getElementById('modal-error');
  const submitBtn = document.getElementById('modal-submit');
  if (!sessionid) { errEl.textContent = 'Pegá el valor del sessionid.'; errEl.style.display = 'block'; return; }

  submitBtn.disabled    = true;
  submitBtn.textContent = 'Validando…';
  errEl.style.display   = 'none';

  try {
    const res  = await fetch('/validate-session', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({sessionid}) });
    const data = await res.json();
    if (!res.ok) { errEl.textContent = data.error; errEl.style.display = 'block'; return; }
    localStorage.setItem('cf_sessionid', sessionid);
    sessionUsername = 'conectado';
    updateSessionUI();
    closeModal();
    startFetch();
  } catch {
    errEl.textContent = 'Error de conexión con el servidor.';
    errEl.style.display = 'block';
  } finally {
    submitBtn.disabled    = false;
    submitBtn.textContent = 'Conectar';
  }
}

function logoutSession() {
  localStorage.removeItem('cf_sessionid');
  sessionUsername = null;
  updateSessionUI();
}

function pendingMutuals() {
  return lists.mutual.filter(u => !profileData[u]);
}

function updateFetchTrigger() {
  const pending = pendingMutuals().length;
  const done    = lists.mutual.length - pending;
  document.getElementById('fetch-btn').textContent =
    done > 0 && pending > 0 ? `Reanudar (${pending} pendientes)` : 'Obtener followers';
}

function setFetchUI(state, text) {
  document.getElementById('fetch-dot').className = 'fetch-dot' + (state ? ' ' + state : '');
  if (text !== undefined) document.getElementById('fetch-eta').textContent = text;
}

async function startFetch() {
  if (!lists.mutual.length) return;

  if (!sessionUsername) { openModal(); return; }

  const pending = pendingMutuals();
  if (!pending.length) { alert('Ya tenés los datos de todos los mutuos.'); return; }

  document.getElementById('fetch-trigger').style.display = 'none';
  document.getElementById('fetch-panel').classList.add('visible');
  setFetchUI('', '');
  setProgress(0);
  fetchPaused = false;
  document.getElementById('pause-btn').textContent = 'Pausar';
  document.getElementById('fetch-status').textContent = 'Iniciando…';
  document.getElementById('fetch-last-error').style.display = 'none';
  document.getElementById('stop-btn').disabled = false;
  document.getElementById('pause-btn').disabled = false;

  try {
    const res = await fetch('/fetch-counts', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ usernames: pending, sessionid: getSavedSessionId() })
    });
    const data = await res.json();
    if (!res.ok) { alert(data.error); resetFetchUI(); return; }
    currentJobId = data.job_id;
    pollInterval = setInterval(pollProgress, 2000);
  } catch (e) {
    alert('Error al iniciar el proceso: ' + e.message);
    resetFetchUI();
  }
}

async function stopFetch() {
  if (!currentJobId) return;
  document.getElementById('stop-btn').disabled = true;
  document.getElementById('pause-btn').disabled = true;
  await fetch('/stop-fetch', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ job_id: currentJobId }) });
  await pollProgress();   // recoge lo que se alcanzó a procesar y cierra el estado
}

async function togglePause() {
  if (!currentJobId) return;
  fetchPaused = !fetchPaused;
  await fetch('/pause-fetch', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ job_id: currentJobId, paused: fetchPaused }) });
  document.getElementById('pause-btn').textContent = fetchPaused ? 'Reanudar' : 'Pausar';
  setFetchUI(fetchPaused ? 'paused' : '', fetchPaused ? 'En pausa' : '');
}

function resetFetchUI() {
  document.getElementById('fetch-panel').classList.remove('visible');
  document.getElementById('fetch-trigger').style.display = '';
  updateFetchTrigger();
}

function setProgress(pctDone) {
  document.getElementById('progress-fill').style.width = pctDone + '%';
  document.getElementById('progress-track').setAttribute('aria-valuenow', pctDone);
}

function finishFetch() {
  clearInterval(pollInterval); pollInterval = null;
  document.getElementById('stop-btn').disabled  = true;
  document.getElementById('pause-btn').disabled = true;
  if (Object.values(profileData).some(Boolean)) {
    document.getElementById('sort-btn').disabled = false;
    document.getElementById('mutual-sort-bar').style.display = '';
    sortMutualBy('ratio');   // auto-orden por ratio al terminar
  }
  // si quedaron pendientes (detenido, fallidos) se ofrece reanudar
  if (pendingMutuals().length) {
    document.getElementById('fetch-trigger').style.display = '';
    updateFetchTrigger();
  }
}

async function pollProgress() {
  try {
    const res = await fetch('/fetch-progress?job_id=' + encodeURIComponent(currentJobId));
    if (res.status === 404) {   // el servidor se reinició y perdió el job
      setFetchUI('stopped', 'El servidor se reinició; lo ya obtenido se conserva. Podés reanudar.');
      document.getElementById('fetch-status').textContent = 'Proceso interrumpido';
      finishFetch();
      return;
    }
    const data = await res.json();

    // Aplicar resultados nuevos (un perfil ahora válido reemplaza un fallo previo)
    let changed = false;
    for (const [u, profile] of Object.entries(data.results)) {
      if (profile && !profileData[u]) {
        profileData[u] = profile;
        updateMutualRow(u, profile);
        changed = true;
      } else if (!profile && !(u in profileData)) {
        profileData[u] = null;
      }
    }
    if (changed) saveState();

    setProgress(data.total ? Math.round(data.done / data.total * 100) : 0);
    document.getElementById('fetch-status').textContent = `${data.done} / ${data.total} usuarios`;

    // ETA
    if (data.running && !data.paused && data.done > 0 && data.started_at) {
      const elapsed   = (Date.now() - new Date(data.started_at)) / 1000;
      const remaining = Math.round((data.total - data.done) / (data.done / elapsed));
      const mins = Math.floor(remaining / 60);
      const secs = remaining % 60;
      document.getElementById('fetch-eta').textContent =
        remaining > 0 ? `~${mins > 0 ? mins + ' min ' : ''}${secs} seg restantes` : '';
    }

    const errDiv = document.getElementById('fetch-last-error');
    if (data.last_error) {
      errDiv.textContent = `Último error: ${data.last_error}`;
      errDiv.style.display = 'block';
    }

    if (!data.running) {
      const ok = Object.values(data.results).filter(Boolean).length;
      if (data.stopped) setFetchUI('stopped', `Proceso detenido — ${ok} cuentas obtenidas.`);
      else if (data.error) setFetchUI('done', `Error: ${data.error}`);
      else setFetchUI('done', `Completado — ${ok} de ${data.total} cuentas obtenidas`);
      finishFetch();
    }
  } catch { /* error de red transitorio: el próximo poll reintenta */ }
}

// ── Drop zones ────────────────────────────────────────────────────────────

function loadZone(key) {
  const input = document.getElementById(`file-${key}`);
  const zone  = document.getElementById(`zone-${key}`);

  function handleFiles(fl) {
    if (!fl || !fl.length) return;
    const existing = fileLists[key] ? [...fileLists[key]] : [];
    const seen = new Set(existing.map(f => `${f.name}:${f.size}`));
    for (const f of fl) {
      const sig = `${f.name}:${f.size}`;
      if (!seen.has(sig)) { existing.push(f); seen.add(sig); }
    }
    fileLists[key] = existing;
    document.getElementById(`name-${key}`).textContent = fileLabel(fileLists[key]);
    zone.classList.add('loaded');
    document.getElementById('compare-btn').disabled = !(fileLists.followers && fileLists.following);
  }

  input.addEventListener('change', e => handleFiles(e.target.files));
  zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('drag-over'); });
  zone.addEventListener('dragleave', () => zone.classList.remove('drag-over'));
  zone.addEventListener('drop', e => { e.preventDefault(); zone.classList.remove('drag-over'); handleFiles(e.dataTransfer.files); });
}

loadZone('followers');
loadZone('following');

// ── Event listeners ───────────────────────────────────────────────────────

document.getElementById('compare-btn').addEventListener('click', compare);

document.getElementById('fetch-btn').addEventListener('click', startFetch);
document.getElementById('stop-btn').addEventListener('click', stopFetch);
document.getElementById('pause-btn').addEventListener('click', togglePause);
document.getElementById('forget-history').addEventListener('click', () => {
  localStorage.removeItem(SNAP_KEY);
  changes = null;
  renderChanges();
  saveState();
});
document.getElementById('sort-btn').addEventListener('click', sortMutual);

document.getElementById('session-btn').addEventListener('click', () => {
  if (confirm(`¿Cerrar sesión de ${sessionUsername}?`)) logoutSession();
});

document.getElementById('modal-cancel').addEventListener('click', closeModal);
document.getElementById('modal-submit').addEventListener('click', submitLogin);
document.getElementById('modal-overlay').addEventListener('click', e => {
  if (e.target === e.currentTarget) closeModal();
});
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') closeModal();
  if (e.key === 'Enter' && document.getElementById('modal-overlay').classList.contains('open')) submitLogin();
});

document.getElementById('reset-btn').addEventListener('click', () => {
  fileLists.followers = fileLists.following = null;
  ['followers', 'following'].forEach(k => {
    document.getElementById(`file-${k}`).value = '';
    document.getElementById(`name-${k}`).textContent = '';
    document.getElementById(`zone-${k}`).classList.remove('loaded');
  });
  document.getElementById('compare-btn').disabled = true;
  document.getElementById('results').classList.remove('visible');
  if (pollInterval) {   // cortar el job en el servidor para no seguir consultando Instagram
    clearInterval(pollInterval); pollInterval = null;
    fetch('/stop-fetch', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ job_id: currentJobId }) }).catch(() => {});
  }
  resetFetchUI();
  document.getElementById('stop-btn').disabled = false;
  showError('');
  currentJobId = null;
  changes = null;
  renderChanges();
  clearState();
  window.scrollTo({ top: 0, behavior: 'smooth' });
});

// Search for list-a and list-b
document.querySelectorAll('.search-input[data-filter]').forEach(input => {
  input.addEventListener('input', () => {
    const q = input.value.toLowerCase();
    document.getElementById(`list-${input.dataset.filter}`)
      .querySelectorAll('.list-item')
      .forEach(item => item.style.display = item.dataset.name.includes(q) ? '' : 'none');
  });
});

// Search for mutuals
document.getElementById('search-mutual').addEventListener('input', e => {
  const q = e.target.value.toLowerCase();
  document.getElementById('list-mutual').querySelectorAll('.mutual-row')
    .forEach(row => row.style.display = row.dataset.name.includes(q) ? '' : 'none');
});

// Column sort headers
document.querySelectorAll('.sort-col[data-sort]').forEach(el => {
  el.addEventListener('click', () => sortMutualBy(el.dataset.sort));
  el.addEventListener('keydown', e => {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); sortMutualBy(el.dataset.sort); }
  });
});

document.querySelectorAll('.copy-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    navigator.clipboard.writeText(lists[btn.dataset.list].join('\n')).then(() => {
      btn.textContent = '¡Copiado!';
      setTimeout(() => btn.textContent = 'Copiar', 2000);
    });
  });
});

document.querySelectorAll('.dl-btn:not(.csv-btn)').forEach(btn => {
  btn.addEventListener('click', () => {
    const key     = btn.dataset.list;
    const content = lists[key].map(u => `https://www.instagram.com/${u}/`).join('\n');
    const blob    = new Blob([content], { type: 'text/plain' });
    const url     = URL.createObjectURL(blob);
    const a       = document.createElement('a');
    a.href = url; a.download = btn.dataset.filename; a.click();
    URL.revokeObjectURL(url);
  });
});

// ── Export CSV ────────────────────────────────────────────────────────────

document.querySelectorAll('.csv-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    const blob = new Blob([buildCsv(lists[btn.dataset.list], profileData)],
                          { type: 'text/csv;charset=utf-8' });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href = url; a.download = btn.dataset.filename; a.click();
    URL.revokeObjectURL(url);
  });
});

// ── LocalStorage persistence ──────────────────────────────────────────────

function saveState() {
  try {
    localStorage.setItem('cf_lists',       JSON.stringify(lists));
    localStorage.setItem('cf_changes',     JSON.stringify(changes));
    localStorage.setItem('cf_profile',     JSON.stringify(profileData));
    localStorage.setItem('cf_stats',       JSON.stringify({
      followers: document.getElementById('count-followers').textContent,
      following: document.getElementById('count-following').textContent,
      countA:    lists.a.length,
      countB:    lists.b.length,
      mutual:    lists.mutual.length,
      pctA:      document.getElementById('pct-a').textContent,
      pctMutual: document.getElementById('pct-mutual').textContent,
    }));
  } catch { /* almacenamiento lleno o bloqueado */ }
}

function loadState() {
  try {
    const savedLists   = localStorage.getItem('cf_lists');
    const savedProfile = localStorage.getItem('cf_profile');
    const savedStats   = localStorage.getItem('cf_stats');
    if (!savedLists) return;

    lists       = JSON.parse(savedLists);
    changes     = JSON.parse(localStorage.getItem('cf_changes') || 'null');
    renderChanges();
    profileData = savedProfile ? JSON.parse(savedProfile) : {};

    if (savedStats) {
      const s = JSON.parse(savedStats);
      document.getElementById('count-followers').textContent = s.followers;
      document.getElementById('count-following').textContent = s.following;
      document.getElementById('count-a').textContent      = s.countA;
      document.getElementById('count-mutual').textContent  = s.mutual;
      document.getElementById('badge-a').textContent      = s.countA;
      document.getElementById('badge-b').textContent      = s.countB;
      document.getElementById('badge-mutual').textContent  = s.mutual;
      document.getElementById('pct-a').textContent        = s.pctA;
      document.getElementById('pct-mutual').textContent   = s.pctMutual;
    }

    renderList('list-a', lists.a, false);
    renderList('list-b', lists.b, false);
    renderMutualList(lists.mutual);

    const hasCounts = Object.keys(profileData).length > 0;
    if (hasCounts) {
      document.getElementById('mutual-sort-bar').style.display = '';
      document.getElementById('sort-btn').disabled = false;
      sortMutualBy('ratio');
    }

    updateFetchTrigger();
    document.getElementById('results').classList.add('visible');
  } catch { /* estado guardado corrupto: se ignora */ }
}

function clearState() {
  localStorage.removeItem('cf_lists');
  localStorage.removeItem('cf_profile');
  localStorage.removeItem('cf_stats');
  localStorage.removeItem('cf_changes');   // el snapshot (cf_snapshot) se conserva para la próxima comparación
}

// Check session on load
checkSession();
loadState();
