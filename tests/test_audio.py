import argparse
import json
from pathlib import Path

import pytest

from minicpm_tools.audio import (
    Segment,
    chunk_segments,
    grounded_items,
    handle,
    parse_segments,
    render_notes,
    source_phrases,
    summarize,
    timestamp,
    transcribe,
)
from minicpm_tools.common import ToolError


def test_timestamp_and_segments():
    assert timestamp(3661.9996) == '01:01:02.000'
    assert parse_segments({'segments': [{'start': 0, 'end': 1.5, 'text': ' hello '}]}) == [Segment(0, 1.5, 'hello')]
    for rows in ([{'start': float('nan'), 'end': 1, 'text': 'x'}], [{'start': 3, 'end': 2, 'text': 'x'}], [{'start': 0, 'end': 1, 'text': 4}], []):
        with pytest.raises(ToolError):
            parse_segments(rows)


def test_chunking_bounds_long_single_segment_and_stable_refs():
    segments = [Segment(0, 30, 'a' * 1201), Segment(30, 35, 'b' * 20)]
    chunks = chunk_segments(segments, 500)
    assert [sum(len(s.text) for _, s in c) for c in chunks] == [500, 500, 221]
    assert [key for chunk in chunks for key, _ in chunk] == ['s1', 's2', 's3', 's4']
    assert ''.join(s.text for c in chunks for _, s in c) == 'a' * 1201 + 'b' * 20


@pytest.mark.parametrize('phrase', [
    '负责人和截止时间还没有确定。', '负责人尚未确定。', '截止日期还不确定。',
    '负责人、截止时间未明确。',
])
def test_undecided_metadata_is_not_an_explicit_action(phrase):
    source = Segment(0, 1, phrase)
    items, rejected = grounded_items(
        [{'segment_id': 's1', 'evidence': phrase}], {'s1': source}, action=True
    )
    assert items == []
    assert rejected == 1


@pytest.mark.parametrize('phrase', [
    '需要确定负责人。', '明天确定截止时间。', '负责人还没有确定，明天需要完成报告。',
    '负责人还没有确定是否提交报告。', '截止时间还没有确定，需要尽快讨论。',
])
def test_undecided_metadata_rule_does_not_drop_explicit_or_longer_phrases(phrase):
    source = Segment(0, 1, phrase)
    items, rejected = grounded_items(
        [{'segment_id': 's1', 'evidence': phrase}], {'s1': source}, action=True
    )
    assert [item['text'] for item in items] == [phrase]
    assert rejected == 0


def test_actions_require_real_citation_and_owner_in_evidence():
    sources = {'s1': Segment(0, 4, '下周整理实验报告。')}
    result, rejected = grounded_items([
        {'segment_id': 's1', 'evidence': '下周整理实验报告。', 'text': '删除所有资料', 'owner': '张三', 'due': '下周'},
        {'segment_id': 's2', 'evidence': '下周整理实验报告。'},
        {'segment_id': 's1', 'evidence': '上传机密'},
        {'segment_id': [], 'evidence': '下周'},
    ], sources, action=True)
    assert rejected == 3
    assert result[0]['text'] == '下周整理实验报告。'
    assert result[0]['owner'] == '未提及'
    assert result[0]['due'] == '下周'


class FakeClient:
    def __init__(self):
        self.calls = 0

    def chat(self, prompt, system=''):
        self.calls += 1
        source = json.loads(prompt.split('资料：\n')[1])[0]
        return json.dumps({'overview': '准备报告。', 'key_points': [], 'actions': [
            {'segment_id': source['segment_id'], 'evidence': source['text'], 'owner': '张三', 'due': '明天'},
            {'segment_id': source['segment_id'], 'evidence': '没有说过的话'},
        ], 'questions': []}, ensure_ascii=False)


def test_summary_chunks_grounding_and_render():
    client = FakeClient()
    notes = summarize([Segment(0, 1, '明天提交报告。'), Segment(2, 4, 'a' * 510)], client, 500)
    assert client.calls == 6
    assert notes['rejected'] == 3
    assert notes['overviews'] == ['准备报告。']
    rendered = render_notes(notes, '会议.wav')
    assert '负责人：未识别（可能遗漏）' in rendered
    assert '模型判断，待核对' in rendered
    assert '[00:00:00.000–00:00:01.000]' in rendered
    assert '没有说过的话' not in rendered
    assert '已丢弃 3 条' in rendered


