"""Bulletin wording that reads as machine-written is caught; ICPAC's plain sentences pass."""

from chatbot.tone import tone_problems
from scripts.check_bulletin_tone import main, report

PLAIN = (
    "The short rains are most active in the south of the region. Moderate rainfall (50-200 "
    "mm) is expected over central to southern parts of Kenya and Burundi. Farmers in these "
    "areas can plan planting."
)


def test_plain_bulletin_sentences_pass():
    assert tone_problems(PLAIN) == []
    assert (
        tone_problems("Light rainfall (less than 50 mm) expected over most parts of Kenya.") == []
    )


def test_essay_connectives_weather_cliches_and_corporate_words_are_caught():
    for text, found in [
        ("Moreover, rain is expected over Kenya.", "Moreover"),
        ("Overall, the week is dry.", "Overall"),
        ("It should be noted that rain eases.", "It should be noted"),
        ("Residents should remain vigilant.", "remain vigilant"),
        ("Farmers should brace for rain.", "brace for"),
        ("The region is poised to see rain.", "poised to"),
        ("A robust forecast for the week.", "robust"),
        ("Stakeholders can leverage the forecast.", "leverage"),
    ]:
        problems = tone_problems(text)
        assert any(found in p for p in problems), (text, problems)


def test_three_sentences_opening_alike_are_caught():
    problems = tone_problems("Rainfall is likely. Rainfall will ease. Rainfall may return.")
    assert problems == ['three sentences in a row open with "rainfall"']
    assert tone_problems("The rain eases. The coast stays dry. The highlands are wetter.") == []


def test_the_checker_keeps_every_figure(tmp_path, capsys):
    original = tmp_path / "original.txt"
    original.write_text("Moderate rainfall (50-200 mm) over Kenya; 12.6 mm on average.")
    good = tmp_path / "good.txt"
    good.write_text("Kenya averages 12.6 mm, with moderate rainfall (50-200 mm) in places.")
    assert main([str(good), "--against", str(original)]) == 0
    assert "OK" in capsys.readouterr().out
    changed = "Kenya averages 13 mm, with moderate rainfall (50-200 mm) in places — moreover."
    found = report(changed, original.read_text())
    assert "figures dropped: 12.6" in found and "figures added: 13" in found
    assert any("dash" in line for line in found)


def test_humanizer_skill_matches_the_service_rules():
    """The .claude skill and the writer's prompt show the same example, and every pattern
    the skill tells people to remove is one the service's checker flags."""
    import re
    from pathlib import Path

    from chatbot import tone

    skill = Path(__file__).resolve().parents[2] / ".claude/skills/bulletin-humanizer/SKILL.md"
    text = skill.read_text(encoding="utf-8")
    quoted = " ".join(line[1:].strip() for line in text.splitlines() if line.startswith(">"))
    for paragraph in (tone.EXAMPLE_COMPUTED, tone.EXAMPLE_AI, tone.EXAMPLE_HUMAN):
        assert paragraph in quoted
    assert tone.tone_problems(tone.EXAMPLE_AI)
    assert tone.tone_problems(tone.EXAMPLE_HUMAN) == []
    for phrase in (
        "crucial",
        "pivotal",
        "a testament",
        "underscores",
        "delve",
        "tapestry",
        "intricate",
        "interplay",
        "showcase",
        "foster",
        "garner",
        "robust",
        "seamless",
        "leverage",
        "Moreover,",
        "Furthermore,",
        "Overall,",
        "In summary,",
        "In conclusion,",
        "It should be noted",
        "Notably,",
        "In light of",
        "remain vigilant",
        "brace for",
        "a mix of",
        "Mother Nature",
        "stakeholders",
        "experts say",
        "observers note",
        "I hope this helps",
        "let me know",
    ):
        assert phrase.lower() in text.lower(), phrase
        sentence = phrase if phrase[0].isupper() else f"Rain is expected and {phrase} it."
        assert tone.tone_problems(sentence), phrase
    assert re.search(r"additionally", text, re.I) and tone.tone_problems("Additionally, rain.")
