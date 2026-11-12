"""Deterministic unit/integration fixtures, not model-quality benchmarks."""

import json
import os
import runpy
import sqlite3
from pathlib import Path

import pytest

from minicpm_tools.common import ToolError
from minicpm_tools.search import index_folder, search_index


class FakeClient:
    embedding_model = "unit-test-only"

    def __init__(self):
        self.batches = []
        self.images = []

    def embed(self, texts):
        self.batches.append(texts)
        return [
            [1.0, 0.01]
            if any(word in text for word in ("biology", "鲸鱼", "ocean"))
            else [0.01, 1.0]
            for text in texts
        ]

    def ocr(self, image):
        assert Path(image).is_file()
        self.images.append(str(image))
        return "课程通知：周五下午三点提交数学作业。"

    def chat(self, prompt, system=""):
        return "此摘录包含查询主题。"


@pytest.fixture
def corpus(tmp_path):
    root = tmp_path / "corpus"
    root.mkdir()
    (root / "marine.md").write_text(
        "Marine biology studies whales and the ocean.", encoding="utf-8"
    )
    (root / "algebra.txt").write_text(
        "线性代数笔记：矩阵求逆、行列式与数学作业。", encoding="utf-8"
    )
    return root, tmp_path / "index.sqlite"


def test_semantic_query_without_literal_overlap_and_model_identity(corpus):
    root, index = corpus
    client = FakeClient()
    result = index_folder(root, index, client=client)
    assert result["files"] == 2
    hits = search_index(index, "鲸鱼", client=client, mode="semantic")
    assert hits[0].path.endswith("marine.md")
    assert "鲸鱼" not in hits[0].excerpt
    client.embedding_model = "different-model"
    with pytest.raises(ToolError, match="模型与索引不一致"):
        search_index(index, "鲸鱼", client=client)


def test_keyword_mode_requires_no_model_calls(corpus):
    root, index = corpus
    client = FakeClient()
    index_folder(root, index, mode="keyword", client=client)
    assert search_index(index, "矩阵", client=client)[0].path.endswith("algebra.txt")
    assert search_index(index, "biology", client=client)[0].path.endswith("marine.md")
    assert search_index(index, "nonexistentterm", client=client) == []
    assert client.batches == []
    with pytest.raises(ToolError, match="只有关键词"):
        search_index(index, "biology", client=client, mode="semantic")


def test_keyword_search_finds_single_chinese_character_inside_words(tmp_path):
    root = tmp_path / "corpus"
    root.mkdir()
    (root / "marine.txt").write_text("蓝鲸是海洋哺乳动物。", encoding="utf-8")
    (root / "other.txt").write_text("海豹生活在海边。", encoding="utf-8")
    index = tmp_path / "index.sqlite"
    client = FakeClient()
    index_folder(root, index, mode="keyword", client=client)

    hits = search_index(index, "鲸", client=client)
    assert [Path(hit.path).name for hit in hits] == ["marine.txt"]
    assert hits[0].score == 1
    assert search_index(index, "鲸 鲸", client=client)[0].score == 0.5
    assert search_index(index, "象", client=client) == []
    assert [Path(hit.path).name for hit in search_index(index, "蓝鲸", client=client)] == [
        "marine.txt"
    ]
    assert client.batches == []


def test_failed_rebuild_and_interruption_preserve_existing_index(corpus):
    root, index = corpus
    index_folder(root, index, client=FakeClient())
    before = index.read_bytes()

    class BrokenClient(FakeClient):
        def embed(self, texts):
            raise ToolError("offline")

    with pytest.raises(ToolError, match="offline"):
        index_folder(root, index, client=BrokenClient(), replace=True)
    assert index.read_bytes() == before
    with pytest.raises(ToolError, match="已存在"):
        index_folder(root, index, client=FakeClient())

    def interrupt(message):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        index_folder(root, index, client=FakeClient(), replace=True, progress=interrupt)
    assert index.read_bytes() == before
    assert list(index.parent.glob(".index.sqlite.*")) == []


def test_symlink_escape_and_deleted_results_excluded(corpus, tmp_path):
    root, index = corpus
    outside = tmp_path / "private"
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text("biology private secret")
    (root / "linked-file.txt").symlink_to(secret)
    (root / "linked-directory").symlink_to(outside, target_is_directory=True)
    result = index_folder(root, index, mode="keyword", client=FakeClient())
    assert result["files"] == 2
    (root / "marine.md").unlink()
    assert search_index(index, "biology", client=FakeClient()) == []


