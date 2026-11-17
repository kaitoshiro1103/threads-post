#!/usr/bin/env python3
"""
make.py — 今日のアニメニュース（news.json）から、ストーリー画像とThreadsの文を作る

  python3 make.py news.json --out 出力/2026-11-17

news.json の形（1件＝1ニュース。並び順＝大事な順）:
  {"日付": "2026-11-17",
   "ニュース": [{"ランク": "A",            # A=新作アニメ化・続編決定／B=放送日・公開日などの大きな続報／C=PV・主題歌・キャストなどの続報
                "札": "TVアニメ化決定",     # 赤い札に出す短い言葉
                "作品": "ダイヤモンドの功罪",
                "作品": "…",                # 長い題は \\n で切る場所を入れる（ストーリーの2行の切れ目）
                "要点": ["…", "…"],         # 事実だけ。3つまで・1つ20字まで（ストーリーで1行に収める）
                "補足": "…",                # Threadsだけに出す文（無くてよい）
                "ひとこと": "…",            # Threadsの最後に付ける1行（無くてよい）
                "出典": "コミックナタリー",
                "url": "https://…",
                "画像": "素材/daiya.jpg",    # このファイルからの相対パス
                "権利": "©…"}]}

ストーリーに入るのはランクAだけ・3枚まで・子ども向け（"子ども向け": true）は除く（2026年11月17日の本人の指示）。Threadsは全部出す。
画面は開かない。フォントは fonts/ の しっぽり明朝（OFL）だけを使うので、クラウドでも同じ絵になる。
"""
import argparse
import json
import os
import sys

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
W, H = 1080, 1920
TOP_SAFE, BOTTOM_SAFE = 230, 1710     # Instagramの画面で隠れる所（上＝名前の行／下＝メッセージ欄）をよける
PAD = 64
RED = (252, 44, 68)                   # あらすじ画像と同じ赤
STORY_MAX = 3
STORY_RANKS = ('A',)

NO_HEAD = set('、。，．・：；？！゛゜ヽヾゝゞ々ー）〕］｝〉》」』】…‥ぁぃぅぇぉっゃゅょゎァィゥェォッャュョヮ,.!?)]}％%')
NO_TAIL = set('（〔［｛〈《「『【([{')


def font(weight, size):
    """しっぽり明朝。その太さのファイルが無ければ Bold を使う（GitHubに置くのは1本30MBの Bold だけ）"""
    path = os.path.join(HERE, 'fonts', 'ShipporiMinchoB1-%s.ttf' % weight)
    if not os.path.exists(path):
        path = os.path.join(HERE, 'fonts', 'ShipporiMinchoB1-Bold.ttf')
    return ImageFont.truetype(path, size)


def wrap(text, f, width):
    """幅に収まるように行に分ける。行の頭に「、」「。」などが来ないようにし、英数字の単語は切らない"""
    lines, cur = [], ''
    tokens, buf = [], ''
    for ch in text:
        if ch.isascii() and (ch.isalnum() or ch in "'&-."):
            buf += ch
            continue
        if buf:
            tokens.append(buf)
            buf = ''
        tokens.append(ch)
    if buf:
        tokens.append(buf)
    for tok in tokens:
        if tok == '\n':
            lines.append(cur)
            cur = ''
            continue
        if f.getlength(cur + tok) <= width or not cur:
            cur += tok
            continue
        if tok[0] in NO_HEAD:                       # 行の頭に来られない字は、前の1字ごと次の行へ
            carry = cur[-1]
            lines.append(cur[:-1])
            cur = carry + tok
        elif cur[-1] in NO_TAIL:                    # 行の終わりに来られない字も次の行へ
            lines.append(cur[:-1])
            cur = cur[-1] + tok
        else:
            lines.append(cur)
            cur = tok.lstrip(' ')
    if cur:
        lines.append(cur)
    return [l for l in lines if l != '']


def fit(text, weight, sizes, width, max_lines):
    """行数が max_lines に収まる、いちばん大きい字を選ぶ"""
    for size in sizes:
        f = font(weight, size)
        lines = wrap(text, f, width)
        if len(lines) <= max_lines:
            return f, lines
    return f, lines[:max_lines]


def cover(img, w, h, top=True):
    """画面いっぱいに敷く（はみ出す分は切る。縦は上寄せ）"""
    s = max(w / img.width, h / img.height)
    img = img.resize((round(img.width * s), round(img.height * s)), Image.LANCZOS)
    x = (img.width - w) // 2
    y = 0 if top else (img.height - h) // 2
    return img.crop((x, y, x + w, y + h))


