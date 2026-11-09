"""CPU-only contracts and checks for the Kaggle Copilot instruction-tuning notebook.

This trains language/tool behaviour, never the scientific rainfall model. Dataset
authors supply reviewed answers and immutable evidence; no chat logs are harvested.
"""

import hashlib
import json
import math
import re
import unicodedata
from collections import Counter
from pathlib import Path

LANGUAGES = {
    "en": "English",
    "sw": "Kiswahili",
    "am": "Amharic",
    "so": "Somali",
    "ar": "Arabic",
    "fr": "French",
    "ti": "Tigrinya",
    "om": "Afaan Oromo",
    "rw": "Kinyarwanda",
    "rn": "Kirundi",
    "lg": "Luganda",
}
TASKS = {"answer", "tool_call", "translation", "refusal"}


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def load_rows(path: Path, contract: dict, minimums: dict | None = None) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    validate_rows(rows, contract, minimums)
    return rows


def validate_rows(rows: list[dict], contract: dict, minimums: dict | None = None) -> dict:
    if not rows:
        raise ValueError("No reviewed Copilot examples supplied")
    groups: dict[str, str] = {}
    duplicates: dict[str, str] = {}
    identifiers: set[str] = set()
    counts: Counter = Counter()
    tasks: Counter = Counter()
    for row in rows:
        for name in ("id", "group_id", "reviewed_by", "reviewed_at", "license", "source_ids"):
            if not row.get(name):
                raise ValueError(f"Missing {name}; synthetic/unreviewed drafts cannot train")
        if row["id"] in identifiers:
            raise ValueError("Duplicate example id")
        identifiers.add(row["id"])
        lang, split, task = row.get("language"), row.get("split"), row.get("task")
        if lang not in LANGUAGES or split not in {"train", "dev", "test"} or task not in TASKS:
            raise ValueError("Unknown language, split or task")
        if row.get("contract_sha256") != digest(contract):
            raise ValueError("Training and serving prompt/tool contracts differ")
        messages = row.get("messages", [])
        if (
            len(messages) < 3
            or messages[0] != {"role": "system", "content": contract["system_prompts"][lang]}
            or messages[-1].get("role") != "assistant"
        ):
            raise ValueError(
                "Use the serving system prompt and finish with the target assistant turn"
            )
        target = messages[-1]
        if not target.get("content") and not target.get("tool_calls"):
            raise ValueError("Empty supervised answer")
        allowed_tools = {tool["function"]["name"]: tool for tool in contract["tools"]}
        selected_tools = row.get("tools", [])
        if not isinstance(selected_tools, list) or any(
            tool not in allowed_tools.values() for tool in selected_tools
        ):
            raise ValueError("Tools must be an unchanged subset of the serving schemas")
        selected_names = {tool["function"]["name"] for tool in selected_tools}
        if len(selected_names) != len(selected_tools):
            raise ValueError("Duplicate tool schemas")
        for message in messages:
            for call in message.get("tool_calls", []):
                if call.get("function", {}).get("name") not in selected_names:
                    raise ValueError("A labelled tool call is missing its serving schema")
        if task == "tool_call" and not target.get("tool_calls"):
            raise ValueError("A tool-call target needs native tool_calls")
        if not isinstance(row.get("checks"), dict):
            raise ValueError("Each example needs explicit evaluation checks")
        if split != "train" and not any(row["checks"].values()):
            raise ValueError("Dev/test cases need a nonempty objective rubric")
        group, fingerprint = row["group_id"], digest(messages[1:])
        for held, key in ((groups, group), (duplicates, fingerprint)):
            if key in held and held[key] != split:
                raise ValueError("Source/translation leakage across train, dev and test")
            held[key] = split
        counts[lang, split] += 1
        tasks[lang, split, task] += 1
    if minimums:
        missing = [
            f"{lang}/{split}: {counts[lang, split]} < {minimum}"
            for lang in LANGUAGES
            for split, minimum in minimums.items()
            if counts[lang, split] < minimum
        ]
        missing += [
            f"{lang}/{task}: missing training task"
            for lang in LANGUAGES
            for task in TASKS
            if not tasks[lang, "train", task]
        ]
        if missing:
            raise ValueError("Incomplete language coverage: " + "; ".join(missing))
    return {
        lang: {split: counts[lang, split] for split in ("train", "dev", "test")}
        for lang in LANGUAGES
    }