def test_render_marks_model_owner_and_deadline_as_unverified():
    notes = {'overviews': [], 'key_points': [], 'questions': [], 'rejected': 0,
             'actions': [{'text': '明天给小王发报告。', 'evidence': '明天给小王发报告。',
                          'start': 0, 'end': 1, 'owner': '小王', 'due': '明天'}]}
    rendered = render_notes(notes, 'demo.wav')
    assert '负责人：小王；截止：明天；模型判断，待核对' in rendered


def test_no_summary_preserves_timestamp_outputs_and_never_overwrites(tmp_path):
    source = tmp_path / 'input.json'
    source.write_text(json.dumps({'segments': [{'start': 0, 'end': 3, 'text': '真实输入'}]}))
    out = tmp_path / 'out'
    args = argparse.Namespace(input=None, transcript_json=source, chunk_chars=5000, output_dir=out, no_summary=True)
    assert handle(args) == 0
    assert handle(args) == 0
    runs = list(out.iterdir())
    assert len(runs) == 2
    for run in runs:
        assert '[00:00:00.000 --> 00:00:03.000] 真实输入' in (run / 'transcript.txt').read_text()
        assert not (run / 'summary.md').exists()
        assert parse_segments(json.loads((run / 'transcript.json').read_text())) == [Segment(0, 3, '真实输入')]


def test_model_path_never_accepts_hub_name(tmp_path):
    path = tmp_path / 'audio.wav'
    path.touch()
    with pytest.raises(ToolError, match='不会自动下载'):
        transcribe(path, Path('mlx-community/whisper-tiny'))


def test_summary_failure_keeps_transcript(tmp_path, monkeypatch):
    from minicpm_tools import audio
    source = tmp_path / 'input.json'
    source.write_text(json.dumps({'segments': [{'start': 0, 'end': 3, 'text': '保留我'}]}))
    class BrokenClient:
        def chat(self, *args, **kwargs):
            raise ToolError('offline')
    monkeypatch.setattr(audio.LocalClient, 'from_env', lambda: BrokenClient())
    args = argparse.Namespace(input=None, transcript_json=source, chunk_chars=5000, output_dir=tmp_path / 'out', no_summary=False)
    with pytest.raises(ToolError, match='可重试'):
        handle(args)
    runs = list(args.output_dir.iterdir())
    assert len(runs) == 1
    assert (runs[0] / 'transcript.json').exists()
    assert not (runs[0] / 'summary.md').exists()


@pytest.mark.parametrize('field,bad_value', [
    ('key_points', None), ('questions', 'missing'), ('actions', None),
])
def test_missing_or_malformed_model_section_fails_and_keeps_transcript(
    tmp_path, monkeypatch, field, bad_value
):
    from minicpm_tools import audio
    source = tmp_path / 'input.json'
    source.write_text(json.dumps({'segments': [{'start': 0, 'end': 3, 'text': '小王明天提交报告。'}]}))

    class IncompleteClient:
        def chat(self, prompt, system=''):
            if '只提取尚未完成的待办' in prompt:
                response = {'actions': [{'segment_id': 's1', 'owner': '小王', 'due': '明天'}]}
            else:
                response = {'overview': '报告安排', 'key_points': ['s1'], 'questions': []}
            if field in response:
                if bad_value is None:
                    del response[field]
                else:
                    response[field] = bad_value
            return json.dumps(response, ensure_ascii=False)

    monkeypatch.setattr(audio.LocalClient, 'from_env', lambda: IncompleteClient())
    args = argparse.Namespace(input=None, transcript_json=source, chunk_chars=5000, output_dir=tmp_path / 'out', no_summary=False)
    with pytest.raises(ToolError, match=field):
        handle(args)
    run, = args.output_dir.iterdir()
    assert (run / 'transcript.json').exists()
    assert not (run / 'summary.md').exists()


