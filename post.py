#!/usr/bin/env python3
"""
post.py — 予約した投稿を、時刻が来たら Threads に出す（GitHubのタイマーが動かす）

  queue.json … 予約のリスト（Macで書いて送る。ここでは読むだけ）
  done.json  … 出し終わった記録（ここだけが書く）

1件の流れ: 画像の入れ物を作る → まとめて1つの投稿にする → 公開 → その投稿にリプ（リンクと #PR）を付ける。
途中で失敗しても、次の回に「続きから」やり直す（同じ投稿を2回出さない）。

公式の説明: https://developers.facebook.com/docs/threads/posts/
"""
import datetime
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = 'https://graph.threads.net/v1.0'
JST = datetime.timezone(datetime.timedelta(hours=9))
HERE = os.path.dirname(os.path.abspath(__file__))
QUEUE = os.path.join(HERE, 'queue.json')
DONE = os.path.join(HERE, 'done.json')
LATE_LIMIT_H = 6      # 予定から6時間を過ぎた予約は出さない（タイマーが止まっていた後に、古い予約がまとめて出るのを防ぐ）
WAIT = 30             # 入れ物を作ってから公開するまで待つ秒数（公式の目安）
TOKEN = os.environ.get('THREADS_TOKEN', '')
DRY = os.environ.get('DRY_RUN') == '1'


def call(method, path, **params):
    params['access_token'] = TOKEN
    data = urllib.parse.urlencode(params).encode()
    url = '%s/%s' % (API, path)
    if method == 'GET':
        url, data = url + '?' + data.decode(), None
    req = urllib.request.Request(url, data=data, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', 'replace')
        raise RuntimeError('Threadsが断りました（%s）: %s' % (e.code, body.replace(TOKEN, '***')[:400]))


def load(path, default):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def save_done(done):
    with open(DONE, 'w', encoding='utf-8') as f:
        json.dump(done, f, ensure_ascii=False, indent=1)


def wait_ready(cid, first=WAIT):
    """入れ物の準備が終わるまで待つ。状態が取れないときは決まった秒数だけ待つ"""
    time.sleep(first)
    for _ in range(18):
        try:
            st = call('GET', cid, fields='status,error_message')
        except RuntimeError:
            time.sleep(max(WAIT - first, 0))
            return
        if st.get('status') in (None, 'FINISHED', 'PUBLISHED'):
            return
        if st.get('status') in ('ERROR', 'EXPIRED'):
            raise RuntimeError('画像を受け取れませんでした: %s' % st.get('error_message'))
        time.sleep(5)


def publish(uid, cid):
    wait_ready(cid)
    return call('POST', '%s/threads_publish' % uid, creation_id=cid)['id']


def image_url(p):
    """queue.json には images/〜.jpg と書いてある。GitHubに置いた画像の、誰でも見られるURLに直す"""
    if p.startswith('http'):
        return p
    return 'https://raw.githubusercontent.com/%s/%s/%s' % (
        os.environ.get('GITHUB_REPOSITORY', ''), os.environ.get('GITHUB_REF_NAME', 'main'),
        urllib.parse.quote(p))


def post_main(uid, e):
    imgs = [image_url(p) for p in e.get('images') or []]
    text = e.get('text') or ''
    if not imgs:
        cid = call('POST', '%s/threads' % uid, media_type='TEXT', text=text)['id']
    elif len(imgs) == 1:
        cid = call('POST', '%s/threads' % uid, media_type='IMAGE', image_url=imgs[0], text=text)['id']
    else:
        kids = [call('POST', '%s/threads' % uid, media_type='IMAGE', image_url=u,
                     is_carousel_item='true')['id'] for u in imgs]
        # 1枚ずつの準備が終わってから、まとめの入れ物を作る。待たずに作ると
        # 「Invalid Carousel Children」で断られる（2026年10月11日、最初の本番で発生）
        for k in kids:
            wait_ready(k, first=5)
        cid = call('POST', '%s/threads' % uid, media_type='CAROUSEL', children=','.join(kids),
                   text=text)['id']
    return publish(uid, cid)


def post_reply(uid, parent, text):
    cid = call('POST', '%s/threads' % uid, media_type='TEXT', text=text, reply_to_id=parent)['id']
    return publish(uid, cid)


def main():
    now = datetime.datetime.now(JST)
    queue = load(QUEUE, [])
    done = load(DONE, {})
    todo = []
    for e in queue:
        d = done.get(e['id'], {})
        if d.get('finished') or d.get('skipped'):
            continue
        when = datetime.datetime.strptime(e['time'], '%Y-%m-%d %H:%M').replace(tzinfo=JST)
        if when > now:
            continue
        if not d.get('post_id') and now - when > datetime.timedelta(hours=LATE_LIMIT_H):
            done[e['id']] = {'skipped': '予定の時刻から%d時間を過ぎたので出しませんでした' % LATE_LIMIT_H}
            print('✕ 見送り %s（%s）' % (e['id'], e['time']))
            continue
        todo.append(e)
    if not todo:
        save_done(done)
        print('出す予約はありません（%s）' % now.strftime('%m/%d %H:%M'))
        return 0
    if DRY:
        for e in todo:
            print('【試し】%s  画像%d枚  本文%d字  リプ%d字' % (
                e['time'], len(e.get('images') or []), len(e.get('text') or ''), len(e.get('reply') or '')))
        return 0
    if not TOKEN:
        print('✕ 合言葉（THREADS_TOKEN）が入っていません')
        return 1
    uid = call('GET', 'me', fields='id')['id']
    bad = 0
    for e in todo:
        d = done.setdefault(e['id'], {})
        try:
            if not d.get('post_id'):
                d['post_id'] = post_main(uid, e)
                d['posted_at'] = datetime.datetime.now(JST).strftime('%Y-%m-%d %H:%M')
                save_done(done)       # ここで必ず残す（リプで失敗しても、投稿を2回出さないため）
                print('○ 投稿しました %s' % e['id'])
            if e.get('reply') and not d.get('reply_id'):
                d['reply_id'] = post_reply(uid, d['post_id'], e['reply'])
                print('○ リプを付けました %s' % e['id'])
            d['finished'] = True
            d.pop('error', None)
            try:
                d['url'] = call('GET', d['post_id'], fields='permalink').get('permalink')
            except RuntimeError:
                pass
        except Exception as ex:          # 1件の失敗で、ほかの予約を止めない
            bad += 1
            d['error'] = str(ex)[:300]
            d['tries'] = d.get('tries', 0) + 1
            if d["tries"] >= 5:
                d['skipped'] = '5回失敗したのでやめました'
            print('✕ 失敗 %s: %s' % (e['id'], d['error']))
        save_done(done)
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
