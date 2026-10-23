#!/usr/bin/env python3
"""Haalt per account de openbare cijfers per video op (yt-dlp, zonder inlog) en schrijft een momentopname naar data/snapshots/<datum>.jsonl."""
import json, shutil, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PER_ACCOUNT = {'eigen': 60, 'niche': 40}
YTDLP = shutil.which('yt-dlp') or 'yt-dlp'


def fetch(handle, limit, kanaal_id=None):
    url = f'tiktokuser:{kanaal_id}' if kanaal_id else f'https://www.tiktok.com/@{handle}'
    err = ''
    for attempt in range(2):
        p = subprocess.run([YTDLP, '--flat-playlist', '--dump-json', '--playlist-end', str(limit), url],
                           capture_output=True, text=True, timeout=90)
        rows = [json.loads(l) for l in p.stdout.splitlines() if l.strip().startswith('{')]
        if rows:
            return rows, ''
        err = (p.stderr.strip().splitlines() or ['geen uitvoer'])[-1][:300]
        time.sleep(10)
    return [], err


def main():
    accounts = json.loads((ROOT / 'accounts.json').read_text(encoding='utf-8'))
    ids = accounts.pop('kanaal_ids', {})
    now = int(time.time())
    out = ROOT / 'data' / 'snapshots' / (time.strftime('%Y-%m-%d', time.gmtime(now)) + '.jsonl')
    out.parent.mkdir(parents=True, exist_ok=True)
    runs = []
    with open(out, 'a', encoding='utf-8') as f:
        for groep, handles in accounts.items():
            for handle in handles:
                rows, err = fetch(handle, PER_ACCOUNT.get(groep, 40), ids.get(handle))
                for r in rows:
                    f.write(json.dumps({'fetched': now, 'account': handle, 'groep': groep, 'id': r['id'],
                                        'posted': r.get('timestamp'), 'desc': (r.get('description') or r.get('title') or '')[:150],
                                        'duur': r.get('duration'), 'views': r.get('view_count'), 'likes': r.get('like_count'),
                                        'comments': r.get('comment_count'), 'shares': r.get('repost_count'),
                                        'saves': r.get('save_count')}, ensure_ascii=False) + '\n')
                runs.append({'fetched': now, 'account': handle, 'ok': int(bool(rows)), 'n': len(rows), 'err': err})
                print(f'{handle}: {len(rows)} video\'s' + (f' (fout: {err})' if err else ''))
                time.sleep(3)
    with open(ROOT / 'data' / 'runs.jsonl', 'a', encoding='utf-8') as f:
        for r in runs:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
    mislukt = [r['account'] for r in runs if not r['ok']]
    if len(mislukt) == len(runs):
        print('ALLE accounts mislukt: waarschijnlijk geblokkeerd. Geen nieuwe data.')
        return 1


if __name__ == '__main__':
    sys.exit(main())
