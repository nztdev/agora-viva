#!/usr/bin/env python3
"""
Agora Viva — data pipeline (static / GitHub Actions edition)

Fetches RSS feeds + Hacker News top stories, clusters headlines
by simple TF-IDF cosine similarity into EventNodes, computes a
resonance score for each, and writes docs/data.json.

No API keys required. Runs in ~15 seconds on the free GitHub Actions tier.
"""

import json, os, re, math, hashlib, time, logging
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from pathlib import Path

import requests
import feedparser
from dateutil import parser as dateparser
import numpy as np

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ── CONFIG ────────────────────────────────────────────────────────────────────

MAX_EVENTS        = int(os.getenv("MAX_EVENTS", 60))
DECAY_HALF_LIFE_H = float(os.getenv("DECAY_HALF_LIFE_HOURS", 12))
MERGE_THRESHOLD   = 0.30          # cosine similarity above this → same event
EDGE_THRESHOLD    = 0.18          # lower threshold → related event (edge)
MAX_SIGNALS       = 300           # cap raw signals before clustering
OUTPUT_PATH       = Path(__file__).parent.parent / "docs" / "data.json"

# ── FEED REGISTRY ─────────────────────────────────────────────────────────────

FEEDS = [
    # outlet, url, political_bias (-1 left, +1 right), credibility (0-1)
    ("BBC News",            "https://feeds.bbci.co.uk/news/rss.xml",                   -0.1, 0.92),
    ("The Guardian",        "https://www.theguardian.com/world/rss",                   -0.4, 0.87),
    ("Reuters",             "https://feeds.reuters.com/reuters/topNews",                0.0, 0.95),
    ("Al Jazeera",          "https://www.aljazeera.com/xml/rss/all.xml",               -0.2, 0.80),
    ("Wall Street Journal", "https://feeds.a.dj.com/rss/RSSWorldNews.xml",             0.3, 0.91),
    ("Fox News",            "https://feeds.foxnews.com/foxnews/latest",                 0.6, 0.58),
    ("TechCrunch",          "https://techcrunch.com/feed/",                            -0.1, 0.82),
    ("The Verge",           "https://www.theverge.com/rss/index.xml",                  -0.1, 0.84),
    ("Ars Technica",        "https://arstechnica.com/feed/",                           -0.1, 0.86),
    ("El País (EN)",        "https://feeds.elpais.com/mrss-s/pages/ep/site/english.elpais.com/portada", -0.2, 0.88),
]

# ── TEXT UTILITIES ─────────────────────────────────────────────────────────────

STOP = set("""a an the and or but in on at to for of with by from as is was are were
              be been have has had do does did will would could should may might shall
              it its this that these those i we you he she they what which who
              when where how why all any both each few more most other some such
              no not only same so than too very just""".split())

def tokenize(text: str) -> list[str]:
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return [w for w in text.split() if w and w not in STOP and len(w) > 2]

def tfidf_vectors(corpus: list[list[str]]) -> np.ndarray:
    """Build TF-IDF matrix from a list of token lists. Returns (n_docs, vocab) array."""
    vocab: dict[str, int] = {}
    for doc in corpus:
        for tok in doc:
            if tok not in vocab:
                vocab[tok] = len(vocab)

    n, v = len(corpus), len(vocab)
    if n == 0 or v == 0:
        return np.zeros((n, 1))

    tf = np.zeros((n, v))
    for i, doc in enumerate(corpus):
        for tok in doc:
            tf[i, vocab[tok]] += 1
        if doc:
            tf[i] /= len(doc)

    df = (tf > 0).sum(axis=0) + 1
    idf = np.log((n + 1) / df) + 1
    tfidf = tf * idf

    norms = np.linalg.norm(tfidf, axis=1, keepdims=True)
    norms[norms == 0] = 1
    return tfidf / norms

def cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b))

# ── FETCHING ──────────────────────────────────────────────────────────────────

HEADERS = {"User-Agent": "AgoraViva/0.1 (github.com/your-org/resonance; research)"}

def fetch_rss(outlet: str, url: str, political: float, credibility: float) -> list[dict]:
    try:
        r = requests.get(url, headers=HEADERS, timeout=12)
        feed = feedparser.parse(r.text)
        signals = []
        for entry in feed.entries[:20]:
            pub = entry.get("published") or entry.get("updated") or ""
            try:
                published_at = dateparser.parse(pub).astimezone(timezone.utc) if pub else datetime.now(timezone.utc)
            except Exception:
                published_at = datetime.now(timezone.utc)

            signals.append({
                "id": "rss:" + hashlib.md5((url + (entry.get("link",""))).encode()).hexdigest()[:12],
                "platform": "rss",
                "outlet": outlet,
                "headline": entry.get("title", "").strip(),
                "url": entry.get("link", ""),
                "published_at": published_at.isoformat(),
                "engagement": {"reach": 0, "depth": 0, "velocity": 0},
                "political_bias": political,
                "credibility": credibility,
            })
        log.info(f"  {outlet}: {len(signals)} signals")
        return signals
    except Exception as e:
        log.warning(f"  {outlet} failed: {e}")
        return []

