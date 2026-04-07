#!/usr/bin/env python3
"""
ai-scan v1.0 — Real-time AI News Aggregator
============================================
Multi-source AI news aggregation, faster than RSS.
Fetches, deduplicates, scores, and summarizes the latest AI news.

Usage:
    python3 ai_scan.py                    # All sources, last 12h
    python3 ai_scan.py --quick            # HN + Reddit, last 2h
    python3 ai_scan.py --deep             # All sources, last 48h
    python3 ai_scan.py --no-summarize     # Skip AI summarization

Dependencies: pip3 install requests
"""

import sys
import os
import json
import time
import hashlib
import sqlite3
import argparse
import re
import math
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.parse import quote_plus
from email.utils import parsedate_to_datetime

try:
    import requests
except ImportError:
    print("Error: requests not installed. Run: pip3 install requests", file=sys.stderr)
    sys.exit(1)

# ============================================
# Configuration
# ============================================
QWEN_CONFIG = {
    "api_key": os.environ.get("DASHSCOPE_API_KEY", ""),
    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "model": "qwen-turbo",
}

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(SCRIPT_DIR, "ai_scan.db")

AI_KEYWORDS = [
    "AI", "LLM", "GPT", "Claude", "Gemini", "Llama", "Mistral", "Qwen",
    "OpenAI", "Anthropic", "DeepMind", "machine learning", "deep learning",
    "neural network", "transformer", "AGI", "artificial intelligence",
    "NLP", "computer vision", "diffusion", "RAG", "fine-tuning",
    "inference", "training", "GPU", "TPU", "CUDA", "model",
    "chatbot", "agent", "multimodal", "embedding", "RLHF",
    "breakthrough", "leak", "open source", "benchmark", "SOTA",
]

HIGH_VALUE_KEYWORDS = [
    "Claude", "GPT-5", "GPT-4", "AGI", "breakthrough", "leak",
    "open source", "SOTA", "state-of-the-art", "released", "launch",
    "benchmark", "frontier", "Gemma", "Llama 4",
]

STOP_WORDS = {"the", "a", "an", "is", "are", "was", "were", "in", "on", "at",
              "to", "for", "of", "and", "or", "but", "not", "no", "new", "has",
              "have", "had", "its", "it", "this", "that", "from", "with", "by",
              "as", "be", "been", "being", "do", "does", "did", "will", "would",
              "can", "could", "may", "might", "shall", "should", "how", "what",
              "which", "who", "when", "where", "why", "than", "then", "so",
              "if", "more", "most", "very", "just", "about", "up", "out",
              "all", "into", "over", "after", "before", "between", "under",
              "your", "you", "we", "they", "he", "she", "our", "my", "me",
              "i", "us", "them", "him", "her", "his", "their"}

SOURCE_WEIGHTS = {
    "hn": 0.9, "reddit": 0.8, "github": 0.7,
    "arxiv": 0.7, "hf": 0.65, "blogs": 0.6, "x": 0.85,
}

