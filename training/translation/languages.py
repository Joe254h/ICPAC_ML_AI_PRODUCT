"""Target languages of the ICPAC Week-2 bulletin and where their training data comes from.

Codes are the FLORES-200 / NLLB codes the models use. Sources are Hugging Face datasets
checked on 25 and 29 October 2026 (see docs/language_training.md for licences): SMOL
sentence and document translations and the GATITOS word and phrase lists (CC-BY-4.0), the
NLLB-v1 mined pairs mirrored per language (sorted by similarity, best first), Sunbird's
SALT sentences for Uganda's languages (CC-BY-SA-4.0, gated: accept its terms first) and
NTREX-128 news sentences for testing (CC-BY-SA-4.0).

A language NLLB-200 does not know (Afar, Tigre, Sudanese Arabic, Acholi, Alur, Rukiga,
Lugbara, Runyankole, Ateso) gets a new language code in the tokenizer, started from the
code of a related language it does know (``init_from``); it needs more data and a
speaker's review before its translations are trusted.
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
    # Dinka and Nuer: mined data is mostly religious text; it is left out unless asked for.
    machine_translation: bool = True
    smol_doc: str | None = None  # google/smol document translations, e.g. "smoldoc__en_sw"
    gatitos: str | None = None  # google/smol word and phrase list, e.g. "gatitos__en_luo"
    salt: str | None = None  # the language's column prefix in Sunbird/salt (text-all)
    # For a code NLLB-200 lacks: the known code its new token starts from.
    init_from: str | None = None


LANGUAGES = {
    "sw": Language(
        "Swahili",
        "swh_Latn",
        "smolsent__en_sw",
        "michsethowusu/english-swahili_sentence-pairs",
        "swa_Latn",
        ("Kenya", "Tanzania", "Uganda", "Rwanda", "Burundi"),
        smol_doc="smoldoc__en_sw",
        salt="swa",
    ),
    "am": Language(
        "Amharic",
        "amh_Ethi",
        "smolsent__en_am",
        "michsethowusu/amharic-english_sentence-pairs",
        "amh_Ethi",
        ("Ethiopia",),
        smol_doc="smoldoc__en_am",
    ),
    "so": Language(
        "Somali",
        "som_Latn",
        "smolsent__en_so",
        "michsethowusu/english-somali_sentence-pairs",
        "som_Latn",
        ("Somalia", "Djibouti", "Ethiopia", "Kenya"),
        smol_doc="smoldoc__en_so",
    ),
    "om": Language(
        "Oromo",
        "gaz_Latn",
        "smolsent__en_om",
        "michsethowusu/english-oromo_sentence-pairs",
        None,  # NTREX's Oromo is in Ethiopic script; Oromo is written in Latin (Qubee)
        ("Ethiopia", "Kenya"),
        smol_doc="smoldoc__en_om",
        gatitos="gatitos__en_om",
    ),
    "ti": Language(
        "Tigrinya",
        "tir_Ethi",
        "smolsent__en_ti",
        "michsethowusu/english-tigrinya_sentence-pairs",
        "tir_Ethi",
        ("Eritrea", "Ethiopia"),
        smol_doc="smoldoc__en_ti",
        gatitos="gatitos__en_ti",
    ),
    "rw": Language(
        "Kinyarwanda",
        "kin_Latn",
        "smolsent__en_rw",
        None,
        "kin_Latn",
        ("Rwanda",),
        smol_doc="smoldoc__en_rw",
    ),
    "rn": Language(
        "Kirundi",
        "run_Latn",
        "smolsent__en_rn",
        "michsethowusu/english-rundi_sentence-pairs",
        None,
        ("Burundi",),
        smol_doc="smoldoc__en_rn",
        gatitos="gatitos__en_rn",
    ),
    "lg": Language(
        "Luganda",
        "lug_Latn",
        "smolsent__en_lg",
        "michsethowusu/english-ganda_sentence-pairs",
        None,
        ("Uganda",),
        smol_doc="smoldoc__en_lg",
        gatitos="gatitos__en_lg",
        salt="lug",
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
    "din": Language(
        "Dinka",
        "dik_Latn",
        "smolsent__en_din",
        None,
        None,
        ("South Sudan",),
        False,
        smol_doc="smoldoc__en_din",
        gatitos="gatitos__en_din",
    ),
    "nus": Language(
        "Nuer",
        "nus_Latn",
        None,
        "michsethowusu/english-nuer_sentence-pairs",
        None,
        ("South Sudan", "Ethiopia"),
        False,
        gatitos="gatitos__en_nus",
    ),
    # Further languages of the member states with public data (checked 29 October 2026).
    "luo": Language(
        "Dholuo",
        "luo_Latn",
        "smolsent__en_luo",
        None,
        None,
        ("Kenya", "Tanzania"),
        smol_doc="smoldoc__en_luo",
        gatitos="gatitos__en_luo",
    ),
    "ki": Language(
        "Kikuyu",
        "kik_Latn",
        "smolsent__en_ki",
        "michsethowusu/english-kikuyu_sentence-pairs",
        None,
        ("Kenya",),
        smol_doc="smoldoc__en_ki",
        gatitos="gatitos__en_ki",
    ),
    "kam": Language(
        "Kamba",
        "kam_Latn",
        None,
        "michsethowusu/english-kamba_sentence-pairs",
        None,
        ("Kenya",),
    ),
    "aa": Language(
        "Afar",
        "aar_Latn",
        "smolsent__en_aa",
        None,
        None,
        ("Djibouti", "Ethiopia", "Eritrea"),
        smol_doc="smoldoc__en_aa",
        gatitos="gatitos__en_aa",
        init_from="som_Latn",  # both Lowland East Cushitic
    ),
    "tig": Language(
        "Tigre",
        "tig_Ethi",
        "smolsent__en_tig",
        None,
        None,
        ("Eritrea", "Sudan"),
        smol_doc="smoldoc__en_tig",
        gatitos="gatitos__en_tig",
        init_from="tir_Ethi",  # both Ethiopic-script Semitic
    ),
    "apd": Language(
        "Sudanese Arabic",
        "apd_Arab",
        "smolsent__en_apd",
        None,
        None,
        ("Sudan",),
        smol_doc="smoldoc__en_apd",
        gatitos="gatitos__en_apd",
        init_from="arb_Arab",
    ),
    "ach": Language(
        "Acholi",
        "ach_Latn",
        "smolsent__en_ach",
        None,
        None,
        ("Uganda", "South Sudan"),
        smol_doc="smoldoc__en_ach",
        gatitos="gatitos__en_ach",
        salt="ach",
        init_from="luo_Latn",  # both Western Nilotic (Luo group)
    ),
    "alz": Language(
        "Alur",
        "alz_Latn",
        "smolsent__en_alz",
        None,
        None,
        ("Uganda",),
        smol_doc="smoldoc__en_alz",
        gatitos="gatitos__en_alz",
        init_from="luo_Latn",
    ),
    "cgg": Language(
        "Rukiga",
        "cgg_Latn",
        "smolsent__en_cgg",
        None,
        None,
        ("Uganda",),
        smol_doc="smoldoc__en_cgg",
        gatitos="gatitos__en_cgg",
        init_from="lug_Latn",  # Great Lakes Bantu
    ),
    "lgg": Language(
        "Lugbara", "lgg_Latn", None, None, None, ("Uganda",), salt="lgg", init_from="lug_Latn"
    ),
    "nyn": Language(
        "Runyankole", "nyn_Latn", None, None, None, ("Uganda",), salt="nyn", init_from="lug_Latn"
    ),
    "teo": Language(
        "Ateso", "teo_Latn", None, None, None, ("Uganda", "Kenya"), salt="teo", init_from="luo_Latn"
    ),
}

#: The languages each phase trains (docs/language_training.md).
PHASES = {
    "1": ["sw", "am", "so", "om"],
    "2": ["ti", "rw", "rn"],
    "3": ["lg", "luo", "ki", "kam"],
    "4": ["aa", "tig", "apd", "ach", "alz", "cgg", "lgg", "nyn", "teo", "din", "nus"],
}
