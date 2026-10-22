#!/usr/bin/env python3
"""Zet alle momentopnames (data/snapshots/*.jsonl) in een tijdelijke database en maakt daarmee index.html."""
import json, sqlite3, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import report  # noqa: E402


def main():
    tmp = Path(tempfile.mkdtemp()) / 'monitor.db'
    con = sqlite3.connect(tmp)
    con.executescript('''
    CREATE TABLE videos(id TEXT PRIMARY KEY, account TEXT, groep TEXT, posted INTEGER, description TEXT, duration INTEGER, url TEXT, first_seen INTEGER);
    CREATE TABLE snaps(id TEXT, fetched INTEGER, views INTEGER, likes INTEGER, comments INTEGER, shares INTEGER, saves INTEGER, PRIMARY KEY(id, fetched));
    CREATE TABLE runs(fetched INTEGER, account TEXT, ok INTEGER, n INTEGER, err TEXT);
    ''')
    for f in sorted((ROOT / 'data' / 'snapshots').glob('*.jsonl')):
        for line in f.read_text(encoding='utf-8').split('\n'):
            if not line.strip():
                continue
            r = json.loads(line)
            con.execute('INSERT OR IGNORE INTO videos VALUES (?,?,?,?,?,?,?,?)',
                        (r['id'], r['account'], r['groep'], r['posted'], r['desc'], r['duur'],
                         f'https://www.tiktok.com/@{r["account"]}/video/{r["id"]}', r['fetched']))
            con.execute('INSERT OR REPLACE INTO snaps VALUES (?,?,?,?,?,?,?)',
                        (r['id'], r['fetched'], r['views'], r['likes'], r['comments'], r['shares'], r['saves']))
    runs = ROOT / 'data' / 'runs.jsonl'
    if runs.exists():
        for line in runs.read_text(encoding='utf-8').split('\n'):
            if line.strip():
                r = json.loads(line)
                con.execute('INSERT INTO runs VALUES (?,?,?,?,?)', (r['fetched'], r['account'], r['ok'], r['n'], r['err']))
    con.commit()
    con.close()
    report.DB = tmp
    report.main()


if __name__ == '__main__':
    main()