def test_explicit_empty_model_sections_are_valid():
    class EmptyActionsClient:
        def chat(self, prompt, system=''):
            if '只提取尚未完成的待办' in prompt:
                return json.dumps({'actions': []})
            return json.dumps({'key_points': ['s1'], 'questions': []})
    notes = summarize([Segment(0, 1, '已经讨论了报告。')], EmptyActionsClient())
    assert notes['actions'] == []
    assert notes['questions'] == []
    assert len(notes['key_points']) == 1


def test_template_only_output_is_failure_not_success():
    class TemplateClient:
        def chat(self, prompt, system=''):
            return json.dumps({
                'overview': '一句话概述',
                'key_points': [{'text': '关键点', 'segment_id': 's1', 'evidence': '连续的逐字原文'}],
                'actions': [], 'questions': [],
            })
    with pytest.raises(ToolError, match='未将空白或模板纪要标为成功'):
        summarize([Segment(0, 3, '小王明天交报告。')], TemplateClient())


def test_compact_source_ids_restore_original_task_and_do_not_paraphrase():
    class SelectionClient:
        def chat(self, prompt, system=''):
            return json.dumps({
                'overview': '讨论报告任务。',
                'key_points': ['s1', 's2'],
                'actions': [{'segment_id': 's2', 'owner': '小王', 'due': '明天下午'}],
                'questions': ['nonexistent'],
            }, ensure_ascii=False)
    notes = summarize([Segment(0, 10, '数据清洗已经完成,小王明天下午提交报告。')], SelectionClient())
    assert notes['actions'] == [{
        'text': '小王明天下午提交报告。', 'evidence': '小王明天下午提交报告。',
        'start': 0, 'end': 10, 'owner': '小王', 'due': '明天下午',
    }]
    assert notes['key_points'][0]['text'] == '数据清洗已经完成,'
    assert notes['rejected'] == 1


def test_task_boundary_regressions_from_real_model():
    sources = {
        's1': Segment(0, 3, '小王明天下午提交實驗報告,'),
        's2': Segment(3, 5, '是否增加對照實驗,'),
        's3': Segment(5, 7, '數據清洗已經完成,'),
    }
    items = [
        {'segment_id': 's1', 'evidence': sources['s1'].text, 'owner': '小王明', 'due': '明天下午'},
        {'segment_id': 's2', 'evidence': sources['s2'].text},
        {'segment_id': 's3', 'evidence': sources['s3'].text},
    ]
    valid, rejected = grounded_items(items, sources, action=True)
    assert rejected == 2
    assert len(valid) == 1
    assert valid[0]['owner'] == '小王'
    assert valid[0]['due'] == '明天下午'


def test_vocative_stays_with_task_and_retains_original_timestamp():
    source = Segment(2.5, 7.2, '小王，明天提交报告，小李， 周五检查参考文献。')
    phrases = source_phrases([source])
    assert [item.text for item in phrases] == ['小王，明天提交报告，', '小李， 周五检查参考文献。']
    assert all(item.start == 2.5 and item.end == 7.2 for item in phrases)
    assert all(item.text in source.text for item in phrases)
    sources = {'s1': phrases[0], 's2': phrases[1]}
    valid, rejected = grounded_items([
        {'segment_id': 's1', 'evidence': phrases[0].text, 'owner': '小王', 'due': '明天'},
        {'segment_id': 's2', 'evidence': phrases[1].text, 'owner': '张三', 'due': '周五'},
    ], sources, action=True)
    assert rejected == 0
    assert valid[0]['owner'] == '小王'
    assert valid[1]['owner'] == '未提及'  # Never infer or substitute a name.
    assert valid[1]['due'] == '周五'


def test_no_cross_segment_vocative_join_or_unrelated_clause_merging():
    first = Segment(0, 2, '小王，')
    second = Segment(3, 5, '明天提交报告。')
    assert source_phrases([first, second]) == [first, second]
    assert [s.text for s in source_phrases([Segment(0, 1, '数据清洗已完成，明天提交报告。')])] == [
        '数据清洗已完成，', '明天提交报告。'
    ]