def test_large_document_is_chunked_and_embedding_batches_bounded(corpus):
    root, index = corpus
    (root / "long.md").write_text("marine biology ocean " * 4000)
    client = FakeClient()
    index_folder(root, index, client=client)
    assert all(0 < len(batch) <= 16 for batch in client.batches)
    assert all(len(part) <= 1200 for batch in client.batches for part in batch)
    assert len(search_index(index, "鲸鱼", client=client)) == 3


def test_wrong_vector_dimension_rejected(corpus):
    root, index = corpus
    index_folder(root, index, client=FakeClient())

    class WrongShape(FakeClient):
        def embed(self, texts):
            return [[1, 2, 3] for _ in texts]

    with pytest.raises(ToolError, match="维度"):
        search_index(index, "biology", client=WrongShape())


def test_pdf_ocr_page_limit_and_cleanup(corpus):
    pdfium = pytest.importorskip("pypdfium2")
    pytest.importorskip("PIL")
    root, index = corpus
    document = pdfium.PdfDocument.new()
    for _ in range(3):
        page = document.new_page(200, 200)
        page.close()
    document.save(root / "notice.pdf")
    document.close()
    client = FakeClient()
    result = index_folder(root, index, client=client, mode="keyword", max_pages=1)
    assert result["ocr_pages"] == 1
    assert len(client.images) == 1
    assert not Path(client.images[0]).exists()
    hits = search_index(index, "周五下午", client=client)
    assert hits[0].path.endswith("notice.pdf")
    assert hits[0].page == 1 and hits[0].source == "ocr"


def test_no_ocr_explicitly_skips_blank_pdf(corpus):
    pdfium = pytest.importorskip("pypdfium2")
    root, index = corpus
    document = pdfium.PdfDocument.new()
    page = document.new_page(200, 200)
    page.close()
    document.save(root / "blank.pdf")
    document.close()
    client = FakeClient()
    messages = []
    result = index_folder(
        root, index, client=client, mode="keyword", ocr=False, progress=messages.append
    )
    assert result["ocr_pages"] == 0 and client.images == []
    assert any("--no-ocr" in message for message in messages)


def test_no_ocr_preserves_short_text_layer_as_searchable_content(tmp_path):
    pytest.importorskip("pypdfium2")
    root = tmp_path / "docs"
    root.mkdir()
    helper = runpy.run_path(str(Path(__file__).parents[1] / "examples/search_make_fixtures.py"))
    (root / "brief.pdf").write_bytes(helper["text_pdf"](["Exam May 10"]))
    index = tmp_path / "index.sqlite"
    messages = []
    client = FakeClient()
    result = index_folder(
        root, index, mode="keyword", ocr=False, client=client, progress=messages.append
    )
    hits = search_index(index, "Exam May", client=client)
    assert result["ocr_pages"] == 0 and not client.images
    assert len(hits) == 1 and hits[0].page == 1 and hits[0].source == "text"
    assert "Exam May 10" in hits[0].excerpt
    assert any("保留现有文字层" in message for message in messages)


def test_text_layer_pdf_does_not_call_ocr(corpus):
    pytest.importorskip("pypdfium2")
    pytest.importorskip("PIL")
    root, index = corpus
    helper = runpy.run_path(str(Path(__file__).parents[1] / "examples/search_make_fixtures.py"))
    (root / "biology.pdf").write_bytes(
        helper["text_pdf"](["Marine biology studies whales in the ocean."])
    )
    client = FakeClient()
    index_folder(root, index, client=client, mode="keyword")
    hits = search_index(index, "Marine biology studies whales", client=client)
    pdf_hits = [hit for hit in hits if hit.path.endswith("biology.pdf")]
    assert pdf_hits and pdf_hits[0].page == 1 and pdf_hits[0].source == "text"
    assert client.images == []


def test_index_metadata_persists_root_and_mode(corpus):
    root, index = corpus
    index_folder(root, index, client=FakeClient(), mode="keyword")
    with sqlite3.connect(index) as db:
        metadata = {k: json.loads(v) for k, v in db.execute("SELECT key,value FROM metadata")}
    assert metadata["root"] == str(root.resolve())
    assert metadata["mode"] == "keyword"


def test_explanation_rejects_invented_quotes_and_accepts_verbatim_evidence(corpus):
    root, index = corpus
    index_folder(root, index, mode="keyword", client=FakeClient())

    class QuoteClient(FakeClient):
        def __init__(self, response):
            super().__init__()
            self.response = response

        def chat(self, prompt, system=""):
            return self.response

    fake = QuoteClient('{"quote":"The homework is due tomorrow."}')
    hits = search_index(index, "biology", client=fake, explain=True)
    assert "无法确认相关性" in hits[0].reason
    correct = QuoteClient('{"quote":"Marine biology studies whales and the ocean."}')
    hits = search_index(index, "biology", client=correct, explain=True)
    assert "模型选取的原文依据" in hits[0].reason
    assert "Marine biology studies whales and the ocean." in hits[0].excerpt


