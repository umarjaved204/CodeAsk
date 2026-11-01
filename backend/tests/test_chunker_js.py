from helpers import check_invariants, fake_count

from codeask.chunker import ChunkSettings, chunk_file, language_for

NO_MERGE = ChunkSettings(min_tokens=1)
TINY = ChunkSettings(max_tokens=70, target_max=30, target_min=15, min_tokens=1)


def chunks_of(text, path, settings=NO_MERGE):
    result = chunk_file(path, text, fake_count, settings)
    check_invariants(text, result, settings.max_tokens)
    return result


def summary(result):
    return [(c.start_line, c.end_line, c.kind, c.breadcrumb) for c in result.chunks]


JS = '''\
const express = require("express");
const app = express();

// Adds two numbers.
function add(a, b) {
  return a + b;
}

const mul = (a, b) => a * b;

class Router {
  constructor() {
    this.routes = [];
  }

  get(path) {
    return path;
  }
}

app.get("/users/:id", async (req, res) => {
  res.json(await find(req.params.id));
});

app.handle = function handle(req, res) {
  return dispatch(req, res);
};

app.use(function (req, res, next) {
  next();
});

module.exports = { add };
'''


def test_js_units():
    result = chunks_of(JS, "lib/app.js")
    assert result.method == "ast"
    assert summary(result) == [
        (1, 1, "module", "<module>"),
        (2, 2, "module", "<module>"),
        (4, 7, "function", "add"),  # leading comment attached
        (9, 9, "function", "mul"),  # const arrow function
        (11, 19, "class", "Router"),
        (21, 23, "function", 'app.get("/users/:id")'),  # callback with a string first arg
        (25, 27, "function", "app.handle"),  # function assignment, named by the left side
        (29, 31, "module", "<module>"),  # callback without a string first arg: anonymous
        (33, 33, "module", "<module>"),
    ]


def test_extensions_and_dts_precedence():
    assert language_for("a.js") == language_for("a.jsx") == language_for("a.mjs") \
        == language_for("a.cjs") == "javascript"
    assert language_for("a.ts") == language_for("a.mts") == "typescript"
    assert language_for("a.tsx") == "tsx"
    assert language_for("types/index.d.ts") is None  # declarations: never parsed as .ts
    result = chunks_of("export declare function f(): void;\n", "types/index.d.ts")
    assert result.method == "windows"


# ---------- JS classes and callbacks over the cap ----------
SMALL = ChunkSettings(max_tokens=90, target_max=50, target_min=30, min_tokens=1,
                      outline_max_tokens=40)


def big_js_class(n):
    methods = "\n".join(
        f"  m{i}(value) {{\n"
        f"    const result = transform{i}(value);\n"
        f"    return result;\n"
        f"  }}\n" for i in range(n))
    return f'export class Signer extends Base {{\n  defaultValue = "x";\n\n{methods}}}\n'


def test_js_class_split_and_closing_brace_attaches():
    text = big_js_class(4)
    result = chunks_of(text, "signer.js", SMALL)
    header, *members = result.chunks
    assert (header.kind, header.breadcrumb, header.start_line) == ("class_header", "Signer", 1)
    assert "Members:\n  m0(value) {" in header.embed_text
    assert [m.breadcrumb for m in members] == [f"Signer > m{i}" for i in range(4)]
    assert members[-1].end_line == len(text.rstrip("\n").split("\n"))  # the final `}`
    assert not any(c.content.strip() in ("}", "});", "};") for c in result.chunks)


def test_express_callback_split_carries_the_route_line():
    body = "\n".join(f"  const step{i} = await service.handleStep{i}(req.params);"
                     for i in range(12))
    text = f'router.post("/orders/:id", async (req, res) => {{\n{body}\n  res.json(step0);\n}});\n'
    result = chunks_of(text, "routes.js", TINY)
    assert len(result.chunks) > 1
    assert all(c.breadcrumb.startswith('router.post("/orders/:id") (part ')
               for c in result.chunks)
    assert all('router.post("/orders/:id", async (req, res) => {' in c.embed_text
               for c in result.chunks)
    assert not any(c.content.strip() == "});" for c in result.chunks)


