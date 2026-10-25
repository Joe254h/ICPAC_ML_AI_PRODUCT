"""Target languages of the ICPAC Week-2 bulletin and where their training data comes from.

Codes are the FLORES-200 / NLLB codes the models use. Sources are Hugging Face datasets
checked on 25 October 2026 (see docs/language_training.md for licences): SMOL sentence
translations (CC-BY-4.0), the NLLB-v1 mined pairs mirrored per language (sorted by
similarity, best first) and NTREX-128 news sentences for testing (CC-BY-SA-4.0).
"""

from dataclasses import dataclass, field

SOURCE = "eng_Latn"
# MADLAD-400 marks the target language with a token in front of the source text.
MADLAD_TAGS = {
    "swh_Latn": "<2sw>",
    "amh_Ethi": "<2am>",
    "som_Latn": "<2so>",
    "gaz_Latn": "<2om>",
    "tir_Ethi": "<2ti>",
    "kin_Latn": "<2rw>",
    "run_Latn": "<2rn>",
    "lug_Latn": "<2lg>",
    "arb_Arab": "<2ar>",
    "fra_Latn": "<2fr>",
    "dik_Latn": "<2din>",
}


@dataclass(frozen=True)
class Language:
    name: str
    code: str  # NLLB / FLORES-200 code
    smol: str | None = None  # google/smol config, e.g. "smolsent__en_sw"
    mined: str | None = None  # NLLB-v1 mined pairs mirror (columns: similarity, English, <name>)
    ntrex: str | None = None  # masakhane/ntrex_african config (test only)
    countries: tuple[str, ...] = field(default_factory=tuple)
    # Dinka and Nuer: mined data is mostly religious text; use human templates only.
    machine_translation: bool = True


LANGUAGES = {
    "sw": Language(
        "Swahili",
        "swh_Latn",
        "smolsent__en_sw",
        "michsethowusu/english-swahili_sentence-pairs",
        "swa_Latn",
        ("Kenya", "Tanzania", "Uganda", "Rwanda", "Burundi"),
    ),
    "am": Language(
        "Amharic",
        "amh_Ethi",
        "smolsent__en_am",
        "michsethowusu/amharic-english_sentence-pairs",
        "amh_Ethi",
        ("Ethiopia",),
    ),
    "so": Language(
        "Somali",
        "som_Latn",
        "smolsent__en_so",
        "michsethowusu/english-somali_sentence-pairs",
        "som_Latn",
        ("Somalia", "Djibouti", "Ethiopia", "Kenya"),
    ),
    "om": Language(
        "Oromo",
        "gaz_Latn",
        "smolsent__en_om",
        "michsethowusu/english-oromo_sentence-pairs",
        None,  # NTREX's Oromo is in Ethiopic script; Oromo is written in Latin (Qubee)
        ("Ethiopia", "Kenya"),
    ),
    "ti": Language(
        "Tigrinya",
        "tir_Ethi",
        "smolsent__en_ti",
        "michsethowusu/english-tigrinya_sentence-pairs",
        "tir_Ethi",
        ("Eritrea", "Ethiopia"),
    ),
    "rw": Language("Kinyarwanda", "kin_Latn", "smolsent__en_rw", None, "kin_Latn", ("Rwanda",)),
    "rn": Language(
        "Kirundi",
        "run_Latn",
        "smolsent__en_rn",
        "michsethowusu/english-rundi_sentence-pairs",
        None,
        ("Burundi",),
    ),
    "lg": Language(
        "Luganda",
        "lug_Latn",
        "smolsent__en_lg",
        "michsethowusu/english-ganda_sentence-pairs",
        None,
        ("Uganda",),
    ),
    "ar": Language(
        "Arabic",
        "arb_Arab",
        None,
        None,
        "arb_Arab",
        ("Sudan", "Djibouti", "Somalia"),
    ),
    "fr": Language("French", "fra_Latn", None, None, "fra_Latn", ("Djibouti", "Burundi", "Rwanda")),
    "din": Language("Dinka", "dik_Latn", "smolsent__en_din", None, None, ("South Sudan",), False),
    "nus": Language("Nuer", "nus_Latn", None, None, None, ("South Sudan", "Ethiopia"), False),
}