def test_verbose_rewrite_falls_back_to_original_query(corpus, capsys):
    root, index = corpus
    index_folder(root, index, mode="keyword", client=FakeClient())

    class VerboseClient(FakeClient):
        def chat(self, prompt, system=""):
            return "irrelevant invented facts\n" * 20

    hits = search_index(index, "biology", client=VerboseClient(), rewrite=True)
    assert hits[0].path.endswith("marine.md")
    assert "使用原始查询" in capsys.readouterr().err


def test_replace_refuses_unrelated_non_index_files(corpus):
    root, index = corpus
    original = b"valuable user notes"
    index.write_bytes(original)
    with pytest.raises(ToolError, match="拒绝覆盖"):
        index_folder(root, index, mode="keyword", client=FakeClient(), replace=True)
    assert index.read_bytes() == original


def test_replace_refuses_other_sqlite_and_corrupt_index(corpus):
    root, index = corpus
    with sqlite3.connect(index) as db:
        db.execute("CREATE TABLE private_data (value TEXT)")
        db.execute("INSERT INTO private_data VALUES ('keep me')")
    original = index.read_bytes()
    with pytest.raises(ToolError, match="拒绝覆盖"):
        index_folder(root, index, mode="keyword", client=FakeClient(), replace=True)
    assert index.read_bytes() == original
    index.unlink()
    index.write_bytes(b"SQLite format 3\x00broken")
    original = index.read_bytes()
    with pytest.raises(ToolError, match="拒绝覆盖"):
        index_folder(root, index, mode="keyword", client=FakeClient(), replace=True)
    assert index.read_bytes() == original


def test_replace_requires_original_root_and_preserves_legacy(corpus, tmp_path):
    root, index = corpus
    index_folder(root, index, mode="keyword", client=FakeClient())
    with sqlite3.connect(index) as db:
        db.execute("PRAGMA application_id=0")  # v1 files predating the marker
    other = tmp_path / "other"
    other.mkdir()
    (other / "other.txt").write_text("other unrelated directory")
    before = index.read_bytes()
    with pytest.raises(ToolError, match="拒绝覆盖"):
        index_folder(other, index, mode="keyword", client=FakeClient(), replace=True)
    assert index.read_bytes() == before
    index_folder(root, index, mode="keyword", client=FakeClient(), replace=True)
    assert search_index(index, "biology", client=FakeClient())


def test_replace_rejects_symlink_and_live_wal(corpus, tmp_path):
    root, index = corpus
    target = tmp_path / "target.sqlite"
    index_folder(root, target, mode="keyword", client=FakeClient())
    original = target.read_bytes()
    index.symlink_to(target)
    with pytest.raises(ToolError, match="符号链接"):
        index_folder(root, index, mode="keyword", client=FakeClient(), replace=True)
    assert target.read_bytes() == original
    index.unlink()
    index_folder(root, index, mode="keyword", client=FakeClient())
    wal = Path(str(index) + "-wal")
    wal.write_bytes(b"journal")
    original = index.read_bytes()
    with pytest.raises(ToolError, match="WAL"):
        index_folder(root, index, mode="keyword", client=FakeClient(), replace=True)
    assert index.read_bytes() == original and wal.read_bytes() == b"journal"


def test_replace_rejects_path_changed_during_rebuild(corpus, tmp_path):
    root, index = corpus
    index_folder(root, index, mode="keyword", client=FakeClient())
    moved = tmp_path / "old-index.sqlite"
    replacement = b"another process wrote this file"

    def change_path(_):
        if index.exists() and not moved.exists():
            index.rename(moved)
            index.write_bytes(replacement)

    with pytest.raises(ToolError, match="拒绝覆盖"):
        index_folder(
            root, index, mode="keyword", client=FakeClient(), replace=True, progress=change_path
        )
    assert index.read_bytes() == replacement
    assert search_index(moved, "biology", client=FakeClient())
    assert list(index.parent.glob(".index.sqlite.*")) == []


def test_replace_new_path_wont_clobber_file_created_during_build(corpus):
    root, index = corpus

    def create_target(_):
        if not index.exists():
            index.write_text("concurrent file")

    with pytest.raises(FileExistsError):
        index_folder(
            root, index, mode="keyword", client=FakeClient(), replace=True, progress=create_target
        )
    assert index.read_text() == "concurrent file"


