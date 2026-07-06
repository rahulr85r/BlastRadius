"""JavaScript adapter for BlastRadius (JSX included).

Captures ES imports (with imported names), CommonJS require(), dynamic
import(), re-exports, definitions with kinds, call references, and type
references (new X, extends X).
"""
from ._base import Symbol, ImportRef, ExtractResult, get_text, first_line

LANGUAGE_NAME = "javascript"
FILE_EXTENSIONS = [".js", ".mjs", ".cjs", ".jsx"]

try:
    from tree_sitter import Parser, Language
    import tree_sitter_javascript
    _PARSER = Parser(Language(tree_sitter_javascript.language()))
    AVAILABLE = True
except Exception:
    _PARSER = None
    AVAILABLE = False

_DEF_KINDS = {
    "function_declaration": "function",
    "generator_function_declaration": "function",
    "class_declaration": "class",
    "method_definition": "method",
}

_LAMBDA_VALUE_TYPES = {
    "arrow_function", "function_expression", "function", "generator_function",
}


def _string_arg(node, source):
    """First string argument of a call's argument list, unquoted."""
    args = node.child_by_field_name("arguments")
    if args is None:
        return None
    for a in args.named_children:
        if a.type == "string":
            return get_text(a, source).strip("'\"`")
        break
    return None


def _clause_names(node, source):
    """All identifiers inside an import clause (default, named, namespace)."""
    names = set()
    stack = [node]
    while stack:
        c = stack.pop()
        if c.type == "identifier":
            names.add(get_text(c, source))
        stack.extend(c.named_children)
    return sorted(names)


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

        if nt in _DEF_KINDS:
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                name = get_text(name_node, source)
                if name:
                    symbols.append(Symbol(
                        name=name,
                        line=name_node.start_point[0] + 1,
                        end_line=node.end_point[0] + 1,
                        kind=_DEF_KINDS[nt],
                        signature=first_line(get_text(node, source))[:200],
                    ))

        elif nt == "variable_declarator":
            # const Foo = (...) => {...} or const Foo = function(...) {...}
            value = node.child_by_field_name("value")
            if value is not None and value.type in _LAMBDA_VALUE_TYPES:
                name_node = node.child_by_field_name("name")
                if name_node is not None:
                    name = get_text(name_node, source)
                    if name:
                        symbols.append(Symbol(
                            name=name,
                            line=name_node.start_point[0] + 1,
                            end_line=node.end_point[0] + 1,
                            kind="function",
                            signature=first_line(get_text(node, source))[:200],
                        ))

        elif nt == "import_statement":
            src = node.child_by_field_name("source")
            if src is not None:
                names = []
                for child in node.named_children:
                    if child.type == "import_clause":
                        names = _clause_names(child, source)
                        break
                imports.append(ImportRef(
                    path=get_text(src, source).strip("'\"`"), names=names))

        elif nt == "export_statement":
            # export { x } from './y' — a dependency edge like any import
            src = node.child_by_field_name("source")
            if src is not None:
                imports.append(ImportRef(path=get_text(src, source).strip("'\"`")))

        elif nt == "class_heritage":
            # class Foo extends Bar
            for child in node.named_children:
                if child.type == "identifier":
                    type_refs.add(get_text(child, source))
                elif child.type == "member_expression":
                    prop = child.child_by_field_name("property")
                    if prop is not None:
                        type_refs.add(get_text(prop, source))

        elif nt == "new_expression":
            ctor = node.child_by_field_name("constructor")
            if ctor is not None and ctor.type == "identifier":
                type_refs.add(get_text(ctor, source))

        elif nt == "call_expression":
            fn = node.child_by_field_name("function")
            if fn is not None:
                if fn.type == "import":  # dynamic import('./x')
                    spec = _string_arg(node, source)
                    if spec:
                        imports.append(ImportRef(path=spec))
                elif fn.type == "identifier":
                    fname = get_text(fn, source)
                    if fname == "require":  # CommonJS
                        spec = _string_arg(node, source)
                        if spec:
                            imports.append(ImportRef(path=spec))
                    else:
                        references.add(fname)
                elif fn.type == "member_expression":
                    prop = fn.child_by_field_name("property")
                    if prop is not None:
                        references.add(get_text(prop, source))

        for child in reversed(node.children):
            stack.append(child)

    seen = set()
    uniq_imports = []
    for imp in imports:
        key = (imp.path, tuple(imp.names))
        if key not in seen:
            seen.add(key)
            uniq_imports.append(imp)

    return ExtractResult(
        symbols=symbols,
        imports=uniq_imports,
        references=sorted(r for r in references if r),
        type_refs=sorted(t for t in type_refs if len(t) >= 2),
    )
