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
    
    def extract_citations(self, text: str) -> List[Dict[str, Any]]:
        # Regex to match [Book Chapter:Verse-Verse] or [Book Chapter:Verse]
        # Example: [창세기 1:1-5], [마태복음 5:3]
        pattern = r"\[([\uac00-\ud7af]+)\s+(\d+):(\d+)(?:-(\d+))?\]"
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
            query_embedding = response.data[0].embedding

            # 2. Call Supabase RPC
            result = self.supabase.rpc(
                "match_bible_sections",
                {
                    "query_embedding": query_embedding,
                    "match_threshold": 0.3,
                    "match_count": limit
                }
            ).execute()
            
            return json.dumps(result.data, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Agent search_bible_tool error: {e}")
            return f"Error searching Bible: {str(e)}"

    def get_bible_text_tool(self, book: str, chapter: int, verse_start: int, verse_end: Optional[int] = None) -> str:
        """Get the specific text of Bible verses."""
        try:
            end = verse_end if verse_end is not None else verse_start
            result = self.supabase.table("bible_verses") \
                .select("book, chapter, verse_start, verse_end, text") \
                .eq("book", book) \
                .eq("chapter", chapter) \
                .gte("verse_start", verse_start) \
                .lte("verse_end", end) \
                .order("verse_start") \
                .execute()
            
            return json.dumps(result.data, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Agent get_bible_text_tool error: {e}")
            return f"Error getting Bible text: {str(e)}"

    def find_pastor_quotes_tool(self, query: str, limit: int = 3) -> str:
        """Search through sermon archives for relevant pastor quotes or theological explanations."""
        try:
            response = self.client.embeddings.create(
                input=query,
                model="openai/text-embedding-3-small"
            )
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
            logger.error(f"Agent find_pastor_quotes_tool error: {e}")
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
        return re.sub(
            r"<\|tool_calls_section_(?:begin|end)\|>.*?<\|tool_calls_section_(?:begin|end)\|>",
            "",
            text,
            flags=re.DOTALL,
        ).strip()

    def run(self, user_message: str, history: Optional[List[Dict[str, str]]] = None) -> ChatResponse:
        messages = [
            {"role": "system", "content": "You are a theological assistant specializing in the Revised Korean Version (개역개정) of the Bible. "
                                          "Your goal is to provide deep insights grounded in scripture. "
                                          "Before answering, determine the user's intent: Is it historical, theological, or for encouragement? "
                                          "Tailor your search and synthesis accordingly. "
                                          "Always search the Bible to find relevant context before answering. "
                                          "When you answer, provide citations in the format [Book Chapter:Verse]. "
                                          "If you use a tool, explain your thought process briefly."},
            *(history or [])[-10:],
            {"role": "user", "content": user_message}
        ]

        thought_process = []
        response_message = None

        for round_idx in range(MAX_TOOL_ROUNDS):
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto"
            )
            response_message = response.choices[0].message
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
            # Max rounds reached with tools still requested: force a final answer
            logger.warning("Max tool rounds reached; requesting final answer without tools")
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages
            )
            response_message = response.choices[0].message

        answer = self.strip_tool_markup(response_message.content) if response_message else None
        if not answer:
            answer = "답변을 생성하지 못했습니다. 다시 시도해 주세요."

        return ChatResponse(
            answer=answer,
            thought=" -> ".join(thought_process) if thought_process else "Direct answer based on internal knowledge (cautioned).",
            citations=self.extract_citations(answer)
        )
