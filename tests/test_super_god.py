"""Tests for 'super god' upgrades: BM25 warm-up, query rewriting, MMR diversify."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.documents import Document


# ──────────────────────────────────────
# BM25 warm-up
# ──────────────────────────────────────

class _FakeVec:
    def __init__(self, metadata):
        self.metadata = metadata


def test_warm_bm25_builds_index_from_namespace():
    from chat.services.bm25 import warm_bm25_for_namespace, invalidate_bm25_cache

    invalidate_bm25_cache("test-ns")

    # Use a corpus large enough that IDF for distinguishing terms stays > 0
    # (BM25 IDF collapses to 0 when a term appears in ≥ half a tiny corpus).
    fake_ids = ["id1", "id2", "id3", "id4", "id5"]
    fake_vectors = {
        "id1": _FakeVec({"text": "curriculum tuition semester payment", "source_filename": "a.pdf"}),
        "id2": _FakeVec({"text": "schedule classroom calendar timetable", "source_filename": "b.pdf"}),
        "id3": _FakeVec({"text": "admission process deadline application", "source_filename": "c.pdf"}),
        "id4": _FakeVec({"text": "faculty staff directory office hours", "source_filename": "d.pdf"}),
        "id5": _FakeVec({"text": "", "source_filename": "e.pdf"}),  # empty → skipped
    }
    fake_index = MagicMock()
    fake_index.fetch.return_value = MagicMock(vectors=fake_vectors)

    with (
        patch("shared.services.vectorstore.list_all_vector_ids", return_value=fake_ids),
        patch("shared.services.vectorstore.get_raw_index", return_value=fake_index),
    ):
        idx = warm_bm25_for_namespace("test-ns")

    assert len(idx.documents) == 4  # empty-text doc dropped
    # Token overlap on "tuition" should match the first doc
    results = idx.search("tuition payment", k=5)
    assert results
    assert "tuition" in results[0].page_content
    assert results[0].metadata.get("source_filename") == "a.pdf"


@pytest.mark.asyncio
async def test_hybrid_search_rewarms_when_invalidate_ts_newer():
    """If tenant.bm25_invalidate_ts > cached BM25 warmed_ts, re-warm on next search.

    This is the cross-process invalidation contract: ingest-worker bumps
    tenant's invalidate_ts; chat-api reads it per-request, compares with
    in-process BM25 cache, and re-warms if stale.
    """
    from langchain_core.documents import Document
    from chat.services.bm25 import BM25Index, invalidate_bm25_cache
    from chat.services import bm25 as bm25_module

    invalidate_bm25_cache("test-stale-ns")

    # Seed cache with a "stale" index warmed at ts=100
    stale_idx = BM25Index([Document(page_content="old", metadata={})])
    stale_idx.warmed_ts = 100.0  # manually backdate
    with bm25_module._lock:
        bm25_module._cache["test-stale-ns"] = stale_idx

    warm_calls = {"n": 0}

    def fake_warm(ns):
        warm_calls["n"] += 1
        fresh = BM25Index([Document(page_content="fresh", metadata={})])
        fresh.warmed_ts = 500.0
        with bm25_module._lock:
            bm25_module._cache[ns] = fresh
        return fresh

    with (
        patch("chat.services.search.get_vectorstore") as mock_vs,
        patch("chat.services.search.warm_bm25_for_namespace", side_effect=fake_warm),
    ):
        mock_store = MagicMock()
        mock_store.similarity_search.return_value = []
        mock_vs.return_value = mock_store

        from chat.services.search import _hybrid_search
        # Simulate a tenant that ingested at ts=300 — newer than cache (100)
        await _hybrid_search("q", "test-stale-ns", invalidate_ts=300.0)

    assert warm_calls["n"] == 1, "stale cache must trigger exactly one re-warm"


@pytest.mark.asyncio
async def test_run_agent_handles_opus47_thinking_block_list_content():
    """Regression (2026-04-17): Opus 4.7 adaptive thinking returns content
    as list[block] not str. Previously crashed ChatResponse pydantic
    validation with 500 — now must extract text blocks cleanly.
    """
    from chat.services.agent import run_agent

    tenant = {
        "tenant_id": "t1", "pinecone_namespace": "ns1", "persona": "p",
        "bm25_invalidate_ts": 0,
    }

    # Simulate Opus 4.7 adaptive-thinking response
    final_msg = MagicMock()
    final_msg.content = [
        {"type": "thinking", "thinking": "user asked about X, I should search..."},
        {"type": "text", "text": "Part A of answer."},
        {"type": "text", "text": "Part B of answer."},
    ]
    final_msg.tool_calls = []

    with (
        patch("chat.services.agent.conversation_memory") as mock_mem,
        patch("chat.services.agent.create_tools", return_value=([], lambda: [])),
        patch("chat.services.agent.create_react_agent") as mock_ra,
        patch("chat.services.agent.track_usage", new=AsyncMock()),
    ):
        mock_mem.get_history = AsyncMock(return_value=[])
        mock_mem.add_turn = AsyncMock()
        mock_agent = MagicMock()
        mock_agent.ainvoke = AsyncMock(return_value={"messages": [final_msg]})
        mock_ra.return_value = mock_agent

        answer, sources = await run_agent("test", "user-1", tenant)

    # Thinking block dropped, both text blocks concatenated
    assert "thinking" not in answer.lower() or "search" not in answer.lower()
    assert "Part A" in answer
    assert "Part B" in answer
    assert isinstance(answer, str)


@pytest.mark.asyncio
async def test_run_agent_fallback_message_matches_query_language():
    """If the agent returns no text (e.g. only a thinking block), the fallback
    error message must match the user's query language — English users
    should NOT see a Thai error.
    """
    from chat.services.agent import run_agent

    tenant = {
        "tenant_id": "t1", "pinecone_namespace": "ns1", "persona": "p",
        "bm25_invalidate_ts": 0,
    }

    # Simulate Opus returning only thinking (no text blocks)
    empty_msg = MagicMock()
    empty_msg.content = [{"type": "thinking", "thinking": "still thinking..."}]
    empty_msg.tool_calls = []

    async def _run(query: str) -> str:
        with (
            patch("chat.services.agent.conversation_memory") as mock_mem,
            patch("chat.services.agent.create_tools", return_value=([], lambda: [])),
            patch("chat.services.agent.create_react_agent") as mock_ra,
            patch("chat.services.agent.track_usage", new=AsyncMock()),
        ):
            mock_mem.get_history = AsyncMock(return_value=[])
            mock_mem.add_turn = AsyncMock()
            mock_agent = MagicMock()
            mock_agent.ainvoke = AsyncMock(return_value={"messages": [empty_msg]})
            mock_ra.return_value = mock_agent
            answer, _ = await run_agent(query, "u", tenant)
            return answer

    # Thai query → Thai fallback
    thai_answer = await _run("ค่าเทอมเท่าไหร่")
    assert "ขออภัยค่ะ" in thai_answer

    # English query → English fallback (no Thai characters leaking)
    english_answer = await _run("what is the tuition")
    assert "Sorry" in english_answer
    assert "ขออภัย" not in english_answer


@pytest.mark.asyncio
async def test_run_agent_replaces_langgraph_step_exhausted_fallback():
    """Regression: LangGraph create_react_agent silently returns the hardcoded
    English string "Sorry, need more steps to process this request." when
    remaining_steps < 2 with pending tool_calls — it does NOT raise
    GraphRecursionError, so the except branch never fires. run_agent must
    detect this and replace with a language-matched fallback, otherwise a
    Thai user sees the raw English string as a confident HTTP 200 answer.
    """
    from chat.services.agent import run_agent, _LANGGRAPH_STEPS_FALLBACK

    tenant = {
        "tenant_id": "t1", "pinecone_namespace": "ns1", "persona": "p",
        "bm25_invalidate_ts": 0,
    }

    step_msg = MagicMock()
    step_msg.content = _LANGGRAPH_STEPS_FALLBACK
    step_msg.tool_calls = []

    async def _run(query: str) -> str:
        with (
            patch("chat.services.agent.conversation_memory") as mock_mem,
            patch("chat.services.agent.create_tools", return_value=([], lambda: [])),
            patch("chat.services.agent.create_react_agent") as mock_ra,
            patch("chat.services.agent.track_usage", new=AsyncMock()),
        ):
            mock_mem.get_history = AsyncMock(return_value=[])
            mock_mem.add_turn = AsyncMock()
            mock_agent = MagicMock()
            mock_agent.ainvoke = AsyncMock(return_value={"messages": [step_msg]})
            mock_ra.return_value = mock_agent
            answer, _ = await run_agent(query, "u", tenant)
            return answer

    # Thai query → Thai step-exhausted fallback, never the raw English string
    thai_answer = await _run("ค่าเทอม TIP เท่าไหร่แล้วเรียนวิชาอะไรบ้าง")
    assert _LANGGRAPH_STEPS_FALLBACK not in thai_answer
    assert "ขออภัย" in thai_answer and "ค้นหาข้อมูลหลายรอบ" in thai_answer

    # English query → English step-exhausted fallback
    english_answer = await _run("what is tuition and what courses")
    assert _LANGGRAPH_STEPS_FALLBACK not in english_answer
    assert "searched multiple times" in english_answer.lower()
    assert "ขออภัย" not in english_answer


@pytest.mark.asyncio
async def test_run_agent_handles_string_content_backward_compat():
    """Non-adaptive-thinking models return plain string content — still works."""
    from chat.services.agent import run_agent

    tenant = {
        "tenant_id": "t1", "pinecone_namespace": "ns1", "persona": "p",
        "bm25_invalidate_ts": 0,
    }

    final_msg = MagicMock()
    final_msg.content = "plain string answer"
    final_msg.tool_calls = []

    with (
        patch("chat.services.agent.conversation_memory") as mock_mem,
        patch("chat.services.agent.create_tools", return_value=([], lambda: [])),
        patch("chat.services.agent.create_react_agent") as mock_ra,
        patch("chat.services.agent.track_usage", new=AsyncMock()),
    ):
        mock_mem.get_history = AsyncMock(return_value=[])
        mock_mem.add_turn = AsyncMock()
        mock_agent = MagicMock()
        mock_agent.ainvoke = AsyncMock(return_value={"messages": [final_msg]})
        mock_ra.return_value = mock_agent

        answer, _ = await run_agent("test", "user-1", tenant)

    assert answer == "plain string answer"


@pytest.mark.asyncio
async def test_run_agent_tolerates_garbage_bm25_invalidate_ts():
    """Regression guard: operator edits tenants/{id}.bm25_invalidate_ts to a
    non-numeric value in Firestore console. run_agent must fall back to 0.0
    instead of crashing with ValueError.
    """
    from chat.services.agent import run_agent

    # Seed tenant with garbage ts
    tenant = {
        "tenant_id": "t_garbage",
        "pinecone_namespace": "ns-x",
        "persona": "test",
        "bm25_invalidate_ts": "not-a-number",  # bad type
    }

    # Only go as far as create_tools — we're proving the coercion doesn't
    # crash, not re-testing the full agent loop.
    with (
        patch("chat.services.agent.conversation_memory") as mock_mem,
        patch("chat.services.agent.create_tools", return_value=([], lambda: [])) as mock_tools,
        patch("chat.services.agent.create_react_agent") as mock_ra,
        patch("chat.services.agent.track_usage", new=AsyncMock()),
    ):
        mock_mem.get_history = AsyncMock(return_value=[])
        mock_mem.add_turn = AsyncMock()
        mock_agent = MagicMock()
        mock_agent.ainvoke = AsyncMock(return_value={
            "messages": [MagicMock(content="ok", tool_calls=[])]
        })
        mock_ra.return_value = mock_agent

        answer, sources = await run_agent("hello", "user-1", tenant)

    # Assert create_tools got the SAFE fallback 0.0, not a crash
    assert mock_tools.call_args.kwargs["invalidate_ts"] == 0.0
    assert answer == "ok"


@pytest.mark.asyncio
async def test_hybrid_search_keeps_cache_when_invalidate_ts_older():
    """Fresh cache (warmed_ts > invalidate_ts) must NOT be re-warmed."""
    from langchain_core.documents import Document
    from chat.services.bm25 import BM25Index, invalidate_bm25_cache
    from chat.services import bm25 as bm25_module

    invalidate_bm25_cache("test-fresh-ns")

    fresh_idx = BM25Index([Document(page_content="current", metadata={})])
    fresh_idx.warmed_ts = 1000.0
    with bm25_module._lock:
        bm25_module._cache["test-fresh-ns"] = fresh_idx

    warm_calls = {"n": 0}

    def fake_warm(ns):
        warm_calls["n"] += 1
        return BM25Index([])

    with (
        patch("chat.services.search.get_vectorstore") as mock_vs,
        patch("chat.services.search.warm_bm25_for_namespace", side_effect=fake_warm),
    ):
        mock_store = MagicMock()
        mock_store.similarity_search.return_value = []
        mock_vs.return_value = mock_store

        from chat.services.search import _hybrid_search
        # Tenant's invalidate_ts=500, cache warmed at 1000 → cache is fresh
        await _hybrid_search("q", "test-fresh-ns", invalidate_ts=500.0)

    assert warm_calls["n"] == 0, "fresh cache must not re-warm"


def test_warm_bm25_empty_namespace_returns_empty_index():
    from chat.services.bm25 import warm_bm25_for_namespace, invalidate_bm25_cache
    invalidate_bm25_cache("empty-ns")
    with patch("shared.services.vectorstore.list_all_vector_ids", return_value=[]):
        idx = warm_bm25_for_namespace("empty-ns")
    assert idx.documents == []
    assert idx.search("anything") == []


def test_warm_bm25_is_concurrent_safe():
    """Two threads racing warm_bm25_for_namespace run Pinecone fetch only once.

    Simulates the cold-start race: both threads see an empty cache, both call
    warm_bm25_for_namespace concurrently. Double-checked locking should cause
    the second thread to return the first thread's result without re-fetching.
    """
    import threading
    from chat.services.bm25 import warm_bm25_for_namespace, invalidate_bm25_cache

    invalidate_bm25_cache("race-ns")

    fetch_calls = {"count": 0}
    start = threading.Event()

    def slow_list_ids(namespace):
        start.wait(timeout=2)  # make sure both threads reach here together
        fetch_calls["count"] += 1
        return ["id1", "id2", "id3", "id4", "id5"]

    fake_index = MagicMock()
    fake_index.fetch.return_value = MagicMock(vectors={
        f"id{i}": _FakeVec({"text": f"content chunk {i} unique tokens here",
                             "source_filename": f"{i}.pdf"})
        for i in range(1, 6)
    })

    results = [None, None]

    def worker(idx):
        with (
            patch("shared.services.vectorstore.list_all_vector_ids",
                  side_effect=slow_list_ids),
            patch("shared.services.vectorstore.get_raw_index", return_value=fake_index),
        ):
            results[idx] = warm_bm25_for_namespace("race-ns")

    t1 = threading.Thread(target=worker, args=(0,))
    t2 = threading.Thread(target=worker, args=(1,))
    t1.start(); t2.start()
    start.set()  # release both threads ~simultaneously
    t1.join(timeout=3); t2.join(timeout=3)

    # At most ONE thread should have called list_ids; the other should have
    # seen the cache populated after waiting on the lock.
    assert fetch_calls["count"] == 1, (
        f"expected 1 Pinecone fetch under race, got {fetch_calls['count']}"
    )
    # Both threads should return the same index (same object after dedup).
    assert results[0] is results[1]
    assert results[0] is not None and len(results[0].documents) == 5


# ──────────────────────────────────────
# Query rewriting with history
# ──────────────────────────────────────

@pytest.mark.asyncio
async def test_rewrite_query_no_history_returns_original():
    from chat.services.search import _rewrite_query_with_history
    out = await _rewrite_query_with_history("what about 5 years?", history=None)
    assert out == "what about 5 years?"

    out = await _rewrite_query_with_history("tuition?", history=[])
    assert out == "tuition?"


@pytest.mark.asyncio
async def test_rewrite_query_with_history_calls_haiku():
    from chat.services.search import _rewrite_query_with_history

    with patch("chat.services.search._get_haiku") as mock_haiku:
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(return_value=MagicMock(content="tuition for 5-year program"))
        mock_haiku.return_value = mock_llm

        history = [{"query": "tuition for 4-year program?", "answer": "84,000 baht"}]
        out = await _rewrite_query_with_history("what about 5 years?", history=history)
        assert out == "tuition for 5-year program"


@pytest.mark.asyncio
async def test_rewrite_query_haiku_failure_falls_back():
    from chat.services.search import _rewrite_query_with_history

    with patch("chat.services.search._get_haiku") as mock_haiku:
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(side_effect=RuntimeError("boom"))
        mock_haiku.return_value = mock_llm

        history = [{"query": "q", "answer": "a"}]
        # query contains a follow-up marker ("what about") so rewriter runs
        out = await _rewrite_query_with_history("what about 5 years?", history=history)
        assert out == "what about 5 years?"


@pytest.mark.asyncio
async def test_rewrite_query_guards_against_oversized_output():
    from chat.services.search import _rewrite_query_with_history

    with patch("chat.services.search._get_haiku") as mock_haiku:
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(return_value=MagicMock(content="x" * 10000))
        mock_haiku.return_value = mock_llm

        # query contains a follow-up marker so rewriter runs; too-long output rejected
        out = await _rewrite_query_with_history(
            "what about this one?", history=[{"query": "q", "answer": "a"}],
        )
        assert out == "what about this one?"  # too-long rewrite rejected


@pytest.mark.asyncio
async def test_rewrite_query_standalone_skips_haiku():
    """Regression (2026-04-19 demo): simple noun queries with no follow-up
    markers must skip Haiku — Haiku empirically injects 'ดาวน์โหลด' / 'ฟอร์ม' /
    'เกณฑ์' qualifiers that kill retrieval.
    """
    from chat.services.search import _rewrite_query_with_history

    history = [{"query": "earlier question", "answer": "earlier answer"}]
    standalone_queries = [
        "ตารางเรียน",
        "ประกาศ",
        "สอบวิทยานิพนธ์",
        "ค่าเทอม",
        "หลักสูตรการจัดการเทคโนโลยีและนวัตกรรมผู้ประกอบการ",
        "schedule",
        "announcement",
    ]
    with patch("chat.services.search._get_haiku") as mock_haiku:
        for q in standalone_queries:
            out = await _rewrite_query_with_history(q, history=history)
            assert out == q, f"standalone {q!r} rewritten to {out!r}"
        mock_haiku.assert_not_called()


@pytest.mark.asyncio
async def test_rewrite_query_with_pronoun_still_calls_haiku():
    """Queries with pronouns go through Haiku for context resolution."""
    from chat.services.search import _rewrite_query_with_history

    with patch("chat.services.search._get_haiku") as mock_haiku:
        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(
            return_value=MagicMock(content="อ.กวิน สอนวิชาอะไร")
        )
        mock_haiku.return_value = mock_llm

        history = [{"query": "อ.กวินคือใคร", "answer": "อาจารย์ในหลักสูตร"}]
        out = await _rewrite_query_with_history("เขาสอนวิชาอะไร", history=history)
        assert out == "อ.กวิน สอนวิชาอะไร"
        mock_haiku.assert_called_once()


# ──────────────────────────────────────
# MMR diversify
# ──────────────────────────────────────

def test_mmr_passthrough_when_candidates_le_top_k():
    from chat.services.search import _mmr_diversify
    scored = [
        (Document(page_content="A", metadata={}), 0.9),
        (Document(page_content="B", metadata={}), 0.8),
    ]
    result = _mmr_diversify(scored, top_k=5)
    assert result == scored


def test_mmr_drops_near_duplicate_in_favor_of_diverse():
    from chat.services.search import _mmr_diversify
    # Top candidate and a near-duplicate should not both be selected over a
    # genuinely diverse third option.
    near_dup_text = "tuition for 4-year program is 21000 baht per semester"
    docs = [
        (Document(page_content=near_dup_text, metadata={"id": "A"}), 0.95),
        (Document(page_content=near_dup_text + " (revised)", metadata={"id": "B"}), 0.92),
        (Document(page_content="class schedule monday through friday from 9 to 16", metadata={"id": "C"}), 0.70),
    ]
    result = _mmr_diversify(docs, top_k=2)
    ids = [d.metadata["id"] for d, _ in result]
    assert ids[0] == "A"          # top-1 is always kept
    assert ids[1] == "C"          # diverse third beats near-duplicate


def test_mmr_always_keeps_top1():
    from chat.services.search import _mmr_diversify
    docs = [
        (Document(page_content="unique topic one", metadata={"id": "A"}), 0.9),
        (Document(page_content="unique topic two", metadata={"id": "B"}), 0.8),
        (Document(page_content="unique topic three", metadata={"id": "C"}), 0.7),
    ]
    result = _mmr_diversify(docs, top_k=3)
    assert result[0][0].metadata["id"] == "A"
    assert len(result) == 3


# ──────────────────────────────────────
# Adaptive TOP_K
# ──────────────────────────────────────

@pytest.mark.asyncio
async def test_search_uses_top_k_complex_for_multi_subquery():
    """When decomposition returns multiple sub-queries, use TOP_K_COMPLEX for rerank+MMR."""
    from shared.config import settings
    # Sanity: the two knobs must differ so this test actually proves routing
    assert settings.TOP_K_COMPLEX > settings.TOP_K

    captured = {}

    async def fake_rerank(query, docs, top_k):
        captured["rerank_top_k"] = top_k
        return [(d, 0.5) for d in docs[:top_k]]

    def fake_mmr(scored, top_k, **_):
        captured["mmr_top_k"] = top_k
        return scored[:top_k]

    with (
        patch("chat.services.search._decompose_query", new_callable=AsyncMock) as mock_d,
        patch("chat.services.search._generate_query_variants", new_callable=AsyncMock) as mock_v,
        patch("chat.services.search._hybrid_search", new_callable=AsyncMock) as mock_h,
        patch("chat.services.search.rerank_with_scores", side_effect=fake_rerank),
        patch("chat.services.search._mmr_diversify", side_effect=fake_mmr),
        patch("chat.services.search._rewrite_query_with_history", new_callable=AsyncMock,
              return_value="q"),
    ):
        mock_d.return_value = ["sub1", "sub2", "sub3"]  # complex → 3 sub-queries
        mock_v.return_value = ["variant"]
        # Return enough candidates so top_k matters
        mock_h.return_value = [
            Document(page_content=f"content {i}", metadata={"source_filename": f"f{i}.pdf"})
            for i in range(20)
        ]

        from chat.services.search import search_with_sources
        await search_with_sources("compare A vs B vs C", "ns")

    assert captured["mmr_top_k"] == settings.TOP_K_COMPLEX
    assert captured["rerank_top_k"] == max(settings.TOP_K_COMPLEX * 2, 10)


@pytest.mark.asyncio
async def test_search_parallelizes_variants_across_subqueries():
    """_generate_query_variants must be invoked concurrently for each sub-query.

    Uses an asyncio.Event to gate the mock: all concurrent calls block, then
    release together. If the code path is sequential, the second call never
    starts before we assert on concurrent_peak.
    """
    import asyncio

    concurrent = 0
    peak = 0
    release = asyncio.Event()

    async def gated_variants(q):
        nonlocal concurrent, peak
        concurrent += 1
        peak = max(peak, concurrent)
        await release.wait()
        concurrent -= 1
        return [q]

    async def release_later():
        await asyncio.sleep(0.05)
        release.set()

    with (
        patch("chat.services.search._decompose_query", new_callable=AsyncMock) as mock_d,
        patch("chat.services.search._generate_query_variants", side_effect=gated_variants),
        patch("chat.services.search._hybrid_search", new_callable=AsyncMock) as mock_h,
        patch("chat.services.search.rerank_with_scores", new_callable=AsyncMock) as mock_r,
        patch("chat.services.search._mmr_diversify", side_effect=lambda s, top_k, **_: s[:top_k]),
        patch("chat.services.search._rewrite_query_with_history", new_callable=AsyncMock,
              return_value="q"),
    ):
        mock_d.return_value = ["sub_a", "sub_b", "sub_c"]
        mock_h.return_value = [Document(page_content="x", metadata={})]
        mock_r.return_value = [(Document(page_content="x", metadata={}), 0.5)]

        from chat.services.search import search_with_sources
        await asyncio.gather(search_with_sources("q", "ns"), release_later())

    # All 3 variants must have been in flight concurrently
    assert peak == 3, f"expected 3 concurrent variants, got {peak}"


@pytest.mark.asyncio
async def test_search_dedupes_variants_before_hybrid_search():
    """Variants that repeat across sub-queries should run hybrid_search only once."""
    with (
        patch("chat.services.search._decompose_query", new_callable=AsyncMock) as mock_d,
        patch("chat.services.search._generate_query_variants", new_callable=AsyncMock) as mock_v,
        patch("chat.services.search._hybrid_search", new_callable=AsyncMock) as mock_h,
        patch("chat.services.search.rerank_with_scores", new_callable=AsyncMock) as mock_r,
        patch("chat.services.search._mmr_diversify", side_effect=lambda s, top_k, **_: s[:top_k]),
        patch("chat.services.search._rewrite_query_with_history", new_callable=AsyncMock,
              return_value="q"),
    ):
        mock_d.return_value = ["sub1", "sub2"]
        # Both sub_queries return overlapping variants — only unique ones should search
        mock_v.side_effect = [["shared_q", "unique_1"], ["shared_q", "unique_2"]]
        mock_h.return_value = [Document(page_content="x", metadata={})]
        mock_r.return_value = [(Document(page_content="x", metadata={}), 0.5)]

        from chat.services.search import search_with_sources
        await search_with_sources("q", "ns")

    # 3 unique variants → 3 hybrid_search calls (not 4)
    assert mock_h.call_count == 3


@pytest.mark.asyncio
async def test_search_uses_top_k_simple_for_single_subquery():
    """Single-topic queries use the tighter TOP_K."""
    from shared.config import settings
    captured = {}

    async def fake_rerank(query, docs, top_k):
        captured["rerank_top_k"] = top_k
        return [(d, 0.5) for d in docs[:top_k]]

    def fake_mmr(scored, top_k, **_):
        captured["mmr_top_k"] = top_k
        return scored[:top_k]

    with (
        patch("chat.services.search._decompose_query", new_callable=AsyncMock) as mock_d,
        patch("chat.services.search._generate_query_variants", new_callable=AsyncMock) as mock_v,
        patch("chat.services.search._hybrid_search", new_callable=AsyncMock) as mock_h,
        patch("chat.services.search.rerank_with_scores", side_effect=fake_rerank),
        patch("chat.services.search._mmr_diversify", side_effect=fake_mmr),
        patch("chat.services.search._rewrite_query_with_history", new_callable=AsyncMock,
              return_value="q"),
    ):
        mock_d.return_value = ["q"]  # simple → single query
        mock_v.return_value = ["variant"]
        mock_h.return_value = [
            Document(page_content=f"content {i}", metadata={"source_filename": f"f{i}.pdf"})
            for i in range(20)
        ]

        from chat.services.search import search_with_sources
        await search_with_sources("what is X?", "ns")

    assert captured["mmr_top_k"] == settings.TOP_K
    assert captured["rerank_top_k"] == max(settings.TOP_K * 2, 10)


# ──────────────────────────────────────
# System prompt caching markers
# ──────────────────────────────────────

def test_system_content_has_cache_control_on_static_block():
    from chat.services.agent import _build_system_content
    content = _build_system_content("Test persona", "ไม่มีประวัติสนทนา")
    assert isinstance(content, list)
    assert len(content) == 2
    assert content[0]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in content[1]  # dynamic block is NOT cached
    assert "Test persona" in content[1]["text"]
    assert "Test persona" not in content[0]["text"]  # persona not leaking into static


def test_system_content_static_prompt_has_core_rules():
    from chat.services.agent import _build_system_content, _STATIC_SYSTEM_PROMPT
    content = _build_system_content("", "")
    assert content[0]["text"] == _STATIC_SYSTEM_PROMPT
    # Prompt was restructured for defense-ready polish — check the section
    # headers that actually ship rather than the original "Core Rules" heading.
    assert "When to Search" in content[0]["text"]
    assert "Confidence Tiers" in content[0]["text"]
    assert "Answer Quality" in content[0]["text"]