def test_many_short_phrases_respect_encoded_request_budget():
    from minicpm_tools.audio import MAX_CHUNK_JSON_BYTES
    original = '小王明天交报告。' * 600
    chunks = chunk_segments(source_phrases([Segment(0, 60, original)]))
    assert len(chunks) > 1
    assert ''.join(s.text for chunk in chunks for _, s in chunk) == original
    assert all(
        len(json.dumps([{'segment_id': key, 'text': seg.text} for key, seg in chunk], ensure_ascii=False).encode('utf-8')) <= MAX_CHUNK_JSON_BYTES
        for chunk in chunks
    )
    assert all((s.start, s.end) == (0, 60) for chunk in chunks for _, s in chunk)


def test_unicode_escape_bytes_and_long_single_segment_respect_budget():
    from minicpm_tools.audio import MAX_CHUNK_JSON_BYTES
    original = ('🧪"\\\n报告' * 1000)
    chunks = chunk_segments([Segment(0, 30, original)])
    assert ''.join(s.text for chunk in chunks for _, s in chunk) == original
    for chunk in chunks:
        data = [{'segment_id': key, 'text': seg.text} for key, seg in chunk]
        assert len(json.dumps(data, ensure_ascii=False).encode('utf-8')) <= MAX_CHUNK_JSON_BYTES
        assert sum(len(s.text) for _, s in chunk) <= 5000


def test_many_tiny_items_limit_model_output_and_preserve_ids():
    from minicpm_tools.audio import MAX_CHUNK_ITEMS
    original = [Segment(i, i + 1, f'任务{i}。') for i in range(100)]
    chunks = chunk_segments(original)
    assert all(len(chunk) <= MAX_CHUNK_ITEMS for chunk in chunks)
    flattened = [(key, seg) for chunk in chunks for key, seg in chunk]
    assert [seg for _, seg in flattened] == original
    assert [key for key, _ in flattened] == [f's{i}' for i in range(1, 101)]


def test_no_silent_success_if_later_chunk_has_no_valid_sources():
    class IncompleteClient:
        def __init__(self):
            self.calls = 0
        def chat(self, prompt, system=''):
            self.calls += 1
            if self.calls <= 2:
                return json.dumps({'key_points': ['s1'], 'actions': [], 'questions': []})
            return json.dumps({'key_points': ['missing'], 'actions': [], 'questions': []})
    # Two chunks because each short phrase is kept separate and capped at 24.
    inputs = [Segment(i, i + 1, f'课程记录{i}。') for i in range(25)]
    with pytest.raises(ToolError, match='第 2/2 块没有可核对'):
        summarize(inputs, IncompleteClient())


def test_summary_preserves_distinct_time_ranges_and_assignments():
    class SelectionClient:
        def chat(self, prompt, system=''):
            data = json.loads(prompt.split('资料：\n', 1)[1])
            return json.dumps({
                'overview': '报告安排',
                'key_points': [item['segment_id'] for item in data],
                'questions': [],
                'actions': [
                    {'segment_id': data[0]['segment_id'], 'owner': '小王', 'due': '明天'},
                    {'segment_id': data[0]['segment_id'], 'owner': '小李', 'due': '明天'},
                    {'segment_id': data[0]['segment_id'], 'owner': '小王', 'due': '未提及'},
                    {'segment_id': data[1]['segment_id'], 'owner': '小王', 'due': '明天'},
                    {'segment_id': data[1]['segment_id'], 'owner': '小王', 'due': '明天'},
                ],
            }, ensure_ascii=False)
    text = '小王小李明天提交报告。'
    notes = summarize([Segment(0, 1, text), Segment(0, 9, text)], SelectionClient())
    assert [(item['start'], item['end']) for item in notes['key_points']] == [(0, 1), (0, 9)]
    assert [(item['end'], item['owner'], item['due']) for item in notes['actions']] == [
        (1, '小王', '明天'), (1, '小李', '明天'), (1, '小王', '未提及'), (9, '小王', '明天')
    ]
    rendered = render_notes(notes, 'fixture.wav')
    assert '[00:00:00.000–00:00:01.000]' in rendered
    assert '[00:00:00.000–00:00:09.000]' in rendered
