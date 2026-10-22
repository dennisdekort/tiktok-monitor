# TikTok-monitor

Dagelijkse momentopname van de openbare TikTok-cijfers (views, likes, reacties, shares, saves) van twee accounts, plus een groep vergelijkingsaccounts. De pagina `index.html` wordt elke dag bijgewerkt door een geplande Claude-agent.

- `monitor/collect.py` haalt de cijfers op met yt-dlp (zonder inlog) en schrijft `data/snapshots/<datum>.jsonl`.
- `monitor/build.py` maakt daaruit `index.html` en `data/samenvatting.json`.
- `data/notitie.md` is de korte dagnotitie van de agent.
