#!/usr/bin/env python3
"""
publish.py — できたニュースを「見せる」「予約する」

  python3 publish.py 見せる 2026-11-17     # README.md を作り直す（スマホで開いて、画像を保存する所）
  python3 publish.py 予約 2026-11-17       # Threadsの予約（../queue.json）に入れる。設定.json の「投稿する」が true のときだけ

置き場所はリポジトリ threads-post の news/。予約は1つ上の queue.json と images/ に書く
（そこから先は、前からある post.py が時刻どおりに出す）。
"""
import datetime
import json
import os
import shutil
import sys

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(HERE, 'out')
JST = datetime.timezone(datetime.timedelta(hours=9))
# 出す時刻。ニュースは大事な順に並んでいるので、人が多い時刻から先に埋める。20時は1作品紹介の時刻なので使わない
SLOTS = ['07:30', '12:15', '19:00', '21:00', '18:00', '08:30', '22:00', '17:00', '11:30', '13:30', '09:30', '15:00', '10:30']
SUMMARY_SLOT = '22:30'
KEEP_DAYS = 14          # README に並べる日数


def load(path, default):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def settings():
    return load(os.path.join(HERE, '設定.json'), {'投稿する': False})


def plan(date):
    """その日のThreadsの投稿と時刻。もう過ぎた時刻は、今から10分後以降の空いている時刻へずらす"""
    posts = load(os.path.join(OUT, date, 'threads.json'), [])
    news = [p for p in posts if p['作品'] != 'まとめ'][:len(SLOTS)]
    summary = [p for p in posts if p['作品'] == 'まとめ']
    now = datetime.datetime.now(JST) + datetime.timedelta(minutes=10)
    free = [s for s in SLOTS if datetime.datetime.strptime('%s %s' % (date, s), '%Y-%m-%d %H:%M').replace(tzinfo=JST) > now]
    out = []
    for p, slot in zip(news, free):
        out.append((slot, p))
    if summary and len(news) >= 3:
        out.append((SUMMARY_SLOT, summary[0]))
    return sorted(out, key=lambda x: x[0])


def cmd_show(date):
    days = sorted((d for d in os.listdir(OUT) if os.path.isdir(os.path.join(OUT, d))), reverse=True)[:KEEP_DAYS]
    live = settings().get('投稿する')
    lines = ['# 今日のアニメニュース', '',
             'Threadsへの自動投稿: **%s**' % ('している' if live else 'していない（お試し中。ここで中身を見るだけ）'), '']
    for d in days:
        folder = os.path.join(OUT, d)
        stories = sorted(f for f in os.listdir(folder) if f.startswith('story_'))
        lines += ['## %s' % d, '']
        if stories:
            lines += ['### ストーリー画像（長押しで保存）', '']
            lines += ['<img src="out/%s/%s" width="270">' % (d, s) for s in stories]
        else:
            lines += ['ストーリー画像: 新作・続編のニュースが無かったので、作っていません']
        posts = load(os.path.join(folder, 'threads.json'), [])
        sched = dict((p['本文'], s) for s, p in plan(d)) if d == date else {}
        if sched:                                  # 今日の分は、出す時刻の順に並べる
            posts = sorted((p for p in posts if p['本文'] in sched), key=lambda p: sched[p['本文']])
        lines += ['', '<details><summary>Threadsの投稿 %d本</summary>' % len(posts), '']
        for p in posts:
            lines += ['**%s %s**' % (sched.get(p['本文'], ''), p['作品']), '', '```', p['本文'], '```', '']
        lines += ['</details>', '']
    with open(os.path.join(HERE, 'README.md'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    print('README.md を作りました（%d日ぶん）' % len(days))
    return 0


def cmd_reserve(date):
    sched = plan(date)
    print('■ %s のThreads: %d本' % (date, len(sched)))
    for slot, p in sched:
        print('  %s  %s（%d字・画像%s）' % (slot, p['作品'], len(p['本文']), 'あり' if p.get('画像') else 'なし'))
    if not settings().get('投稿する'):
        print('お試し中なので、予約には入れていません（設定.json の「投稿する」が false）')
        return 0
    queue = load(os.path.join(ROOT, 'queue.json'), [])
    have = {e['id'] for e in queue}
    os.makedirs(os.path.join(ROOT, 'images'), exist_ok=True)
    added = 0
    for slot, p in sched:
        eid = 'news-%s-%s' % (date.replace('-', ''), slot.replace(':', ''))
        if eid in have:
            continue
        entry = {'id': eid, 'time': '%s %s' % (date, slot), 'title': 'ニュース: %s' % p['作品'], 'text': p['本文']}
        if p.get('画像'):
            dst = 'images/%s.jpg' % eid
            im = Image.open(os.path.join(HERE, p['画像'])).convert('RGB')
            if max(im.size) > 2000:
                im.thumbnail((2000, 2000), Image.LANCZOS)
            im.save(os.path.join(ROOT, dst), 'JPEG', quality=90)
            entry['images'] = [dst]
        queue.append(entry)
        added += 1
    with open(os.path.join(ROOT, 'queue.json'), 'w', encoding='utf-8') as f:
        json.dump(queue, f, ensure_ascii=False, indent=1)
        f.write('\n')
    print('予約に %d本 入れました' % added)
    return 0


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in ('見せる', '予約'):
        print(__doc__)
        return 1
    return {'見せる': cmd_show, '予約': cmd_reserve}[sys.argv[1]](sys.argv[2])


if __name__ == '__main__':
    sys.exit(main())
