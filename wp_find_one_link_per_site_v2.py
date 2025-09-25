#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse, csv, re, threading
from urllib.parse import urlparse, urljoin, quote_plus
import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) WP-Finder/3.4-fast-url-notes"
TIMEOUT = 14
MAX_HTML_BYTES = 200_000  # stream up to this many bytes when scanning for external links
DEFAULT_WORKERS = 8

# ---------------- Keyword expansion + scoring ----------------
BASE_SYNS = {
    "car": ["car", "auto", "automotive", "vehicle"],
    "paint": ["paint", "painting", "repaint", "spray paint", "color", "coating", "touch up", "touch-up"],
    "design": ["design", "styling", "aesthetic", "look"],
    "outdoor": ["outdoor", "exterior", "outside", "garden", "landscape", "patio", "yard"],
    "polish": ["polish", "buff", "compound"],
    "detailing": ["detailing", "detail", "paint correction"],
    "ceramic": ["ceramic", "ceramic coating", "nano coating"],
    "body": ["bodywork", "body work", "body shop", "panel"],
}

def expand_keyword(kw: str):
    kw = kw.strip()
    terms = set([kw])
    if " " in kw: terms.add(kw.replace(" ", "-"))
    if kw.endswith("s"): terms.add(kw[:-1])
    tokens = re.split(r"[\s\-_/]+", kw.lower())
    tok_syns = []
    for t in tokens:
        syns = BASE_SYNS.get(t, [t])
        tok_syns.append(set(syns))
    for syns in tok_syns:
        for s in syns:
            terms.add(s)
            if " " in s: terms.add(s.replace(" ", "-"))
    if len(tok_syns) >= 2:
        for a in tok_syns[0]:
            for b in tok_syns[1]:
                pair = f"{a} {b}".strip()
                terms.add(pair); terms.add(pair.replace(" ", "-"))
    return {t for t in terms if t}

def ensure_root(site: str) -> str:
    site = site.strip().rstrip("/")
    if not site.startswith("http"): site = "https://" + site
    p = urlparse(site)
    return f"{p.scheme}://{p.netloc}"

def score_text(title: str, snippet: str, kw: str) -> float:
    title = (title or "").lower()
    snippet = (snippet or "").lower()
    terms = expand_keyword(kw)

    def term_hits(text: str, weight_contains=1.0, weight_word=1.4):
        sc = 0.0
        for t in terms:
            t_l = t.lower()
            if t_l in text: sc += weight_contains
            if re.search(rf"\b{re.escape(t_l)}\b", text): sc += weight_word
        return sc

    score = 0.0
    score += 2.2 * term_hits(title, 1.0, 1.6)
    score += 1.0 * term_hits(snippet, 0.6, 1.1)
    return score

def score_url(url: str, kw: str) -> float:
    url = (url or "").lower()
    terms = expand_keyword(kw)
    slug = url.split("//",1)[-1]
    sc = 0.0
    parts = re.split(r"[-/_]+", slug)
    for t in terms:
        t_l = t.lower().replace(" ", "-")
        if t_l in slug: sc += 1.2
        if any(tok == t_l for tok in parts): sc += 0.8
    return sc

# ---------------- Thread-local session ----------------
_thread_local = threading.local()
def sess():
    s = getattr(_thread_local, "session", None)
    if s is None:
        s = requests.Session()
        s.headers.update({"User-Agent": UA})
        _thread_local.session = s
    return s

def get(url, params=None, stream=False):
    return sess().get(url, params=params, timeout=TIMEOUT, allow_redirects=True, stream=stream)

# ---------------- External link checker (streaming + early exit) ----------------
IGNORE_HOSTS = [
    'facebook.com','x.com','twitter.com','instagram.com','pinterest.com',
    'linkedin.com','tumblr.com','reddit.com','threads.net',
    'whatsapp.com','wa.me','api.whatsapp.com','web.whatsapp.com',
    't.me','telegram.me','telegram.org','discord.com',
    'youtube.com','youtu.be','tiktok.com',
    'messenger.com','skype.com','viber.com','line.me',
    'vk.com','ok.ru','weibo.com','qq.com',
    'google.com',
    'theme-sphere.com',
    'wordpress.org',
    'addtoany.com',
    'getpocket.com',
    'demo.mythemeshop.com',
]
IGNORE_SUFFIXES = [".stackstaging.com"]

def normalize_host(h):
    if not h: return ''
    return h.lower().lstrip("www.")

def extract_host(href, base_host):
    try:
        href = href.strip()
        if href.startswith(("http://","https://")):
            return normalize_host(urlparse(href).netloc)
        if href.startswith("//"):
            return normalize_host(urlparse("http:" + href).netloc)
        return base_host or ''
    except:
        return ''

def is_skippable(href):
    if href.startswith(("#","mailto:","tel:","javascript:","data:")):
        return True
    if href.startswith(("https://wa.me/","http://wa.me/","//wa.me/")):
        return True
    return False

