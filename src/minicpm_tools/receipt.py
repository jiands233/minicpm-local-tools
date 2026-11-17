"""Self-contained reading receipts; no remote assets or browser-side data processing."""
import re
from html import escape
from importlib.resources import files
from urllib.parse import quote as url_quote
from urllib.parse import urlsplit

from .common import ToolError, write_new

_UNSAFE_DISPLAY = re.compile(r'[\x00-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]')

# Decorative bars only. Widths are fixed and are not derived from titles or URLs.
_BARCODE_WIDTHS = (
    2, 1, 1, 1, 3, 1, 1, 2, 1, 1, 1, 2, 1, 3, 1, 1,
    1, 2, 1, 1, 4, 1, 1, 1, 2, 1, 1, 3, 1, 1, 2, 1,
    1, 1, 2, 1, 1, 3, 1, 1, 2, 1, 1, 1, 1, 2, 1, 4,
    1, 1, 1, 2, 1, 1, 3, 1, 1, 2, 1, 1, 1, 1, 2, 1,
    3, 1, 1, 1, 2, 1, 1, 2, 1, 1, 1, 1, 2, 1, 3, 1,
)


def _safe_text(value, *, quote=False):
    text = str(value).replace('\r', ' ').replace('\n', ' ')
    text = _UNSAFE_DISPLAY.sub(lambda match: ascii(match.group())[1:-1], text)
    return escape(text, quote=quote)


def _safe_url(raw):
    if urlsplit(raw).scheme not in {'http', 'https'}:
        raise ToolError('小票包含不受支持的链接。')
    url = _UNSAFE_DISPLAY.sub(lambda match: url_quote(match.group(), safe=''), raw)
    return escape(url, quote=True)


def _barcode():
    bars = ''.join(f'<span class="b{width}"></span>' for width in _BARCODE_WIDTHS)
    return f'<div class="barcode" aria-hidden="true">{bars}</div>'


def _barcode_digits(day):
    digits = ' '.join(ch for ch in str(day) if ch.isdigit())
    if not digits:
        return ''
    return f'<div class="barcode-digits" aria-hidden="true">{escape(digits)}</div>'


def _overview(overview, by_id):
    if overview is None:
        return ''
    if (not isinstance(overview, tuple) or len(overview) != 2
            or not isinstance(overview[0], list) or type(overview[1]) is not int
            or overview[1] < 0):
        raise ToolError('小票概览结构无效，拒绝输出。')
    insights, sampled = overview
    if not insights:
        return ('<aside class="overview"><h2>今日概览</h2>'
                '<p>标题信息不足或概览生成失败，请查看下方记录。</p></aside>')
    items = []
    for entry in insights:
        if (not isinstance(entry, tuple) or len(entry) != 2
                or not isinstance(entry[0], str) or not entry[0].strip()
                or not isinstance(entry[1], list) or not entry[1]
                or any(type(key) is not int or key not in by_id for key in entry[1])):
            raise ToolError('小票概览包含无效引用，拒绝输出。')
        text, ids = entry
        links = '、'.join(f'<a href="#record-{key}">记录 {key}</a>' for key in ids)
        items.append(f'<li>{_safe_text(text)} <span class="sources">依据：{links}</span></li>')
    return (f'<aside class="overview"><h2>今日概览</h2>'
            f'<p>模型依据抽样的 {sampled} 条标题提炼，未读取正文，可能遗漏或误判，请核对引用。</p>'
            f'<ul>{"".join(items)}</ul></aside>')


