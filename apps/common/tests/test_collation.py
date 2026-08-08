"""The French sort key.

`localeCompare(name, "fr-FR")` is a real ICU implementation, so the Node
comparison in this module is authoritative rather than a transcription — unlike
the report cross-checks, which re-implement the frontend's logic in inline JS.
"""

import json
import shutil
import subprocess

import pytest

from apps.common import collation
from apps.common.collation import collation_key
from apps.common.tests.purity import django_imports_of

# Accents, ligatures, case, digits and a leading accented lowercase letter.
CORPUS = [
    "Épicerie", "Fruits", "Boissons", "Œufs", "Oignons", "Zeste", "eau", "Eau",
    "Ananas", "à la carte", "Bœuf", "Boeuf", "Café", "Cafe", "Chocolat",
    "Crème", "Cereales", "Céréales", "Ail", "Aïoli", "Huile", "Hôtel", "Île",
    "Igname", "Maïs", "Mais", "Noix", "Nöel", "Œillet", "Ocre", "Pâtes",
    "Pates", "Patte", "Poisson", "Riz", "Sucre", "Sûr", "Sur", "Thé", "The",
    "Ugni", "Vin", "Vinaigre", "Whisky", "Xérès", "Yaourt", "Zébu", "Zebu",
    "Æther", "Aether", "Ça va", "Cava", "0 sucre", "10 kg", "2 kg", "élan",
    "Elan", "ÉLAN", "œuf", "oeuf",
]


class TestTheKey:
    def test_accents_are_stripped(self):
        assert collation_key("Épicerie") == "epicerie"

    def test_case_is_folded(self):
        assert collation_key("ÉLAN") == collation_key("élan") == "elan"

    def test_the_oe_ligature_expands(self):
        # NFKD alone leaves Œ untouched, which would sort Œufs after Zeste.
        assert collation_key("Œufs") == "oeufs"
        assert collation_key("bœuf") == "boeuf"

    def test_the_ae_ligature_expands(self):
        assert collation_key("Æther") == "aether"

    def test_the_sharp_s_expands(self):
        assert collation_key("Straße") == "strasse"

    def test_cedilla_and_grave_come_from_nfkd(self):
        assert collation_key("Ça") == "ca"
        assert collation_key("où") == "ou"

    def test_digits_and_spaces_are_untouched(self):
        assert collation_key("10 kg") == "10 kg"

    def test_an_empty_name_is_an_empty_key(self):
        assert collation_key("") == ""

    def test_epicerie_now_sorts_before_fruits(self):
        # The defect this module exists to prevent.
        assert sorted(["Fruits", "Épicerie"], key=collation_key) == [
            "Épicerie",
            "Fruits",
        ]

    def test_oeufs_sorts_between_fruits_and_oignons(self):
        got = sorted(["Oignons", "Œufs", "Fruits"], key=collation_key)
        assert got == ["Fruits", "Œufs", "Oignons"]


class TestPurity:
    def test_the_module_does_not_import_django(self):
        assert django_imports_of(collation) == []


NODE = shutil.which("node")

JS = """
const names = JSON.parse(process.argv[1]);
process.stdout.write(JSON.stringify(
  [...names].sort((a, b) => a.localeCompare(b, "fr-FR"))
));
"""


@pytest.mark.skipif(NODE is None, reason="node is not on PATH")
class TestAgainstIcu:
    """Diffed against the same API the frontend calls.

    Compared as a sequence of *keys*, not of names: names that collate equally
    (`Cafe`/`Café`, `eau`/`Eau`) tie, and ICU breaks those ties at a tertiary
    level this key deliberately does not reproduce. If the key sequences match,
    every difference is a tie — which is the documented limit.
    """

    def js_sorted(self, names: list[str]) -> list[str]:
        result = subprocess.run(
            [NODE, "-e", JS, json.dumps(names)],
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(result.stdout)

    def test_the_key_sequence_matches_fr_fr(self):
        ours = [collation_key(name) for name in sorted(CORPUS, key=collation_key)]
        theirs = [collation_key(name) for name in self.js_sorted(CORPUS)]
        assert ours == theirs

    def test_every_tie_is_only_a_tie(self):
        # Names that differ after keying must be ordered identically; only
        # equal-key groups may differ. This states the limit as an assertion.
        ours = sorted(CORPUS, key=collation_key)
        theirs = self.js_sorted(CORPUS)
        for mine, yours in zip(ours, theirs):
            if mine != yours:
                assert collation_key(mine) == collation_key(yours)
