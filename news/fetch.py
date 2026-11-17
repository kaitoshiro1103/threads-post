#!/usr/bin/env python3
"""
fetch.py — アニメニュースの材料を取ってくる（判断はしない。選ぶのは担当）

  python3 fetch.py 一覧 --時間 24          # コミックナタリーとアニメ！アニメ！の新着（この24時間ぶん）
  python3 fetch.py 記事 URL               # 記事の本文・画像の候補・権利表記
  python3 fetch.py 画像 URL 保存先.jpg     # 画像を落として大きさを出す

外に送るのは、記事や画像を取りに行く通信だけ。鍵は使わない。
"""
import argparse
import datetime
import email.utils
import html
import json
import re
import subprocess
import sys

JST = datetime.timezone(datetime.timedelta(hours=9))
UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36'
FEEDS = [('コミックナタリー', 'https://natalie.mu/comic/feed/news'),
         ('アニメ！アニメ！', 'https://animeanime.jp/rss20/index.rdf')]
# ニュースではない記事（配信の案内・グッズ・発売リスト）。題にこれがあれば一覧に出さない
SKIP = ('配信はどこで見れる', '配信はどこ', '何台まで', '発売のマンガ', '発売分のマンガ雑誌', '【写真', 'レイヤーまとめ')


def get(url, binary=False):
    r = subprocess.run(['curl', '-sL', '--max-time', '40', '-A', UA, url], capture_output=True)
    if r.returncode != 0:
        raise RuntimeError('取れませんでした（curl %d）: %s' % (r.returncode, url))
    return r.stdout if binary else r.stdout.decode('utf-8', 'replace')


def clean(s):
    s = re.sub(r'<!\[CDATA\[(.*?)\]\]>', r'\1', s, flags=re.S)
    return html.unescape(re.sub(r'<[^>]+>', '', s)).strip()


def cmd_list(a):
    now = datetime.datetime.now(JST)
    since = now - datetime.timedelta(hours=a.hours)
    out, bad = [], []
    for name, url in FEEDS:
        try:
            t = get(url)
        except RuntimeError as e:
            bad.append(str(e))
            continue
        blocks = re.findall(r'<entry>(.*?)</entry>', t, re.S) or re.findall(r'<item>(.*?)</item>', t, re.S)
        if not blocks:
            bad.append('%s: 新着が読めませんでした（形が変わったかもしれません）' % name)
        for b in blocks:
            title = clean(re.search(r'<title[^>]*>(.*?)</title>', b, re.S).group(1))
            m = re.search(r'<(?:published|updated)>(.*?)<', b)
            if m:
                when = datetime.datetime.fromisoformat(m.group(1).replace('Z', '+00:00'))
            else:
                when = email.utils.parsedate_to_datetime(re.search(r'<pubDate>(.*?)<', b).group(1))
            m = re.search(r'<link[^>]*href="([^"]+)"', b) or re.search(r'<link>(.*?)<', b)
            if when < since or any(k in title for k in SKIP):
                continue
            out.append({'時刻': when.astimezone(JST).strftime('%m/%d %H:%M'), 'サイト': name,
                        '題': title, 'url': m.group(1).strip()})
    out.sort(key=lambda x: x['時刻'], reverse=True)
    print(json.dumps({'いま': now.strftime('%Y-%m-%d %H:%M'), '件数': len(out), '取れなかった': bad, '新着': out},
                     ensure_ascii=False, indent=1))
    return 1 if bad and not out else 0


def cmd_article(a):
    t = get(a.url)
    body = re.sub(r'<script.*?</script>|<style.*?</style>', '', t, flags=re.S)
    m = re.search(r'<article.*?</article>', body, re.S)
    text = re.sub(r'\s+', ' ', clean(m.group(0) if m else body))
    imgs = []
    if 'natalie.mu' in a.url:
        og = re.search(r'og:image" content="([^"?]+)', t).group(1)
        head = re.split(r'[_.]', og.rsplit('/', 1)[1])[0]              # 同じ記事の画像は名前の頭が同じ（ほかの記事のサムネを除く）
        for u in re.findall(r'https://ogre\.natalie\.mu/media/news/comic/[^"\'? ]+\.(?:jpg|png|webp)', t):
            if u.rsplit('/', 1)[1].startswith(head) and u not in imgs:
                imgs.append(u)
    else:
        for i in re.findall(r'/imgs/(?:ogp_f|sq_sl|zoom)/(\d+)\.jpg', t):
            u = 'https://animeanime.jp/imgs/zoom/%s.jpg' % i
            if u not in imgs:
                imgs.append(u)
    rights = list(dict.fromkeys(c.strip() for c in re.findall(r'[©Ⓒ][^<"\n]{3,90}', t) if 'Natasha' not in c and 'IID' not in c))
    official = re.findall(r'href="(https?://[^"]+)"[^>]*>[^<]{0,30}公式(?:サイト|HP)', t)
    print(json.dumps({'本文': text[:a.chars], '画像の候補': imgs[:12], '権利': rights[:3],
                      '公式サイト': list(dict.fromkeys(official))[:3]}, ensure_ascii=False, indent=1))
    return 0


def cmd_image(a):
    data = get(a.url, binary=True)
    with open(a.dest, 'wb') as f:
        f.write(data)
    from PIL import Image
    try:
        im = Image.open(a.dest)
        im.load()
    except Exception:
        print('✕ 画像として読めません: %s' % a.url)
        return 1
    if im.format not in ('JPEG', 'PNG'):            # webpなどはjpgに直す（Threadsが受け付ける形にする）
        im.convert('RGB').save(a.dest, 'JPEG', quality=92)
    print('%s  %dx%d  %s' % (a.dest, im.width, im.height, '縦長' if im.height >= im.width * 1.15 else '横長'))
    return 0


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('一覧')
    s.add_argument('--時間', dest='hours', type=float, default=24)
    s = sub.add_parser('記事')
    s.add_argument('url')
    s.add_argument('--字数', dest='chars', type=int, default=1600)
    s = sub.add_parser('画像')
    s.add_argument('url')
    s.add_argument('dest')
    a = p.parse_args()
    return {'一覧': cmd_list, '記事': cmd_article, '画像': cmd_image}[a.cmd](a)


if __name__ == '__main__':
    sys.exit(main())
