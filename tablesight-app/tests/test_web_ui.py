"""Browser tests for web/ (Playwright + chromium). Skips gracefully when either is unavailable."""
import glob
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

try:
    from playwright.sync_api import sync_playwright
except Exception:  # noqa: BLE001  # pragma: no cover
    sync_playwright = None

def _find_chrome():
    found = sorted(glob.glob("/opt/pw-browsers/chromium-*/chrome-linux*/chrome"))
    if found:
        return found[-1]
    if sync_playwright is None:
        return None
    try:  # Playwright's own managed browser (what `playwright install chromium` provides, e.g. in CI)
        with sync_playwright() as p:
            path = p.chromium.executable_path
        return path if path and os.path.exists(path) else None
    except Exception:  # noqa: BLE001  # any launch/probe failure means 'not available'
        return None


CHROME = _find_chrome()

if os.environ.get("REQUIRE_UI_TESTS") and (sync_playwright is None or not CHROME):
    raise RuntimeError("REQUIRE_UI_TESTS=1 but playwright/chromium not found; UI tests must not skip in CI")
pytestmark = pytest.mark.skipif(sync_playwright is None or not CHROME, reason="playwright/chromium not available")

PW = "demo-password-123"
OWNER, GM = "owner@demo.tablesight.test", "gm@demo.tablesight.test"

CONTRAST_JS = """() => {
  const parse = c => { const m = c.match(/rgba?\\(([^)]+)\\)/); if (!m) return null; const p = m[1].split(/[ ,\\/]+/).filter(Boolean).map(Number); return {r:p[0],g:p[1],b:p[2],a:p.length>3?p[3]:1}; };
  const lum = ({r,g,b}) => { const f = v => { v/=255; return v<=0.03928? v/12.92 : Math.pow((v+0.055)/1.055,2.4); }; return 0.2126*f(r)+0.7152*f(g)+0.0722*f(b); };
  const over = (top, bot) => ({r: top.r*top.a+bot.r*(1-top.a), g: top.g*top.a+bot.g*(1-top.a), b: top.b*top.a+bot.b*(1-top.a), a:1});
  const bgOf = el => { let stack=[]; for (let e=el; e; e=e.parentElement) { const c=parse(getComputedStyle(e).backgroundColor); if (c && c.a>0) { stack.push(c); if (c.a===1) break; } }
    let base={r:255,g:255,b:255,a:1}; for (let i=stack.length-1;i>=0;i--) base=over(stack[i],base); return base; };
  const bad = []; let n = 0;
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const seen = new Set();
  while (walker.nextNode()) {
    const tx = walker.currentNode; if (!tx.textContent.trim()) continue;
    const el = tx.parentElement; if (seen.has(el)) continue; seen.add(el);
    const cs = getComputedStyle(el); const r = el.getBoundingClientRect();
    if (cs.visibility==='hidden' || cs.display==='none' || (r.width===0&&r.height===0) || el.closest('.sr,.skip')) continue;
    const fg = parse(cs.color); const bg = bgOf(el); const f = over(fg, bg);
    const L1 = lum(f), L2 = lum(bg), ratio = (Math.max(L1,L2)+0.05)/(Math.min(L1,L2)+0.05);
    const px = parseFloat(cs.fontSize), bold = parseInt(cs.fontWeight) >= 700, large = px >= 24 || (px >= 18.66 && bold);
    n++; if (ratio < (large ? 3 : 4.5)) bad.push({text: tx.textContent.trim().slice(0,30), ratio: +ratio.toFixed(2), tag: el.tagName+'.'+el.className});
  }
  return {n, bad};
}"""

A11Y_JS = """() => {
  const name = el => (el.getAttribute('aria-label') || (el.labels && [...el.labels].map(l=>l.textContent).join(' ')) || el.textContent || el.getAttribute('title') || '').trim();
  const bad = [];
  document.querySelectorAll('input:not([type=hidden]),select,textarea').forEach(e => { if (!name(e)) bad.push('input#'+e.id); });
  document.querySelectorAll('button,a[href]').forEach(e => { if (!name(e)) bad.push(e.tagName+'.'+e.className); });
  document.querySelectorAll('svg').forEach(s => { if (s.getAttribute('aria-hidden')!=='true' && !s.getAttribute('aria-label')) bad.push('svg'); });
  const ids = [...document.querySelectorAll('[id]')].map(e=>e.id); const dup = ids.filter((x,i)=>ids.indexOf(x)!==i);
  return {bad, dup, lang: document.documentElement.lang, hasH1: !!document.querySelector('h1'), hasMain: !!document.querySelector('main')};
}"""


@pytest.fixture(scope="module")
def servers():
    import seed_demo
    fresh_app, info = seed_demo.build_demo()
    stale_app, _ = seed_demo.build_demo(stale=True)
    a, b = seed_demo.serve(fresh_app), seed_demo.serve(stale_app)
    yield {"fresh": a.url + "/app/", "stale": b.url + "/app/", "api": a.url, "info": info}
    a.stop()
    b.stop()


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        try:
            br = p.chromium.launch(executable_path=CHROME, args=["--no-sandbox", "--no-proxy-server"])
        except Exception as e:  # noqa: BLE001  # pragma: no cover
            pytest.skip(f"chromium cannot launch: {e}")
        yield br
        br.close()


