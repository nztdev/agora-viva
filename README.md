# Agora Viva — The Living Field

A force-directed map of what the world is paying attention to right now.
Events, not articles. Resonance, not recency.

**Live demo:** https://nztdev.github.io/agora-viva

---

## What it does

- Fetches RSS feeds from 10 major outlets + Hacker News top stories every 30 minutes
- Clusters headlines into **events** (30 articles about Ukraine → 1 node)
- Scores each event by a **resonance formula** (source diversity + engagement + velocity + longevity)
- Draws a living force-directed graph — bigger nodes = more resonant, edges = related events
- Runs entirely free on GitHub Pages + GitHub Actions. No server. No database. No cost.

---

## How resonance is scored

```
score = source_diversity × 0.25
      + engagement_depth × 0.30
      + velocity         × 0.25
      + longevity        × 0.10
      + recency          × 0.10

then decayed by: score × 0.5^(age_hours / half_life)
default half_life = 12 hours
```

- **Source diversity** — more distinct outlets covering it = higher score
- **Engagement depth** — comments and replies weighted 3× over passive reach
- **Velocity** — rate of new engagement (a story with 100 comments in 2 hours beats one with 1000 over a week)
- **Longevity** — stories that sustain coverage over days score higher than flashes
- **Recency** — freshness of the latest signal

---

## Tuning

Edit environment variables in `.github/workflows/refresh.yml`:

| Variable | Default | Effect |
|---|---|---|
| `MAX_EVENTS` | `60` | Max nodes shown |
| `DECAY_HALF_LIFE_HOURS` | `12` | How fast stories fade |

Edit `scripts/fetch.py` to add or remove RSS feeds from the `FEEDS` list.
Each feed needs: `(outlet_name, rss_url, political_bias, credibility_score)`.

---

## Adding data sources

Add a new feed to the `FEEDS` list in `scripts/fetch.py`:

```python
("My Outlet", "https://example.com/feed.rss", 0.0, 0.80),
#              ^url                             ^bias ^credibility (0-1)
```

Political bias: `-1.0` (far left) → `0.0` (center) → `+1.0` (far right).
Credibility: use [NewsGuard](https://www.newsguardtech.com) or [AllSides](https://www.allsides.com) as reference.

---

## Roadmap

- [ ] Entity extraction (who/where are in each event)
- [ ] Causal edges (event A caused event B)
- [ ] Topic filtering (politics, tech, science, etc.)
- [ ] Mobile layout
- [ ] Historical replay (scrub back through past resonance states)
- [ ] Embeddable widget

---

*Built on GitHub Pages. Forever free as a public record.*
