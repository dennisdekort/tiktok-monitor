#!/usr/bin/env python3
"""Maakt uit de momentopnames een dashboard (index.html) en een samenvatting (data/samenvatting.json). Wordt aangeroepen door build.py."""
import csv, html, json, re, sqlite3, statistics, time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / 'data' / 'monitor.db'  # build.py zet dit op een tijdelijke database
SCRIPTS = ROOT / 'geen-scripts'  # de koppeling aan productiebestanden doet alleen de lokale monitor
DAG = 86400


def norm(s):
    return re.sub(r'[^a-z0-9€%]+', ' ', (s or '').lower()).strip()


def bali_scripts():
    """Caption per Bali-script, om eigen video's aan een script te koppelen."""
    out = []
    try:
        files = sorted(SCRIPTS.glob('*.md'))
    except OSError:  # launchd mag ~/Documents soms niet lezen (macOS-privacy)
        return out
    for f in files:
        try:
            t = f.read_text(encoding='utf-8')
        except OSError:
            return out
        titel = re.search(r'^# (.+)$', t, re.M)
        kop = t.splitlines()[2] if len(t.splitlines()) > 2 else ''
        cap = re.search(r'\*\*Caption:\*\*\s*(.+)', t)
        out.append({'nr': f.name[:2], 'titel': titel.group(1) if titel else f.stem,
                    'thema': kop.split('·')[0].strip(), 'caption': cap.group(1) if cap else '',
                    'bord': 'bord' if 'bord' in kop.lower() else ('scherm' if 'SCHERM' in kop else 'gezicht')})
    return out


def koppel(desc, scripts):
    d = norm(desc)[:45]
    if len(d) < 12:
        return None
    for s in scripts:
        if s['caption'] and norm(s['caption']).startswith(d[:35]):
            return s
    return None


def interp(snaps, posted, uren):
    """Views op een bepaalde leeftijd, als er snapshots aan weerszijden zijn."""
    doel = posted + uren * 3600
    voor = [s for s in snaps if s[0] <= doel]
    na = [s for s in snaps if s[0] >= doel]
    if not voor or not na:
        return None
    a, b = voor[-1], na[0]
    if a[0] == b[0]:
        return a[1]
    return round(a[1] + (b[1] - a[1]) * (doel - a[0]) / (b[0] - a[0]))


def delta(s, uren=24):
    """Verschil met de momentopname van ± 24 uur eerder (of de oudste, als er nog geen dag data is)."""
    if len(s) < 2:
        return None
    last = s[-1]
    eerder = [x for x in s[:-1] if x[0] <= last[0] - (uren - 4) * 3600]
    base = eerder[-1] if eerder else s[0]
    d = [((a or 0) - (b or 0)) for a, b in zip(last[1:], base[1:])]
    return {'uren': round((last[0] - base[0]) / 3600), 'views': d[0], 'likes': d[1], 'comm': d[2], 'shares': d[3], 'saves': d[4],
            'views_basis': base[1] or 0}


def pct(a, b):
    return round(100 * a / b, 2) if b else None