def is_ignored_domain(link_host):
    if any(link_host == ih or link_host.endswith("." + ih) for ih in IGNORE_HOSTS):
        return True
    if any(link_host.endswith(suffix) for suffix in IGNORE_SUFFIXES):
        return True
    return False

_href_re = re.compile(r'<a[^>]+href=["\'](.*?)["\']', re.IGNORECASE)

def has_external_link(page_url):
    """Return (has_external, first_external_url). Streams up to MAX_HTML_BYTES and exits early on first valid external link."""
    try:
        r = get(page_url, stream=True)
        page_host = normalize_host(urlparse(page_url).netloc)
        buf = b""
        for chunk in r.iter_content(chunk_size=8192):
            if not chunk:
                break
            buf += chunk
            if len(buf) >= MAX_HTML_BYTES:
                break
            text = buf.decode(errors="ignore")
            for href in _href_re.findall(text):
                href = href.replace("&amp;", "&").strip()
                if not href: continue
                if not href.startswith(("http://","https://","//")): continue
                if is_skippable(href): continue
                link_host = extract_host(href, page_host)
                if not link_host: continue
                is_internal = (link_host == page_host) or link_host.endswith("." + page_host)
                if is_ignored_domain(link_host): continue
                if not is_internal:
                    r.close()
                    return True, href
        # Final pass on whatever we buffered
        text = buf.decode(errors="ignore")
        for href in _href_re.findall(text):
            href = href.replace("&amp;", "&").strip()
            if not href: continue
            if not href.startswith(("http://","https://","//")): continue
            if is_skippable(href): continue
            link_host = extract_host(href, page_host)
            if not link_host: continue
            is_internal = (link_host == page_host) or link_host.endswith("." + page_host)
            if is_ignored_domain(link_host): continue
            if not is_internal:
                return True, href
        return False, ""
    except Exception:
        return False, ""

# ---------------- WordPress fetchers ----------------
def fetch_wp_search(base, kw):
    url = urljoin(base, "/wp-json/wp/v2/search")
    params = {"search": kw, "per_page": 10}
    r = get(url, params=params)
    if r.status_code != 200:
        return None
    items = r.json()
    best = None
    for it in items:
        link = it.get("url") or it.get("link")
        title = (it.get("title") or "").strip()
        if not link: continue
        s = score_text(title, "", kw) + 0.8 * score_url(link, kw)
        cand = {"url": link, "title": title, "snippet": "", "score": s, "method": "wp-json search"}
        if not best or s > best["score"]:
            best = cand
    return best

def fetch_wp_posts(base, kw):
    url = urljoin(base, "/wp-json/wp/v2/posts")
    params = {"search": kw, "per_page": 10, "_fields": "link,title,excerpt"}
    r = get(url, params=params)
    if r.status_code != 200:
        return None
    items = r.json()
    best = None
    for it in items:
        link = it.get("link")
        title = (it.get("title") or {}).get("rendered", "").strip()
        snippet_html = (it.get("excerpt") or {}).get("rendered", "")
        snippet = BeautifulSoup(snippet_html or "", "html.parser").get_text(" ", strip=True)
        if not link: continue
        s = score_text(title, snippet, kw) + 0.8 * score_url(link, kw)
        cand = {"url": link, "title": title, "snippet": snippet, "score": s, "method": "wp-json posts"}
        if not best or s > best["score"]:
            best = cand
    return best

def fetch_by_taxonomy(base, kw):
    best = None
    for endpoint, field in [("/wp-json/wp/v2/tags", "tags"), ("/wp-json/wp/v2/categories", "categories")]:
        try:
            r = get(urljoin(base, endpoint), params={"search": kw, "per_page": 5})
            if r.status_code != 200:
                continue
            terms = r.json()
            for term in terms[:3]:
                term_id = term.get("id")
                if not term_id: continue
                posts_url = urljoin(base, "/wp-json/wp/v2/posts")
                params = {"per_page": 10, "_fields": "link,title,excerpt"}
                if field == "tags": params["tags"] = term_id
                else: params["categories"] = term_id
                rr = get(posts_url, params=params)
                if rr.status_code != 200:
                    continue
                for it in rr.json():
                    link = it.get("link")
                    title = (it.get("title") or {}).get("rendered","").strip()
                    snippet_html = (it.get("excerpt") or {}).get("rendered","")
                    snippet = BeautifulSoup(snippet_html or "", "html.parser").get_text(" ", strip=True)
                    s = score_text(title, snippet, kw) + 0.9 * score_url(link, kw)
                    s += 0.8  # taxonomy bonus
                    cand = {"url": link, "title": title, "snippet": snippet, "score": s, "method": f"wp-json {field[:-1]}"}
                    if not best or s > best["score"]:
                        best = cand
        except Exception:
            continue
    return best

