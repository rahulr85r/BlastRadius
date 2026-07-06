"""Swift adapter for BlastRadius.

Swift has no intra-module file imports — `import` targets whole modules.
Edges are therefore driven by type references: a file that mentions type
`Foo` depends on the file that defines `Foo` (resolved in the graph layer,
gated on repo-wide uniqueness so ambiguous names never create false edges).
Extensions contribute an edge to the extended type's defining file.
"""
from ._base import Symbol, ImportRef, ExtractResult, get_text, first_line, head_keyword

LANGUAGE_NAME = "swift"
FILE_EXTENSIONS = [".swift"]

try:
    from tree_sitter import Parser, Language
    import tree_sitter_swift
    _PARSER = Parser(Language(tree_sitter_swift.language()))
    AVAILABLE = True
except Exception:
    _PARSER = None
    AVAILABLE = False

_KIND_BY_TYPE = {
    "function_declaration": "function",
    "protocol_declaration": "protocol",
    "struct_declaration": "struct",
    "enum_declaration": "enum",
    "extension_declaration": "extension",
    "init_declaration": "method",
    "deinit_declaration": "method",
    "subscript_declaration": "method",
    "property_declaration": "property",
}

_DEF_TYPES = set(_KIND_BY_TYPE) | {"class_declaration"}

# tree-sitter-swift reuses class_declaration for class/struct/enum/actor —
# classify by the declaration-head keyword.
_CLASS_KEYWORDS = {"class": "class", "struct": "struct", "enum": "enum",
                   "actor": "actor", "extension": "extension"}

_NAME_FALLBACK_TYPES = ("simple_identifier", "type_identifier", "identifier")


def _find_name(node):
    n = node.child_by_field_name("name")
    if n is not None:
        return n
    for child in node.named_children:
        if child.type in _NAME_FALLBACK_TYPES:
            return child
    return None


def _kind_of(node, source) -> str:
    if node.type == "class_declaration":
        kw = head_keyword(node, source, _CLASS_KEYWORDS)
        if kw:
            return _CLASS_KEYWORDS[kw]
        return "class"
    return _KIND_BY_TYPE.get(node.type, "def")


def extract(source: bytes, filepath: str) -> ExtractResult:
    if not AVAILABLE:
        return ExtractResult()

    tree = _PARSER.parse(source)
    root = tree.root_node

    symbols = []
    imports = []
    references = set()
    type_refs = set()

    stack = [root]
    while stack:
        node = stack.pop()
        nt = node.type

        if nt in _DEF_TYPES:
            name_node = _find_name(node)
            if name_node is not None:
                name = get_text(name_node, source)
                if name:
                    kind = _kind_of(node, source)
                    symbols.append(Symbol(
                        name=name,
                        line=name_node.start_point[0] + 1,
                        end_line=node.end_point[0] + 1,
                        kind=kind,
                        signature=first_line(get_text(node, source))[:200],
                    ))
                    if kind == "extension":
                        # `extension Foo` depends on wherever Foo is defined
                        type_refs.add(name.split(".")[-1])

        elif nt == "import_declaration":
            # Module-level import (UIKit, Foundation, local module) —
            # recorded for stats, never resolves to a repo file.
            for child in node.named_children:
                if child.type in _NAME_FALLBACK_TYPES:
                    imports.append(ImportRef(path=get_text(child, source)))
                    break

        elif nt == "type_identifier":
            t = get_text(node, source)
            if len(t) >= 2:
                type_refs.add(t)

        elif nt == "call_expression":
            for child in node.named_children:
                if child.type in _NAME_FALLBACK_TYPES + ("navigation_expression",):
                    name = get_text(child, source).split(".")[-1]
                    references.add(name)
                    # Uppercase-initial call targets are almost always
                    # initializers: `Foo(bar: 1)` — treat as a type use.
                    if name[:1].isupper() and len(name) >= 2:
                        type_refs.add(name)
                    break

        for child in reversed(node.children):
            stack.append(child)

    seen = set()
    uniq_imports = []
    for imp in imports:
        if imp.path not in seen:
            seen.add(imp.path)
            uniq_imports.append(imp)

    return ExtractResult(
        symbols=symbols,
        imports=uniq_imports,
        references=sorted(r for r in references if r),
        type_refs=sorted(type_refs),
    )
