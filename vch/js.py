"""JavaScript evaluated inside Vortex's renderer.

This file is the contract with Vortex's DOM and preload API. Keep every
snippet here: a Vortex update breaks this file first, and having the
selectors and the return protocol in one place makes that visible.
"""

_VIS = (
    "const vis = el => el.getClientRects().length > 0 && "
    "getComputedStyle(el).visibility !== 'hidden';"
)


def _page(body: str) -> str:
    return "(() => {" + _VIS + body + "})()"


JS_HOOK = r"""
(() => {
  if (window.__vch_installed) return "already";
  const api = window.api;
  if (!api || !api.shell || typeof api.shell.openUrl !== "function") return "no-api";
  window.__vch_urls = [];
  window.__vch_origOpenUrl = api.shell.openUrl.bind(api.shell);
  api.shell.openUrl = function (u) {
    try { window.__vch_urls.push(String(u)); } catch (e) {}
    return Promise.resolve();
  };
  window.__vch_installed = true;
  return "installed";
})()
"""

JS_UNHOOK = r"""
(() => {
  if (!window.__vch_installed) return "not-installed";
  try { window.api.shell.openUrl = window.__vch_origOpenUrl; } catch (e) {}
  window.__vch_installed = false;
  return "restored";
})()
"""

JS_PROMPT = _page(r"""
  const btns = [...document.querySelectorAll('button')].filter(vis);
  const dm = btns.find(b => /^download manually$/i.test((b.innerText || '').trim()));
  const dlg = [...document.querySelectorAll('[role=dialog],.modal')]
      .find(d => /download mod/i.test(d.innerText || ''));
  const text = dlg ? dlg.innerText.replace(/\s+/g, ' ') : '';
  const m = text.match(/(\d+)\s*\/\s*(\d+)/);
  const n = text.match(/download mod\s+(.+?)\s+by\s+/i);
  return {
    hasPrompt: !!dm,
    index: m ? parseInt(m[1], 10) : null,
    total: m ? parseInt(m[2], 10) : null,
    modName: n ? n[1] : null,
    text: text.slice(0, 240)
  };
""")

JS_CLICK_DOWNLOAD_MANUALLY = _page(r"""
  const b = [...document.querySelectorAll('button')]
      .find(e => vis(e) && /^download manually$/i.test((e.innerText || '').trim()));
  if (!b) return "none";
  b.click();
  return "clicked";
""")

JS_CLICK_INSTALLER = _page(r"""
  for (const nav of [...document.querySelectorAll('.fomod-nav-buttons')].filter(vis)) {
    const btns = [...nav.querySelectorAll('button')].filter(vis);
    const fin = btns.find(b => /^(finish|install)$/i.test((b.innerText || '').trim()));
    const nxt = btns.find(b => /^next$/i.test((b.innerText || '').trim()));
    const t = fin || nxt;
    if (t) { t.click(); return "clicked:" + t.innerText.trim(); }
  }
  return "none";
""")

JS_CLICK_SKIP_MOD = _page(r"""
  const b = [...document.querySelectorAll('button')].filter(vis)
      .find(e => /^skip mod$/i.test((e.innerText || '').trim()));
  if (!b) return "none";
  b.click();
  return "clicked";
""")

JS_TAKE_URLS = r"""
(() => {
  const u = window.__vch_urls || [];
  window.__vch_urls = [];
  return u;
})()
"""
