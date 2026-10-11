const test = require('node:test');
const assert = require('node:assert/strict');
const { parseContent, diffSnapshots, csvCell, buildCsv } = require('../static/lib.js');

test('JSON de followers', () => {
  const data = [{ string_list_data: [{ value: 'Alice' }] }, { string_list_data: [{ value: 'bob' }] }];
  assert.deepEqual([...parseContent(JSON.stringify(data), 'followers_1.json')].sort(), ['alice', 'bob']);
});

test('JSON de following', () => {
  const data = { relationships_following: [{ string_list_data: [{ value: 'Carol' }] }] };
  assert.deepEqual([...parseContent(JSON.stringify(data), 'following.json')], ['carol']);
});

test('HTML con links _u/', () => {
  const html = '<a href="https://www.instagram.com/_u/dave.x">x</a><a href="https://www.instagram.com/_u/Eve_1">e</a>';
  assert.deepEqual([...parseContent(html, 'followers.html')].sort(), ['dave.x', 'eve_1']);
});

test('HTML sin _u/ usa el link directo', () => {
  const html = '<a href="https://www.instagram.com/frank">f</a>';
  assert.deepEqual([...parseContent(html, 'f.html')], ['frank']);
});

test('texto plano: ignora comentarios, vacíos y @', () => {
  assert.deepEqual([...parseContent('# nota\n@Frank\n\n  grace  \n', 'l.txt')].sort(), ['frank', 'grace']);
});

test('descarta usernames inválidos (evita inyección en el DOM)', () => {
  const out = parseContent('ok_user\n<img src=x onerror=alert(1)>\na"b\n' + 'x'.repeat(31), 'l.txt');
  assert.deepEqual([...out], ['ok_user']);
});

test('diffSnapshots', () => {
  const prev = { followers: ['a', 'b'], following: ['a', 'c'] };
  const cur  = { followers: ['b', 'd'], following: ['a', 'e'] };
  assert.deepEqual(diffSnapshots(prev, cur), {
    lostFollowers: ['a'], newFollowers: ['d'], unfollowed: ['c'], newFollowing: ['e'],
  });
});

test('csvCell escapa comas, comillas y saltos de línea', () => {
  assert.equal(csvCell('a,b'), '"a,b"');
  assert.equal(csvCell('say "hi"'), '"say ""hi"""');
  assert.equal(csvCell(null), '');
  assert.equal(csvCell(5), '5');
});

test('buildCsv incluye BOM, cabecera y perfiles faltantes', () => {
  const csv = buildCsv(['a', 'b'], { a: { followers: 10, following: 2, posts: 3, verified: true }, b: null });
  const lines = csv.slice(1).split('\n');
  assert.equal(csv[0], '﻿');
  assert.equal(lines[0], 'username,url,followers,following,posts,verified');
  assert.equal(lines[1], 'a,https://www.instagram.com/a/,10,2,3,si');
  assert.equal(lines[2], 'b,https://www.instagram.com/b/,,,,');
});