def main():
    con = sqlite3.connect(DB)
    accounts = json.loads((ROOT / 'accounts.json').read_text(encoding='utf-8'))
    accounts.pop('kanaal_ids', None)
    labels = {h: l for g in accounts.values() for h, l in g.items()}
    now = int(time.time())
    vids = {r[0]: dict(zip(['id', 'account', 'groep', 'posted', 'desc', 'duur', 'url'], r))
            for r in con.execute('SELECT id,account,groep,posted,description,duration,url FROM videos')}
    snaps = defaultdict(list)
    for r in con.execute('SELECT id,fetched,views,likes,comments,shares,saves FROM snaps ORDER BY fetched'):
        snaps[r[0]].append(r[1:])
    scripts = bali_scripts()

    per_acc = defaultdict(list)
    for v in vids.values():
        s = snaps.get(v['id'])
        if not s or not v['posted']:
            continue
        f, views, likes, comm, shares, saves = s[-1]
        v.update(views=views or 0, likes=likes or 0, comm=comm or 0, shares=shares or 0, saves=saves or 0,
                 leeftijd=round((now - v['posted']) / DAG, 1))
        if v['groep'] == 'eigen':
            tag = koppel(v['desc'], scripts)
            v['script'] = tag
            ser = [(x[0], x[1] or 0) for x in s]
            v['v24'], v['v72'], v['v7d'] = interp(ser, v['posted'], 24), interp(ser, v['posted'], 72), interp(ser, v['posted'], 168)
        v['delta'] = delta(s)
        per_acc[v['account']].append(v)

    mediaan = {}
    for acc, lst in per_acc.items():
        oud = sorted([v for v in lst if v['leeftijd'] >= 3], key=lambda v: -v['posted'])[:30]
        mediaan[acc] = statistics.median([v['views'] for v in oud]) if oud else None
    for lst in per_acc.values():
        for v in lst:
            m = mediaan.get(v['account'])
            v['x'] = round(v['views'] / m, 2) if m else None
            v['likes_pct'], v['saves_pct'], v['shares_pct'], v['comm_pct'] = (
                pct(v['likes'], v['views']), pct(v['saves'], v['views']), pct(v['shares'], v['views']), pct(v['comm'], v['views']))

    eigen = {a: sorted(per_acc.get(a, []), key=lambda v: -v['posted']) for a in accounts['eigen']}
    radar = sorted([v for a in accounts['niche'] for v in per_acc.get(a, [])
                    if v['leeftijd'] <= 14 and v.get('x') and v['x'] >= 3], key=lambda v: -v['x'])

    # Wat werkt: eigen video's per thema en per opnamevorm (alleen gekoppelde Bali-video's, minstens 2 dagen oud)
    veranderd = {}
    for a, lst in eigen.items():
        rij = [v for v in lst if v.get('delta') and (v['delta']['views'] or v['delta']['comm'] or v['delta']['saves'])]
        for v in rij:
            d = v['delta']
            v['oud_groeit'] = v['leeftijd'] > 7 and (d['views'] >= 200 or (d['views_basis'] and d['views'] >= 0.2 * d['views_basis']))
        veranderd[a] = sorted(rij, key=lambda v: -v['delta']['views'])
    groepen = defaultdict(list)
    for a, lst in eigen.items():
        for v in lst:
            if v.get('script') and v['leeftijd'] >= 2 and v.get('x'):
                groepen[('thema', v['script']['thema'])].append(v['x'])
                groepen[('vorm', v['script']['bord'])].append(v['x'])
    werkt = [{'soort': k[0], 'naam': k[1], 'n': len(x), 'mediaan_x': round(statistics.median(x), 2)}
             for k, x in groepen.items()]

    sales = []
    sp = ROOT / 'handmatig' / 'sales.csv'
    if sp.exists():
        sales = [r for r in csv.DictReader(sp.open(encoding='utf-8')) if r.get('datum')]

    runs = con.execute('SELECT account, ok, n, err, MAX(fetched) FROM runs GROUP BY account').fetchall()
    trend = dagtrend(con, list(accounts['eigen']))
    laatste = con.execute('SELECT MAX(fetched) FROM snaps').fetchone()[0] or now
    con.close()
    schrijf_export(per_acc)

    samenvatting = {
        'gemaakt': time.strftime('%Y-%m-%d %H:%M'),
        'mediaan_views_per_account': mediaan,
        'eigen': {a: [{k: v.get(k) for k in ['url', 'desc', 'leeftijd', 'duur', 'views', 'x', 'likes_pct', 'saves_pct',
                                             'shares_pct', 'comm', 'v24', 'v72', 'v7d']}
                      | {'script': (v.get('script') or {}).get('titel')} for v in lst[:40]] for a, lst in eigen.items()},
        'veranderingen': {a: [{'url': v['url'], 'desc': (v['desc'] or '')[:80], 'leeftijd': v['leeftijd'], 'oud_groeit': v.get('oud_groeit'),
                               **{('erbij_' + k): v['delta'][k] for k in ['views', 'likes', 'comm', 'shares', 'saves', 'uren']}}
                              for v in lst[:20]] for a, lst in veranderd.items()},
        'wat_werkt': werkt,
        'niche_uitschieters_14d': [{k: v.get(k) for k in ['account', 'url', 'desc', 'views', 'x', 'saves_pct', 'shares_pct', 'duur']}
                                   for v in radar[:25]],
        'sales_handmatig': sales,
        'laatste_ophaalrondes': [{'account': r[0], 'ok': r[1], 'n': r[2], 'fout': r[3],
                                  'wanneer': time.strftime('%Y-%m-%d %H:%M', time.localtime(r[4]))} for r in runs],
    }
    (ROOT / 'data' / 'samenvatting.json').write_text(json.dumps(samenvatting, ensure_ascii=False, indent=1), encoding='utf-8')
    samenvatting['trend'] = trend
    (ROOT / 'data' / 'samenvatting.json').write_text(json.dumps(samenvatting, ensure_ascii=False, indent=1), encoding='utf-8')
    dag = time.strftime('%Y-%m-%d', time.gmtime(laatste))
    noot_p = ROOT / 'data' / 'notitie.md'
    if noot_p.exists():
        (ROOT / 'data' / 'notities').mkdir(exist_ok=True)
        (ROOT / 'data' / 'notities' / f'{dag}.md').write_text(noot_p.read_text(encoding='utf-8'), encoding='utf-8')
    (ROOT / 'dagen').mkdir(exist_ok=True)
    weken = schrijf_weken()
    args = (samenvatting, eigen, radar, mediaan, labels, werkt, veranderd)
    (ROOT / 'dagen' / f'{dag}.html').write_text(dashboard(*args, trend=trend, dag=dag, prefix='../', weken=weken), encoding='utf-8')
    (ROOT / 'index.html').write_text(dashboard(*args, trend=trend, dag=dag, prefix='', weken=weken), encoding='utf-8')
    schrijf_archief(trend, labels)
    print('index.html en data/samenvatting.json bijgewerkt')


