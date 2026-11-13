import sys

import pytest

from minicpm_tools import cli, history, receipt
from minicpm_tools.common import ToolError


def test_receipt_style_is_local_and_rows_keep_fields():
    entries, day, zone, groups = history.demo_data()
    html = receipt.render_receipt(entries, day, zone, groups, demo=True)
    style = html.split('<style>', 1)[1].split('</style>', 1)[0]
    footer = html.split('<footer>', 1)[1]
    assert '<link ' not in html
    assert 'url(' not in style and 'http://' not in style and 'https://' not in style
    assert 'text-overflow: ellipsis' in style
    assert html.count('class="total-row"') == 2
    assert 'class="barcode"' in footer and 'example.org' not in footer
    assert 'example.org · 00:30' in html and '2 次访问' in html
    assert 'title="Python 文件读取教程"' in html
    share = receipt.render_receipt(entries, day, zone, groups, share=True)
    assert 'class="barcode"' in share and 'example.org' not in share


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


def test_html_escapes_model_and_title():
    entries, day, zone, _ = history.demo_data()
    entries = entries[:1]
    entries[0]['title'] = '<script>alert("x")</script>'
    html = receipt.render_receipt(entries, day, zone, [('<img src=x onerror=alert(1)>', [1])])
    assert '<script>' not in html and '<img ' not in html
    assert '&lt;script&gt;' in html and '&lt;img ' in html
    assert "default-src 'none'" in html


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
    capsys.readouterr()
    assert cli.main() == 1
    assert '拒绝覆盖' in capsys.readouterr().err
