// Shield's door to DiceOS's own pages (Settings, SereneTab): they ask with
// window.postMessage({dice: 'shield', id, msg}) and hear back {dice: 'shield-re', id, data}.
// Only pages from DiceOS itself (127.0.0.1) get this script.
(() => {
  'use strict';
  const here = location.origin;
  addEventListener('message', (e) => {
    if (e.source !== window || e.origin !== here || !e.data || e.data.dice !== 'shield') return;
    const id = e.data.id, msg = Object.assign({}, e.data.msg || {}, { t: 'shell' });
    try {
      chrome.runtime.sendMessage(msg, (r) => window.postMessage({ dice: 'shield-re', id, data: chrome.runtime.lastError ? null : r }, here));
    } catch (err) { window.postMessage({ dice: 'shield-re', id, data: null }, here); }
  });
  const hello = () => window.postMessage({ dice: 'shield-here' }, here);
  hello();
  addEventListener('DOMContentLoaded', hello);
})();
