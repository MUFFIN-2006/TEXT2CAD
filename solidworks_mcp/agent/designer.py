"""Interactive terminal for the local CAD agent."""

import json
import sys

from rich.console import Console
from rich.text import Text

from ..com_adapter import MockSolidWorksAdapter, get_adapter
from .local_agent import LocalCADAgent
from .terminal_header import show_header


def read_command(console):
    if not console.is_terminal:
        return input("SolidWorks-CAD > ").strip()
    prompt = Text.assemble((" CAD ", "bold black on cyan"), (" > ", "bold cyan"))
    return console.input(prompt).strip()


def main():
    console = Console()
    adapter = get_adapter()
    agent = LocalCADAgent(adapter)
    session = None

    def execute(command):
        nonlocal session
        result = agent.run(command, session)
        session = result["conversation_id"]
        data = json.dumps(result["data"], ensure_ascii=True, indent=2, default=str) if result.get("data") else None
        if console.is_terminal:
            labels = {"needs_input": ("Question", "yellow"), "planned": ("Plan", "cyan"),
                      "error": ("Error", "red"), "cancelled": ("Cancelled", "yellow"),
                      "success": ("Done", "green")}
            label, color = labels.get(result["status"], (result["status"], "default"))
            console.print(Text(label, style=f"bold {color}"))
            console.print(Text(result["message"]))
            if data:
                console.print_json(data)
            console.print()
        else:
            print(result["message"])
            if data:
                print(data)
        return result["status"]

    show_header(console, isinstance(adapter, MockSolidWorksAdapter))
    if len(sys.argv) > 1:
        status = execute(" ".join(sys.argv[1:]))
        while status == "needs_input":
            try:
                answer = read_command(console)
            except (EOFError, KeyboardInterrupt):
                raise SystemExit(2)
            status = execute(answer)
        raise SystemExit(0 if status in {"success", "planned"} else 1)
    while True:
        try:
            command = read_command(console)
        except (EOFError, KeyboardInterrupt):
            break
        if command.lower() in {"quit", "exit", "q"}:
            break
        if command:
            execute(command)


if __name__ == "__main__":
    main()