@pytest.fixture
def page(browser):
    ctx = browser.new_context(viewport={"width": 375, "height": 740})
    pg = ctx.new_page()
    yield pg
    ctx.close()


_TOKENS = {}


def api_token(url, email):
    """One real API login per user per server (the API rate-limits logins); UI-login flows are tested explicitly."""
    import urllib.request
    base = url.split("/app/")[0]
    if (base, email) not in _TOKENS:
        req = urllib.request.Request(base + "/login", data=json.dumps({"email": email, "password": PW}).encode(),
                                     headers={"Content-Type": "application/json"})
        _TOKENS[(base, email)] = json.loads(urllib.request.urlopen(req).read())["token"]
    return _TOKENS[(base, email)]


def login(pg, url, email=OWNER, totp=None, lang="en", theme="dark"):
    """Sign in through the real form only when a totp is supplied; otherwise reuse a session token."""
    if totp is None:
        pg.add_init_script(f"try{{sessionStorage.setItem('ts.tok','{api_token(url, email)}')}}catch(e){{}}")
        pg.goto(f"{url}?lang={lang}&theme={theme}")
        return
    pg.goto(f"{url}?lang={lang}&theme={theme}")
    pg.fill("#email", email)
    pg.fill("#password", PW)
    pg.fill("#totp", totp)
    pg.click("button[type=submit]")


def rows(pg):
    pg.wait_for_selector(".floor .row")
    return pg.query_selector_all(".floor .row")


def test_login_error_then_success_and_floor_sorted_by_wait(servers, page):
    page.goto(servers["fresh"] + "?lang=en")
    assert page.locator("html").get_attribute("data-theme") == "dark"  # dark by default
    page.fill("#email", OWNER)
    page.fill("#password", "wrong-password-1")
    page.click("button[type=submit]")
    page.wait_for_selector("#login-err span")
    assert "don't match" in page.inner_text("#login-err")
    page.fill("#password", PW)
    page.click("button[type=submit]")
    rs = rows(page)
    assert "DEMO MODE" in page.inner_text("#demo")
    seated = [r for r in rs if r.get_attribute("data-status") in ("attn", "ok", "unk")]
    waits = [int(r.query_selector(".wait").inner_text().split()[0]) for r in seated]
    assert waits == sorted(waits, reverse=True) and len(waits) >= 5
    assert "to check in on" in page.inner_text("#sum")
    # status is never colour alone: every row carries an svg shape AND status text
    for r in rs:
        assert r.query_selector("svg.ico") and r.query_selector(".st").inner_text().strip()
    assert {"attn", "ok", "unk", "clean", "idle"} <= {r.get_attribute("data-status") for r in rs}
    # low-confidence state is worded, not just styled
    assert "Not sure" in page.locator('[data-table="T5"]').inner_text()


def test_two_factor_field(servers, page):
    totp = __import__("tablesight.platform.security", fromlist=["x"]).totp(servers["info"]["totp_secret"])
    page.goto(servers["fresh"])
    assert page.get_by_label("Authenticator code").is_visible()
    page.fill("#email", GM)
    page.fill("#password", PW)
    page.click("button[type=submit]")
    page.wait_for_selector("#login-err span")
    assert "6-digit" in page.inner_text("#login-err")
    assert page.evaluate("document.activeElement.id") == "totp"  # focus moved to the field that needs fixing
    page.fill("#totp", totp)
    page.click("button[type=submit]")
    rows(page)


@pytest.mark.parametrize("hash_", ["", "#/host", "#/tv", "#/settings"])
def test_no_horizontal_scroll_at_375(servers, page, hash_):
    page.goto(servers["fresh"])
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")  # login
    login(page, servers["fresh"])
    rows(page)
    page.evaluate(f"location.hash = '{hash_ or '#/floor'}'")
    page.wait_for_timeout(600)
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth"), hash_


def test_rtl_layout_flips(servers, browser):
    pos = {}
    for lang in ("en", "ar"):
        ctx = browser.new_context(viewport={"width": 375, "height": 740})
        pg = ctx.new_page()
        login(pg, servers["fresh"], lang=lang)
        rows(pg)
        assert pg.evaluate("document.documentElement.dir") == ("rtl" if lang == "ar" else "ltr")
        pos[lang] = pg.evaluate("""() => { const r=document.querySelector('.floor .row'); const n=r.querySelector('.name').getBoundingClientRect(); const w=r.querySelector('.wait').getBoundingClientRect(); return {name:n.left, wait:w.left}; }""")
        if lang == "ar":
            assert "طاولة" in pg.get_attribute(".floor .row .name", "aria-label")
            assert pg.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
        ctx.close()
    assert pos["en"]["wait"] > pos["en"]["name"]   # LTR: wait on the right of the name
    assert pos["ar"]["wait"] < pos["ar"]["name"]   # RTL: mirrored


