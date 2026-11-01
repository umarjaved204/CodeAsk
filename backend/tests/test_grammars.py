import pytest
import tree_sitter_javascript as tsjs
import tree_sitter_python as tspy
import tree_sitter_typescript as tsts
from tree_sitter import Language, Parser

GRAMMARS = {
    "python": (tspy.language, "def f():\n    return 1\n"),
    "javascript": (tsjs.language, "const f = () => <div/>;\n"),
    "typescript": (tsts.language_typescript, "interface A { x: number }\n"),
    "tsx": (tsts.language_tsx, "const C = () => <div/>;\n"),
}


@pytest.mark.parametrize("name", GRAMMARS)
def test_grammar_loads_and_parses(name):
    # Catches an incompatible grammar/runtime version pair (e.g. after a dependency bump).
    lang_fn, source = GRAMMARS[name]
    tree = Parser(Language(lang_fn())).parse(source.encode("utf-8"))
    assert not tree.root_node.has_error
