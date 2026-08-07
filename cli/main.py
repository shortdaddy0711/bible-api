"""bible — opencode-style CLI for Bible study against the Logos Mind API."""
import argparse
import os
import sys

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from cli.client import BibleClient, BibleAPIError
from cli.parser import parse_reference, ReferenceError
from cli.render import (
    render_chat_text, render_error, render_thought, render_verses, render_sections, render_sermons,
)

BANNER = "✝ Bible Study CLI (Logos Mind)"


def _print_help(console: Console):
    console.print(Panel(
        "[bold]시편 23:1[/bold]            verse lookup from the prompt\n"
        "[bold]/search <topic>[/bold]    semantic Bible search\n"
        "[bold]/sermons <topic>[/bold]   sermon archive search\n"
        "[bold]/reset[/bold]             clear conversation\n"
        "[bold]/copyright[/bold]         toggle ESV copyright footer\n"
        "[bold]/help[/bold]              this help\n"
        "[bold]/quit[/bold]              exit",
        title="Commands",
        border_style="cyan",
    ))


def _cmd_text(args, client: BibleClient, console: Console) -> int:
    try:
        ref = parse_reference(args.reference)
    except ReferenceError as e:
        render_error(console, str(e))
        return 1
    try:
        data = client.text(ref.book, ref.verse_start, ref.verse_end, ref.chapter, args.version)
    except BibleAPIError as e:
        render_error(console, str(e))
        return 1
    rows = list(data.values())[0] if isinstance(data, dict) else data
    render_verses(console, rows, title=str(ref))
    return 0


def _cmd_search(args, client: BibleClient, console: Console) -> int:
    try:
        rows = client.search(args.query, limit=args.limit, version=getattr(args, "version", None))
    except BibleAPIError as e:
        render_error(console, str(e))
        return 1
    render_sections(console, rows, title=f"Search: {args.query}")
    return 0


def _cmd_sermons(args, client: BibleClient, console: Console) -> int:
    try:
        rows = client._get("/api/sermons/search", {"query": args.query, "limit": args.limit})
    except BibleAPIError as e:
        render_error(console, str(e))
        return 1
    render_sermons(console, rows)
    return 0


def _cmd_chat(args, client: BibleClient, console: Console, show_copyright: bool = True) -> int:
    show_copyright = show_copyright and not getattr(args, "no_copyright", False)
    return _stream_chat(client, console, args.query, None, show_copyright)


def _stream_chat(client: BibleClient, console: Console, message: str,
                  history: list | None, show_copyright: bool) -> int:
    status = console.status("[dim]consulting...[/dim]")
    returned = False
    try:
        for event in client.chat_stream(message, history):
            t = event.get("type")
            if t == "error":
                status.stop()
                render_error(console, str(event.get("detail", "unknown error")))
                return 1
            if t == "delta":
                if not returned:
                    status.stop()
                    returned = True
                console.print(event.get("content", ""), end="", markup=False, emoji=False)
            elif t == "done":
                status.stop()
                returned = True
                thought = event.get("thought")
                if thought and "Direct answer" not in str(thought):
                    console.print()
                    render_thought(console, str(thought))
                console.print()
                render_chat_text(console, str(event.get("answer", "")), show_copyright=show_copyright)
                cits = event.get("citations") or []
                if cits:
                    console.print()
                    console.print("[bold]Citations:[/bold]")
                    for c in cits:
                        ref = f"{c['book']} {c['chapter']}:{c['verse_start']}"
                        if c.get("verse_end") and int(c["verse_end"]) != int(c["verse_start"]):
                            ref += f"-{c['verse_end']}"
                        console.print(f"  [bold cyan]{ref}[/bold cyan]")
    except BibleAPIError as e:
        if status.is_started:
            status.stop()
        render_error(console, str(e))
        return 1
    finally:
        status.stop()
    return 0


