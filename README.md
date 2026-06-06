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

## Roadmap

- [ ] Entity extraction (who/where are in each event)
- [ ] Causal edges (event A caused event B)
- [ ] Topic filtering (politics, tech, science, etc.)
- [ ] Mobile layout
- [ ] Historical replay (scrub back through past resonance states)
- [ ] Embeddable widget

---

*Built on GitHub Pages. Forever free as a public record.*