def fetch_theme_search(base, kw):
    search_url = base + "/?s=" + quote_plus(kw)
    r = get(search_url)
    if r.status_code != 200:
        return None
    soup = BeautifulSoup(r.text, "html.parser")
    best = None
    selectors = [
        "h1.entry-title a","h2.entry-title a","h3.entry-title a",
        ".entry-title a",".post-title a",".card-title a",
        "article h2 a","article h3 a","article .entry-title a"
    ]
    candidates = []
    for sel in selectors:
        for a in soup.select(sel):
            href = a.get("href")
            text = a.get_text(strip=True)
            if not href or not text: continue
            if not href.startswith("http"): href = urljoin(base, href)
            if re.search(r"/(category|tag|author|search)/", href): continue
            candidates.append((href, text))
    if not candidates:
        for art in soup.select("article"):
            a = art.find("a", href=True)
            if a:
                href = a["href"]
                text = a.get_text(strip=True)
                if not href.startswith("http"): href = urljoin(base, href)
                if not re.search(r"/(category|tag|author|search)/", href):
                    candidates.append((href, text))
    for href, text in candidates[:15]:
        snippet = ""
        s = score_text(text, "", kw) + 1.0 * score_url(href, kw)
        try:
            parent = soup.find("a", href=lambda u: u and href in u)
            if parent:
                par = parent.find_parent(["article","div","li"])
                if par:
                    snippet = par.get_text(" ", strip=True)[:180]
                    s += 0.6 * score_text("", snippet, kw)
        except Exception:
            pass
        cand = {"url": href, "title": text, "snippet": snippet, "score": s, "method": "theme search"}
        if not best or s > best["score"]:
            best = cand
    return best

# ---------------- Site selection (with external-link filter) ----------------
def find_one_for_site(site, kw, threshold=2.0, mode="strict", require_external=True):
    base = ensure_root(site)
    candidates = []

    for fetcher in (fetch_wp_posts, fetch_wp_search, fetch_by_taxonomy, fetch_theme_search):
        try:
            hit = fetcher(base, kw)
            if hit: candidates.append(hit)
        except Exception:
            pass

    if not candidates:
        return {"url": "", "notes": "no relevant post"}

    best_any = max(candidates, key=lambda x: x.get("score", 0.0))

    if require_external:
        filtered = []
        first_ext_note = ""
        for c in candidates:
            ok, first_ext = has_external_link(c["url"])
            if ok:
                c["_first_ext"] = first_ext
                filtered.append(c)
        candidates = filtered
        if not candidates:
            return {"url": "", "notes": "no external links in candidates"}

    best = max(candidates, key=lambda x: x.get("score", 0.0))
    note = best.get("_first_ext","")

    if mode == "loose":
        return {"url": best["url"], "notes": note}
    else:
        if best["score"] >= threshold:
            return {"url": best["url"], "notes": note}
        # below threshold but still return reason
        return {"url": "", "notes": (note or "below threshold")}

# ---------------- Worker + Main ----------------
def worker(site, idx, kw, threshold, mode, require_external):
    try:
        res = find_one_for_site(site, kw, threshold, mode, require_external)
        res["_idx"] = idx
        return res
    except Exception as e:
        return {"url": "", "notes": str(e), "_idx": idx}

def main():
    ap = argparse.ArgumentParser(description="Find one relevant WP post per site (fast). Output CSV: url,notes")
    ap.add_argument("--sites", required=True, help="Text file with one site per line.")
    ap.add_argument("--keyword", required=True, help="Search keyword.")
    ap.add_argument("--out", default="results.csv", help="Output CSV file.")
    ap.add_argument("--threshold", type=float, default=2.0, help="Score threshold for strict mode.")
    ap.add_argument("--mode", choices=["strict","loose"], default="strict", help="In loose mode, return best even if below threshold.")
    ap.add_argument("--require-external", choices=["yes","no"], default="yes", help="Require at least one external link on candidate page.")
    ap.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help=f"Parallel threads (default {DEFAULT_WORKERS}).")
    args = ap.parse_args()

    require_external = (args.require_external.lower() == "yes")

    with open(args.sites, "r", encoding="utf-8") as f:
        sites = [ln.strip() for ln in f if ln.strip()]

    results = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        futs = {ex.submit(worker, site, idx, args.keyword, args.threshold, args.mode, require_external): idx
                for idx, site in enumerate(sites)}
        for fut in as_completed(futs):
            results.append(fut.result())

    # restore input order
    results.sort(key=lambda r: r.get("_idx", 10**9))

    # Write ONLY two columns: url, notes
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["url", "notes"])
        for r in results:
            w.writerow([r.get("url",""), r.get("notes","")])

    print(f"Done. Wrote {len(results)} rows to {args.out}")

if __name__ == "__main__":
    main()