def render_receipt(entries, day, zone, groups=None, *, share=False, demo=False, approximate=False,
                   overview=None):
    by_id = {row['id']: row for row in entries}
    sections = groups or [('访问记录 · 未作主题归类', list(by_id))]
    ids = [i for _, members in sections for i in members]
    if len(ids) != len(set(ids)) or set(ids) != set(by_id):
        raise ToolError('小票分组未完整覆盖记录，拒绝输出。')
    overview_html = _overview(overview, by_id) if not share else ''
    body = []
    for number, (label, members) in enumerate(sections, 1):
        if not members:
            continue
        items = []
        if not share:
            for key in members:
                row = by_id[key]
                title = _safe_text(row['title'])
                title_attr = _safe_text(row['title'], quote=True)
                href = _safe_url(row['url'])
                notice = (
                    '<span class="redacted">链接参数已隐藏，可能无法返回原页面</span>'
                    if row.get('link_redacted') else ''
                )
                detail = _safe_text(
                    f'{row["domain"]} · {row["time"]} · {row["visits"]} 次访问', quote=True
                )
                items.append(
                    f'<li id="record-{key}"><a rel="noreferrer noopener" href="{href}" '
                    f'title="{title_attr}">{title}</a>'
                    f'<div class="meta" title="{detail}"><span class="meta-text">'
                    f'{_safe_text(row["domain"])} · {_safe_text(row["time"])}</span>'
                    f'<span class="visits">{row["visits"]} 次访问</span></div>{notice}</li>'
                )
        body.append(
            f'<section><div class="section-head"><span class="index">{number:02}</span>'
            f'<h2>{_safe_text(label)}</h2><span class="quantity">{len(members)} 条</span></div>'
            + ('<ul>' + ''.join(items) + '</ul>' if items else '') + '</section>'
        )
    notices = []
    if demo:
        subject = '主题与概览' if overview_html else '主题'
        notices.append(f'演示 · 记录为虚构；{subject}为预录的 MiniCPM5-2B 输出，非本次运行。')
    if approximate:
        notices.append('注意：来自无锁近似快照，可能包含未提交内容，不能保证事务一致。')
    if share:
        notices.append('分享视图 · 已省略标题、链接与域名；主题名称仍可能涉及隐私，请先核对。')
    style = files('minicpm_tools').joinpath('receipt.css').read_text(encoding='utf-8')
    mode = '分享小票' if share else '本地详单'
    content = ''.join(body) if entries else '<p class="empty">当天没有符合筛选条件的访问记录。</p>'
    sites = len({row['domain'] for row in entries})
    safe_day = _safe_text(day)
    safe_zone = _safe_text(zone)
    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<meta name="referrer" content="no-referrer"><title>阅读小票 · {safe_day}</title><style>{style}</style></head>
<body><div class="slip"><main class="receipt"><header><div class="brand">MINICPM / LOCAL TOOLS</div>
<h1>每日阅读小票</h1><div class="edition">DAILY READING RECEIPT</div>
<div class="date">{safe_day}</div><div class="zone">{safe_zone} · {mode}</div></header>
<div class="rule" aria-hidden="true"></div>
<div class="notices">{''.join('<p>' + _safe_text(n) + '</p>' for n in notices)}</div>
<div class="totals"><div class="total-row"><span class="label">访问记录</span><span class="leader" aria-hidden="true"></span><strong>{len(entries):02}</strong></div>
<div class="total-row"><span class="label">站点</span><span class="leader" aria-hidden="true"></span><strong>{sites:02}</strong></div></div>
<p class="count-note">过滤、去重后的页面数 · 不代表已读完</p>
{overview_html}{content}<footer>{_barcode()}{_barcode_digits(day)}<div class="stamp">LOCAL ONLY</div>
<p class="fine">仅依据本机访问记录的标题和域名。<br>主题归类请核对；未通过此小票上传数据。</p>
<p class="thanks">谢谢阅读，下次再见。</p><div class="closing">— END OF RECEIPT —</div></footer></main></div></body></html>'''


def publish_receipt(directory, day, html, markdown=None, *, share=False):
    """Refuse existing outputs before publishing either part of a local receipt."""
    stem = f'{day}-reading-share' if share else f'{day}-reading'
    outputs = [(directory / f'{stem}.html', html)]
    if markdown is not None and not share:
        outputs.append((directory / f'{stem}.md', markdown))
    for path, _ in outputs:
        if path.exists() or path.is_symlink():
            raise ToolError(f'文件已存在，拒绝覆盖：{path}')
    written = []
    try:
        for path, value in outputs:
            write_new(path, value)
            written.append((path, path.stat()))
    except BaseException:
        for path, identity in written:
            try:
                current = path.lstat()
                if (current.st_dev, current.st_ino) == (identity.st_dev, identity.st_ino):
                    path.unlink()
            except OSError:
                pass
        raise
    return [path for path, _ in written]