def fetch_hn(max_items: int = 60) -> list[dict]:
    try:
        ids = requests.get("https://hacker-news.firebaseio.com/v0/topstories.json", timeout=10).json()
        signals = []
        now = datetime.now(timezone.utc)
        for item_id in ids[:max_items]:
            try:
                item = requests.get(f"https://hacker-news.firebaseio.com/v0/item/{item_id}.json", timeout=8).json()
                if not item or item.get("type") != "story" or not item.get("title"):
                    continue
                pub = datetime.fromtimestamp(item.get("time", 0), tz=timezone.utc)
                age_h = max((now - pub).total_seconds() / 3600, 0.1)
                score = item.get("score", 0)
                comments = item.get("descendants", 0)
                signals.append({
                    "id": f"hn:{item_id}",
                    "platform": "hackernews",
                    "outlet": "Hacker News",
                    "headline": item["title"],
                    "url": item.get("url") or f"https://news.ycombinator.com/item?id={item_id}",
                    "published_at": pub.isoformat(),
                    "engagement": {
                        "reach": score * 10,
                        "depth": comments,
                        "velocity": (score + comments) / age_h,
                    },
                    "political_bias": 0.0,
                    "credibility": 0.75,
                })
                time.sleep(0.05)   # be polite to HN
            except Exception:
                pass
        log.info(f"  Hacker News: {len(signals)} signals")
        return signals
    except Exception as e:
        log.warning(f"  HN failed: {e}")
        return []

# ── RESONANCE SCORE ───────────────────────────────────────────────────────────

def resonance_score(signals: list[dict], now: datetime) -> float:
    """
    Weighted composite:
      source_diversity  0.25  — distinct outlets
      engagement_depth  0.30  — comments / depth
      velocity          0.25  — rate of engagement
      longevity         0.10  — time span of coverage
      recency           0.10  — how fresh the latest signal is
    Decay applied using half-life.
    """
    if not signals:
        return 0.0

    outlets = {s["outlet"] for s in signals}
    source_div = min(math.log(len(outlets) + 1) / math.log(16), 1.0)

    total_depth = sum(s["engagement"]["depth"] for s in signals)
    eng_depth = min(math.log(total_depth + 1) / math.log(5001), 1.0)

    max_vel = max((s["engagement"]["velocity"] for s in signals), default=0)
    velocity = min(math.log(max_vel + 1) / math.log(101), 1.0)

    times = [dateparser.parse(s["published_at"]).astimezone(timezone.utc) for s in signals]
    span_h = (max(times) - min(times)).total_seconds() / 3600 if len(times) > 1 else 0
    longevity = min(span_h / 72, 1.0)

    latest = max(times)
    age_h = max((now - latest).total_seconds() / 3600, 0)
    recency = math.exp(-age_h / 6)   # 6-hour soft decay for recency component

    raw = (source_div * 0.25 + eng_depth * 0.30 + velocity * 0.25 +
           longevity * 0.10 + recency * 0.10)

    # Half-life decay on the whole score
    age_since_latest_h = (now - latest).total_seconds() / 3600
    decayed = raw * math.pow(0.5, age_since_latest_h / DECAY_HALF_LIFE_H)

    return round(max(0.0, min(1.0, decayed)), 4)

def bias_distribution(signals: list[dict]) -> dict:
    biases = [s["political_bias"] for s in signals if "political_bias" in s]
    if not biases:
        return {"mean": 0, "spread": 0, "left": 0, "center": 0, "right": 0}
    mean = sum(biases) / len(biases)
    variance = sum((b - mean) ** 2 for b in biases) / len(biases)
    spread = round(min(math.sqrt(variance), 1.0), 3)
    return {
        "mean": round(mean, 3),
        "spread": spread,
        "left":   sum(1 for b in biases if b < -0.2),
        "center": sum(1 for b in biases if -0.2 <= b <= 0.2),
        "right":  sum(1 for b in biases if b > 0.2),
    }

# ── CLUSTERING ────────────────────────────────────────────────────────────────

