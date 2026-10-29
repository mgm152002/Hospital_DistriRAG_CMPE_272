"""PHI screening (CP-3). Structured identifiers by format; names by a local NER model. No network I/O.
Matches are replaced with [REDACTED-<TYPE>]."""
import re
from dataclasses import dataclass
from functools import lru_cache

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    ("SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("MRN", re.compile(r"(?i)\b(?:MRN|medical record (?:number|no\.?))\s*[:#]?\s*\d{4,12}\b")),
    ("DOB", re.compile(r"(?i)\b(?:DOB|D\.O\.B\.|date of birth|born(?: on)?)\s*[:#]?\s*"
                       r"(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2})")),
    ("PHONE", re.compile(r"(?<!\w)(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}\b"
                         r"|(?<![\w+])(?:\+?1\s?)?\d{10}(?!\d)")),  # also 10 digits written without separators
    ("ADDRESS", re.compile(r"\b\d{1,5}\s+(?:[A-Z][a-z]+\s+){1,3}(?:Street|St|Avenue|Ave|Road|Rd|Lane|Ln|Drive|Dr|"
                           r"Boulevard|Blvd|Court|Ct|Terrace|Way|Place|Pl)\b\.?")),
    # Age with a patient-style suffix. "patients over 65 years old" is policy language and is left alone.
    ("AGE", re.compile(r"(?i)\b\d{1,3}\s?(?:y/o|y\.o\.|yo)(?!\w)(?:\s+(?:male|female|man|woman|boy|girl))?"
                       r"|\b\d{1,3}[- ]year[- ]old(?:\s+(?:male|female|man|woman|boy|girl))?(?!\w)")),
    ("LOCATION", re.compile(r"(?i)\b(?:room|rm\.?|bed)\s*#?\s*\d{1,4}[A-Za-z]?\b")),
]
# Names are found by a local language model (spaCy NER and dependency parse, in-process: nothing leaves the server),
# not by word lists. Structured identifiers above are formats, so they stay as patterns.
NAME_FIELD = re.compile(r"(?i:\bname\s*[:=]\s*)([^\s,.;:!?]+(?:[ \t]+[A-Z][^\s,.;:!?]*)?)")  # "name: Ravi Kumar"
NOTICE = {"NAME": "a name", "MRN": "a medical record number", "DOB": "a date of birth", "EMAIL": "an email address",
          "SSN": "a social security number", "PHONE": "a phone number", "ADDRESS": "an address", "AGE": "an age",
          "LOCATION": "a room or bed number"}
PLACEHOLDER = re.compile(r"\[REDACTED-[A-Z]+\]")


@dataclass(frozen=True)
class PhiFinding:
    type: str
    start: int
    end: int


@dataclass(frozen=True)
class PhiResult:
    redacted: str
    findings: list[PhiFinding]

    @property
    def found(self) -> bool:
        return bool(self.findings)

    @property
    def search_text(self) -> str:
        """The redacted text with the placeholders removed, for retrieval: "[REDACTED-NAME]" matches nothing."""
        text = re.sub(r"\s+", " ", PLACEHOLDER.sub(" ", self.redacted)).strip()
        return re.sub(r"\s+([,.;:?!])", r"\1", text)

    @property
    def notice(self) -> str:
        """One plain sentence for the user: what was removed before the question was searched."""
        kinds = list(dict.fromkeys(f.type for f in self.findings))
        if not kinds:
            return ""
        parts = [NOTICE[k] for k in kinds]
        listed = parts[0] if len(parts) == 1 else f"{', '.join(parts[:-1])} and {parts[-1]}"
        return f"Removed {listed} before searching."


@lru_cache(maxsize=1)
def _nlp():
    import spacy  # loaded on first use; a missing model fails loudly rather than letting names through
    return spacy.load("en_core_web_lg")


# Field words that announce a personal value ("address is …"). These are labels, not personal data.
FIELDS = {"address": "ADDRESS", "addr": "ADDRESS", "residence": "ADDRESS", "zip": "ADDRESS", "zipcode": "ADDRESS",
          "postcode": "ADDRESS", "phone": "PHONE", "number": "PHONE", "mobile": "PHONE", "cell": "PHONE",
          "telephone": "PHONE", "contact": "PHONE", "email": "EMAIL", "e-mail": "EMAIL", "dob": "DOB",
          "birthday": "DOB", "birthdate": "DOB", "birth": "DOB", "mrn": "MRN", "ssn": "SSN", "age": "AGE"}
FIELD_COLON = re.compile(r"(?i)\b(address|addr|zip|zipcode|postcode|phone|mobile|cell|telephone|email|e-mail|dob|"
                         r"birthday|birthdate|mrn|ssn)\s*[:=#]\s*([^\s,;!?][^,;!?\n]{0,60}?)(?=[,;!?\n]|\.(?:\s|$)|$)")
RESIDE = {"live", "reside", "stay"}
NAME_HEADS = {"name", "named", "call", "called", "surname", "firstname"}
NAMEABLE = {"PROPN", "NOUN", "X"}
TITLES = {"patient", "pt", "mr", "mrs", "ms", "miss", "dr"}  # words that introduce a person, not personal data


@lru_cache(maxsize=4096)
def _is_person(word: str) -> bool:
    """Ask the NER model whether a word reads as a person's name in a neutral sentence. Used to confirm grammar-based
    candidates ("patient" at the start of a sentence is tagged a proper noun, but it is not a name)."""
    probe = f"Yesterday I spoke with {word[:1].upper()}{word[1:]} about it."
    start = len("Yesterday I spoke with ")
    return any(e.label_ == "PERSON" and e.start_char <= start < e.end_char for e in _nlp()(probe).ents)


def _imperative(token) -> bool:
    """A capitalised first word that the model reads as a verb once lowercased ("Rub all surfaces…") is an
    instruction, not a name; "Manoj fell" still reads as a noun."""
    if not token.is_sent_start:
        return False
    sent = token.sent
    offset = token.idx - sent.start_char
    lowered = sent.text[:offset] + token.text[:1].lower() + sent.text[offset + 1:]
    redo = _nlp()(lowered)
    return any(t.idx == offset and t.pos_ == "VERB" for t in redo)


def _span(token) -> tuple[int, int]:
    """The token with the rest of the name after it ("Aarav" + "Sharma"), stopping at acronyms ("MRN")."""
    doc, end = token.doc, token.i
    while (end + 1 < len(doc) and doc[end + 1].pos_ == "PROPN" and doc[end + 1].ent_type_ in ("", "PERSON")
           and not doc[end + 1].text.isupper()):
        end += 1
    return token.idx, doc[end].idx + len(doc[end].text)


def _names(text: str, after: list[int]) -> list[PhiFinding]:
    doc = _nlp()(text)
    out = []
    for e in doc.ents:
        # An eponym modifying an ordinary noun is a thing, not a person: "Braden Scale score", "Glasgow Coma Scale".
        if e.label_ == "PERSON" and not (e.root.dep_ == "compound" and e.root.head.pos_ == "NOUN"):
            if len(e) == 1 and _imperative(e[0]):
                continue
            words = [t for t in e if not (t.text.isupper() and len(t.text) > 1)]  # "John Smith MRN" -> "John Smith"
            words = words[:next((i for i, t in enumerate(words) if i and t.i != words[i - 1].i + 1), len(words))]
            if words:
                out.append(PhiFinding("NAME", words[0].idx, words[-1].idx + len(words[-1].text)))
    for token in doc:
        head = token.head
        modified = any(c.dep_ in ("det", "poss", "amod", "nummod") for c in token.children)
        # "her name is manoj": the complement of "be" whose subject is "name"; an adjective ("is correct") is not.
        stated = (token.dep_ in ("attr", "oprd", "appos", "npadvmod", "dobj") and token.pos_ in NAMEABLE
                  and not modified and (token.pos_ == "PROPN" or head.lemma_ not in ("call", "called"))
                  and (head.lower_ in NAME_HEADS or head.lemma_ in NAME_HEADS
                       or (head.lemma_ == "be" and any(c.dep_ == "nsubj" and c.lower_ in NAME_HEADS
                                                       for c in head.children))))
        # "Patient Aarav Sharma", "Mr Rao": a proper noun straight after the word for the person, not a compound noun
        # phrase ("Patient Safety reporting").
        titled = (token.pos_ == "PROPN" and token.i > 0 and doc[token.i - 1].lower_ in TITLES
                  and not (token.dep_ in ("compound", "amod", "nmod") and head.pos_ != "PROPN"))
        # "Manoj fell", "Patient Aarav Sharma needs": a proper-noun subject, checked as a whole phrase so that
        # "the Hand Hygiene Policy says" is judged as "Hand Hygiene Policy".
        if (token.pos_ == "PROPN" and token.dep_ == "nsubj" and head.pos_ in ("VERB", "AUX")
                and not token.text.isupper() and not any(c.dep_ in ("det", "amod", "poss") for c in token.children)):
            parts = [c for c in token.children if c.dep_ == "compound" and c.i < token.i] + [token]
            if all(p.pos_ == "PROPN" for p in parts):
                while len(parts) > 1 and parts[0].lower_ in TITLES:
                    parts = parts[1:]
                phrase = " ".join(p.text for p in parts)
                if _is_person(phrase) and not (len(parts) == 1 and _imperative(token)):
                    out.append(PhiFinding("NAME", parts[0].idx, token.idx + len(token.text)))
        # "who is manoj": what answers "who" is a person, unless it is a role ("who is the charge nurse").
        asked = (head.lemma_ == "be" and token.dep_ in ("attr", "nsubj") and token.pos_ in NAMEABLE
                 and token.lower_ != "who" and any(c.lower_ == "who" for c in head.children) and not modified)
        # "bed 4 Smith": a capitalised word straight after a room or bed number.
        located = token.idx in after and token.text[:1].isupper()
        confirmed = (titled or asked or located) and token.ent_type_ in ("", "PERSON") and _is_person(token.text)
        if stated or confirmed:
            out.append(PhiFinding("NAME", *_span(token)))
    out += [PhiFinding("NAME", m.start(1), m.end(1)) for m in NAME_FIELD.finditer(text)]
    out += _stated_fields(doc)
    out += [PhiFinding(FIELDS[m.group(1).lower()], m.start(2), m.end(2)) for m in FIELD_COLON.finditer(text)]
    return out


def _value(token) -> tuple[int, int] | None:
    """The stated value: the token's phrase, unless it reads as a description ("is required", "is not enough")."""
    if token.pos_ in ("ADJ", "VERB", "AUX", "ADV", "PART", "PRON", "DET", "ADP", "SCONJ", "CCONJ") or token.is_stop:
        return None
    if any(c.dep_ in ("det", "poss") for c in token.children):  # "the address is the ward's", "is a requirement"
        return None
    words = [t for t in token.subtree if not t.is_punct]
    return (words[0].idx, words[-1].idx + len(words[-1].text)) if words else None


def _stated_fields(doc) -> list[PhiFinding]:
    """ "my patient's address is 28N", "his phone number was 6693408", "she lives at 28 N": a field the sentence
    says has a value. The field word decides the type; the model's parse decides what the value is."""
    out = []
    for token in doc:
        field = FIELDS.get(token.lower_) or FIELDS.get(token.lemma_.lower())
        if field and token.dep_ in ("nsubj", "nsubjpass") and token.head.lemma_ == "be":
            for value in token.head.children:
                if value.dep_ in ("attr", "acomp", "oprd", "npadvmod", "dobj", "nummod", "appos") and value.i > token.i:
                    found = _value(value)
                    if found:
                        out.append(PhiFinding(field, *found))
        # "lives at 28N", "resides in Fremont"
        if token.dep_ == "pobj" and token.head.lower_ in ("at", "in", "on") and token.head.head.lemma_ in RESIDE:
            found = _value(token)
            if found:
                out.append(PhiFinding("ADDRESS", *found))
    return out


def _next_word(text: str, end: int) -> int | None:
    match = re.compile(r",?\s+(?=\w)").match(text, end)
    return match.end() if match else None


def screen(text: str) -> PhiResult:
    findings = [PhiFinding(kind, m.start(), m.end()) for kind, pattern in PATTERNS for m in pattern.finditer(text)]
    # Words right after a room or bed number are name candidates ("bed 4 Smith").
    after = [_next_word(text, f.end) for f in findings if f.type == "LOCATION"]
    findings += _names(text, [i for i in after if i is not None])
    findings.sort(key=lambda f: (f.start, -f.end))
    kept: list[PhiFinding] = []
    for f in findings:
        if kept and f.start < kept[-1].end:
            continue
        kept.append(f)
    redacted = text
    for f in reversed(kept):
        redacted = redacted[: f.start] + f"[REDACTED-{f.type}]" + redacted[f.end:]
    return PhiResult(redacted, kept)
