"""Freeze the current Copilot prompts/tool schemas for offline training; no API calls."""

import argparse
import json
from pathlib import Path

from chatbot.agent import LANGUAGES, function_tool, instructions, tools


def contract() -> dict:
    return {
        "version": 1,
        "languages": LANGUAGES,
        "system_prompts": {code: instructions(code) for code in LANGUAGES},
        "tools": [function_tool(tool) for tool in tools()],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    path = parser.parse_args().output
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(contract(), ensure_ascii=False, indent=2) + "\n")
    print(f"Saved prompt/tool contract to {path}")