def notities():
    """data/notitie.md van de agent, opgesplitst per kopje (## Dennis, ## Kaya, ## Niche)."""
    p = ROOT / 'data' / 'notitie.md'
    out, kop = {}, 'algemeen'
    if not p.exists():
        return out
    for r in p.read_text(encoding='utf-8').splitlines():
        r = r.strip()
        if r.startswith('#'):
            kop = r.lstrip('# ').strip().lower()
        elif r:
            out.setdefault(kop, []).append(re.sub(r'^[-*]\s+', '', r).strip())
    return out


def md_inline(t):
    t = html.escape(t)
    return re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', t)


def dagtrend(con, eigen_accounts):
    """Per account per dag (UTC): totalen van de laatste meting die dag, en wat erbij kwam t.o.v. de vorige dag."""
    out = {}
    for acc in eigen_accounts:
        rows = con.execute('''SELECT s.fetched, SUM(s.views), SUM(s.likes), SUM(s.comments), SUM(s.shares), SUM(s.saves)
                              FROM snaps s JOIN videos v ON v.id = s.id WHERE v.account = ? GROUP BY s.fetched ORDER BY s.fetched''', (acc,)).fetchall()
        perdag = {}
        for f, *tot in rows:
            perdag[time.strftime('%Y-%m-%d', time.gmtime(f))] = [x or 0 for x in tot]
        nieuw = defaultdict(int)
        for (p,) in con.execute('SELECT posted FROM videos WHERE account = ? AND posted IS NOT NULL', (acc,)):
            nieuw[time.strftime('%Y-%m-%d', time.gmtime(p))] += 1
        dagen, vorige = [], None
        for d in sorted(perdag):
            t = perdag[d]
            rij = {'dag': d, 'views': t[0], 'nieuw': nieuw.get(d, 0)}
            if vorige:
                for i, k in enumerate(['views', 'likes', 'reacties', 'shares', 'saves']):
                    rij['erbij_' + k] = t[i] - vorige[i]
            dagen.append(rij)
            vorige = t
        out[acc] = dagen[-30:]
    return out


