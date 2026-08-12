import os
import json
import logging
from typing import List, Dict, Any, Optional
from openai import OpenAI
from pydantic import BaseModel

logger = logging.getLogger("agent_logger")

class ChatRequest(BaseModel):
    message: str
    history: Optional[List[Dict[str, str]]] = None

class ChatResponse(BaseModel):
    answer: str
    thought: Optional[str] = None
    citations: List[Dict[str, Any]] = []

import re
import traceback

# Single source of truth for book mappings — see books.py
from books import (
    KO_TO_EN,
    detect_version,
    to_db_book,
)

SYSTEM_PROMPT_KR = ("You are a theological assistant specializing in the Revised Korean Version (개역개정) of the Bible. "
                    "Your goal is to provide deep insights grounded in scripture. "
                    "Before answering, determine the user's intent: Is it historical, theological, or for encouragement? "
                    "Tailor your search and synthesis accordingly. "
                    "Always search the Bible to find relevant context before answering. "
                    "When you answer, provide citations in the format [Book Chapter:Verse] using the Korean book name (e.g. [시편 23:1]). "
                    "If you use a tool, explain your thought process briefly.")

ESV_COPYRIGHT = ("Scripture quotations are from The Holy Bible, English Standard Version® (ESV®), "
                 "copyright © 2001 by Crossway, a publishing ministry of Good News Publishers. "
                 "Used by permission. All rights reserved.")

SYSTEM_PROMPT_EN = ("You are a theological assistant specializing in the English Standard Version (ESV) of the Bible. "
                    "Your goal is to provide deep insights grounded in scripture. "
                    "Before answering, determine the user's intent: Is it historical, theological, or for encouragement? "
                    "Tailor your search and synthesis accordingly. "
                    "Always search the Bible to find relevant context before answering. "
                    "When you answer, provide citations in the format [Book Chapter:Verse] using the English book name (e.g. [Psalm 23:1]). "
                    "If you use a tool, explain your thought process briefly. "
                    f"When you quote ESV text, end your response with: \"{ESV_COPYRIGHT}\"")

MAX_TOOL_ROUNDS = 5
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_bible",
            "description": "Search the Bible for relevant sections or topics.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The topic or theme to search for."},
                    "limit": {"type": "integer", "description": "Number of results to return."}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_bible_text",
            "description": "Get exact verse text for a specific reference.",
            "parameters": {
                "type": "object",
                "properties": {
                    "book": {"type": "string", "description": "Book name in Korean (e.g., '창세기')"},
                    "chapter": {"type": "integer", "description": "Chapter number"},
                    "verse_start": {"type": "integer", "description": "Start verse"},
                    "verse_end": {"type": "integer", "description": "End verse (optional)"}
                },
                "required": ["book", "chapter", "verse_start"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "find_pastor_quotes",
            "description": "Find relevant sermon quotes or pastoral explanations for a topic.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The topic or verse to find in sermons."},
                    "limit": {"type": "integer", "description": "Number of results to return."}
                },
                "required": ["query"]
            }
        }
    }
]

