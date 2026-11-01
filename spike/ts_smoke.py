"""M1 step 2: tree-sitter smoke test.

Loads the Python, JavaScript, TypeScript and TSX grammars, parses a small sample of each
(covering the constructs the chunker cares about) and prints the named-node tree with
1-based line ranges. The node-type names printed here become the chunker's "named units".

Run: python spike/ts_smoke.py
"""

import tree_sitter
import tree_sitter_javascript as tsjs
import tree_sitter_python as tspy
import tree_sitter_typescript as tsts
from tree_sitter import Language, Parser

PY = '''\
"""Module docstring."""
import os
from typing import Any

MAX = 10  # constant


# Leading comment for helper.
def helper(x: int) -> int:
    """Docstring."""
    return x + 1


@decorator
def decorated():
    pass


class Signer(Base):
    """Class docstring."""

    default: str = "x"

    def sign(self, value):
        if value:
            return value
        return None

    @property
    def key(self):
        return 1


if __name__ == "__main__":
    helper(1)
'''

PY_BROKEN = '''\
def ok():
    return 1

def broken(:
    return 2
'''

JS = '''\
const express = require("express");
const app = express();

// Leading comment for add.
function add(a, b) {
  return a + b;
}

const mul = (a, b) => a * b;
const div = function (a, b) { return a / b; };

class Router {
  constructor() { this.routes = []; }
  get(path) { return path; }
}

app.get("/users/:id", async (req, res) => {
  const user = await find(req.params.id);
  res.json(user);
});

export default function main() {}
export const sub = (a, b) => a - b;
module.exports = { add };

const el = <div className="x">hi</div>;
'''

TS = '''\
import { x } from "./x";

export interface User {
  id: number;
  name: string;
}

type Id = string | number;

export enum Color { Red, Green }

/** Doc comment. */
export async function load(id: Id): Promise<User> {
  return { id: 1, name: "a" };
}

export const save = async (u: User): Promise<void> => {};

@Component({ selector: "x" })
export abstract class Base<T> {
  private items: T[] = [];
  abstract run(): void;
  add(item: T): void { this.items.push(item); }
}

namespace NS { export const y = 1; }
'''

TSX = '''\
import React from "react";

type Props = { title: string };

export function Card({ title }: Props) {
  return <div className="card">{title}</div>;
}

export const List = <T,>(items: T[]) => <ul>{items.length}</ul>;
'''

# Leaf-ish node types hidden to keep the output readable.
SKIP = {
    "identifier", "property_identifier", "type_identifier", "shorthand_property_identifier",
    "string", "string_fragment", "string_content", "string_start", "string_end", "number",
    "integer", "true", "false", "none", "null", "this", "escape_sequence",
}
MAX_DEPTH = 5


def show(node, depth=0):
    if depth > MAX_DEPTH or node.type in SKIP:
        return
    start, end = node.start_point[0] + 1, node.end_point[0] + 1  # tree-sitter rows are 0-based
    flag = "  <-- ERROR" if node.type == "ERROR" or node.is_missing else ""
    print(f"{'  ' * depth}{node.type} [{start}-{end}]{flag}")
    for child in node.named_children:
        show(child, depth + 1)


def run(name, lang_ptr, source):
    print(f"\n===== {name} =====")
    try:
        lang = Language(lang_ptr)
    except Exception as e:  # incompatible grammar ABI shows up here
        print(f"FAILED to load grammar: {type(e).__name__}: {e}")
        return
    abi = getattr(lang, "abi_version", None) or getattr(lang, "version", "?")
    tree = Parser(lang).parse(source.encode("utf-8"))
    print(f"grammar ABI {abi}; root.has_error = {tree.root_node.has_error}")
    show(tree.root_node)


def main():
    print(f"tree-sitter {tree_sitter.__version__ if hasattr(tree_sitter, '__version__') else '?'}")
    run("Python", tspy.language(), PY)
    run("Python (syntax error)", tspy.language(), PY_BROKEN)
    run("JavaScript (incl. JSX)", tsjs.language(), JS)
    run("TypeScript", tsts.language_typescript(), TS)
    run("TSX", tsts.language_tsx(), TSX)


if __name__ == "__main__":
    main()
