// Shield's background: the switches, the sites it's paused on, the addresses you let
// through, and how many ads it kept out (today, and the last week).
//
// The blocking itself is Chromium's: rules/ads.json (made from domains.txt by
// tools/make-shield.js) stops requests to ad and tracker addresses before they leave.
// page.js hides the empty boxes ads leave behind, and yt.js takes the ads out of
// YouTube's videos. DiceOS's desktop talks to this through bridge.js.
'use strict';

const DEF = { on: true, yt: true, paused: [], allow: [], day: '', n: 0, sites: {}, week: {}, total: 0 };
let S = null;
const dayOf = (d) => d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
const site = (h) => String(h || '').toLowerCase().replace(/^www\./, '').replace(/\.$/, '');
const okSite = (h) => /^[a-z0-9-]+(\.[a-z0-9-]+)+$/.test(h) && h.length < 200;
const under = (h, list) => list.some((p) => h === p || h.endsWith('.' + p));

async function load() {
  if (S) return S;
  const got = await chrome.storage.local.get('shield');
  S = Object.assign({}, DEF, got.shield || {});
  return S;
}
const keep = () => chrome.storage.local.set({ shield: S });
let keepT = 0;
const keepSoon = () => { clearTimeout(keepT); keepT = setTimeout(keep, 1500); };

// a new day: yesterday goes into the week
function roll() {
  const d = dayOf(new Date());
  if (S.day === d) return;
  if (S.day) S.week[S.day] = S.n;
  Object.keys(S.week).sort().slice(0, -7).forEach((k) => delete S.week[k]);
  S.day = d; S.n = 0; S.sites = {};
}
function count(host, n) {
  if (!n) return;
  roll();
  S.n += n; S.total += n;
  const h = site(host);
  if (h) S.sites[h] = (S.sites[h] || 0) + n;
  keepSoon();
}

// the rules that change: Shield on or off, paused sites, addresses let through
async function apply() {
  await load();
  try { await chrome.declarativeNetRequest.updateEnabledRulesets(S.on ? { enableRulesetIds: ['ads'] } : { disableRulesetIds: ['ads'] }); } catch (e) { /* already that way */ }
  const old = await chrome.declarativeNetRequest.getDynamicRules();
  const add = [];
  let id = 1;
  S.paused.filter(okSite).slice(0, 500).forEach((h) => add.push({ id: id++, priority: 100, action: { type: 'allowAllRequests' }, condition: { requestDomains: [h], resourceTypes: ['main_frame', 'sub_frame'] } }));
  const allow = S.allow.filter(okSite).slice(0, 2000);
  if (allow.length) add.push({ id: id++, priority: 50, action: { type: 'allow' }, condition: { requestDomains: allow } });
  await chrome.declarativeNetRequest.updateDynamicRules({ removeRuleIds: old.map((r) => r.id), addRules: add });
}

// every request Shield stopped (Chromium tells unpacked extensions, which DiceOS's is)
if (chrome.declarativeNetRequest.onRuleMatchedDebug) {
  chrome.declarativeNetRequest.onRuleMatchedDebug.addListener(async (info) => {
    if (info.rule.rulesetId !== 'ads') return;
    await load();
    let h = '';
    try { h = new URL(info.request.initiator || info.request.documentUrl || info.request.url).hostname; } catch (e) { /* no page */ }
    count(h, 1);
  });
}

function view(host) {
  roll();
  const h = site(host);
  const top = Object.entries(S.sites).sort((a, b) => b[1] - a[1]).slice(0, 8).map(([k, n]) => ({ site: k, n }));
  return {
    here: true, version: chrome.runtime.getManifest().version, on: S.on, yt: S.yt, paused: S.paused.slice(), allow: S.allow.slice(),
    today: S.n, total: S.total, week: Object.assign({}, S.week, { [S.day]: S.n }), top,
    site: h ? { site: h, n: S.sites[h] || 0, paused: under(h, S.paused) } : null,
  };
}

async function fromShell(m) {
  await load();
  const h = site(m.site);
  let changed = false;
  if (m.cmd === 'set') { ['on', 'yt'].forEach((k) => { if (typeof m[k] === 'boolean') { S[k] = m[k]; changed = true; } }); }
  else if (m.cmd === 'pause' && okSite(h)) { if (!S.paused.includes(h)) S.paused.push(h); changed = true; }
  else if (m.cmd === 'resume' && h) { S.paused = S.paused.filter((x) => x !== h && !h.endsWith('.' + x)); changed = true; }
  else if (m.cmd === 'allow' && okSite(h)) { if (!S.allow.includes(h)) S.allow.push(h); changed = true; }
  else if (m.cmd === 'unallow' && h) { S.allow = S.allow.filter((x) => x !== h); changed = true; }
  else if (m.cmd === 'reset') { S.day = ''; S.n = 0; S.sites = {}; S.week = {}; S.total = 0; changed = true; }
  if (changed) { await keep(); await apply(); }
  return view(m.site);
}

chrome.runtime.onMessage.addListener((m, sender, reply) => {
  (async () => {
    await load();
    if (m.t === 'page') { const h = site(m.host); return { on: S.on && !under(h, S.paused), yt: S.yt }; }
    if (m.t === 'hid') { count(m.host, Math.min(200, m.n | 0)); return {}; }
    if (m.t === 'shell') return fromShell(m);
    return null;
  })().then(reply, () => reply(null));
  return true;
});

chrome.runtime.onInstalled.addListener(() => { apply(); });
chrome.runtime.onStartup.addListener(() => { apply(); });