def cluster_signals(signals: list[dict]) -> list[dict]:
    """
    Simple greedy clustering:
    For each signal (sorted newest first), check against existing cluster centroids.
    If cosine similarity > MERGE_THRESHOLD → merge. Else → new cluster.
    Returns list of EventNode dicts.
    """
    if not signals:
        return []

    headlines = [s["headline"] for s in signals]
    tokens   = [tokenize(h) for h in headlines]
    vecs     = tfidf_vectors(tokens)

    clusters: list[dict] = []            # [{signals, centroid_vec, ...}]

    for i, sig in enumerate(signals):
        best_idx, best_sim = -1, -1.0
        for j, cl in enumerate(clusters):
            sim = cosine(vecs[i], cl["_centroid"])
            if sim > best_sim:
                best_sim, best_idx = sim, j

        if best_sim >= MERGE_THRESHOLD and best_idx >= 0:
            cl = clusters[best_idx]
            cl["signals"].append(sig)
            # Update centroid as running average
            n = len(cl["signals"])
            cl["_centroid"] = (cl["_centroid"] * (n - 1) + vecs[i]) / n
            norm = np.linalg.norm(cl["_centroid"])
            if norm > 0:
                cl["_centroid"] /= norm
        else:
            clusters.append({"signals": [sig], "_centroid": vecs[i].copy()})

    return clusters

def node_from_cluster(cl: dict, now: datetime) -> dict:
    sigs = cl["signals"]
    # Pick the headline from the highest-credibility source, or just the first
    title_sig = max(sigs, key=lambda s: s.get("credibility", 0))
    title = title_sig["headline"]

    urls = [{"outlet": s["outlet"], "url": s["url"], "headline": s["headline"],
             "platform": s["platform"]} for s in sigs[:8]]

    times = [dateparser.parse(s["published_at"]).astimezone(timezone.utc) for s in sigs]
    first_seen = min(times).isoformat()
    last_seen  = max(times).isoformat()

    node_id = hashlib.md5(title.encode()).hexdigest()[:10]

    # Derive geographic regions from geo_tags if present, else leave empty
    all_geo = []
    for s in sigs:
        all_geo.extend(s.get("geo_tags", []))
    geo_regions = list(set(all_geo)) if all_geo else []

    return {
        "id":           node_id,
        "title":        title,
        "resonance":    resonance_score(sigs, now),
        "signal_count": len(sigs),
        "sources":      urls,
        "bias":         bias_distribution(sigs),
        "first_seen":   first_seen,
        "last_seen":    last_seen,
        "platforms":    list({s["platform"] for s in sigs}),
        "geo_regions":  geo_regions,
    }

def build_edges(nodes: list[dict], vecs_map: dict) -> list[dict]:
    """Form edges between nodes whose centroids are related but not merged."""
    edges = []
    ids = [n["id"] for n in nodes]
    for i in range(len(nodes)):
        for j in range(i + 1, len(nodes)):
            a, b = ids[i], ids[j]
            if a not in vecs_map or b not in vecs_map:
                continue
            sim = cosine(vecs_map[a], vecs_map[b])
            if EDGE_THRESHOLD <= sim < MERGE_THRESHOLD:
                weight = round((sim - EDGE_THRESHOLD) / (MERGE_THRESHOLD - EDGE_THRESHOLD), 3)
                edges.append({"source": a, "target": b, "weight": weight, "type": "thematic"})
    return edges

# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    now = datetime.now(timezone.utc)
    log.info("Fetching signals...")

    all_signals: list[dict] = []

    for outlet, url, political, cred in FEEDS:
        all_signals.extend(fetch_rss(outlet, url, political, cred))
        time.sleep(0.5)

    all_signals.extend(fetch_hn(max_items=60))

    # Deduplicate by URL
    seen_urls: set[str] = set()
    deduped = []
    for s in all_signals:
        if s["url"] and s["url"] not in seen_urls:
            seen_urls.add(s["url"])
            deduped.append(s)

    # Sort by recency, cap
    deduped.sort(key=lambda s: s["published_at"], reverse=True)
    deduped = deduped[:MAX_SIGNALS]

    log.info(f"Clustering {len(deduped)} signals...")
    clusters = cluster_signals(deduped)

    # Build nodes
    raw_nodes = [node_from_cluster(cl, now) for cl in clusters]

    # Sort by resonance, take top N
    raw_nodes.sort(key=lambda n: n["resonance"], reverse=True)
    raw_nodes = raw_nodes[:MAX_EVENTS]

    # Drop zero-resonance nodes
    raw_nodes = [n for n in raw_nodes if n["resonance"] > 0.005]

    # Build centroid map for edge computation
    # Re-cluster just the surviving nodes' headlines for centroid vecs
    surviving_titles = [n["title"] for n in raw_nodes]
    s_tokens = [tokenize(t) for t in surviving_titles]
    s_vecs   = tfidf_vectors(s_tokens)
    vecs_map = {n["id"]: s_vecs[i] for i, n in enumerate(raw_nodes)}

    edges = build_edges(raw_nodes, vecs_map)

    # Strip internal centroid data (not needed in JSON)
    output = {
        "generated_at": now.isoformat(),
        "node_count":   len(raw_nodes),
        "edge_count":   len(edges),
        "nodes":        raw_nodes,
        "edges":        edges,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    log.info(f"Wrote {len(raw_nodes)} nodes, {len(edges)} edges → {OUTPUT_PATH}")

if __name__ == "__main__":
    main()
