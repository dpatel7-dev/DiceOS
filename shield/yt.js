// Shield, on YouTube: takes the ads out of what YouTube's player is told to play, before it
// reads it. YouTube's ads come from the same servers as its videos, so an address list
// can't stop them; this is how ad blockers do it. If one slips through anyway, it's skipped.
// (YouTube changes its site often, so now and then an ad may get through until this is updated.)
(() => {
  'use strict';
  try { if (localStorage.getItem('dice-shield') === 'off') return; } catch (e) { /* storage is off: go on */ }
  const KEYS = ['adPlacements', 'adSlots', 'playerAds', 'adBreakHeartbeatParams'];
  const prune = (o) => {
    if (!o || typeof o !== 'object') return o;
    KEYS.forEach((k) => { if (k in o) delete o[k]; });
    if (o.playerResponse) prune(o.playerResponse);
    return o;
  };
  const hasAds = (o) => o && typeof o === 'object' && KEYS.some((k) => k in o || (o.playerResponse && k in o.playerResponse));

  // the first video's player, written into the page
  let first;
  try { Object.defineProperty(window, 'ytInitialPlayerResponse', { configurable: true, get: () => first, set: (v) => { first = prune(v); } }); } catch (e) { /* already there */ }

  // the next ones, which YouTube reads as text
  const parse = JSON.parse;
  JSON.parse = function () {
    const out = parse.apply(this, arguments);
    try { if (hasAds(out)) prune(out); } catch (e) { /* leave it */ }
    return out;
  };
  const get = window.fetch;
  window.fetch = async function (input) {
    const res = await get.apply(this, arguments);
    try {
      const url = typeof input === 'string' ? input : (input && input.url) || '';
      if (res.ok && /\/youtubei\/v1\/player(\?|$)/.test(url)) {
        const j = parse(await res.clone().text());
        if (hasAds(j)) {
          prune(j);
          const headers = new Headers(res.headers);
          headers.delete('content-length'); headers.delete('content-encoding');
          return new Response(JSON.stringify(j), { status: res.status, statusText: res.statusText, headers });
        }
      }
    } catch (e) { /* leave it as it was */ }
    return res;
  };

  // anything that still plays as an ad: silent, and skipped
  let hushed = false;
  setInterval(() => {
    const p = document.querySelector('.html5-video-player.ad-showing');
    const v = document.querySelector('.html5-video-player video');
    if (!p) { if (hushed && v) { v.muted = false; hushed = false; } return; }
    const pv = p.querySelector('video');
    if (pv) {
      if (!pv.muted) { pv.muted = true; hushed = true; }
      if (isFinite(pv.duration) && pv.duration > 0 && pv.currentTime < pv.duration - 0.1) pv.currentTime = pv.duration;
    }
    const b = p.querySelector('.ytp-skip-ad-button, .ytp-ad-skip-button, .ytp-ad-skip-button-modern');
    if (b) b.click();
  }, 300);
})();
