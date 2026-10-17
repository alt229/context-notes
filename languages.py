"""
languages.py - language codes and names shared by the other scripts.

Subtitle files and video tracks label languages in several ways ("fr", "fre", "fra", "French",
"fr-CA"); everything here is reduced to a two-letter code such as "fr".
"""
import re

# two-letter code -> (English name, other labels seen on subtitle tracks and file names)
LANGUAGES = {
    "en": ("English", {"eng", "english"}),
    "fr": ("French", {"fre", "fra", "french", "francais", "français", "vf", "vff", "vfq"}),
    "de": ("German", {"ger", "deu", "german", "deutsch"}),
    "es": ("Spanish", {"spa", "spanish", "espanol", "español", "castellano", "esp"}),
    "it": ("Italian", {"ita", "italian", "italiano"}),
    "pt": ("Portuguese", {"por", "portuguese", "portugues", "português"}),
    "nl": ("Dutch", {"dut", "nld", "dutch", "nederlands"}),
    "sv": ("Swedish", {"swe", "swedish", "svenska"}),
    "da": ("Danish", {"dan", "danish", "dansk"}),
    "no": ("Norwegian", {"nor", "nob", "nno", "norwegian", "norsk"}),
    "pl": ("Polish", {"pol", "polish", "polski"}),
    "ru": ("Russian", {"rus", "russian"}),
    "ja": ("Japanese", {"jpn", "japanese"}),
    "ko": ("Korean", {"kor", "korean"}),
    "zh": ("Chinese", {"chi", "zho", "chinese", "mandarin", "cantonese"}),
}
_ALIASES = {alias: code for code, (_, aliases) in LANGUAGES.items() for alias in aliases | {code}}


def code(label):
    """'fre', 'French', 'fr-CA', 'es_419' -> 'fr' / 'es'. Unknown labels come back lower-cased; None/'und' -> None."""
    if not label:
        return None
    s = str(label).strip().lower()
    if s in ("und", "unk", "unknown", "mis", "zxx", ""):
        return None
    if s in _ALIASES:
        return _ALIASES[s]
    base = re.split(r"[-_ ]", s)[0]
    return _ALIASES.get(base, s)


def name(label):
    """'fr' -> 'French'. Unknown codes are returned as given."""
    c = code(label)
    return LANGUAGES[c][0] if c in LANGUAGES else str(label)


def same(a, b):
    return a is not None and b is not None and code(a) == code(b)


def from_filename(path_name, stem):
    """Language tag in a subtitle file name next to a video, e.g. 'Film.fr.srt' or 'Film.French.forced.srt'
    for the video stem 'Film'. Returns (code or None, extra tags such as {'forced', 'sdh'})."""
    rest = path_name[len(stem):] if path_name.startswith(stem) else path_name
    parts = [p.lower() for p in rest.split(".") if p]
    if parts and parts[-1] == "srt":
        parts = parts[:-1]
    lang, tags = None, set()
    for p in parts:
        if p in ("forced", "sdh", "cc", "hi", "default", "full"):
            tags.add("sdh" if p in ("cc", "hi") else p)
        elif lang is None and code(p) in LANGUAGES:
            lang = code(p)
        else:
            tags.add(p)
    return lang, tags


# A few very common words per language, to tell which language a subtitle file is in.
_COMMON = {
    "en": "the you and to is it that of what in me this have was not know for i'm don't on be with your are",
    "fr": "je de est pas le la vous et tu les un une que ce il qui ne des en c'est on mais pour moi",
    "de": "ich die und der nicht das du ist sie es ein zu was den mit mir wir ja auf eine sich",
    "es": "que de no la el es y en lo un por qué me se los las una con para te está mi",
    "it": "che non di il la è e un per mi ti sono una lo ma cosa ho ci questo bene",
    "pt": "que não de o a é e um para eu se com uma os do da você isso me está",
    "nl": "de het een ik je niet en is dat van wat we hij zijn er maar op met",
}
_COMMON = {k: set(v.split()) for k, v in _COMMON.items()}


def guess(text):
    """Best guess at the language of some subtitle text ('en', 'fr', ...), or None if it's too short or unclear."""
    words = re.findall(r"[^\W\d_]+(?:'[^\W\d_]+)?", text.lower())
    if len(words) < 40:
        return None
    scores = {lang: sum(w in common for w in words) / len(words) for lang, common in _COMMON.items()}
    best = max(scores, key=scores.get)
    second = sorted(scores.values())[-2]
    return best if scores[best] >= 0.15 and scores[best] >= 1.5 * second else None


REGISTER = {
    "fr": "tu vs vous", "de": "du vs Sie", "es": "tú vs usted (and vos)", "it": "tu vs Lei", "pt": "tu/você vs o senhor",
    "nl": "jij vs u", "sv": "du vs ni", "pl": "ty vs pan/pani", "ru": "ты vs вы", "ja": "plain vs polite (keigo) forms",
    "ko": "banmal vs jondaetmal",
}
