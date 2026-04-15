import pytest
from unittest.mock import patch, MagicMock


def test_format_history_with_summary():
    from shared.services.dependencies import format_history
    history = {
        "summary": "นักศึกษาถามเรื่องค่าเทอมหลักสูตร 5 ปี",
        "turns": [{"query": "แล้ววิชาเลือกล่ะ", "answer": "มีวิชาเลือก 12 หน่วยกิต"}],
    }
    result = format_history(history)
    assert "บริบทก่อนหน้า" in result
    assert "ค่าเทอม" in result
    assert "วิชาเลือก" in result


def test_format_history_list_backward_compat():
    from shared.services.dependencies import format_history
    history = [{"query": "ค่าเทอมเท่าไหร่", "answer": "21,000 บาท"}]
    result = format_history(history)
    assert "ค่าเทอมเท่าไหร่" in result
    assert "บริบทก่อนหน้า" not in result


def test_format_history_empty():
    from shared.services.dependencies import format_history
    assert format_history([]) == "ไม่มีประวัติสนทนา"
    assert format_history({}) == "ไม่มีประวัติสนทนา"


def test_summarize_produces_text():
    with patch("chat.services.memory.ChatAnthropic") as MockLLM:
        mock_instance = MagicMock()
        mock_instance.invoke.return_value = MagicMock(
            content="นักศึกษาถามเรื่องค่าเทอมและตารางเรียน"
        )
        MockLLM.return_value = mock_instance

        from chat.services.memory import ConversationMemory
        mem = ConversationMemory()
        summary = mem._summarize([
            {"query": "q1", "answer": "a1"},
            {"query": "q2", "answer": "a2"},
        ])
        assert len(summary) > 0
        assert "ค่าเทอม" in summary


def test_summarize_includes_existing_summary():
    with patch("chat.services.memory.ChatAnthropic") as MockLLM:
        mock_instance = MagicMock()
        mock_instance.invoke.return_value = MagicMock(content="Updated summary")
        MockLLM.return_value = mock_instance

        from chat.services.memory import ConversationMemory
        mem = ConversationMemory()
        summary = mem._summarize(
            [{"query": "new q", "answer": "new a"}],
            existing_summary="Old context about tuition"
        )
        # Verify the prompt included the old summary
        call_args = mock_instance.invoke.call_args[0][0]
        assert "Old context about tuition" in call_args