def test_k_and_r_else_lines_are_covered():
    body = "\n".join(f"    total += compute{i}(x);" for i in range(6))
    text = (f"function f(x) {{\n  let total = 0;\n  if (x > 0) {{\n{body}\n  }} else if (x < 0) {{\n"
            f"{body}\n  }} else {{\n{body}\n  }}\n  return total;\n}}\n")
    result = chunks_of(text, "f.js", TINY)  # invariants prove `} else {` lines are owned
    assert len(result.chunks) > 1


# ---------- window-fallback reasons ----------
def test_iife_and_object_literal_reasons():
    body = "\n".join(f"  var v{i} = setupSomething{i}();" for i in range(15))
    iife = chunk_file("a.js", f"(function () {{\n{body}\n}})();\n", fake_count, TINY)
    assert iife.window_reasons == {"IIFE": 1}
    entries = "\n".join(f"  handler{i}: require('./handlers/h{i}')," for i in range(15))
    obj = chunk_file("b.js", f"module.exports = {{\n{entries}\n}};\n", fake_count, TINY)
    assert obj.window_reasons == {"object literal": 1}


# ---------- TypeScript ----------
TS = '''\
import { Injectable, Log } from "./di";

export interface User {
  id: number;
}

export type Id = string | number;

export enum Color { Red, Green }

export function load(id: Id): User;
export function load(id: Id, deep: boolean): User;
export function load(id: Id, deep?: boolean): User {
  return { id: 1 } as User;
}

@Injectable()
export abstract class Repository<T extends { id: Id }> {
  protected items: T[] = [];

  abstract count(): number;

  @Log()
  find(id: Id): T | undefined {
    return this.items.find((item) => item.id === id);
  }

  *iterate(): Generator<T> {
    yield* this.items;
  }
}

export function* ids(): Generator<number> {
  yield 1;
}

namespace Util {
  export const one = 1;
}
'''


def parse_errors(text, lang):
    """(line, node type, text) of every ERROR/MISSING node, for readable failures."""
    from codeask.chunker import _parser

    found = []

    def walk(node):
        if node.type == "ERROR" or node.is_missing:
            found.append((node.start_point[0] + 1, node.type, node.text.decode()[:40]))
        for child in node.children:
            walk(child)

    walk(_parser(lang).parse(text.encode("utf-8")).root_node)
    return found


def test_ts_sample_parses_cleanly():
    assert parse_errors(TS, "typescript") == []


def test_ts_units_decorators_abstract_generics_generators():
    result = chunks_of(TS, "src/repo.ts")
    assert result.method == "ast", parse_errors(TS, "typescript")
    named = [(c.kind, c.breadcrumb) for c in result.chunks if c.kind != "module"]
    assert named == [
        ("type", "User"), ("type", "Id"), ("type", "Color"),
        ("function", "load"), ("function", "load"), ("function", "load"),  # overloads
        ("class", "Repository"), ("function", "ids"), ("class", "Util"),
    ]
    repo = next(c for c in result.chunks if c.breadcrumb == "Repository")
    assert repo.content.startswith("@Injectable()")  # the class decorator is included


def test_ts_class_split_attaches_member_decorators():
    settings = ChunkSettings(max_tokens=80, target_max=40, target_min=20, min_tokens=1,
                             outline_max_tokens=40)
    result = chunks_of(TS, "src/repo.ts", settings)
    assert result.method == "ast", parse_errors(TS, "typescript")
    find = next(c for c in result.chunks if c.breadcrumb == "Repository > find")
    assert find.content.lstrip().startswith("@Log()")  # the sibling decorator attached
    header = next(c for c in result.chunks if c.kind == "class_header")
    assert header.breadcrumb == "Repository"
    assert "abstract count(): number;" in header.embed_text  # outline lists abstract members


def test_tsx_components():
    text = ('import React from "react";\n\n'
            'export function Card({ title }: { title: string }) {\n'
            '  return <div className="card">{title}</div>;\n}\n\n'
            'export const List = <T,>(items: T[]) => <ul>{items.length}</ul>;\n')
    result = chunks_of(text, "Card.tsx")
    assert [c.breadcrumb for c in result.chunks if c.kind == "function"] == ["Card", "List"]


def test_js_syntax_error_falls_back():
    result = chunks_of("function ok() { return 1; }\nfunction broken( {\n", "x.js")
    assert result.method == "fallback"
