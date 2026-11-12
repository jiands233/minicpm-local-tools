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


def test_empty_ocr_does_not_replace_existing_index(corpus):
    pdfium = pytest.importorskip("pypdfium2")
    pytest.importorskip("PIL")
    root, index = corpus
    index_folder(root, index, client=FakeClient(), mode="keyword")
    before = index.read_bytes()
    document = pdfium.PdfDocument.new()
    page = document.new_page(200, 200)
    page.close()
    document.save(root / "notice.pdf")
    document.close()

    class EmptyOCR(FakeClient):
        def ocr(self, image):
            self.images.append(str(image))
            return "  \n"

    client = EmptyOCR()
    with pytest.raises(ToolError, match="OCR.*空"):
        index_folder(root, index, client=client, mode="keyword", replace=True)
    assert index.read_bytes() == before
    assert len(client.images) == 1 and not Path(client.images[0]).exists()
    assert search_index(index, "biology", client=client)[0].path.endswith("marine.md")


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


def test_incremental_reuses_unchanged_and_handles_changed_added_deleted(corpus):
    root, index = corpus
    removed = root / "deleted.md"
    removed.write_text("only deleted text")
    first = FakeClient()
    index_folder(root, index, client=first)
    with sqlite3.connect(index) as db:
        old_marine = db.execute(
            "SELECT body,vector FROM chunks WHERE path=?", (str(root / "marine.md"),)
        ).fetchall()
    (root / "algebra.txt").write_text("Changed calculus lesson with unique new terms.")
    removed.unlink()
    (root / "new.md").write_text("New course introduction.")
    client = FakeClient()
    result = index_folder(root, index, client=client, replace=True, incremental=True)
    embedded = [value for batch in client.batches for value in batch]
    assert len(embedded) == 2
    assert any("Changed calculus" in text for text in embedded)
    assert any("New course" in text for text in embedded)
    assert not any("Marine biology" in text for text in embedded)
    assert result["files"] == 3 and result["reused_files"] == 1
    with sqlite3.connect(index) as db:
        assert db.execute(
            "SELECT body,vector FROM chunks WHERE path=?", (str(root / "marine.md"),)
        ).fetchall() == old_marine
        assert db.execute("SELECT COUNT(*) FROM chunks WHERE path=?", (str(removed),)).fetchone()[0] == 0
    assert search_index(index, "calculus", mode="keyword", client=client)[0].path.endswith("algebra.txt")
    assert search_index(index, "introduction", mode="keyword", client=client)[0].path.endswith("new.md")
    assert not search_index(index, "deleted", mode="keyword", client=client)


def test_incremental_matches_full_rebuild_for_mixed_documents(tmp_path):
    pdfium = pytest.importorskip("pypdfium2")
    pytest.importorskip("PIL")
    helper = runpy.run_path(str(Path(__file__).parents[1] / "examples/search_make_fixtures.py"))
    root = tmp_path / "corpus"
    root.mkdir()
    (root / "long.txt").write_text("Marine biology notes about whales and oceans. " * 100)
    (root / "changed.md").write_text("Original algebra material.")
    (root / "deleted.txt").write_text("Content later removed.")
    (root / "text.pdf").write_bytes(helper["text_pdf"](["Marine biology notes about whales and oceans."]))
    document = pdfium.PdfDocument.new()
    page = document.new_page(200, 200)
    page.close()
    document.save(root / "scan.pdf")
    document.close()

    incremental = tmp_path / "incremental.sqlite"
    complete = tmp_path / "complete.sqlite"
    index_folder(root, incremental, client=FakeClient())
    (root / "changed.md").write_text("New linear algebra material and matrix practice.")
    (root / "deleted.txt").unlink()
    (root / "added.txt").write_text("New notes on biology and ocean life.")

    incremental_client = FakeClient()
    updated = index_folder(root, incremental, client=incremental_client, replace=True, incremental=True)
    full_client = FakeClient()
    rebuilt = index_folder(root, complete, client=full_client)
    assert updated["reused_files"] == 3  # Multichunk text, text PDF, OCR PDF.
    assert incremental_client.images == [] and len(full_client.images) == 1
    assert sum(map(len, incremental_client.batches)) == 2
    assert sum(map(len, full_client.batches)) > 2
    assert {key: updated[key] for key in ("files", "chunks", "ocr_pages", "dimension")} == {
        key: rebuilt[key] for key in ("files", "chunks", "ocr_pages", "dimension")
    }
    with sqlite3.connect(incremental) as left, sqlite3.connect(complete) as right:
        statement = "SELECT path,page,body,source,vector FROM chunks ORDER BY id"
        assert left.execute(statement).fetchall() == right.execute(statement).fetchall()
    for query in ("biology", "矩阵", "作业"):
        left_hits = search_index(incremental, query, client=FakeClient(), top_k=10)
        right_hits = search_index(complete, query, client=FakeClient(), top_k=10)
        assert left_hits == right_hits


