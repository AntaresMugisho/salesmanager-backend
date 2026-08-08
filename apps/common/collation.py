"""A sort key that orders French text the way `Intl.Collator("fr-FR")` does.

Python and SQLite both compare code points, which puts every accented word at
the end of the alphabet: `Fruits | Oignons | Zeste | Épicerie | Œufs`. The
frontend sorts with `localeCompare(name, "fr-FR")`, so a report that sorted by
code point would disagree with the screen it is printed from.

Imports nothing from Django: `apps.catalogue` feeds this into a model field and
`apps.reports` into a pure builder, and neither should have to care.

Known limit: names whose keys are equal — `Cafe`/`Café`, `eau`/`Eau` — tie
here, where ICU would break the tie at a tertiary level (unaccented before
accented, plain before ligature, lowercase before uppercase). Callers append a
stable secondary key, usually the row's id, so the order is deterministic.
Reproducing ICU's tertiary weights was considered and rejected: it is a
hand-rolled collation implementation with more surface to get wrong than the
defect it fixes.
"""

import unicodedata

#: Expanded before normalisation because Unicode assigns these no compatibility
#: decomposition — `unicodedata.normalize("NFKD", "Œ") == "Œ"` — so NFKD alone
#: would still sort `Œufs` after `Zeste`.
LIGATURES = {
    "Œ": "OE",
    "œ": "oe",
    "Æ": "AE",
    "æ": "ae",
    "ß": "ss",
    "ﬁ": "fi",
    "ﬂ": "fl",
}


def collation_key(name: str) -> str:
    """`name` reduced to base letters, lowercased.

    Note that the key can be *longer* than its input: every ligature expands to
    two characters. A database column storing it needs twice the source field's
    `max_length`.
    """
    expanded = "".join(LIGATURES.get(char, char) for char in name)
    decomposed = unicodedata.normalize("NFKD", expanded)
    stripped = "".join(char for char in decomposed if not unicodedata.combining(char))
    return stripped.casefold()
