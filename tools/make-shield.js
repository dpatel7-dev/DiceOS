#!/usr/bin/env node
// Turns Shield's list (shield/domains.txt) into the extension's blocking rules
// (shield/rules/ads.json). Run it after changing the list:  node tools/make-shield.js
'use strict';
const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const list = fs.readFileSync(path.join(ROOT, 'shield', 'domains.txt'), 'utf8')
  .split('\n').map((l) => l.trim().toLowerCase()).filter((l) => l && !l.startsWith('#'));
const ok = /^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$/;
const bad = list.filter((d) => !ok.test(d));
if (bad.length) { console.error('Not addresses: ' + bad.join(', ')); process.exit(1); }
// "ads.example.com" is already covered by "example.com"
const all = [...new Set(list)].sort();
const set = new Set(all);
const top = all.filter((d) => { const p = d.split('.'); for (let i = 1; i < p.length - 1; i++) if (set.has(p.slice(i).join('.'))) return false; return true; });
const rules = [];
for (let i = 0; i < top.length; i += 1000) {
  rules.push({ id: rules.length + 1, priority: 1, action: { type: 'block' }, condition: { requestDomains: top.slice(i, i + 1000), excludedResourceTypes: ['main_frame'] } });
}
fs.mkdirSync(path.join(ROOT, 'shield', 'rules'), { recursive: true });
fs.writeFileSync(path.join(ROOT, 'shield', 'rules', 'ads.json'), JSON.stringify(rules, null, 1) + '\n');
console.log('Shield: ' + all.length + ' addresses (' + top.length + ' once the parts under others are left out), in ' + rules.length + ' rule' + (rules.length === 1 ? '' : 's') + '.');