@pytest.mark.parametrize("change", ["legacy", "embedding_model", "embedding_url", "ocr_model", "ocr_url", "max_pages", "no_ocr", "mode"])
def test_incremental_incompatible_or_legacy_settings_rebuild_every_file(corpus, change):
    root, index = corpus
    initial = FakeClient()
    initial.embedding_url = "http://127.0.0.1:12001/v1"
    initial.ocr_model = "test-ocr"
    initial.ocr_url = "http://127.0.0.1:12002/v1"
    index_folder(root, index, client=initial)
    if change == "legacy":
        with sqlite3.connect(index) as db:
            db.execute("DELETE FROM metadata WHERE key='extraction_revision'")
    client = FakeClient()
    client.embedding_url = initial.embedding_url
    client.ocr_model = initial.ocr_model
    client.ocr_url = initial.ocr_url
    kwargs = {}
    if change == "embedding_model":
        client.embedding_model = "other"
    elif change == "embedding_url":
        client.embedding_url = "http://127.0.0.1:12003/v1"
    elif change == "ocr_model":
        client.ocr_model = "other-ocr"
    elif change == "ocr_url":
        client.ocr_url = "http://127.0.0.1:12004/v1"
    elif change == "max_pages":
        kwargs["max_pages"] = 2
    elif change == "no_ocr":
        kwargs["ocr"] = False
    elif change == "mode":
        kwargs["mode"] = "keyword"
    messages = []
    result = index_folder(root, index, client=client, replace=True, incremental=True,
                          progress=messages.append, **kwargs)
    assert result["reused_files"] == 0
    assert any("完整重建" in message for message in messages)
    if change != "mode":
        assert sum(len(batch) for batch in client.batches) == 2


def test_incremental_rejects_invalid_vectors_without_replacing_old_index(corpus):
    root, index = corpus
    index_folder(root, index, client=FakeClient())
    with sqlite3.connect(index) as db:
        db.execute("UPDATE chunks SET vector='[0, 0]' WHERE path=?", (str(root / "marine.md"),))
    before = index.read_bytes()
    with pytest.raises(ToolError, match="零向量"):
        index_folder(root, index, client=FakeClient(), replace=True, incremental=True)
    assert index.read_bytes() == before
    assert not list(index.parent.glob(".index.sqlite.*"))


def test_incremental_checks_new_vectors_against_reused_dimensions(corpus):
    root, index = corpus
    index_folder(root, index, client=FakeClient())
    (root / "algebra.txt").write_text("changed file")
    before = index.read_bytes()

    class ChangedShape(FakeClient):
        def embed(self, texts):
            return [[1, 2, 3] for _ in texts]

    with pytest.raises(ToolError, match="维度"):
        index_folder(root, index, client=ChangedShape(), replace=True, incremental=True)
    assert index.read_bytes() == before


def test_incremental_rechecks_all_sources_before_publishing(corpus):
    root, index = corpus
    index_folder(root, index, mode="keyword", client=FakeClient())
    before = index.read_bytes()
    (root / "z-new.txt").write_text("new content")
    def mutate_after_reuse(message):
        if message.startswith("索引 z-new.txt"):
            (root / "algebra.txt").write_text("changed after it was reused")
    with pytest.raises(ToolError, match="索引期间发生变化"):
        index_folder(root, index, mode="keyword", client=FakeClient(), replace=True,
                     incremental=True, progress=mutate_after_reuse)
    assert index.read_bytes() == before


def test_incremental_pdf_reuses_all_chunks_but_counts_unique_ocr_page(corpus):
    pdfium = pytest.importorskip("pypdfium2")
    pytest.importorskip("PIL")
    root, index = corpus
    document = pdfium.PdfDocument.new()
    page = document.new_page(200, 200)
    page.close()
    document.save(root / "scan.pdf")
    document.close()
    class LongOCR(FakeClient):
        def ocr(self, image):
            self.images.append(str(image))
            return "长期课程笔记" * 500
    initial = LongOCR()
    result = index_folder(root, index, mode="keyword", client=initial)
    assert result["ocr_pages"] == 1 and len(initial.images) == 1
    next_client = LongOCR()
    result = index_folder(root, index, mode="keyword", client=next_client,
                          replace=True, incremental=True)
    assert result["ocr_pages"] == 1 and result["reused_files"] == 3
    assert next_client.images == []


def test_incremental_requires_existing_explicit_replace(corpus):
    root, index = corpus
    with pytest.raises(ToolError, match="增量更新需要"):
        index_folder(root, index, mode="keyword", client=FakeClient(), replace=True, incremental=True)
    index_folder(root, index, mode="keyword", client=FakeClient())
    with pytest.raises(ToolError):
        index_folder(root, index, mode="keyword", client=FakeClient(), incremental=True)


def test_incremental_preserves_empty_files_and_exposes_no_backend_url(corpus, capsys):
    root, index = corpus
    (root / "empty.txt").write_text("")
    secret_url = "http://127.0.0.1:12001/v1/private-path-credential"
    client = FakeClient()
    client.embedding_url = secret_url
    client.ocr_url = secret_url
    result = index_folder(root, index, client=client)
    assert result["files"] == 3
    assert secret_url not in json.dumps(result)
    assert secret_url.encode() not in index.read_bytes()
    client.batches.clear()
    next_result = index_folder(root, index, client=client, replace=True, incremental=True)
    assert next_result["reused_files"] == 3 and client.batches == []
    assert secret_url not in json.dumps(next_result)
    assert secret_url not in capsys.readouterr().err
    assert secret_url.encode() not in index.read_bytes()


def test_incremental_rejects_index_changed_during_reuse(corpus, tmp_path):
    root, index = corpus
    index_folder(root, index, mode="keyword", client=FakeClient())
    original = index.read_bytes()
    other_path = tmp_path / "moved.sqlite"
    def replace_target(message):
        if message.startswith("复用 ") and not other_path.exists():
            index.rename(other_path)
            index.write_bytes(b"concurrently created user file")
    with pytest.raises(ToolError, match="拒绝覆盖"):
        index_folder(root, index, mode="keyword", client=FakeClient(), replace=True,
                     incremental=True, progress=replace_target)
    assert index.read_bytes() == b"concurrently created user file"
    assert other_path.read_bytes() == original
    assert not list(index.parent.glob(".index.sqlite.*"))
