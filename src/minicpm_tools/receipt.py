"""Self-contained reading receipts; no remote assets or browser-side data processing."""
from html import escape
from importlib.resources import files
from urllib.parse import urlsplit

from .common import ToolError, write_new


def render_receipt(entries, day, zone, groups=None, *, share=False, demo=False, approximate=False):
    by_id = {row['id']: row for row in entries}
    sections = groups or [('访问记录 · 未作主题归类', list(by_id))]
    ids = [i for _, members in sections for i in members]
    if len(ids) != len(set(ids)) or set(ids) != set(by_id):
        raise ToolError('小票分组未完整覆盖记录，拒绝输出。')
    body = []
    for number, (label, members) in enumerate(sections, 1):
        if not members:
            continue
        items = []
        if not share:
            for key in members:
                row = by_id[key]
                title = escape(row['title'])
                url = row['url']
                if urlsplit(url).scheme not in {'http', 'https'}:
                    raise ToolError('小票包含不受支持的链接。')
                notice = '<span class="redacted">链接参数已隐藏，可能无法返回原页面</span>' if row.get('link_redacted') else ''
                items.append(f'<li><a rel="noreferrer noopener" href="{escape(url, quote=True)}">{title}</a>'
                             f'<div class="meta">{escape(row["domain"])} · {escape(row["time"])} · {row["visits"]} 次访问</div>{notice}</li>')
        body.append(f'<section><div class="section-head"><span class="index">{number:02}</span>'
                    f'<h2>{escape(label)}</h2><span class="quantity">{len(members)} 条</span></div>'
                    + ('<ul>' + ''.join(items) + '</ul>' if items else '') + '</section>')
    notices = []
    if demo:
        notices.append('演示 · 记录为虚构；主题为预录的 MiniCPM5-2B 输出，非本次运行。')
    if approximate:
        notices.append('注意：来自无锁近似快照，可能包含未提交内容，不能保证事务一致。')
    if share:
        notices.append('分享视图 · 已省略标题、链接与域名；主题名称仍可能涉及隐私，请先核对。')
    style = files('minicpm_tools').joinpath('receipt.css').read_text(encoding='utf-8')
    mode = '分享小票' if share else '本地详单'
    content = ''.join(body) if entries else '<p class="empty">当天没有符合筛选条件的访问记录。</p>'
    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<meta name="referrer" content="no-referrer"><title>阅读小票 · {escape(str(day))}</title><style>{style}</style></head>
<body><main class="receipt"><header><div class="brand">MINICPM / LOCAL TOOLS</div><div class="edition">DAILY READING RECEIPT</div>
<h1>每日阅读小票</h1><div class="date">{escape(str(day))}</div><div class="zone">{escape(str(zone))} · {mode}</div></header>
<div class="notices">{''.join('<p>' + escape(n) + '</p>' for n in notices)}</div>
<div class="totals"><div><strong>{len(entries):02}</strong><span>访问记录</span></div><div><strong>{len({r['domain'] for r in entries}):02}</strong><span>站点</span></div></div>
<p class="count-note">过滤、去重后的页面数 · 不代表已读完</p>
{content}<footer><div class="stamp">LOCAL ONLY</div><p>仅依据本机访问记录的标题和域名。<br>主题归类请核对；未通过此小票上传数据。</p><p class="thanks">谢谢阅读，下次再见。</p><div class="closing">— END OF RECEIPT —</div></footer></main></body></html>'''


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