def test_unreadable_subdirectory_aborts_rebuild_and_preserves_previous_index(corpus):
    root, index = corpus
    client = FakeClient()
    index_folder(root, index, mode="keyword", client=client)
    old_index = index.read_bytes()
    denied = root / "private-course"
    denied.mkdir()
    (denied / "lesson.txt").write_text("biology exercise")
    denied.chmod(0)
    try:
        if os.access(denied, os.R_OK | os.X_OK):
            pytest.skip("current user can read mode-000 directories")
        with pytest.raises(ToolError, match="无法读取资料目录"):
            index_folder(root, index, mode="keyword", client=client, replace=True)
    finally:
        denied.chmod(0o700)
    assert index.read_bytes() == old_index
    assert search_index(index, "biology", client=client)[0].path.endswith("marine.md")
    assert not list(index.parent.glob(".index.sqlite.*"))


def test_unreadable_subdirectory_never_publishes_new_index(corpus):
    root, index = corpus
    denied = root / "inaccessible"
    denied.mkdir()
    (denied / "missing.txt").write_text("this content must not be silently omitted")
    denied.chmod(0)
    try:
        if os.access(denied, os.R_OK | os.X_OK):
            pytest.skip("current user can read mode-000 directories")
        with pytest.raises(ToolError, match="无法读取资料目录"):
            index_folder(root, index, mode="keyword", client=FakeClient())
    finally:
        denied.chmod(0o700)
    assert not index.exists()
    assert not list(index.parent.glob(".index.sqlite.*"))


def test_source_change_is_explicit_for_results_and_legacy_is_unknown(corpus):
    root, index = corpus
    target = root / "marine.md"
    index_folder(root, index, mode="keyword", client=FakeClient())
    hit = search_index(index, "biology", client=FakeClient())[0]
    assert hit.source_changed is False
    target.write_text("This source was replaced with an unrelated passage.")
    hit = search_index(index, "biology", client=FakeClient())[0]
    assert hit.source_changed is True
    assert "biology" in hit.excerpt  # Indexed excerpt, not current file contents.
    with sqlite3.connect(index) as db:
        db.execute("DELETE FROM metadata WHERE key = 'file_fingerprints'")
        db.execute("PRAGMA application_id = 0")  # An existing v1 index.
    assert search_index(index, "biology", client=FakeClient())[0].source_changed is None
    # Legacy v1 files remain rebuildable without making claims about old data freshness.
    index_folder(root, index, mode="keyword", client=FakeClient(), replace=True)
    assert search_index(index, "unrelated", client=FakeClient())[0].source_changed is False
    assert not search_index(index, "biology", client=FakeClient())


def test_rebuild_rejects_file_modified_during_embedding_and_keeps_old_index(corpus):
    root, index = corpus
    original_client = FakeClient()
    index_folder(root, index, client=original_client)
    before = index.read_bytes()

    class ChangingClient(FakeClient):
        def embed(self, texts):
            target = root / "algebra.txt"  # first path in sorted index traversal
            target.write_text("file changed while embedding")
            return super().embed(texts)

    with pytest.raises(ToolError, match="索引期间发生变化"):
        index_folder(root, index, client=ChangingClient(), replace=True)
    assert index.read_bytes() == before
    assert not list(index.parent.glob(".index.sqlite.*"))


def test_cli_json_and_human_output_expose_source_freshness(corpus, capsys):
    import argparse

    from minicpm_tools.search import _query_command

    root, index = corpus
    target = root / "marine.md"
    index_folder(root, index, mode="keyword", client=FakeClient())
    target.write_text("changed file")
    args = argparse.Namespace(
        index=index,
        query="biology",
        mode="keyword",
        top_k=5,
        rewrite=False,
        explain=False,
        json=True,
        open=None,
    )
    _query_command(args)
    result = json.loads(capsys.readouterr().out)
    assert result[0]["source_changed"] is True
    args.json = False
    _query_command(args)
    assert "摘录可能过期" in capsys.readouterr().out


def test_no_results_still_warn_when_source_changed(corpus, capsys):
    import argparse

    from minicpm_tools.search import _query_command

    root, index = corpus
    index_folder(root, index, mode="keyword", client=FakeClient())
    (root / "marine.md").write_text("Unique new marine content: starlight.")
    args = argparse.Namespace(
        index=index,
        query="starlight",
        mode="keyword",
        top_k=5,
        rewrite=False,
        explain=False,
        json=True,
        open=None,
    )
    _query_command(args)
    result = capsys.readouterr()
    assert json.loads(result.out) == []
    assert "1 个文件已变化" in result.err
    assert "--replace" in result.err
