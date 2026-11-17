import sys

import pytest

from minicpm_tools import cli, history, receipt
from minicpm_tools.common import ToolError


def test_demo_receipt_counts_links_and_disclosure():
    entries, day, zone, groups = history.demo_data()
    html = receipt.render_receipt(entries, day, zone, groups, demo=True)
    assert '<strong>18</strong>' in html and '<strong>03</strong>' in html
    assert html.count('<a ') == 18
    assert '链接参数已隐藏' in html
    assert '2 次访问' in html
    assert '预录' in html and '未归类' in html


def test_share_has_no_hidden_details():
    entries, day, zone, groups = history.demo_data()
    html = receipt.render_receipt(entries, day, zone, groups, share=True)
    for row in entries:
        assert row['url'] not in html
        assert row['domain'] not in html
    assert 'Python 文件读取教程' not in html
    assert '<a ' not in html
    assert '主题名称仍可能涉及隐私' in html


def test_overview_escapes_analysis_and_links_to_evidence():
    entries, day, zone, _ = history.demo_data()
    groups = [('甲', list(range(1, 19)))]
    overview_data = ([('<script>分析</script>', [1, 2])], 18)
    html = receipt.render_receipt(entries, day, zone, groups, overview=overview_data)
    overview = html.split('<aside class="overview">', 1)[1].split('</aside>', 1)[0]
    assert '&lt;script&gt;分析&lt;/script&gt;' in overview
    assert 'href="#record-1"' in overview and 'id="record-1"' in html
    assert '未读取正文' in overview
    assert '今日概览' not in receipt.render_receipt(entries, day, zone, groups, share=True,
                                                    overview=overview_data)
    assert '<aside class="overview">' not in receipt.render_receipt(entries, day, zone)


def test_content_overview_checks_model_references():
    entries, _, _, _ = history.demo_data()
    prompts = []

    class Client:
        def chat(self, prompt):
            prompts.append(prompt)
            return '{"insights":[{"text":"网页涉及编程","ids":[1,1,2,3,4,5,6]}]}'

    items, sampled = history.content_overview(entries, Client())
    assert items == [('网页涉及编程', [1, 2, 3, 4, 5])]
    assert sampled == 16
    assert 'example.org' not in prompts[0]
    assert '\n17 ' not in prompts[0]

    for bad_ids in ('[999]', '[1,2,3,4,5,999]', '[17]'):
        class BadClient:
            def chat(self, prompt, ids=bad_ids):
                return f'{{"insights":[{{"text":"编造","ids":{ids}}}]}}'

        with pytest.raises(ToolError):
            history.content_overview(entries, BadClient())


def test_html_escapes_model_and_title():
    entries, day, zone, _ = history.demo_data()
    entries = entries[:1]
    entries[0]['title'] = '<script>alert("x")</script>'
    html = receipt.render_receipt(entries, day, zone, [('<img src=x onerror=alert(1)>', [1])])
    assert '<script>' not in html and '<img ' not in html
    assert '&lt;script&gt;' in html and '&lt;img ' in html
    assert "default-src 'none'" in html


def test_receipt_escapes_terminal_and_bidi_controls():
    entries = [{
        'id': 1,
        'time': '08:30',
        'title': 'Page\x1b]52;c;payload\x07\u202e',
        'url': 'https://example.com/\x1b[0m/\u202e',
        'domain': 'example.com\u202e',
        'visits': 1,
        'link_redacted': False,
    }]
    groups = [('Topic\x1b[0m\u202e', [1])]
    overview = ([('Insight\x9b\u202e', [1])], 1)
    html = receipt.render_receipt(entries, '2026-11-12', 'Asia/Shanghai', groups, overview=overview)
    for raw_char in ('\x1b', '\x07', '\x9b', '\u202e'):
        assert raw_char not in html
    assert r'\x1b' in html and r'\x07' in html and r'\x9b' in html and r'\u202e' in html
    assert '%1B' in html and '%E2%80%AE' in html
    share_html = receipt.render_receipt(entries, '2026-11-12', 'Asia/Shanghai', groups, share=True)
    for raw_char in ('\x1b', '\x07', '\u202e'):
        assert raw_char not in share_html


def test_list_empty_and_approximate():
    html = receipt.render_receipt([], '2026-11-12', 'UTC', approximate=True)
    assert '当天没有符合筛选条件' in html
    assert '可能包含未提交内容' in html
    entries, day, zone, _ = history.demo_data()
    assert '未作主题归类' in receipt.render_receipt(entries, day, zone)


def test_invalid_group_fails_before_output():
    entries, day, zone, _ = history.demo_data()
    with pytest.raises(ToolError):
        receipt.render_receipt(entries, day, zone, [('wrong', [999])])
    groups = [('甲', list(range(1, 19)))]
    for bad_overview in (
        ([('越界引用', [999])], 16),
        ([('非整数引用', ['1'])], 16),
        ([('空白', [1])], -1),
    ):
        with pytest.raises(ToolError):
            receipt.render_receipt(entries, day, zone, groups, overview=bad_overview)


def test_receipt_existing_markdown_prevents_html(tmp_path):
    old = tmp_path / '2026-11-12-reading.md'
    old.write_text('keep')
    with pytest.raises(ToolError):
        receipt.publish_receipt(tmp_path, '2026-11-12', 'html', 'markdown')
    assert old.read_text() == 'keep'
    assert not (tmp_path / '2026-11-12-reading.html').exists()


def test_second_write_failure_cleans_first(tmp_path, monkeypatch):
    original = receipt.write_new

    def fail_second(path, value):
        if path.suffix == '.md':
            raise OSError('synthetic failure')
        return original(path, value)

    monkeypatch.setattr(receipt, 'write_new', fail_second)
    with pytest.raises(OSError):
        receipt.publish_receipt(tmp_path, '2026-11-12', 'html', 'md')
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('mode,expected', [('receipt', 2), ('receipt-share', 1)])
def test_cli_demo_exports_no_personal_history(tmp_path, monkeypatch, capsys, mode, expected):
    monkeypatch.setenv('MINICPM_BASE_URL', 'https://invalid.example')
    monkeypatch.setattr(sys, 'argv', ['mcpm', 'history', '--demo', '--format', mode,
                                    '--output-dir', str(tmp_path)])
    assert cli.main() == 0
    assert len(list(tmp_path.iterdir())) == expected
    if mode == 'receipt':
        html = (tmp_path / '2026-11-12-reading.html').read_text(encoding='utf-8')
        assert '今日概览' in html and '抽样的 16 条' in html
        assert '主题与概览为预录的 MiniCPM5-2B 输出' in html
    else:
        html = (tmp_path / '2026-11-12-reading-share.html').read_text(encoding='utf-8')
        assert '今日概览' not in html
        assert '主题为预录的 MiniCPM5-2B 输出' in html
    capsys.readouterr()
    assert cli.main() == 1
    assert '拒绝覆盖' in capsys.readouterr().err
