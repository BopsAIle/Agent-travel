"""Khoá lại hành vi embedding sau sự cố `text-embedding-004` bị Google tắt (14/01/2026).

Lỗi cũ: model hardcode trong embed.py đã ngừng tồn tại, API trả 404 NOT_FOUND, exception
bị nuốt rồi trả `[None]` nên memory mất embedding mà không ai biết. Test ở đây chốt lại:
model lấy từ config, số chiều phải khớp schema, lỗi tạm thời phải được thử lại, text hỏng
không kéo theo cả batch, và lý do lỗi phải trả về được cho script re-embed.
"""
import pytest

from app.core import telemetry
from app.db.models import EMBEDDING_DIM
from app.memory import embed
from packages.agent_runtime import embed as runtime_embed

ITEM_ERROR = "400 INVALID_ARGUMENT: request contains text longer than 2048 tokens"
SYSTEM_ERROR = (
    "Error embedding content (RESOURCE_EXHAUSTED): 429 RESOURCE_EXHAUSTED. "
    "Quota exceeded for metric: embed_content_free_tier_requests, limit: 100. "
    "Please retry in 45.802764896s."
)


class FakeEmbeddings:
    """Model giả: không gọi mạng, điều khiển được lỗi và số chiều trả về."""

    def __init__(
        self,
        dim=768,
        bad_texts=(),
        batch_error=None,
        single_error=None,
        transient_failures=0,
        fail_after=0,
    ):
        self.dim = dim
        self.bad_texts = set(bad_texts)
        self.batch_error = batch_error
        self.single_error = single_error
        self.transient_failures = transient_failures
        # fail_after=N: N text đầu chạy được, từ text thứ N+1 trở đi (khi gọi lẻ) thì lỗi
        self.fail_after = fail_after
        self.calls = 0
        self.seen_texts = []

    def embed_documents(self, texts):
        self.calls += 1
        if self.transient_failures > 0:
            self.transient_failures -= 1
            raise RuntimeError(SYSTEM_ERROR)
        if self.batch_error and len(texts) > 1:
            raise RuntimeError(self.batch_error)
        if self.single_error and len(texts) == 1:
            raise RuntimeError(self.single_error)
        if self.fail_after and len(self.seen_texts) >= self.fail_after:
            raise RuntimeError(SYSTEM_ERROR)
        vectors = []
        for text in texts:
            if text in self.bad_texts:
                raise RuntimeError(ITEM_ERROR)
            vectors.append([0.1] * self.dim)
        self.seen_texts.extend(texts)
        return vectors


@pytest.fixture(autouse=True)
def no_backoff_sleep(monkeypatch):
    """Backoff thật sẽ làm test chậm; chỉ cần biết nó có được gọi."""
    monkeypatch.setattr(runtime_embed.time, "sleep", lambda seconds: None)


def use_model(monkeypatch, model, module=embed):
    monkeypatch.setattr(module, "_embeddings", None)
    monkeypatch.setattr(module, "_get_embeddings", lambda: model)
    return model


# --- cấu hình ----------------------------------------------------------------


def test_model_embedding_mac_dinh_khong_con_model_da_bi_tat():
    """Chốt lại sự cố: không được quay về text-embedding-004 (đã tắt 14/01/2026)."""
    from app.core.config import GEMINI_EMBED_DIM, GEMINI_EMBED_MODEL

    assert "text-embedding-004" not in GEMINI_EMBED_MODEL
    assert GEMINI_EMBED_MODEL == "models/gemini-embedding-001"
    assert GEMINI_EMBED_DIM == EMBEDDING_DIM, "output_dimensionality phải khớp cột Vector"


def test_hai_ban_model_khai_bao_cung_so_chieu():
    """orchestrator (app/db/models.py) và packages/ phải cùng EMBEDDING_DIM."""
    from packages.agent_runtime.models import EMBEDDING_DIM as runtime_dim

    assert runtime_dim == EMBEDDING_DIM


# --- đường bình thường -------------------------------------------------------


def test_batch_binh_thuong_tra_vector_dung_so_chieu(monkeypatch):
    use_model(monkeypatch, FakeEmbeddings())

    vectors = embed.embed_texts(["  hanoi  ", "", "   "])

    assert len(vectors) == 1, "text rỗng bị loại trước khi gọi API"
    assert len(vectors[0]) == EMBEDDING_DIM
    assert embed.embed_text("hanoi") is not None
    assert embed.embed_texts([]) == []