def _lookup_or_chat(client: BibleClient, console: Console, line: str,
                    history: list, show_copyright: bool) -> int:
    """A bare line: if it parses as a verse ref, fetch it; else chat."""
    try:
        ref = parse_reference(line)
        is_ref = True
    except ReferenceError:
        is_ref = False
    if is_ref:
        try:
            data = client.text(ref.book, ref.verse_start, ref.verse_end, ref.chapter)
        except BibleAPIError as e:
            render_error(console, str(e))
            return 1
        rows = list(data.values())[0] if isinstance(data, dict) else data
        render_verses(console, rows, title=str(ref))
        return 0
    return _stream_chat(client, console, line, history, show_copyright)


def _repl(client: BibleClient, console: Console, show_copyright: bool) -> int:
    import readline

    history_file = os.path.expanduser("~/.bible-cli_history")
    try:
        readline.read_history_file(history_file)
    except (FileNotFoundError, OSError):
        pass
    readline.set_history_length(1000)

    console.print(Panel(BANNER, border_style="blue"))
    console.print("[dim]Type a question, a verse reference (시편 23:1), or /help.[/dim]")

    convo = []
    try:
        while True:
            try:
                line = input("bible> ")
            except (EOFError, KeyboardInterrupt):
                console.print()
                break
            line = line.strip()
            if not line:
                continue
            if line in ("/quit", "/exit", "/q"):
                break
            if line == "/reset":
                convo.clear()
                console.print("[dim]Conversation reset.[/dim]")
                continue
            if line == "/help":
                _print_help(console)
                continue
            if line == "/copyright":
                show_copyright = not show_copyright
                console.print(f"[dim]Copyright footer: {'on' if show_copyright else 'off'}.[/dim]")
                continue
            if line.startswith("/search "):
                args = argparse.Namespace(query=line[len("/search "):].strip(), limit=5, version=None)
                _cmd_search(args, client, console)
                continue
            if line.startswith("/sermons "):
                args = argparse.Namespace(query=line[len("/sermons "):].strip(), limit=3)
                _cmd_sermons(args, client, console)
                continue

            _lookup_or_chat(client, console, line, convo, show_copyright)
    finally:
        try:
            readline.write_history_file(history_file)
        except OSError:
            pass
    return 0


def main(argv=None) -> int:
    args_list = list(argv) if argv is not None else sys.argv[1:]
    parser = argparse.ArgumentParser(prog="bible", description=BANNER)
    parser.add_argument("--api-url", default=os.environ.get("BIBLE_API_URL"), help="API base URL")
    sub = parser.add_subparsers(dest="command")

    p_text = sub.add_parser("text", help="Fetch exact verses: bible text '시편 23:1-3'")
    p_text.add_argument("reference")
    p_text.add_argument("--version", default=None, help="NKRV, ESV, or 'all'")

    p_search = sub.add_parser("search", help="Semantic Bible search")
    p_search.add_argument("query")
    p_search.add_argument("--limit", type=int, default=5)
    p_search.add_argument("--version", default=None)

    p_sermons = sub.add_parser("sermons", help="Sermon search")
    p_sermons.add_argument("query")
    p_sermons.add_argument("--limit", type=int, default=3)

    p_chat = sub.add_parser("chat", help="Agentic chat (streaming)")
    p_chat.add_argument("query")
    p_chat.add_argument("--no-copyright", action="store_true")

    p_repl = sub.add_parser("repl", help="Interactive REPL")
    p_repl.add_argument("--no-copyright", action="store_true")

    args = parser.parse_args(args_list)
    console = Console()
    base_url = args.api_url or os.environ.get("BIBLE_API_URL", "http://76.13.110.111:8080")
    client = BibleClient(base_url=base_url)

    if args.command is None or args.command == "repl":
        show_copyright = not getattr(args, "no_copyright", False)
        return _repl(client, console, show_copyright)
    if args.command == "text":
        return _cmd_text(args, client, console)
    if args.command == "search":
        return _cmd_search(args, client, console)
    if args.command == "sermons":
        return _cmd_sermons(args, client, console)
    if args.command == "chat":
        return _cmd_chat(args, client, console)
    return 1


def run():
    return main()


if __name__ == "__main__":
    sys.exit(run())