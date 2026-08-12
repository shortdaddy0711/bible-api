import json
from unittest.mock import Mock, MagicMock, patch

import pytest
from agent import BibleAgent


@pytest.fixture
def mock_clients():
    openai_mock = Mock()
    supabase_mock = Mock()
    return openai_mock, supabase_mock


@pytest.fixture
def agent(mock_clients):
    oc, supabase = mock_clients
    # Use dummy model
    with patch.dict("os.environ", {"AGENT_MODEL": "dummy/model"}):
        a = BibleAgent(oc, supabase)
    a.model = "dummy/model"
    return a


class TestExtractCitations:
    def test_single_citation(self, agent):
        cits = agent.extract_citations("See [Genesis 1:1] for creation.")
        assert cits == [{"book": "Genesis", "chapter": 1, "verse_start": 1, "verse_end": 1}]

    def test_range_citation(self, agent):
        cits = agent.extract_citations("[Psalm 23:1-3] is famous")
        assert cits == [{"book": "Psalm", "chapter": 23, "verse_start": 1, "verse_end": 3}]

    def test_multiple_citations(self, agent):
        text = "[Genesis 1:1] and [John 3:16-17] and [Psalms 23:1]"
        cits = agent.extract_citations(text)
        assert len(cits) == 3
        assert cits[1]["book"] == "John"
        assert cits[1]["verse_end"] == 17

    def test_no_citations(self, agent):
        assert agent.extract_citations("No refs here") == []

    def test_multiword_book(self, agent):
        cits = agent.extract_citations("[1 Samuel 2:5] and [Song of Solomon 2:4]")
        assert cits[0]["book"] == "1 Samuel"
        assert cits[1]["book"] == "Song of Solomon"


class TestStripToolMarkup:
    def test_removes_markup(self, agent):
        text = "Hello <|tool_calls_section_begin|> tool call <|tool_calls_section_end|> world"
        assert agent.strip_tool_markup(text) == "Hello  world"

    def test_no_markup(self, agent):
        assert agent.strip_tool_markup("Hello world") == "Hello world"

    def test_none_returns_empty(self, agent):
        assert agent.strip_tool_markup(None) == ""
        assert agent.strip_tool_markup("") == ""

    def test_multiline_markup(self, agent):
        text = "a <|tool_calls_section_begin|>\nfoo\n<|tool_calls_section_end|> b"
        assert agent.strip_tool_markup(text) == "a  b"


class TestBuildMessages:
    def test_english_sets_esv(self, agent):
        msgs = agent._build_messages("Hello", [])
        assert agent.current_version == "ESV"
        assert "English Standard Version" in msgs[0]["content"]

    def test_korean_sets_nkrv(self, agent):
        msgs = agent._build_messages("하나님", [])
        assert agent.current_version == "NKRV"
        assert "Revised Korean Version" in msgs[0]["content"]

    def test_sanitizes_history(self, agent):
        history = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": None},  # should be dropped
            {"role": "invalid", "content": "x"},  # bad role dropped
            {"role": "user", "content": "   "},  # empty dropped
            "not a dict",  # dropped
            {"role": "user", "content": "valid"},
        ]
        msgs = agent._build_messages("question", history)
        # system + 2 valid history + user
        contents = [m["content"] for m in msgs]
        assert "hi" in contents
        assert "valid" in contents
        assert "question" in contents
        assert len([m for m in msgs if m["role"] == "user"]) == 3  # hi, valid, question (system is separate)

    def test_truncates_history_to_10(self, agent):
        history = [{"role": "user", "content": f"msg {i}"} for i in range(20)]
        msgs = agent._build_messages("final", history)
        # system + 10 history + final = 12
        assert len(msgs) == 12
        assert msgs[1]["content"] == "msg 10"  # first kept after truncation
        assert msgs[-1]["content"] == "final"


