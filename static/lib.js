// Lógica pura (sin DOM): parseo de exports de Instagram, diff entre corridas y CSV.
// Se carga como script clásico en el navegador y como módulo CommonJS en los tests.

const USERNAME_RE = /^[a-z0-9_.]{1,30}$/;

function addUser(users, raw) {
  const u = String(raw).trim().replace(/^@/, '').toLowerCase();
  if (USERNAME_RE.test(u)) users.add(u);
}

function parseContent(text, filename) {
  const users = new Set();

  if (filename.endsWith('.html') || text.includes('instagram.com')) {
    let m = [...text.matchAll(/instagram\.com\/_u\/([A-Za-z0-9_.]+)/g)].map(x => x[1]);
    if (!m.length)
      m = [...text.matchAll(/instagram\.com\/([A-Za-z0-9_.][A-Za-z0-9_.]*)["'?]/g)].map(x => x[1]);
    m.forEach(u => addUser(users, u));
    if (users.size) return users;
  }

  try {
    const data = JSON.parse(text);
    const extract = (arr) => {
      if (!Array.isArray(arr)) return;
      for (const item of arr) {
        if (item && typeof item === 'object') {
          for (const e of (item.string_list_data || []))
            if (e.value) addUser(users, e.value);
          if (item.value) addUser(users, item.value);
        }
      }
    };
    if (Array.isArray(data)) {
      extract(data);
    } else if (data && typeof data === 'object') {
      if (data.relationships_following) extract(data.relationships_following);
      else for (const v of Object.values(data)) extract(v);
    }
    if (users.size) return users;
  } catch { /* no es JSON: se trata como texto */ }

  for (const line of text.split('\n')) {
    const t = line.trim();
    if (t && !t.startsWith('#')) addUser(users, t);
  }
  return users;
}

// Compara dos snapshots {followers: [...], following: [...]}.
function diffSnapshots(prev, cur) {
  const minus = (a, b) => { const s = new Set(b); return a.filter(u => !s.has(u)).sort(); };
  return {
    lostFollowers: minus(prev.followers, cur.followers),   // dejaron de seguirte
    newFollowers:  minus(cur.followers, prev.followers),   // te siguen desde ahora
    unfollowed:    minus(prev.following, cur.following),   // dejaste de seguir
    newFollowing:  minus(cur.following, prev.following),   // empezaste a seguir
  };
}

function csvCell(v) {
  const s = v == null ? '' : String(v);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

function buildCsv(users, profileData) {
  const rows = [['username', 'url', 'followers', 'following', 'posts', 'verified']];
  for (const u of users) {
    const p = profileData[u];
    rows.push([u, `https://www.instagram.com/${u}/`,
               p ? p.followers : '', p ? p.following : '', p ? p.posts : '',
               p ? (p.verified ? 'si' : 'no') : '']);
  }
  return '﻿' + rows.map(r => r.map(csvCell).join(',')).join('\n');
}

if (typeof module !== 'undefined') {
  module.exports = { parseContent, diffSnapshots, csvCell, buildCsv, USERNAME_RE };
}