def trend_html(dagen):
    met = [d for d in dagen if 'erbij_views' in d]
    if not met:
        return '<h3>Trend</h3><p class="sub">Vanaf de tweede meetdag zie je hier per dag wat erbij kwam.</p>'
    laatste = met[-14:]
    top = max([d['erbij_views'] for d in laatste] + [1])
    rows = ''.join(
        f'<tr><td>{d["dag"][8:10]}-{d["dag"][5:7]}</td>'
        f'<td class="n">+{fmt(d["erbij_views"])}</td><td><div class="bar" style="width:{max(2, round(100 * max(d["erbij_views"], 0) / top))}%"></div></td>'
        f'<td class="n">+{fmt(d["erbij_likes"])}</td><td class="n">+{fmt(d["erbij_saves"])}</td><td class="n">+{fmt(d["erbij_reacties"])}</td>'
        f'<td class="n">{d["nieuw"] or ""}</td></tr>'
        for d in reversed(laatste))
    w1 = sum(d['erbij_views'] for d in met[-7:])
    w0 = sum(d['erbij_views'] for d in met[-14:-7])
    vergelijk = (f'Laatste 7 meetdagen +{fmt(w1)} views'
                 + (f', de 7 daarvoor +{fmt(w0)} ({"+" if w1 >= w0 else ""}{round(100 * (w1 - w0) / w0)}%)' if w0 else ''))
    return ('<h3>Trend <span class="sub">' + html.escape(vergelijk) + '</span></h3>'
            '<div class="scroll"><table class="trend"><tr><th>Dag</th><th>Views erbij</th><th></th><th>Likes</th><th>Saves</th><th>Reacties</th><th>Nieuwe video\'s</th></tr>'
            + rows + '</table></div>')


def nav_html(dag, prefix):
    dagen = sorted(p.stem for p in (ROOT / 'dagen').glob('20*.html')) if (ROOT / 'dagen').exists() else []
    if dag and dag not in dagen:
        dagen.append(dag)
        dagen.sort()
    links = [f'<a href="{prefix}index.html">Vandaag</a>', f'<a href="{prefix}dagen/index.html">Archief ({len(dagen)} dagen)</a>']
    if dag in dagen and dagen.index(dag) > 0:
        vorige = dagen[dagen.index(dag) - 1]
        links.append(f'<a href="{prefix}dagen/{vorige}.html">Vorige dag ({vorige[8:10]}-{vorige[5:7]})</a>')
    links.append(f'<a href="{prefix}data/export.csv">Export (csv)</a>')
    titel = f' · stand {dag[8:10]}-{dag[5:7]}-{dag[:4]}' if dag else ''
    return f'<div class="sub nav">{" · ".join(links)}{titel}</div>'


def schrijf_weken():
    """data/weken/<jaar>-W<nr>.md (geschreven door de agent op maandag) als losse pagina's."""
    src = ROOT / 'data' / 'weken'
    if not src.exists():
        return []
    (ROOT / 'weken').mkdir(exist_ok=True)
    out = []
    for f in sorted(src.glob('*.md')):
        body = md_blok(f.read_text(encoding='utf-8'))
        (ROOT / 'weken' / f'{f.stem}.html').write_text(
            f'<!doctype html><html lang="nl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>Week {f.stem}</title><style>body{{font:15px/1.5 -apple-system,Inter,sans-serif;max-width:760px;margin:0 auto;padding:24px 16px;background:#fafaf8;color:#1b1b1f}}'
            f'@media (prefers-color-scheme:dark){{body{{background:#111116;color:#ececf0}}a{{color:#ececf0}}}}</style></head><body>'
            f'<p><a href="../index.html">Terug naar vandaag</a></p>{body}</body></html>', encoding='utf-8')
        out.append((f.stem, body))
    return out


def md_blok(t):
    uit, lijst = [], False
    for r in t.splitlines():
        r = r.rstrip()
        if r.startswith(('- ', '* ')):
            if not lijst:
                uit.append('<ul>'); lijst = True
            uit.append(f'<li>{md_inline(r[2:])}</li>')
            continue
        if lijst:
            uit.append('</ul>'); lijst = False
        if r.startswith('#'):
            n = min(len(r) - len(r.lstrip('#')) + 1, 4)
            uit.append(f'<h{n}>{md_inline(r.lstrip("# "))}</h{n}>')
        elif r.strip():
            uit.append(f'<p>{md_inline(r)}</p>')
    if lijst:
        uit.append('</ul>')
    return ''.join(uit)