def test_stale_state_when_device_last_seen_old(servers, browser):
    ctx = browser.new_context(viewport={"width": 375, "height": 740})
    pg = ctx.new_page()
    login(pg, servers["stale"])
    rows(pg)
    pg.wait_for_selector("#stale-banner")
    txt = pg.inner_text("#stale-banner")
    assert "Camera offline" in txt and "last known" in txt.lower()
    assert pg.query_selector(".row.stale") and "last known" in pg.locator(".row.stale").first.inner_text()
    ctx.close()
    pg2 = browser.new_context().new_page()
    login(pg2, servers["fresh"])
    rows(pg2)
    assert pg2.query_selector("#stale-banner") is None


def test_error_state_when_offline_keeps_last_data(servers, page):
    login(page, servers["fresh"])
    rows(page)
    page.route("**/events*", lambda route: route.abort())
    page.evaluate("document.querySelector('#modes a[href=\"#/host\"]').click()")  # remount -> refresh fails
    page.wait_for_selector(".banner.bad, .state")
    assert "Can't reach TableSight" in page.inner_text("main")


def test_acknowledge_and_wrong_alert(servers, page):
    login(page, servers["fresh"])
    rows(page)
    first = page.locator(".row.attn").first
    first.get_by_role("button", name="I'll check in").click()
    page.wait_for_selector(".ackd")
    assert "Thanks for covering" in page.inner_text(".ackd")
    # wrong alert -> reason chooser -> thanks
    page.locator(".row.attn .btn.sec").first.click()
    page.get_by_role("button", name="Guests had left").click()
    page.wait_for_selector(".ackd:has-text('helps us')")
    assert 'role="status"' in page.inner_html(".toasts") or page.query_selector(".toast")


def test_owner_settings_roundtrip(servers, page):
    login(page, servers["fresh"])
    rows(page)
    page.click("#modes a[href='#/settings']")
    page.wait_for_selector("input[name=sa]")
    assert page.get_by_role("radio", name="Team only").is_checked()  # recommended default
    page.get_by_label("Off", exact=False).first.check()
    page.fill("#ret", "7")
    page.click("text=Save changes")
    page.wait_for_selector(".ok-msg:has-text('Saved.')")
    tok = page.evaluate("sessionStorage.getItem('ts.tok')")
    import urllib.request
    req = urllib.request.Request(servers["api"] + "/locations", headers={"Authorization": "Bearer " + tok})
    loc = json.loads(urllib.request.urlopen(req).read())[0]
    assert loc["staff_analytics"] == "off" and loc["retention_days"] == 7


def test_tv_mode_large_type_and_no_controls(servers, page):
    login(page, servers["fresh"])
    rows(page)
    page.set_viewport_size({"width": 1920, "height": 1080})
    page.evaluate("location.hash='#/tv'")
    page.wait_for_selector("body.m-tv .row")
    assert float(page.evaluate("parseFloat(getComputedStyle(document.querySelector('.row .name')).fontSize)")) >= 40
    assert page.query_selector(".row .acts") is None  # tables, never people; nothing to tap
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")


def test_host_mode_grid(servers, page):
    login(page, servers["fresh"])
    rows(page)
    page.set_viewport_size({"width": 1024, "height": 768})
    page.evaluate("location.hash='#/host'")
    page.wait_for_selector("body.m-host .row")
    cols = page.evaluate("getComputedStyle(document.querySelector('.floor')).gridTemplateColumns.split(' ').length")
    assert cols >= 3


@pytest.mark.parametrize("theme", ["dark", "light"])
@pytest.mark.parametrize("lang", ["en", "ar"])
def test_contrast_and_labels(servers, page, theme, lang):
    page.goto(servers["fresh"] + f"?lang={lang}&theme={theme}")
    page.wait_for_selector("#email")  # sample only after first render (was a race)
    for stage in ("login", "floor", "settings"):
        if stage == "floor":
            login(page, servers["fresh"], lang=lang, theme=theme)
            rows(page)
        if stage == "settings":
            page.evaluate("location.hash='#/settings'")
            page.wait_for_selector("input[name=sa]")
        res = page.evaluate(CONTRAST_JS)
        assert res["n"] > 5 and not res["bad"], (theme, lang, stage, res["bad"][:5])
        a = page.evaluate(A11Y_JS)
        assert not a["bad"] and not a["dup"] and a["hasMain"] and a["hasH1"] and a["lang"] == lang, (stage, a)


def test_keyboard_focus_visible(servers, page):
    page.goto(servers["fresh"])
    page.wait_for_selector("#email")
    page.evaluate("document.activeElement.blur()")
    seen = []
    for _ in range(6):
        page.keyboard.press("Tab")
        seen.append(page.evaluate("""() => { const e=document.activeElement; const cs=getComputedStyle(e); return {id:e.id||e.tagName, w:parseFloat(cs.outlineWidth), s:cs.outlineStyle}; }"""))
    focused = [s for s in seen if s["id"] in ("email", "password", "totp")]
    assert len(focused) == 3 and all(s["s"] != "none" and s["w"] >= 2 for s in focused), seen