def shade(canvas, y0, y1, a0, a1):
    """y0〜y1 を上から下へ a0→a1 の濃さで黒くする"""
    grad = Image.new('L', (1, max(y1 - y0, 1)))
    grad.putdata([round(a0 + (a1 - a0) * i / max(y1 - y0 - 1, 1)) for i in range(max(y1 - y0, 1))])
    black = Image.new('RGB', (W, y1 - y0), (8, 8, 8))
    canvas.paste(black, (0, y0), grad.resize((W, y1 - y0)))


def story(item, date_label, page, total, out, warn):
    """1ニュース1枚。上に公式の画像を切らずに丸ごと置き、下に 札→作品名→要点→出典 を積む。
    画像を画面いっぱいに敷く形は、画像の中の文字とこちらの文字が重なって読みにくかったのでやめた"""
    canvas = Image.new('RGB', (W, H), (12, 12, 12))
    src = Image.open(os.path.join(HERE, item['画像'])).convert('RGB')
    name = item['作品'].replace('\n', '')

    tw = W - PAD * 2
    f_tag = font('Bold', 46)
    if '\n' in item['作品']:                       # 改行が指定してあれば、その位置で2行にする
        t_lines = item['作品'].split('\n')[:2]
        for size in (92, 84, 76, 68, 60, 54):
            f_title = font('Bold', size)
            if max(f_title.getlength(l) for l in t_lines) <= tw:
                break
    else:
        f_title, t_lines = fit(item['作品'], 'Bold', (92, 84, 76, 68, 60), tw, 2)
        if len(t_lines) > 1:
            warn.append('%s: 作品名が途中で折り返されました（"作品" に \\n で切る場所を入れてください）: %s' % (name, ' / '.join(t_lines)))
    f_pt = font('SemiBold', 44)
    pts = [wrap(p, f_pt, tw - 50) for p in item.get('要点', [])[:3]]
    for p, raw in zip(pts, item.get('要点', [])):
        if len(p) > 1:
            warn.append('%s: 要点が1行に収まっていません（20字まで）: %s' % (name, raw))
    f_src = font('Medium', 26)
    credit = '出典：%s' % item['出典'] + ('　%s' % item['権利'] if item.get('権利') else '')
    c_lines = wrap(credit, f_src, tw)[:2]

    title_lh = round(f_title.size * 1.22)
    pt_lh, h_tag = 66, 78
    h_title = title_lh * len(t_lines)
    h_pts = sum(len(p) for p in pts) * pt_lh + max(len(pts) - 1, 0) * 10
    h_src = 36 * len(c_lines)
    block = h_tag + 28 + h_title + 26 + h_pts + 30 + h_src
    top = BOTTOM_SAFE - block

    d = ImageDraw.Draw(canvas)
    # 見出し
    f_head = font('Bold', 40)
    d.rectangle((PAD, TOP_SAFE + 6, PAD + 8, TOP_SAFE + 50), fill=RED)
    d.text((PAD + 26, TOP_SAFE + 28), '今日のアニメニュース', font=f_head, fill='white', anchor='lm')
    f_date = font('SemiBold', 34)
    d.text((W - PAD, TOP_SAFE + 28), '%s　%d/%d' % (date_label, page, total), font=f_date,
           fill=(200, 200, 200), anchor='rm')

    # 画像（切らずに丸ごと。見出しの下〜文字の上の間に、いちばん大きく入れる）
    ay0, ay1 = TOP_SAFE + 86, top - 44
    aw, ah = W - 80, ay1 - ay0
    s = min(aw / src.width, ah / src.height)
    iw, ih = round(src.width * s), round(src.height * s)
    if s > 2.2:
        warn.append('%s: 画像が小さいです（%dx%d を %.1f倍に拡大）。もっと大きい画像を探してください' % (name, src.width, src.height, s))
    ix, iy = (W - iw) // 2, ay0 + (ah - ih) // 2
    canvas.paste(src.resize((iw, ih), Image.LANCZOS), (ix, iy))
    d.rectangle((ix - 1, iy - 1, ix + iw, iy + ih), outline=(70, 70, 70), width=2)

    # 赤い札
    y = top
    tag_w = round(f_tag.getlength(item['札'])) + 56
    d.rounded_rectangle((PAD, y, PAD + tag_w, y + h_tag), radius=14, fill=RED)
    d.text((PAD + tag_w / 2, y + h_tag / 2), item['札'], font=f_tag, fill='white', anchor='mm')
    y += h_tag + 28
    for line in t_lines:
        d.text((PAD, y + title_lh / 2), line, font=f_title, fill='white', anchor='lm')
        y += title_lh
    y += 26
    for p in pts:
        d.ellipse((PAD + 6, y + pt_lh / 2 - 9, PAD + 24, y + pt_lh / 2 + 9), fill=RED)
        for line in p:
            d.text((PAD + 50, y + pt_lh / 2), line, font=f_pt, fill=(240, 240, 240), anchor='lm')
            y += pt_lh
        y += 10
    y += 20
    for line in c_lines:
        d.text((PAD, y + 18), line, font=f_src, fill=(150, 150, 150), anchor='lm')
        y += 36
    canvas.save(out, quality=95)
    return out