def encode_example(row: dict, tokenizer, max_length: int) -> dict:
    options = {"tools": row["tools"], "tokenize": True}
    prefix = tokenizer.apply_chat_template(
        row["messages"][:-1], add_generation_prompt=True, **options
    )
    full = tokenizer.apply_chat_template(row["messages"], add_generation_prompt=False, **options)
    if full[: len(prefix)] != prefix:
        raise ValueError("Chat template changed: assistant-only loss masking would be incorrect")
    if len(full) > max_length:
        raise ValueError(
            f"{row['id']}: evidence exceeds context; shorten the case, never truncate it"
        )
    labels = [-100] * len(prefix) + full[len(prefix) :]
    if not any(token != -100 for token in labels):
        raise ValueError("No supervised tokens")
    return {"input_ids": full, "attention_mask": [1] * len(full), "labels": labels}


def numeric_tokens(text: str) -> set[str]:
    normal = "".join(str(unicodedata.decimal(char)) if char.isdecimal() else char for char in text)
    return set(re.findall(r"\d+(?:[.,]\d+)?", normal))


def tool_calls(text: str) -> list[dict]:
    calls = []
    for value in re.findall(r"<tool_call>\s*(.*?)\s*</tool_call>", text, flags=re.S):
        parsed = json.loads(value)
        calls.append({"name": parsed["name"], "arguments": parsed["arguments"]})
    return calls


def score_answer(row: dict, text: str) -> dict:
    checks = row["checks"]
    lower = text.casefold()
    required = all(str(token).casefold() in lower for token in checks.get("required_tokens", []))
    forbidden = not any(
        str(token).casefold() in lower for token in checks.get("forbidden_tokens", [])
    )
    numbers = numeric_tokens(text) <= set(map(str, checks.get("allowed_numbers", [])))
    try:
        parsed = tool_calls(text)
        tools = parsed == checks.get("expected_tool_calls", [])
    except (ValueError, KeyError, TypeError):
        tools = False
    # These are mechanical constraints, not a claim of semantic/language accuracy.
    return {
        "required": required,
        "forbidden": forbidden,
        "numbers": numbers,
        "tools": tools,
        "constraint_pass": required and forbidden and numbers and tools,
    }


def summary(results: list[dict]) -> dict:
    out = {}
    for language in LANGUAGES:
        held = [row for row in results if row["language"] == language]
        n = len(held)
        p = sum(row["constraint_pass"] for row in held) / n if n else 0
        # Wilson interval: a perfect small test set does not establish near-perfect accuracy.
        z = 1.96
        center = (p + z * z / (2 * n)) / (1 + z * z / n) if n else 0
        radius = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n) if n else 0
        out[language] = {
            "cases": n,
            "case_ids": sorted(row["id"] for row in held),
            "prediction_sha256": {row["id"]: digest(row.get("prediction", "")) for row in held},
            "constraint_pass_rate": p,
            "constraint_wilson_95": [max(0, center - radius), min(1, center + radius)],
        }
    return out


def promotion_gates(baseline: dict, candidate: dict, human_rows: list[dict]) -> dict:
    failures = []
    for language in LANGUAGES:
        base, tuned = baseline.get(language, {}), candidate.get(language, {})
        if tuned.get("cases", 0) < 20 or tuned.get("constraint_pass_rate", 0) < 0.98:
            failures.append(f"{language}: insufficient cases or failed mechanical constraints")
        if tuned.get("constraint_pass_rate", 0) < base.get("constraint_pass_rate", 0):
            failures.append(f"{language}: regression from baseline")
        if tuned.get("case_ids") != base.get("case_ids"):
            failures.append(f"{language}: baseline and candidate cases differ")
        reviewed = [r for r in human_rows if r.get("language") == language]
        if (
            len(reviewed) != tuned.get("cases", 0)
            or not reviewed
            or sorted(r.get("id", "") for r in reviewed) != tuned.get("case_ids")
        ):
            failures.append(f"{language}: native-speaker review incomplete")
        for row in reviewed:
            if (
                not row.get("reviewed_by")
                or row.get("factual_correct") != "1"
                or row.get("language_quality") not in {"4", "5"}
                or digest(row.get("prediction", ""))
                != tuned.get("prediction_sha256", {}).get(row.get("id"))
            ):
                failures.append(f"{language}: human review did not pass")
                break
    return {
        "eligible_for_shadow_test": not failures,
        "failures": failures,
        "production_approved": False,
    }
