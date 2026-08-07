"""Rich terminal rendering for Bible results."""
import re
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

CITATION_RE = re.compile(r"\[([^\[\]]+?\s+[^\[\]]*?\d+:\d+(?:-\d+)?)\]")


def _styled_text(console: Console, text: str) -> Text:
    """Split answer text around [Citation] markers; render citations cyan."""
    result = Text()
    # Split on brackets; the regex extracts citation content within [..]
    # We iterate over segments: plain text and citation spans.
    pos = 0
    for m in CITATION_RE.finditer(text):
        if m.start() > pos:
            result.append(text[pos:m.start()])
        result.append(f"[{m.group(0)}]", style="bold cyan")
        pos = m.end()
    if pos < len(text):
        result.append(text[pos:])
    return result


def render_thought(console: Console, thought: str):
    if thought:
        console.print(f"[dim]▶ {thought}[/dim]")


def render_verses(console: Console, rows: list, title: str | None = None):
    if not rows:
        console.print("[yellow]No verses found.[/yellow]")
        return
    table = Table(title=title, box=box.SIMPLE_HEAVY, expand=False)
    table.add_column("Ref", style="bold cyan", no_wrap=True)
    table.add_column("Text")
    for r in rows:
        ref = _ref_label(r)
        table.add_row(ref, r.get("text", "").strip())
    console.print(table)


def render_sections(console: Console, rows: list, title: str | None = None):
    if not rows:
        console.print("[yellow]No results found.[/yellow]")
        return
    for r in rows:
        ref = f"{r.get('book', '')} {r.get('chapter', '')}:{r.get('verse_range', '')}"
        sim = f"{r.get('similarity', 0):.3f}" if isinstance(r.get("similarity"), (int, float)) else ""
        console.print(Panel(
            Text(r.get("content", "").strip()),
            title=f"[bold cyan]{ref}[/bold cyan]" + (f"  [dim]({sim})[/dim]" if sim else ""),
            border_style="bright_blue",
            title_align="left",
        ))


def render_sermons(console: Console, rows: list):
    if not rows:
        console.print("[yellow]No sermons found.[/yellow]")
        return
    for r in rows:
        title = r.get("title") or "Sermon excerpt"
        meta = " | ".join(x for x in [r.get("date"), r.get("speaker")] if x)
        console.print(Panel(
            Text(r.get("chunk_text", "").strip()),
            title=f"[bold magenta]{title}[/bold magenta]" + (f"  [dim]{meta}[/dim]" if meta else ""),
            border_style="magenta",
            title_align="left",
        ))


def render_chat_text(console: Console, answer: str, show_copyright: bool = True):
    """Print an agent answer with citations styled; optionally strip ESV copyright footer."""
    if not show_copyright:
        answer = answer.replace(ESV_COPYRIGHT, "").rstrip()
    console.print(_styled_text(console, answer))


def render_error(console: Console, message: str):
    console.print(f"[bold red]Error:[/bold red] {message}")


def _ref_label(r: dict) -> str:
    book = r.get("book", "")
    chapter = r.get("chapter", "")
    vs, ve = r.get("verse_start"), r.get("verse_end")
    v = f"{vs}" if vs is not None and (ve is None or ve == vs) else f"{vs}-{ve}"
    version = r.get("version")
    ref = f"{book} {chapter}:{v}" if chapter not in (None, "") else f"{book} {v}"
    if version:
        ref += f"  ({version})"
    return ref


ESV_COPYRIGHT = ("Scripture quotations are from The Holy Bible, English Standard Version® (ESV®), "
                 "copyright © 2001 by Crossway, a publishing ministry of Good News Publishers. "
                 "Used by permission. All rights reserved.")