def test_model_tra_sai_so_chieu_thi_tra_none(monkeypatch):
    """Vector 3072 chiều không insert được vào cột 768 chiều — chặn trước khi ghi DB."""
    use_model(monkeypatch, FakeEmbeddings(dim=3072))

    assert embed.embed_texts(["hanoi"]) == [None]


def test_text_qua_dai_bi_cat_truoc_khi_embed(monkeypatch):
    """Không cắt thì text > 2048 token vĩnh viễn không có embedding."""
    model = use_model(monkeypatch, FakeEmbeddings())

    vectors = embed.embed_texts(["x" * (runtime_embed.MAX_EMBED_CHARS + 500)])

    assert vectors[0] is not None
    assert len(model.seen_texts[0]) == runtime_embed.MAX_EMBED_CHARS


# --- lỗi tạm thời và lỗi theo từng text --------------------------------------


def test_loi_tam_thoi_duoc_thu_lai(monkeypatch):
    model = use_model(monkeypatch, FakeEmbeddings(transient_failures=1))

    vectors = embed.embed_texts(["hanoi"])

    assert vectors[0] is not None, "429 một lần không được coi là hỏng"
    assert model.calls == 2, "1 lần lỗi + 1 lần thử lại"


def test_mot_text_hong_khong_keo_ca_batch_ve_none(monkeypatch):
    model = use_model(
        monkeypatch,
        FakeEmbeddings(bad_texts={"bad"}, batch_error=ITEM_ERROR),
    )

    vectors = embed.embed_texts(["good one", "bad", "good two"])

    assert vectors[0] is not None and vectors[2] is not None
    assert vectors[1] is None
    assert model.calls == 4, "1 lần batch lỗi + 3 lần gọi từng text"


def test_text_dau_loi_do_du_lieu_thi_van_thu_cac_text_sau(monkeypatch):
    """Lỗi 400 là lỗi của riêng text đó, không phải API hỏng -> không được bỏ cả batch."""
    model = use_model(
        monkeypatch,
        FakeEmbeddings(bad_texts={"bad"}, batch_error=ITEM_ERROR),
    )

    vectors = embed.embed_texts(["bad", "good one", "good two"])

    assert vectors[0] is None
    assert vectors[1] is not None and vectors[2] is not None
    assert model.calls == 4


def test_loi_he_thong_o_text_dau_thi_dung_som(monkeypatch):
    """Hết quota/sai khoá: text đầu đã hỏng thì gọi thêm 50 lần cũng vô ích."""
    model = use_model(
        monkeypatch,
        FakeEmbeddings(batch_error=SYSTEM_ERROR, single_error=SYSTEM_ERROR),
    )

    assert embed.embed_texts(["a", "b", "c"]) == [None, None, None]
    assert model.calls == 4, "2 lần thử batch + 2 lần thử text đầu rồi dừng"


def test_het_quota_giua_batch_thi_dung_ngay_khong_dot_quota(monkeypatch):
    """429 ở text thứ 3 không được biến thành 50 request nữa — đó là cách quota cháy sạch."""
    model = use_model(
        monkeypatch,
        FakeEmbeddings(batch_error=SYSTEM_ERROR, fail_after=2),
        module=runtime_embed,
    )

    vectors, errors = runtime_embed.embed_texts_detailed(
        model,
        ["t1", "t2", "t3", "t4", "t5"],
        policy=runtime_embed.PATIENT,
    )

    assert [item is not None for item in vectors] == [True, True, False, False, False]
    assert all("429" in item for item in errors[2:])
    # 5 lần thử batch + t1 + t2 chạy được + 3 lần thử t3 rồi dừng hẳn (không thử t4, t5).
    assert model.calls == 10


def test_tran_so_request_khi_phai_goi_rieng_tung_text(monkeypatch):
    """Batch hỏng vì dữ liệu cũng không được vượt trần request riêng."""
    model = use_model(
        monkeypatch,
        FakeEmbeddings(bad_texts={f"bad{i}" for i in range(40)}, batch_error=ITEM_ERROR),
        module=runtime_embed,
    )
    texts = [f"bad{i}" for i in range(40)]

    vectors, errors = runtime_embed.embed_texts_detailed(model, texts)

    assert all(item is None for item in vectors)
    assert model.calls <= 1 + runtime_embed.MAX_INDIVIDUAL_REQUESTS
    assert any("tiết kiệm quota" in (item or "") for item in errors)