class BibleAgent:
    def __init__(self, openai_client: OpenAI, supabase_client: Any):
        self.client = openai_client
        self.supabase = supabase_client
        self.model = os.environ.get("AGENT_MODEL", "moonshotai/kimi-k2.6")
        self.current_version = "NKRV"
    
    def extract_citations(self, text: str) -> List[Dict[str, Any]]:
        # Regex to match [Book Chapter:Verse-Verse] or [Book Chapter:Verse]
        # Example: [창세기 1:1-5], [마태복음 5:3], [Psalm 23:1]
        pattern = r"\[([^\[\]]+?)\s+(\d+):(\d+)(?:-(\d+))?\]"
        matches = re.finditer(pattern, text)
        citations = []
        for match in matches:
            book, chapter, v_start, v_end = match.groups()
            citations.append({
                "book": book,
                "chapter": int(chapter),
                "verse_start": int(v_start),
                "verse_end": int(v_end) if v_end else int(v_start)
            })
        return citations

    def search_bible_tool(self, query: str, limit: int = 5) -> str:
        """Search the Bible for relevant sections based on a semantic query."""
        try:
            # 1. Embed the query (Using OpenAI embedding model via OpenRouter or direct if needed)
            # OpenRouter often proxies openai/text-embedding-3-small
            response = self.client.embeddings.create(
                input=query,
                model="openai/text-embedding-3-small"
            )
            if not response or not getattr(response, "data", None) or not response.data or not response.data[0].embedding:
                logger.error(f"Agent search_bible_tool: empty embedding response: {response}")
                return "Error searching Bible: empty embedding response"
            query_embedding = response.data[0].embedding

            # 2. Call the version-aware Supabase RPC
            result = self.supabase.rpc(
                "match_bible_sections_v",
                {
                    "query_embedding": query_embedding,
                    "match_threshold": 0.3,
                    "match_count": limit,
                    "version_filter": self.current_version
                }
            ).execute()

            return json.dumps(result.data, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Agent search_bible_tool error: {e}\n{traceback.format_exc()}")
            return f"Error searching Bible: {str(e)}"

    def get_bible_text_tool(self, book: str, chapter: int, verse_start: int, verse_end: Optional[int] = None) -> str:
        """Get the specific text of Bible verses."""
        try:
            end = verse_end if verse_end is not None else verse_start
            # ESV rows are stored under English book names, NKRV under Korean
            db_book = to_db_book(book, self.current_version)
            result = self.supabase.table("bible_verses") \
                .select("book, chapter, verse_start, verse_end, text") \
                .eq("book", db_book) \
                .eq("chapter", chapter) \
                .eq("version", self.current_version) \
                .gte("verse_start", verse_start) \
                .lte("verse_end", end) \
                .order("verse_start") \
                .limit(500) \
                .execute()
            
            return json.dumps(result.data, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Agent get_bible_text_tool error: {e}\n{traceback.format_exc()}")
            return f"Error getting Bible text: {str(e)}"

    def find_pastor_quotes_tool(self, query: str, limit: int = 3) -> str:
        """Search through sermon archives for relevant pastor quotes or theological explanations."""
        try:
            response = self.client.embeddings.create(
                input=query,
                model="openai/text-embedding-3-small"
            )
            if not response or not getattr(response, "data", None) or not response.data or not response.data[0].embedding:
                logger.error(f"Agent find_pastor_quotes_tool: empty embedding response: {response}")
                return "Error searching sermons: empty embedding response"
            query_embedding = response.data[0].embedding

            result = self.supabase.rpc(
                "match_sermons",
                {
                    "query_embedding": query_embedding,
                    "match_threshold": 0.4,
                    "match_count": limit
                }
            ).execute()
            
            return json.dumps(result.data, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Agent find_pastor_quotes_tool error: {e}\n{traceback.format_exc()}")
            return f"Error searching sermons: {str(e)}"

    def call_tool(self, function_name: str, function_args: Dict[str, Any]) -> str:
        if function_name == "search_bible":
            return self.search_bible_tool(**function_args)
        if function_name == "get_bible_text":
            return self.get_bible_text_tool(**function_args)
        if function_name == "find_pastor_quotes":
            return self.find_pastor_quotes_tool(**function_args)
        return "Unknown tool"

    @staticmethod
    def strip_tool_markup(text: str) -> str:
        # Safety net: remove kimi-style tool-call markup from final answers
        if not text:
            return ""
        return re.sub(
            r"<\|tool_calls_section_(?:begin|end)\|>.*?<\|tool_calls_section_(?:begin|end)\|>",
            "",
            text,
            flags=re.DOTALL,
        ).strip()

    def _build_messages(self, user_message: str, history: Optional[List[Dict[str, str]]] = None) -> List[Dict[str, Any]]:
        self.current_version = detect_version(user_message)
        system_prompt = SYSTEM_PROMPT_KR if self.current_version == "NKRV" else SYSTEM_PROMPT_EN
        # Sanitize history: drop non-dict entries or entries with None content to avoid LLM returning None choices
        sanitized_history = []
        for h in (history or [])[-10:]:
            if not isinstance(h, dict):
                continue
            role = h.get("role")
            content = h.get("content")
            if role not in ("user", "assistant", "system", "tool"):
                continue
            if not isinstance(content, str) or not content.strip():
                continue
            # Keep optional tool fields if present
            entry = {"role": role, "content": content}
            if h.get("tool_call_id"):
                entry["tool_call_id"] = h["tool_call_id"]
            if h.get("name"):
                entry["name"] = h["name"]
            sanitized_history.append(entry)
        return [
            {"role": "system", "content": system_prompt},
            *sanitized_history,
            {"role": "user", "content": user_message}
        ]

    def _run_tool_loop(self, messages: List[Dict[str, Any]], thought_process: List[str], stream_final: bool = False):
        """Drive the tool-call loop. Returns (response_message, tool_rounds, stream).
        response_message is None if the loop exhausted all rounds on tool calls
        (caller must then force a final answer without tools)."""
        response_message = None
        tool_rounds = 0
        stream = None
        for round_idx in range(MAX_TOOL_ROUNDS):
            if stream_final and round_idx == MAX_TOOL_ROUNDS - 1:
                # Last allowed round: stream the final answer instead of requesting tools
                tool_rounds = round_idx + 1
                return response_message, tool_rounds, self._final_stream(messages)
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto"
            )
            if not response or not getattr(response, "choices", None) or not response.choices:
                logger.error(f"_run_tool_loop: empty choices response: {response}\n{traceback.format_exc()}")
                raise RuntimeError("LLM returned empty choices")
            msg = response.choices[0].message if response.choices[0] else None
            if msg is None:
                logger.error(f"_run_tool_loop: choices[0].message is None: {response}\n{traceback.format_exc()}")
                raise RuntimeError("LLM returned None message")
            response_message = msg
            tool_rounds = round_idx + 1
            if not response_message.tool_calls:
                break

            messages.append(response_message)
            for tool_call in response_message.tool_calls:
                try:
                    function_args = json.loads(tool_call.function.arguments or "{}")
                except json.JSONDecodeError:
                    function_args = {}
                function_name = tool_call.function.name

                query = function_args.get("query")
                if query:
                    thought_process.append(f"Searching for: {query}")
                else:
                    thought_process.append(
                        f"Searching for: {function_args.get('book', '?')} {function_args.get('chapter', '?')}"
                    )

                result = self.call_tool(function_name, function_args)
                messages.append({
                    "tool_call_id": tool_call.id,
                    "role": "tool",
                    "name": function_name,
                    "content": result
                })
        else:
            # Loop exhausted without a final message: caller must force an answer
            response_message = None
        return response_message, tool_rounds, stream

    def _final_stream(self, messages: List[Dict[str, Any]]):
        """Stream a final answer without tools (used when max rounds reached or last chance)."""
        return self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            stream=True
        )

    def run(self, user_message: str, history: Optional[List[Dict[str, str]]] = None) -> ChatResponse:
        messages = self._build_messages(user_message, history)

        thought_process = []
        response_message, _, _ = self._run_tool_loop(messages, thought_process)

        if response_message is None:
            # Max rounds reached with tools still requested: force a final answer
            logger.warning("Max tool rounds reached; requesting final answer without tools")
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages
            )
            if not response or not getattr(response, "choices", None) or not response.choices or not response.choices[0].message:
                logger.error(f"run fallback: empty choices: {response}\n{traceback.format_exc()}")
                raise RuntimeError("LLM fallback returned empty choices")
            response_message = response.choices[0].message

        answer = self.strip_tool_markup(response_message.content) if response_message and response_message.content else None
        if not answer:
            answer = "답변을 생성하지 못했습니다. 다시 시도해 주세요."

        return ChatResponse(
            answer=answer,
            thought=" -> ".join(thought_process) if thought_process else "Direct answer based on internal knowledge (cautioned).",
            citations=self.extract_citations(answer)
        )

    def run_stream(self, user_message: str, history: Optional[List[Dict[str, str]]] = None):
        """Generator yielding events: {"type": "delta", "content": str} and
        {"type": "done", "answer": str, "thought": str, "citations": [...]}."""
        messages = self._build_messages(user_message, history)
        thought_process = []
        response_message, _, stream = self._run_tool_loop(messages, thought_process, stream_final=True)

        answer = None
        if stream is not None:
            chunks = []
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                    piece = chunk.choices[0].delta.content
                    chunks.append(piece)
                    yield {"type": "delta", "content": piece}
            answer = "".join(chunks)
            if not answer and response_message and response_message.content:
                answer = response_message.content
        elif response_message:
            answer = response_message.content or ""
            if answer:
                yield {"type": "delta", "content": answer}

        answer = self.strip_tool_markup(answer) if answer else None
        if not answer:
            answer = "답변을 생성하지 못했습니다. 다시 시도해 주세요."

        yield {
            "type": "done",
            "answer": answer,
            "thought": " -> ".join(thought_process) if thought_process else "Direct answer based on internal knowledge (cautioned).",
            "citations": self.extract_citations(answer)
        }