class TestRunStream:
    def test_simple_stream_no_tools(self, agent):
        # Mock LLM to return answer without tool calls
        mock_msg = Mock(content="Hello answer", tool_calls=None)
        mock_choice = Mock(message=mock_msg)
        mock_resp = Mock(choices=[mock_choice])
        agent.client.chat.completions.create = Mock(return_value=mock_resp)

        events = list(agent.run_stream("hello", []))
        assert any(e["type"] == "done" for e in events)
        done = next(e for e in events if e["type"] == "done")
        assert done["answer"] == "Hello answer"
        assert "Direct answer" in done["thought"] or done["thought"]

    def test_tool_call_loop(self, agent):
        # First call returns tool_calls, second returns final answer
        tool_call = Mock(id="call1", function=Mock(name="search_bible", arguments=json.dumps({"query": "creation"})))
        msg_with_tool = Mock(content=None, tool_calls=[tool_call])
        msg_final = Mock(content="Final answer [Genesis 1:1]", tool_calls=None)
        agent.client.chat.completions.create = Mock(side_effect=[
            Mock(choices=[Mock(message=msg_with_tool)]),
            Mock(choices=[Mock(message=msg_final)]),
        ])
        # Mock tool execution
        agent.search_bible_tool = Mock(return_value=json.dumps([{"book": "Genesis", "chapter": 1, "content": "In the beginning"}]))

        events = list(agent.run_stream("Explain creation", []))
        done = next(e for e in events if e["type"] == "done")
        assert "Final answer" in done["answer"]
        assert len(done["citations"]) == 1
        assert done["citations"][0]["book"] == "Genesis"

    def test_empty_choices_raises(self, agent):
        agent.client.chat.completions.create = Mock(return_value=Mock(choices=[]))
        # run_stream will propagate via error event? Actually _run_tool_loop raises RuntimeError
        # run_stream catches? No, _run_tool_loop raises, which bubbles to run_stream's caller. run_stream doesn't catch, so it will raise
        with pytest.raises(RuntimeError, match="empty choices"):
            list(agent.run_stream("hello", []))

    def test_run_wrapper_aggregates(self, agent):
        # Test non-streaming wrapper aggregates done event
        def fake_stream(*args, **kwargs):
            yield {"type": "delta", "content": "Hello"}
            yield {"type": "done", "answer": "Hello world", "thought": "thought", "citations": []}
        agent.run_stream = fake_stream
        res = agent.run("hi", [])
        assert res.answer == "Hello world"
        assert res.thought == "thought"

    def test_run_propagates_error(self, agent):
        def fake_stream_error(*args, **kwargs):
            yield {"type": "error", "detail": "LLM failed"}
        agent.run_stream = fake_stream_error
        with pytest.raises(RuntimeError, match="LLM failed"):
            agent.run("hi", [])


class TestSearchTools:
    def test_search_bible_tool_empty_embedding(self, agent):
        agent.client.embeddings.create = Mock(return_value=Mock(data=[]))
        result = agent.search_bible_tool("query")
        assert "empty embedding" in result

    def test_search_bible_tool_success(self, agent):
        agent.client.embeddings.create = Mock(return_value=Mock(data=[Mock(embedding=[0.1, 0.2])]))
        mock_rpc = Mock(execute=Mock(return_value=Mock(data=[{"content": "verse"}])))
        agent.supabase.rpc = Mock(return_value=mock_rpc)
        result = agent.search_bible_tool("creation")
        assert "verse" in result

    def test_get_bible_text_tool(self, agent):
        mock_table = Mock()
        # chain: table().select().eq().eq().eq().gte().lte().order().limit().execute()
        mock_execute = Mock(return_value=Mock(data=[{"text": "In the beginning"}]))
        # Build chain mock
        chain = Mock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.gte.return_value = chain
        chain.lte.return_value = chain
        chain.order.return_value = chain
        chain.limit.return_value = Mock(execute=Mock(return_value=Mock(data=[{"text": "verse"}])))
        agent.supabase.table = Mock(return_value=chain)
        result = agent.get_bible_text_tool("Genesis", 1, 1)
        assert "verse" in result