def test_duong_chat_khong_cho_lau_khi_het_quota(monkeypatch):
    """Chat phải trả lời: gặp 429 thì bỏ embedding của lượt đó, không ngồi chờ 45s."""
    waits = []
    monkeypatch.setattr(runtime_embed.time, "sleep", lambda seconds: waits.append(seconds))
    use_model(monkeypatch, FakeEmbeddings(batch_error=SYSTEM_ERROR, single_error=SYSTEM_ERROR))

    embed.embed_text("hanoi")

    assert waits, "có thử lại"
    assert max(waits) <= runtime_embed.FAST.max_wait


def test_cho_dung_retry_delay_cua_api(monkeypatch):
    """API nói 'retry in 45.8s' thì chờ 45.8s, không phải 1s rồi bỏ."""
    assert runtime_embed.retry_delay_seconds(SYSTEM_ERROR, 1.0) == pytest.approx(45.802764896)
    assert runtime_embed.retry_delay_seconds("retryDelay': '45s'", 1.0) == pytest.approx(45.0)
    assert runtime_embed.retry_delay_seconds("no hint here", 2.0) == 2.0


# --- lý do lỗi trả về cho script re-embed ------------------------------------


def test_embed_texts_with_errors_tra_ly_do_tung_dong(monkeypatch):
    use_model(monkeypatch, FakeEmbeddings(bad_texts={"bad"}, batch_error=ITEM_ERROR))

    vectors, errors = embed.embed_texts_with_errors(["good one", "bad", "good two"])

    assert [None if item is None else "ok" for item in vectors] == ["ok", None, "ok"]
    assert errors[1] and "400" in errors[1]
    assert errors[0] is None and errors[2] is None


def test_embed_texts_with_errors_bao_het_quota_cho_moi_dong(monkeypatch):
    use_model(monkeypatch, FakeEmbeddings(batch_error=SYSTEM_ERROR, single_error=SYSTEM_ERROR))

    vectors, errors = embed.embed_texts_with_errors(["a", "b"])

    assert vectors == [None, None]
    assert all("429" in item for item in errors), errors


def test_embed_texts_with_errors_khi_tat_embedding(monkeypatch):
    monkeypatch.setattr(embed, "_embeddings", None)
    monkeypatch.setattr(embed, "_get_embeddings", lambda: None)

    vectors, errors = embed.embed_texts_with_errors(["a", "b"])

    assert vectors == [None, None]
    assert errors == ["embeddings unavailable"] * 2


# --- telemetry và bản song song ---------------------------------------------


def test_record_embed_ghi_dung_model_va_chi_phi(monkeypatch):
    """Span telemetry phải mang model hiện hành, không hardcode model cũ."""
    captured = {}
    monkeypatch.setattr(telemetry, "add_span", lambda **kwargs: captured.update(kwargs))

    telemetry.record_embed(["xin chao"], 10.0)

    assert captured["model"] == telemetry.GEMINI_EMBED_MODEL
    assert captured["provider"] == "google"
    assert captured["cost_usd"] > 0
    assert captured["kind"] == "embed"


def test_span_lich_su_cua_model_da_tat_van_tinh_duoc_chi_phi():
    assert telemetry.normalize_model("models/text-embedding-004") == "text-embedding-004"
    assert telemetry.calc_cost_usd("models/text-embedding-004", 1_000_000, 0) == pytest.approx(0.025)


def test_packages_agent_runtime_hanh_xu_giong_het(monkeypatch):
    """Bản song song trong packages/ phải cùng luật, nếu không agent-service lại hỏng âm thầm."""
    assert runtime_embed.EMBEDDING_DIM == EMBEDDING_DIM

    use_model(monkeypatch, FakeEmbeddings(), module=runtime_embed)
    assert runtime_embed.embed_texts(["hanoi"])[0] is not None

    use_model(monkeypatch, FakeEmbeddings(dim=3072), module=runtime_embed)
    assert runtime_embed.embed_texts(["hanoi"]) == [None]

    model = use_model(
        monkeypatch,
        FakeEmbeddings(bad_texts={"bad"}, batch_error=ITEM_ERROR),
        module=runtime_embed,
    )
    vectors = runtime_embed.embed_texts(["good", "bad"])
    assert vectors[0] is not None and vectors[1] is None
    assert model.calls == 3


def test_gemini_embed_dim_lech_schema_thi_tat_embedding(monkeypatch):
    monkeypatch.setattr(embed, "_embeddings", None)
    monkeypatch.setattr(embed, "GEMINI_EMBED_DIM", EMBEDDING_DIM * 2)

    assert embed._get_embeddings() is None
    assert embed.embed_texts(["hanoi"]) == [None]