def week_html(weken, prefix):
    if not weken:
        return ''
    stem, body = weken[-1]
    oud = ' · '.join(f'<a href="{prefix}weken/{w}.html">{w}</a>' for w, _ in reversed(weken[:-1]))
    return (f'<section id="week"><h2>Weekoverzicht {html.escape(stem)} <span class="sub">elke maandag door de agent'
            + (f' · eerder: {oud}' if oud else '') + f'</span></h2>{body}</section>')


def schrijf_archief(trend, labels):
    dagen = sorted((p.stem for p in (ROOT / 'dagen').glob('20*.html')), reverse=True)
    perdag = defaultdict(dict)
    for acc, lst in trend.items():
        for d in lst:
            perdag[d['dag']][acc] = d
    accs = list(trend)
    kop = ''.join(f'<th>{html.escape(labels.get(a, a))}: views erbij</th>' for a in accs)
    rows = ''
    for d in dagen:
        cel = ''.join(f'<td class="n">{("+" + fmt(perdag[d][a]["erbij_views"])) if a in perdag[d] and "erbij_views" in perdag[d][a] else "–"}</td>' for a in accs)
        heeft_noot = (ROOT / 'data' / 'notities' / f'{d}.md').exists()
        rows += f'<tr><td><a href="{d}.html">{d[8:10]}-{d[5:7]}-{d[:4]}</a></td>{cel}<td>{"notitie" if heeft_noot else ""}</td></tr>'
    (ROOT / 'dagen' / 'index.html').write_text(
        '<!doctype html><html lang="nl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Archief TikTok-monitor</title>'
        '<style>body{font:15px/1.5 -apple-system,Inter,sans-serif;max-width:900px;margin:0 auto;padding:24px 16px;background:#fafaf8;color:#1b1b1f}'
        'table{border-collapse:collapse;width:100%}th,td{text-align:left;padding:7px 8px;border-bottom:1px solid #e4e4e0}td.n{text-align:right}'
        '@media (prefers-color-scheme:dark){body{background:#111116;color:#ececf0}a{color:#ececf0}th,td{border-color:#2a2a33}}</style></head><body>'
        '<p><a href="../index.html">Terug naar vandaag</a></p><h1>Archief</h1><p>Elke dag een eigen pagina, zoals hij die ochtend was.</p>'
        f'<div style="overflow-x:auto"><table><tr><th>Dag</th>{kop}<th></th></tr>{rows}</table></div></body></html>', encoding='utf-8')