# ============================================
# Database
# ============================================
def get_db():
    db = sqlite3.connect(DB_PATH, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("""
        CREATE TABLE IF NOT EXISTS seen_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url_hash TEXT UNIQUE NOT NULL,
            title_hash TEXT NOT NULL,
            sim_key TEXT NOT NULL,
            source TEXT NOT NULL,
            title TEXT NOT NULL,
            url TEXT,
            first_seen INTEGER NOT NULL,
            last_seen INTEGER NOT NULL,
            relevance_score REAL DEFAULT 0,
            summary TEXT
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_url_hash ON seen_items(url_hash)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_sim_key ON seen_items(sim_key)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_first_seen ON seen_items(first_seen)")
    db.commit()
    return db


def db_check_new(db, items):
    new_items = []
    for item in items:
        url_hash = hash_url(item.get("url", ""))
        # Check URL hash via SQL
        row = db.execute("SELECT 1 FROM seen_items WHERE url_hash = ?", (url_hash,)).fetchone()
        if row:
            continue
        # Check sim_key for 48h dedup
        sim_key = compute_sim_key(item["title"])
        cutoff = int(time.time()) - 172800
        row2 = db.execute("SELECT 1 FROM seen_items WHERE sim_key = ? AND first_seen > ?", (sim_key, cutoff)).fetchone()
        if row2:
            continue
        item["_url_hash"] = url_hash
        item["_sim_key"] = sim_key
        new_items.append(item)
    return new_items


def db_record(db, items):
    now = int(time.time())
    for item in items:
        try:
            db.execute(
                "INSERT OR IGNORE INTO seen_items (url_hash, title_hash, sim_key, source, title, url, first_seen, last_seen, relevance_score) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (item["_url_hash"], hash_title(item["title"]), item["_sim_key"],
                 item["source"], item["title"], item.get("url", ""), now, now, item.get("score", 0))
            )
        except sqlite3.IntegrityError:
            pass
    db.commit()


def db_prune(db, days=30):
    cutoff = int(time.time()) - days * 86400
    db.execute("DELETE FROM seen_items WHERE first_seen < ?", (cutoff,))
    db.commit()


# ============================================
# Helpers
# ============================================
def hash_url(url):
    normalized = re.sub(r"^https?://(www\.)?", "", url).rstrip("/?")
    return hashlib.sha256(normalized.encode()).hexdigest()


def hash_title(title):
    normalized = re.sub(r"[^\w\s]", "", title.lower().strip())
    return hashlib.sha256(normalized.encode()).hexdigest()


def compute_sim_key(title):
    words = re.sub(r"[^\w\s]", "", title.lower()).split()
    significant = [w for w in words if w not in STOP_WORDS and len(w) > 1]
    return " ".join(significant[:6])


def safe_fetch(url, headers=None, timeout=10, fallback=None):
    try:
        resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        if resp.status_code == 429:
            time.sleep(5)
            resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        if resp.status_code != 200:
            log(f"HTTP {resp.status_code} from {url[:80]}")
            return fallback
        return resp
    except Exception:
        return fallback


def age_string(timestamp):
    hours_ago = (time.time() - timestamp) / 3600
    if hours_ago < 1:
        return f"{int(hours_ago * 60)}m ago"
    elif hours_ago < 24:
        return f"{hours_ago:.0f}h ago"
    else:
        return f"{hours_ago / 24:.0f}d ago"


def log(msg):
    print(f"  [scan] {msg}", file=sys.stderr)


# ============================================
# Collectors
# ============================================
def collect_hn(hours=12):
    """Hacker News via Algolia API + Firebase top stories"""
    log("Fetching Hacker News...")
    items = []
    cutoff = int(time.time() - hours * 3600)

    # Algolia search by date — short queries (Algolia uses AND by default)
    query_tags = "(story,show_hn)"
    algolia_queries = ["AI", "LLM", "Claude", "Gemini", "OpenAI", "GPT"]
    seen_ids = set()
    for q in algolia_queries:
        url = (f"https://hn.algolia.com/api/v1/search_by_date?query={quote_plus(q)}"
               f"&tags={query_tags}&numericFilters=created_at_i%3E{cutoff}&hitsPerPage=20")
        resp = safe_fetch(url)
        if resp:
            try:
                for hit in resp.json().get("hits", []):
                    oid = hit.get("objectID", "")
                    if oid in seen_ids:
                        continue
                    seen_ids.add(oid)
                    ts = hit.get("created_at_i", 0)
                    if ts < cutoff:
                        continue
                    items.append({
                        "source": "hn", "source_name": "Hacker News",
                        "title": hit.get("title", ""),
                        "url": hit.get("url") or f"https://news.ycombinator.com/item?id={oid}",
                        "body": hit.get("story_text", "") or "",
                        "timestamp": ts,
                        "metadata": {
                            "points": hit.get("points", 0) or 0,
                            "comments": hit.get("num_comments", 0) or 0,
                        }
                    })
            except Exception as e:
                log(f"H Algolia parse error: {e}")

    # Firebase top stories (fastest signal)
    top_resp = safe_fetch("https://hacker-news.firebaseio.com/v0/topstories.json", timeout=5)
    if top_resp:
        try:
            top_ids = top_resp.json()[:30]
            for i, sid in enumerate(top_ids):
                if i > 0 and i % 5 == 0:
                    time.sleep(0.2)
                item_resp = safe_fetch(f"https://hacker-news.firebaseio.com/v0/item/{sid}.json", timeout=5)
                if not item_resp:
                    continue
                d = item_resp.json()
                if not d or d.get("type") != "story" or d.get("time", 0) < cutoff:
                    continue
                title = d.get("title", "")
                if any(kw.lower() in title.lower() for kw in AI_KEYWORDS):
                    items.append({
                        "source": "hn", "source_name": "Hacker News",
                        "title": title,
                        "url": d.get("url") or f"https://news.ycombinator.com/item?id={sid}",
                        "body": "",
                        "timestamp": d["time"],
                        "metadata": {
                            "points": d.get("score", 0),
                            "comments": d.get("descendants", 0) or 0,
                        }
                    })
        except Exception as e:
            log(f"H Firebase parse error: {e}")

    log(f"  HN: {len(items)} items")
    return items


def collect_reddit(hours=12):
    """Reddit via JSON API"""
    log("Fetching Reddit...")
    items = []
    cutoff = time.time() - hours * 3600
    subreddits = ["LocalLLaMA", "MachineLearning", "artificial", "singularity"]
    headers = {"User-Agent": "ai-scan/1.0 (news aggregator)"}

    for sub in subreddits:
        resp = safe_fetch(f"https://www.reddit.com/r/{sub}/new.json?limit=25", headers=headers)
        if not resp:
            continue
        try:
            for child in resp.json().get("data", {}).get("children", []):
                d = child["data"]
                ts = d.get("created_utc", 0)
                if ts < cutoff:
                    continue
                items.append({
                    "source": "reddit", "source_name": f"r/{sub}",
                    "title": d.get("title", ""),
                    "url": f"https://reddit.com/comments/{d['id']}",
                    "body": d.get("selftext", "")[:500],
                    "timestamp": ts,
                    "metadata": {
                        "points": d.get("score", 0),
                        "comments": d.get("num_comments", 0),
                    }
                })
        except Exception as e:
            log(f"  Reddit r/{sub} parse error: {e}")
        time.sleep(2)

    log(f"  Reddit: {len(items)} items")
    return items


def collect_github(hours=12):
    """GitHub trending + search API"""
    log("Fetching GitHub...")
    items = []

    # Trending (daily)
    resp = safe_fetch("https://github.com/trending?since=daily")
    if resp:
        try:
            repos = re.findall(
                r'<article class="Box-row".*?<h2[^>]*>.*?<a\s+href="/([^/]+/[^/"]+)"[^>]*>.*?</h2>.*?'
                r'<p[^>]*>\s*(.*?)\s*</p>.*?'
                r'(\d[\d,]*)\s*stars\s*today',
                resp.text, re.DOTALL
            )
            for full_name, desc, stars_str in repos:
                # Filter non-repo paths (sponsors, orgs, etc.)
                parts = full_name.strip().split("/")
                if len(parts) != 2 or not all(p.strip() for p in parts):
                    continue
                desc_clean = re.sub(r"<.*?>", "", desc).strip()
                title_text = f"{full_name}: {desc_clean}" if desc_clean else full_name
                if any(kw.lower() in title_text.lower() for kw in AI_KEYWORDS + ["ai", "ml", "llm"]):
                    stars = int(stars_str.replace(",", ""))
                    items.append({
                        "source": "github", "source_name": "GitHub Trending",
                        "title": title_text,
                        "url": f"https://github.com/{full_name}",
                        "body": desc_clean,
                        "timestamp": int(time.time()) - 3600 * 6,
                        "metadata": {"stars_today": stars}
                    })
        except Exception as e:
            log(f"  GitHub trending parse error: {e}")

    # Search API: recently created AI repos (OR logic for topics)
    search_date = datetime.fromtimestamp(time.time() - hours * 3600, tz=timezone.utc).strftime("%Y-%m-%d")
    search_url = (f"https://api.github.com/search/repositories"
                  f"?q=created:>{search_date}+topic:ai&sort=stars&order=desc&per_page=15")
    resp = safe_fetch(search_url, headers={"Accept": "application/vnd.github.v3+json"})
    if resp:
        try:
            for repo in resp.json().get("items", []):
                items.append({
                    "source": "github", "source_name": "GitHub",
                    "title": f"{repo['full_name']}: {repo.get('description', '')}",
                    "url": repo["html_url"],
                    "body": repo.get("description", ""),
                    "timestamp": int(time.mktime(datetime.fromisoformat(
                        repo["created_at"].replace("Z", "+00:00")).timetuple())),
                    "metadata": {"stars": repo.get("stargazers_count", 0)}
                })
        except Exception as e:
            log(f"  GitHub search parse error: {e}")

    log(f"  GitHub: {len(items)} items")
    return items


def collect_arxiv(hours=12):
    """ArXiv via Atom API"""
    log("Fetching ArXiv...")
    items = []
    url = ("https://export.arxiv.org/api/query?search_query="
           "cat:cs.AI+OR+cat:cs.CL+OR+cat:cs.LG+OR+cat:cs.CV"
           "&max_results=20&sortBy=submittedDate&sortOrder=descending")
    resp = safe_fetch(url, timeout=30)
    if not resp:
        log("  ArXiv: fetch failed")
        return items

    try:
        root = ET.fromstring(resp.text)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        cutoff = time.time() - hours * 3600
        for entry in root.findall("atom:entry", ns):
            title = entry.find("atom:title", ns).text.strip().replace("\n", " ")
            link = ""
            for l in entry.findall("atom:link", ns):
                if l.get("type") == "text/html":
                    link = l.get("href", "")
                    break
            if not link:
                link = entry.find("atom:id", ns).text.strip()
            summary = entry.find("atom:summary", ns).text.strip()[:300] if entry.find("atom:summary", ns) is not None else ""
            published = entry.find("atom:published", ns).text.strip()
            ts = int(time.mktime(datetime.fromisoformat(published.replace("Z", "+00:00")).timetuple()))
            if ts < cutoff:
                continue
            items.append({
                "source": "arxiv", "source_name": "ArXiv",
                "title": title,
                "url": link,
                "body": summary,
                "timestamp": ts,
                "metadata": {"category": "cs.AI/CL/LG/CV"}
            })
    except Exception as e:
        log(f"  ArXiv parse error: {e}")

    log(f"  ArXiv: {len(items)} items")
    return items


def collect_hf(hours=12):
    """Hugging Face Blog via RSS (RSS 2.0 format)"""
    log("Fetching Hugging Face...")
    items = []
    resp = safe_fetch("https://huggingface.co/blog/feed.xml")
    if not resp:
        log("  HF: fetch failed")
        return items

    try:
        root = ET.fromstring(resp.text)
        cutoff = time.time() - hours * 3600

        # RSS 2.0 format
        for item_el in root.iter("item"):
            title_el = item_el.find("title")
            link_el = item_el.find("link")
            date_el = item_el.find("pubDate")
            if title_el is None or not title_el.text:
                continue
            title = title_el.text.strip()
            link = link_el.text.strip() if link_el is not None and link_el.text else ""
            if not link.startswith("http"):
                link = f"https://huggingface.co{link}"
            ts = int(time.time())
            if date_el is not None and date_el.text:
                try:
                    dt = parsedate_to_datetime(date_el.text)
                    ts = int(dt.timestamp())
                except Exception:
                    pass
            if ts < cutoff:
                continue
            items.append({
                "source": "hf", "source_name": "Hugging Face",
                "title": title,
                "url": link,
                "body": "",
                "timestamp": ts,
                "metadata": {}
            })

        # Atom fallback (in case they switch back)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        for entry in root.findall("atom:entry", ns):
            title = entry.find("atom:title", ns).text.strip()
            link = entry.find("atom:link", ns).get("href", "")
            if not link.startswith("http"):
                link = f"https://huggingface.co{link}"
            published = entry.find("atom:published", ns)
            ts = int(time.time())
            if published is not None and published.text:
                ts = int(time.mktime(datetime.fromisoformat(published.text.replace("Z", "+00:00")).timetuple()))
            if ts < cutoff:
                continue
            items.append({
                "source": "hf", "source_name": "Hugging Face",
                "title": title,
                "url": link,
                "body": "",
                "timestamp": ts,
                "metadata": {}
            })
    except Exception as e:
        log(f"  HF parse error: {e}")

    log(f"  HF: {len(items)} items")
    return items


def collect_blogs(hours=12):
    """AI company blogs via RSS"""
    log("Fetching AI blogs...")
    items = []
    feeds = [
        ("https://blog.google/innovation-and-ai/technology/ai/rss/", "Google AI Blog"),
        ("https://deepmind.google/blog/rss.xml", "DeepMind Blog"),
        ("https://openai.com/blog/rss.xml", "OpenAI Blog"),
        # Anthropic removed their RSS feed — disabled 2026-04-07
    ]
    cutoff = time.time() - hours * 3600

    for feed_url, source_name in feeds:
        resp = safe_fetch(feed_url, timeout=8)
        if not resp:
            continue
        try:
            root = ET.fromstring(resp.text)
            # RSS 2.0
            for item_el in root.iter("item"):
                title_el = item_el.find("title")
                link_el = item_el.find("link")
                date_el = item_el.find("pubDate")
                if title_el is None:
                    continue
                title = title_el.text.strip() if title_el.text else ""
                link = link_el.text.strip() if link_el is not None and link_el.text else ""
                ts = int(time.time())
                if date_el is not None and date_el.text:
                    try:
                        dt = parsedate_to_datetime(date_el.text)
                        ts = int(dt.timestamp())
                    except Exception:
                        pass
                if ts < cutoff:
                    continue
                items.append({
                    "source": "blogs", "source_name": source_name,
                    "title": title,
                    "url": link,
                    "body": "",
                    "timestamp": ts,
                    "metadata": {}
                })
            # Atom
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            for entry in root.findall(".//atom:entry", ns):
                title_el = entry.find("atom:title", ns)
                link_el = entry.find("atom:link", ns)
                date_el = entry.find("atom:published", ns) or entry.find("atom:updated", ns)
                if title_el is None:
                    continue
                title = title_el.text.strip() if title_el.text else ""
                link = link_el.get("href", "") if link_el is not None else ""
                ts = int(time.time())
                if date_el is not None and date_el.text:
                    try:
                        ts = int(time.mktime(datetime.fromisoformat(date_el.text.replace("Z", "+00:00")).timetuple()))
                    except Exception:
                        pass
                if ts < cutoff:
                    continue
                items.append({
                    "source": "blogs", "source_name": source_name,
                    "title": title,
                    "url": link,
                    "body": "",
                    "timestamp": ts,
                    "metadata": {}
                })
        except Exception as e:
            log(f"  {source_name} parse error: {e}")

    # Dedup blog items by title
    seen_titles = set()
    deduped = []
    for item in items:
        key = item["title"].lower().strip()
        if key not in seen_titles:
            seen_titles.add(key)
            deduped.append(item)
    items = deduped

    log(f"  Blogs: {len(items)} items")
    return items


def collect_x(hours=12):
    """X/Twitter — stub for future activation"""
    token = os.environ.get("X_API_BEARER_TOKEN", "")
    if not token:
        return []
    # TODO: Implement X API v2 search when token is available
    return []


# ============================================
# Scoring
# ============================================
def score_items(items):
    now = time.time()
    for item in items:
        # Source signal (0-1)
        meta = item.get("metadata", {})
        points = meta.get("points", 0) or meta.get("stars", 0) or meta.get("stars_today", 0) or 0
        if points > 0:
            source_signal = min(points / 300, 1.0)
        else:
            source_signal = 0.1

        # Freshness (0-1) — exponential decay, half-life ~8h
        hours_ago = (now - item["timestamp"]) / 3600
        freshness = math.exp(-hours_ago / 12)

        # Keyword match (0-1)
        body_text = item.get("body") or ""
        text = (item["title"] + " " + body_text).lower()
        keyword_hits = sum(1 for kw in AI_KEYWORDS if kw.lower() in text)
        high_value_hits = sum(1 for kw in HIGH_VALUE_KEYWORDS if kw.lower() in text)
        keyword_score = min((keyword_hits * 0.1 + high_value_hits * 0.2), 1.0)

        # Source weight
        source_weight = SOURCE_WEIGHTS.get(item["source"], 0.5)

        # Composite score (0-100)
        item["score"] = int(100 * (
            0.4 * source_signal +
            0.3 * freshness +
            0.2 * keyword_score +
            0.1 * source_weight
        ))

    return sorted(items, key=lambda x: x["score"], reverse=True)


# ============================================
# Summarization
# ============================================
def summarize_batch(items, batch_size=8):
    """Summarize items using Qwen-turbo"""
    if not items:
        return

    for i in range(0, len(items), batch_size):
        batch = items[i:i + batch_size]
        news_text = ""
        for j, item in enumerate(batch, 1):
            news_text += f"\n{j}. [{item['source_name']}] {item['title']}\n"
            if item.get("body"):
                news_text += f"   Body: {item['body'][:200]}\n"
            meta = item.get("metadata", {})
            meta_str = ", ".join(f"{k}: {v}" for k, v in meta.items() if v)
            if meta_str:
                news_text += f"   ({meta_str})\n"

        prompt = (
            "You are an AI news analyst. For each news item below, write a 1-2 sentence summary "
            "explaining what happened and why it matters. Be specific and factual. "
            "Use the same numbering.\n"
            f"{news_text}"
        )

        try:
            resp = requests.post(
                f"{QWEN_CONFIG['base_url']}/chat/completions",
                headers={"Authorization": f"Bearer {QWEN_CONFIG['api_key']}"},
                json={
                    "model": QWEN_CONFIG["model"],
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3,
                    "max_tokens": 1000,
                },
                timeout=30,
            )
            if resp.status_code == 200:
                summary_text = resp.json()["choices"][0]["message"]["content"]
                summaries = re.split(r"\n\d+[\.\)]\s*", summary_text)
                summaries = [s.strip() for s in summaries if s.strip()]
                for k, s in enumerate(summaries):
                    if k < len(batch):
                        batch[k]["summary"] = s
            else:
                log(f"  Summary API error: {resp.status_code}")
        except Exception as e:
            log(f"  Summary error: {e}")


# ============================================
# Output Formatting
# ============================================
def format_markdown(items, sources_used, dupes, hours, total_fetched):
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# AI News Scan — {now_str}",
        "",
        f"> Sources: {', '.join(sources_used)}",
        f"> New: {len(items)} | Duplicates filtered: {dupes} | Range: last {hours}h",
        "",
        "---",
        "",
    ]

    if not items:
        lines.append("*No new AI news items found in this scan.*")
        return "\n".join(lines)

    # Top stories (score >= 40)
    top = [i for i in items if i["score"] >= 40]
    if top:
        lines.append("## Top Stories\n")
        for idx, item in enumerate(top[:15], 1):
            meta = item.get("metadata", {})
            meta_parts = []
            if meta.get("points"):
                meta_parts.append(f"{meta['points']} pts")
            if meta.get("comments"):
                meta_parts.append(f"{meta['comments']} comments")
            if meta.get("stars"):
                meta_parts.append(f"{meta['stars']} stars")
            if meta.get("stars_today"):
                meta_parts.append(f"{meta['stars_today']} stars today")
            meta_str = ", ".join(meta_parts)
            age = age_string(item["timestamp"])

            lines.append(f"### {idx}. {item['title']} (Score: {item['score']})")
            lines.append(f"> **{item['source_name']}** ({meta_str}) | **{age}**")
            if item.get("url"):
                lines.append(f"> {item['url']}")
            if item.get("summary"):
                lines.append(f"\n{item['summary']}")
            lines.append("")

    # ArXiv papers
    arxiv = [i for i in items if i["source"] == "arxiv" and i not in top]
    if arxiv:
        lines.append("## New on ArXiv\n")
        for item in arxiv[:10]:
            lines.append(f"- **{item['title']}**")
            if item.get("summary"):
                lines.append(f"  {item['summary']}")
            if item.get("url"):
                lines.append(f"  [Link]({item['url']})")
            lines.append("")

    # GitHub
    gh = [i for i in items if i["source"] == "github" and i not in top]
    if gh:
        lines.append("## GitHub\n")
        for item in gh[:10]:
            lines.append(f"- **{item['title']}** (Score: {item['score']})")
            if item.get("url"):
                lines.append(f"  [Link]({item['url']})")
            lines.append("")

    # Blogs
    blogs = [i for i in items if i["source"] in ("blogs", "hf") and i not in top]
    if blogs:
        lines.append("## Blog Posts\n")
        for item in blogs[:10]:
            lines.append(f"- **{item['title']}** — *{item['source_name']}*")
            if item.get("url"):
                lines.append(f"  [Link]({item['url']})")
            lines.append("")

    lines.append(f"\n---\n*Generated by ai-scan v1.0*")
    return "\n".join(lines)


def format_json(items, sources_used, dupes, hours, total_fetched):
    return json.dumps({
        "timestamp": datetime.now().isoformat(),
        "hours": hours,
        "sources": sources_used,
        "total_fetched": total_fetched,
        "duplicates_filtered": dupes,
        "new_items": len(items),
        "items": [{
            "title": i["title"],
            "url": i.get("url", ""),
            "source": i["source_name"],
            "score": i.get("score", 0),
            "age": age_string(i["timestamp"]),
            "summary": i.get("summary", ""),
            "metadata": i.get("metadata", {}),
        } for i in items],
    }, indent=2, ensure_ascii=False)


# ============================================
# Feishu Bilingual Output
# ============================================
def translate_for_feishu(items):
    """Translate titles and summaries to Chinese for Feishu card"""
    if not items:
        return
    news_list = ""
    for i, item in enumerate(items, 1):
        news_list += f"\n{i}. {item['title']}"
        if item.get("summary"):
            news_list += f"\n   Summary: {item['summary']}"

    prompt = (
        "你是一个 AI 新闻编辑。对下面的每条新闻，提供：\n"
        "1. 中文标题翻译（技术术语保留英文如 LLM、RAG、token，只翻译自然语言部分）\n"
        "2. 一句话中文摘要（控制在 40 字以内，突出「发生了什么」和「为什么值得关注」）\n\n"
        "严格按以下格式输出，每条新闻占一行，编号必须与输入一致：\n"
        "1. CN_TITLE | CN_SUMMARY\n"
        "2. CN_TITLE | CN_SUMMARY\n"
        "...\n\n"
        f"{news_list}"
    )

    try:
        resp = requests.post(
            f"{QWEN_CONFIG['base_url']}/chat/completions",
            headers={"Authorization": f"Bearer {QWEN_CONFIG['api_key']}"},
            json={
                "model": QWEN_CONFIG["model"],
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
                "max_tokens": 2000,
            },
            timeout=30,
        )
        if resp.status_code == 200:
            text = resp.json()["choices"][0]["message"]["content"].strip()
            for line in text.split("\n"):
                line = line.strip()
                if "|" not in line:
                    continue
                # Parse numbered line: "1. CN_TITLE | CN_SUMMARY"
                m = re.match(r"(\d+)[\.\)]\s*(.+)", line)
                if not m:
                    continue
                idx = int(m.group(1)) - 1
                if idx < 0 or idx >= len(items):
                    continue
                content = m.group(2)
                parts = content.split("|", 1)
                items[idx]["cn_title"] = parts[0].strip()
                items[idx]["cn_summary"] = parts[1].strip() if len(parts) > 1 else ""
    except Exception as e:
        log(f"  Translation error: {e}")
        for item in items:
            item["cn_title"] = item["title"]
            item["cn_summary"] = ""


def extract_signals(items):
    """Extract 3 key signals from the news batch"""
    if len(items) < 2:
        return ["暂无显著趋势信号"]
    titles = "\n".join(f"- {i['title']}" for i in items[:15])
    prompt = (
        "基于以下 AI 新闻标题，用中文提炼 3 个跨条目的关键趋势信号。"
        "每个信号 10-20 字，简洁有力。严格每行一个信号，不要编号，不要多余文字。"
        "必须用中文输出。\n"
        f"{titles}"
    )
    try:
        resp = requests.post(
            f"{QWEN_CONFIG['base_url']}/chat/completions",
            headers={"Authorization": f"Bearer {QWEN_CONFIG['api_key']}"},
            json={
                "model": QWEN_CONFIG["model"],
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
                "max_tokens": 200,
            },
            timeout=15,
        )
        if resp.status_code == 200:
            text = resp.json()["choices"][0]["message"]["content"].strip()
            signals = [l.strip().lstrip("0123456789.-) ") for l in text.split("\n") if l.strip()]
            return signals[:3]
    except Exception:
        pass
    return ["暂无显著趋势信号"]


def format_feishu(items, sources_used, dupes, hours, total_fetched):
    """Format as Feishu card-ready lark_md content"""
    now_str = datetime.now().strftime("%m/%d %H:%M")

    # Translate all items
    translate_for_feishu(items)
    signals = extract_signals(items)

    lines = []

    if not items:
        lines.append("*本轮无新 AI 新闻*")
        return "\n".join(lines)

    # Stats line
    lines.append(f"**本轮 {len(items)} 条新发现 | 最近 {hours}h | 筛选自 {total_fetched} 条**")
    lines.append("")

    # Hot stories (Score >= 55)
    hot = [i for i in items if i.get("score", 0) >= 45]
    quick = [i for i in items if i.get("score", 0) < 45]

    if hot:
        lines.append("**🔥 热点头条**")
        lines.append("")
        for idx, item in enumerate(hot[:10], 1):
            title = item["title"]
            url = item.get("url", "")
            cn_title = item.get("cn_title", title)
            cn_summary = item.get("cn_summary", "")
            score = item.get("score", 0)
            age = age_string(item["timestamp"])
            meta = item.get("metadata", {})

            # Build stats string
            stats_parts = []
            src = item.get("source_name", "")
            if "points" in meta and meta["points"]:
                stats_parts.append(f"{meta['points']}pts")
            if "comments" in meta and meta["comments"]:
                stats_parts.append(f"{meta['comments']}评论")
            if "stars_today" in meta and meta["stars_today"]:
                stats_parts.append(f"+{meta['stars_today']}★")
            if "stars" in meta and meta["stars"]:
                stats_parts.append(f"{meta['stars']}★")
            stats_str = f"{src} {', '.join(stats_parts)}" if stats_parts else src

            # Title line (English as link)
            link_md = f"[{title}]({url})" if url else title
            lines.append(f"**{idx}. {link_md}**")
            lines.append(f"　 {cn_title}")
            lines.append(f"　 📊 {stats_str} · {age} · Score:{score}")
            if cn_summary:
                lines.append(f"　 💬 {cn_summary}")
            lines.append("")

    if quick:
        lines.append("---")
        lines.append("")
        lines.append("**📰 快速浏览**")
        lines.append("")
        start_idx = len(hot) + 1
        for idx, item in enumerate(quick[:10], start_idx):
            title = item["title"]
            url = item.get("url", "")
            cn_title = item.get("cn_title", title)
            age = age_string(item["timestamp"])
            src = item.get("source_name", "")

            link_md = f"[{title}]({url})" if url else title
            lines.append(f"**{idx}. {link_md}**")
            lines.append(f"　 {cn_title} · {src} · {age}")
            lines.append("")

    # Key signals
    lines.append("---")
    lines.append("")
    lines.append(f"本轮共 **{len(items)}** 条 | 去重 **{dupes}** 条")
    if signals:
        lines.append("")
        lines.append("**📌 关键信号**")
        for s in signals:
            lines.append(f"- {s}")

    return "\n".join(lines)


# ============================================
# Main
# ============================================
def main():
    parser = argparse.ArgumentParser(description="ai-scan: Real-time AI news aggregator")
    parser.add_argument("--quick", action="store_true", help="Quick scan: HN + Reddit, last 2h")
    parser.add_argument("--deep", action="store_true", help="Deep scan: all sources, last 48h")
    parser.add_argument("--sources", type=str, default=None,
                        help="Comma-separated sources: hn,reddit,github,arxiv,hf,blogs,x")
    parser.add_argument("--no-summarize", action="store_true", help="Skip AI summarization")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--feishu", action="store_true", help="Feishu card-ready bilingual output (lark_md)")
    parser.add_argument("--hours", type=int, default=None, help="Lookback hours (default: 12)")
    args = parser.parse_args()

    # Determine time range
    if args.hours:
        hours = args.hours
    elif args.quick:
        hours = 2
    elif args.deep:
        hours = 48
    else:
        hours = 12

    # Determine sources
    all_collectors = {
        "hn": ("Hacker News", collect_hn),
        "reddit": ("Reddit", collect_reddit),
        "github": ("GitHub", collect_github),
        "arxiv": ("ArXiv", collect_arxiv),
        "hf": ("Hugging Face", collect_hf),
        "blogs": ("AI Blogs", collect_blogs),
        "x": ("X/Twitter", collect_x),
    }

    if args.quick:
        active = {"hn": all_collectors["hn"], "reddit": all_collectors["reddit"]}
    elif args.sources:
        active = {}
        for s in args.sources.split(","):
            s = s.strip().lower()
            if s in all_collectors:
                active[s] = all_collectors[s]
    else:
        active = all_collectors

    # Fetch all sources
    all_items = []
    sources_used = []
    for key, (name, collector) in active.items():
        try:
            items = collector(hours=hours)
            all_items.extend(items)
            if items:
                sources_used.append(name)
        except Exception as e:
            log(f"  {name} error: {e}")

    total_fetched = len(all_items)

    # Deduplicate in-memory (cross-source) — O(n) with dict
    sim_map = {}
    for item in all_items:
        sk = compute_sim_key(item["title"])
        if sk in sim_map:
            existing = sim_map[sk]
            existing_meta = existing.get("metadata", {})
            item_meta = item.get("metadata", {})
            existing_score = existing_meta.get("points", 0) or existing_meta.get("stars", 0) or 0
            item_score = item_meta.get("points", 0) or item_meta.get("stars", 0) or 0
            if item_score > existing_score:
                sim_map[sk] = item
        else:
            sim_map[sk] = item
    deduped = list(sim_map.values())

    # Score
    deduped = score_items(deduped)

    # DB dedup
    db = get_db()
    db_prune(db)
    new_items = db_check_new(db, deduped)
    dupes = total_fetched - len(new_items)

    # Keep top 25
    new_items = new_items[:25]

    # Summarize
    if not args.no_summarize and new_items:
        log("Summarizing with Qwen-turbo...")
        summarize_batch(new_items)

    # Record to DB
    if new_items:
        db_record(db, new_items)
    db.close()

    # Output
    if args.feishu:
        print(format_feishu(new_items, sources_used, dupes, hours, total_fetched))
    elif args.json:
        print(format_json(new_items, sources_used, dupes, hours, total_fetched))
    else:
        print(format_markdown(new_items, sources_used, dupes, hours, total_fetched))

    # Summary to stderr
    log(f"Done: {total_fetched} fetched, {dupes} duplicates, {len(new_items)} new")


if __name__ == "__main__":
    main()