def threads_text(item):
    """Threadsの本文。ひとこと（1人のアニメ好きの声）→事実→問いかけ の順（出典は書かない。11/17の指示）（2026/11/17に変更。
    Threadsで伸びているのは、話しかけて答えたくなる投稿。お知らせの形は見られなかった）"""
    parts = []
    if item.get('ひとこと'):
        parts += [item['ひとこと'], '']
    parts += ['【%s】%s' % (item['札'], item['作品'].replace('\n', ''))]
    parts += ['・' + p for p in item.get('要点', [])]
    if item.get('補足'):
        parts += ['', item['補足']]
    if item.get('問いかけ'):
        parts += ['', item['問いかけ']]
    return '\n'.join(parts)


def summary_text(items, date_label):
    lines = ['【%s のアニメニュースまとめ】' % date_label, '']
    for i in items:
        lines.append('・%s：%s' % (i['作品'].replace('\n', ''), i['札']))
    lines += ['', '気になるニュースはありましたか？']
    return '\n'.join(lines)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('news')
    p.add_argument('--out', required=True)
    a = p.parse_args()
    data = json.load(open(a.news, encoding='utf-8'))
    items = data['ニュース']
    y, m, dd = data['日付'].split('-')
    date_label = '%d/%d' % (int(m), int(dd))
    os.makedirs(a.out, exist_ok=True)

    picks = [i for i in items if i.get('ランク') in STORY_RANKS and not i.get('子ども向け')][:STORY_MAX]   # 子ども向けはストーリーに入れない（11/17の指示）
    warn = []
    for n, item in enumerate(picks, 1):
        out = story(item, date_label, n, len(picks), os.path.join(a.out, 'story_%d.jpg' % n), warn)
        print('ストーリー %d/%d: %s（%s）' % (n, len(picks), item['作品'], out))
    if not picks:
        print('ストーリー: 新作・続編のニュースが無いので、今日は作りません')

    posts = [{'作品': i['作品'].replace('\n', ''), 'ランク': i.get('ランク'), '本文': threads_text(i), '画像': i.get('画像')} for i in items]
    posts.append({'作品': 'まとめ', 'ランク': '-', '本文': summary_text(items, date_label), '画像': None})
    talks = data.get('話しかけ', [])
    for t in talks:                                  # ニュースとは別の「アニメ好きの1人」の投稿（画像・リンクなし）
        posts.append({'作品': '話しかけ', 'ランク': t.get('型', '-'), '本文': t['本文'].strip(), '画像': None})
    with open(os.path.join(a.out, 'threads.json'), 'w', encoding='utf-8') as f:
        json.dump(posts, f, ensure_ascii=False, indent=1)
    with open(os.path.join(a.out, 'threads.txt'), 'w', encoding='utf-8') as f:
        for n, post in enumerate(posts, 1):
            f.write('━━ %d本目（%s・%d字・画像%s）━━\n%s\n\n' % (
                n, post['ランク'], len(post['本文']), 'あり' if post['画像'] else 'なし', post['本文']))
    print('Threads: %d本（%s）' % (len(posts), os.path.join(a.out, 'threads.txt')))
    warn += ['%s: Threadsの本文が500字を超えています' % post['作品'] for post in posts if len(post['本文']) > 500]
    warn += ['%s: 問いかけがありません（Threadsは問いかけで終える）' % i['作品'].replace('\n', '') for i in items if not i.get('問いかけ')]
    warn += ['%s: ひとことがありません（Threadsは1人の声から始める）' % i['作品'].replace('\n', '') for i in items if not i.get('ひとこと')]
    if len(talks) < 2:
        warn.append('話しかけの投稿が%d本です（毎日2本）' % len(talks))
    for t in talks:
        if 'http' in t['本文'] or '#' in t['本文']:
            warn.append('話しかけにリンクか＃が入っています: %s' % t['本文'][:20])
    for w in warn:
        print('▲ ' + w)
    return 1 if warn else 0


if __name__ == '__main__':
    sys.exit(main())