def schrijf_export(per_acc):
    p = ROOT / 'data' / 'export.csv'
    with open(p, 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        w.writerow(['account', 'groep', 'gepost', 'leeftijd_dagen', 'duur_s', 'views', 'likes', 'reacties', 'shares', 'saves',
                    'x_mediaan', 'likes_pct', 'saves_pct', 'shares_pct', 'url', 'omschrijving'])
        for acc, lst in per_acc.items():
            for v in sorted(lst, key=lambda v: -(v['posted'] or 0)):
                w.writerow([acc, v['groep'], time.strftime('%Y-%m-%d', time.gmtime(v['posted'])), v['leeftijd'], v['duur'], v['views'],
                            v['likes'], v['comm'], v['shares'], v['saves'], v.get('x'), v.get('likes_pct'), v.get('saves_pct'),
                            v.get('shares_pct'), v['url'], (v['desc'] or '').replace('\n', ' ')])


def badge(x):
    if x is None:
        return '<span class="b">nieuw</span>'
    cls = 'up' if x >= 1.5 else ('down' if x < 0.7 else 'mid')
    return f'<span class="b {cls}">{x:.1f}×</span>'


def fmt(n):
    return '' if n is None else f'{n:,}'.replace(',', '.')


def dashboard(s, eigen, radar, mediaan, labels, werkt, veranderd, trend=None, dag='', prefix='', weken=None):
    e = html.escape
    OUD = ' <span class="b up">oud, groeit weer</span>'
    noot = notities()
    parts = []
    for acc in eigen:
        naam = labels.get(acc, acc)
        lst = veranderd.get(acc, [])
        tot = {k: sum(v['delta'][k] for v in lst) for k in ['views', 'likes', 'comm', 'saves', 'shares']}
        uren = max([v['delta']['uren'] for v in lst] or [0])
        drows = ''.join(
            f'<tr><td class="cap"><a href="{v["url"]}">{e((v["desc"] or "")[:70])}</a>'
            f'{OUD if v.get("oud_groeit") else ""}</td>'
            f'<td>{v["leeftijd"]:.0f} d</td><td class="n">+{fmt(v["delta"]["views"])}</td><td class="n">+{v["delta"]["likes"]}</td>'
            f'<td class="n">+{v["delta"]["comm"]}</td><td class="n">+{v["delta"]["saves"]}</td><td class="n">+{v["delta"]["shares"]}</td></tr>'
            for v in lst[:12])
        vrows = ''.join(
            f'<tr><td>{time.strftime("%d-%m", time.localtime(v["posted"]))}</td>'
            f'<td class="cap"><a href="{v["url"]}">{e((v["desc"] or "")[:70])}</a></td>'
            f'<td class="n">{fmt(v["views"])}</td><td>{badge(v.get("x"))}</td>'
            f'<td class="n">{v["likes_pct"] or 0}%</td><td class="n">{v["saves_pct"] or 0}%</td>'
            f'<td class="n">{v["shares_pct"] or 0}%</td><td class="n">{v["comm"]}</td>'
            f'<td class="n">{fmt(v.get("v24")) or "–"}</td><td class="n">{fmt(v.get("v7d")) or "–"}</td></tr>'
            for v in eigen[acc][:25])
        items = ''.join(f'<li>{md_inline(r)}</li>' for r in noot.get(naam.lower(), []))
        parts.append(
            f'<section class="person" id="{e(acc)}"><h2>{e(naam)} <span class="sub">@{e(acc)} · mediaan {fmt(mediaan.get(acc))} views</span></h2>'
            + (f'<h3>Wat valt op</h3><ul class="note">{items}</ul>' if items else '')
            + trend_html((trend or {}).get(acc, []))
            + f'<h3>Laatste {uren} uur <span class="sub">+{fmt(tot["views"])} views · +{tot["likes"]} likes · +{tot["comm"]} reacties · +{tot["saves"]} saves · +{tot["shares"]} shares</span></h3>'
            '<div class="scroll"><table><tr><th>Video</th><th>Leeftijd</th><th>Views</th><th>Likes</th><th>Reacties</th><th>Saves</th><th>Shares</th></tr>'
            f'{drows or "<tr><td colspan=7>Nog geen veranderingen gemeten.</td></tr>"}</table></div>'
            '<h3>Alle video\'s</h3><div class="scroll"><table><tr><th>Post</th><th>Video</th><th>Views</th><th>t.o.v. mediaan</th>'
            '<th>Likes</th><th>Saves</th><th>Shares</th><th>Reacties</th><th>Na 24 u</th><th>Na 7 d</th></tr>'
            f'{vrows}</table></div></section>')
    niche_items = ''.join(f'<li>{md_inline(r)}</li>' for r in noot.get('niche', []))
    nav = nav_html(dag, prefix)
    week_sec = week_html(weken or [], prefix)
    werkt_rows = ''.join(f'<tr><td>{e(w["soort"])}</td><td>{e(w["naam"])}</td><td class="n">{w["n"]}</td><td>{badge(w["mediaan_x"])}</td></tr>'
                         for w in sorted(werkt, key=lambda w: -w['mediaan_x']))
    radar_rows = ''.join(f'<tr><td>@{e(v["account"])}</td><td class="cap"><a href="{v["url"]}">{e((v["desc"] or "")[:80])}</a></td>'
                         f'<td class="n">{fmt(v["views"])}</td><td>{badge(v["x"])}</td><td class="n">{v["saves_pct"] or 0}%</td></tr>'
                         for v in radar[:20])
    runs = ''.join(f'<li>@{e(r["account"])}: {r["n"]} video\'s, {e(r["wanneer"])}{" · " + e(r["fout"]) if r["fout"] else ""}</li>'
                   for r in s['laatste_ophaalrondes'])
    return f'''<!doctype html><html lang="nl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TikTok-monitor</title><style>
:root{{--bg:#fafaf8;--fg:#1b1b1f;--mut:#6b6b74;--line:#e4e4e0;--card:#fff;--up:#1f8a4c;--down:#b3402b;--mid:#8a7a1f}}
@media (prefers-color-scheme:dark){{:root{{--bg:#111116;--fg:#ececf0;--mut:#9a9aa6;--line:#2a2a33;--card:#18181f;--up:#4cc27f;--down:#e0745d;--mid:#d6c35a}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.45 -apple-system,Inter,sans-serif}}
main{{max-width:1100px;margin:0 auto;padding:24px 16px 64px}} h1{{font-size:24px;margin:0 0 4px}} h2{{font-size:20px;margin:24px 0 8px}} h3{{font-size:15px;margin:18px 0 6px}} section.person{{border-width:2px}}
.sub{{color:var(--mut);font-size:13px;font-weight:400}} section{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:4px 16px 12px;margin-top:16px}}
.scroll{{overflow-x:auto}} table{{border-collapse:collapse;width:100%;font-size:14px}} th,td{{text-align:left;padding:7px 8px;border-bottom:1px solid var(--line);vertical-align:top}}
th{{color:var(--mut);font-weight:500;font-size:12px;white-space:nowrap}} td.n{{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}}
td.cap{{min-width:260px}} a{{color:inherit}} .b{{display:inline-block;padding:1px 7px;border-radius:99px;font-size:12px;border:1px solid var(--line)}}
.up{{color:var(--up);border-color:var(--up)}} .down{{color:var(--down);border-color:var(--down)}} .mid{{color:var(--mid);border-color:var(--mid)}}
ul{{color:var(--mut);font-size:13px}} ul.note{{color:var(--fg);font-size:15px}} .nav{{margin:4px 0 10px}} .nav a{{font-weight:600}} .bar{{height:10px;background:var(--up);border-radius:3px;min-width:2px}} table.trend td{{padding:4px 8px}}
</style></head><body><main>
<h1>TikTok-monitor</h1>{nav}<div class="sub"><a href="#dennis.dekort">Dennis</a> · <a href="#kayaguness">Kaya</a> · <a href="#niche">Niche</a></div><div class="sub">Bijgewerkt {e(s["gemaakt"])} · openbare cijfers per video (views, likes, reacties, shares, saves) · "t.o.v. mediaan" = views gedeeld door de mediaan van dat account (video's van 3+ dagen oud)</div>
{"".join(parts)}
{week_sec}<section><h2>Wat werkt bij ons <span class="sub">Bali-video's per thema en opnamevorm, mediaan t.o.v. de accountmediaan (vanaf 2 dagen oud)</span></h2>
<div class="scroll"><table><tr><th>Soort</th><th>Groep</th><th>Video's</th><th>Mediaan</th></tr>{werkt_rows or '<tr><td colspan=4>Nog te weinig data.</td></tr>'}</table></div></section>
<section id="niche"><h2>Niche-radar <span class="sub">video's van NL-ecomaccounts uit de laatste 14 dagen met 3× of meer hun eigen mediaan</span></h2>
{('<ul class="note">' + niche_items + '</ul>') if niche_items else ''}<div class="scroll"><table><tr><th>Account</th><th>Video</th><th>Views</th><th>t.o.v. mediaan</th><th>Saves</th></tr>{radar_rows or '<tr><td colspan=5>Geen uitschieters.</td></tr>'}</table></div></section>
<section><h2>Laatste ophaalronde</h2><ul>{runs}</ul></section>
</main></body></html>'''


if __name__ == '__main__':
    main()
