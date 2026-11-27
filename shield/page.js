// Shield, in each page: hides the empty boxes ads leave behind (and the ones that come
// from the site itself), and drops Google's full-page "vignette" ads.
(() => {
  'use strict';
  const host = location.hostname.replace(/^www\./, '');
  if (!host || !chrome.runtime || !chrome.runtime.id) return;

  // boxes that are only ever ads, on any site
  const ANY = [
    'ins.adsbygoogle', '.adsbygoogle', 'iframe[id^="google_ads_iframe"]', 'div[id^="google_ads_iframe"]', 'div[id^="div-gpt-ad"]', '[data-google-query-id]',
    'iframe[src*="doubleclick.net"]', 'iframe[src*="googlesyndication.com"]', 'iframe[src*="amazon-adsystem.com"]', 'iframe[src*="adnxs.com"]',
    'amp-ad', 'amp-embed[type="taboola"]', 'amp-embed[type="outbrain"]', 'amp-sticky-ad',
    'div[id^="taboola-"]', '.trc_related_container', '.trc_rbox_container', '.OUTBRAIN', '.ob-widget', '.ob-smartfeed-wrapper', 'div[data-widget-id^="AR_"]',
    'div[id^="rc-widget-"]', 'div[id^="mgid_"]', 'div[data-type="_mgwidget"]', 'div[id^="ezoic-pub-ad"]', '.ezoic-ad', '.adthrive-ad', '.adthrive-content', '.mv-ad-box',
    '.ad-slot', '.ad-slot-container', '.ad-container', '.ad-wrapper', '.ad-banner', '.ad-unit', '.ad-placement', '.ad-leaderboard', '.ad-rail', '.ad-sidebar',
    '.advertisement', '.advertisment', '#advertisement', '[aria-label="Advertisement"]', '[aria-label="advertisement"]', '.sponsored-ad', '#carbonads', '.native-ad', '.pub_300x250', '.pub_728x90',
  ];
  // the ads sites put among their own things
  const SITES = {
    'youtube.com': ['ytd-ad-slot-renderer', 'ytd-in-feed-ad-layout-renderer', 'ytd-banner-promo-renderer', 'ytd-statement-banner-renderer', 'ytd-promoted-sparkles-web-renderer',
      'ytd-promoted-video-renderer', 'ytd-display-ad-renderer', 'ytd-compact-promoted-video-renderer', 'ytd-action-companion-ad-renderer', 'ytd-player-legacy-desktop-watch-ads-renderer',
      'ytd-engagement-panel-section-list-renderer[target-id="engagement-panel-ads"]', '#player-ads', '#masthead-ad', '.ytp-ad-overlay-container', '.ytp-ad-image-overlay',
      'ytd-rich-item-renderer:has(ytd-ad-slot-renderer)', 'ytd-rich-section-renderer:has(ytd-statement-banner-renderer)', 'ytd-merch-shelf-renderer', 'ytm-promoted-sparkles-web-renderer', 'ad-slot-renderer'],
    'google.com': ['#tads', '#tadsb', '#bottomads', '.commercial-unit-desktop-top', '.commercial-unit-desktop-rhs', 'div[data-text-ad]', '#atvcap'],
    'bing.com': ['li.b_ad', '.b_ad', '.b_adBottom'],
    'duckduckgo.com': ['li[data-layout="ad"]', '[data-testid="ad"]', '.badge--ad'],
    'reddit.com': ['shreddit-ad-post', 'shreddit-comments-page-ad', '.promotedlink', 'faceplate-tracker[noun="ad_click"]'],
    'amazon.com': ['[data-component-type="sp-sponsored-result"]', '.AdHolder', 'div[data-cel-widget^="adplacements"]', '#sp_detail', '#sp_detail2'],
    'x.com': ['div[data-testid="placementTracking"]'],
    'twitter.com': ['div[data-testid="placementTracking"]'],
    'yahoo.com': ['.Ad', '#my-adsLREC', '.gemini-ad'],
  };
  const mine = Object.keys(SITES).filter((s) => host === s || host.endsWith('.' + s)).flatMap((s) => SITES[s]);
  const SEL = ANY.concat(mine).join(',\n');

  chrome.runtime.sendMessage({ t: 'page', host }, (st) => {
    if (chrome.runtime.lastError || !st) return;
    // yt.js reads this as the page starts, before Shield could answer it
    try { localStorage.setItem('dice-shield', st.on && st.yt ? 'on' : 'off'); } catch (e) { /* storage is off */ }
    if (!st.on) return;
    const style = document.createElement('style');
    style.dataset.shield = '';
    style.textContent = SEL + ' { display: none !important; }';
    (document.head || document.documentElement).appendChild(style);
    // Google's full-page ad shows itself with #google_vignette on the address
    const vignette = () => { if (location.hash === '#google_vignette') history.replaceState(history.state, '', location.href.replace(/#google_vignette$/, '')); };
    vignette();
    addEventListener('hashchange', vignette);
    // count what was hidden, once the page has settled
    setTimeout(() => {
      let n = 0;
      try { n = document.querySelectorAll(SEL).length; } catch (e) { /* an old browser without :has() */ }
      if (n) chrome.runtime.sendMessage({ t: 'hid', host, n });
    }, 5000);
  });
})();
