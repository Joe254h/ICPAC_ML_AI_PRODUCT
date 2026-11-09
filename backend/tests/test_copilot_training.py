"""The offline training kit must preserve serving contracts and fail closed."""

import copy
import json
from pathlib import Path

import pytest

from scripts.export_copilot_training_contract import contract
from training.copilot.data_contract import (
    LANGUAGES,
    digest,
    encode_example,
    promotion_gates,
    score_answer,
    summary,
    validate_rows,
)

ROOT = Path(__file__).resolve().parents[2]


def example():
    cfg = contract()
    return {
        "id": "case-en",
        "group_id": "immutable-week-1",
        "language": "en",
        "split": "train",
        "task": "answer",
        "reviewed_by": "Test reviewer",
        "reviewed_at": "2026-11-09",
        "source_ids": ["test-fixture"],
        "license": "test",
        "contract_sha256": digest(cfg),
        "tools": cfg["tools"],
        "messages": [
            {"role": "system", "content": cfg["system_prompts"]["en"]},
            {"role": "user", "content": "The source says 25 mm."},
            {"role": "assistant", "content": "25 mm; MBC."},
        ],
        "checks": {
            "required_tokens": ["25 mm", "MBC"],
            "allowed_numbers": ["25"],
            "forbidden_tokens": ["independent validation"],
            "expected_tool_calls": [],
        },
    }


def test_notebook_is_self_contained_syntax_valid_and_matches_serving():
    notebook = json.loads(
        (ROOT / "training/copilot/kaggle_copilot_multilingual_qlora.ipynb").read_text()
    )
    for index, cell in enumerate(notebook["cells"]):
        if cell["cell_type"] == "code":
            compile("".join(cell["source"]), f"notebook-cell-{index}", "exec")
            assert cell["outputs"] == []
    embedded = {"json": json}
    exec("".join(notebook["cells"][5]["source"]), embedded)
    assert embedded["CONTRACT"] == contract()
    assert embedded["HELPER_SOURCE"] == (ROOT / "training/copilot/data_contract.py").read_text()
    assert LANGUAGES == contract()["languages"]
    assert json.loads((ROOT / "training/copilot/serving_contract.json").read_text()) == contract()


def test_review_and_grouped_translation_leakage_are_enforced():
    row = example()
    assert validate_rows([row], contract())["en"]["train"] == 1
    unreviewed = {**row, "reviewed_by": ""}
    with pytest.raises(ValueError, match="reviewed_by"):
        validate_rows([unreviewed], contract())
    translated = copy.deepcopy(row)
    translated.update(id="case-sw", split="test", language="sw")
    translated["messages"][0]["content"] = contract()["system_prompts"]["sw"]
    with pytest.raises(ValueError, match="leakage"):
        validate_rows([row, translated], contract())
    with pytest.raises(ValueError, match="coverage"):
        validate_rows([row], contract(), {"train": 1, "dev": 1, "test": 1})


def test_numeric_claims_and_tool_call_arguments_are_checked():
    row = example()
    assert score_answer(row, "25 mm; MBC.")["constraint_pass"]
    assert not score_answer(row, "250 mm; MBC.")["constraint_pass"]
    assert not score_answer(row, "25 mm; MBC; independent validation")["constraint_pass"]
    assert not score_answer(row, '25 mm; MBC <tool_call>{"name":"publish"}</tool_call>')["tools"]


def test_loss_masking_rejects_truncated_evidence():
    class Tokenizer:
        def apply_chat_template(self, messages, add_generation_prompt=False, **options):
            text = "".join(f"<{m['role']}>" + m["content"] for m in messages)
            return list(text.encode()) + (list(b"<assistant>") if add_generation_prompt else [])

    row = example()
    encoded = encode_example(row, Tokenizer(), 100_000)
    assert -100 in encoded["labels"] and encoded["labels"][-1] != -100
    with pytest.raises(ValueError, match="never truncate"):
        encode_example(row, Tokenizer(), 10)


def test_missing_or_duplicate_human_review_never_passes_promotion():
    results = [
        {"id": f"{lang}-{n}", "language": lang, "constraint_pass": True}
        for lang in LANGUAGES
        for n in range(20)
    ]
    metrics = summary(results)
    assert metrics["sw"]["constraint_wilson_95"][0] < 0.9  # 20 successes do not establish 99%
    assert not promotion_gates(metrics, metrics, [])["eligible_for_shadow_test"]
    human = [
        {
            "id": r["id"],
            "language": r["language"],
            "reviewed_by": "Native reviewer",
            "factual_correct": "1",
            "language_quality": "5",
        }
        for r in results
    ]
    gate = promotion_gates(metrics, metrics, human)
    assert gate["eligible_for_shadow_test"] and not gate["production_approved"]
    human[0] = human[1]
    assert not promotion_gates(metrics, metrics, human)["eligible_for_shadow_test"]
