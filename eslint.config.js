const js = require('@eslint/js');
const globals = require('globals');

module.exports = [
  js.configs.recommended,
  {
    files: ['static/app.js'],
    languageOptions: {
      sourceType: 'script',
      // diffSnapshots y buildCsv vienen de lib.js (script clásico)
      globals: { ...globals.browser, diffSnapshots: 'readonly', buildCsv: 'readonly', parseContent: 'readonly' },
    },
  },
  {
    files: ['static/lib.js'],
    languageOptions: { sourceType: 'commonjs', globals: { ...globals.browser, ...globals.node } },
    rules: { 'no-unused-vars': ['error', { varsIgnorePattern: '^(parseContent|diffSnapshots|buildCsv|csvCell)$' }] },
  },
  {
    files: ['tests/**/*.js', 'eslint.config.js'],
    languageOptions: { sourceType: 'commonjs', globals: globals.node },
  },
];
