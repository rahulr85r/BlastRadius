"""Python adapter for BlastRadius.

Extracts function/class definitions (with kinds), structured imports
(relative dots preserved, imported names captured), call references, and
superclass type references via tree-sitter-python.
"""
from ._base import Symbol, ImportRef, ExtractResult, get_text, first_line

LANGUAGE_NAME = "python"
FILE_EXTENSIONS = [".py"]

try:
    from tree_sitter import Parser, Language
    import tree_sitter_python
    _PARSER = Parser(Language(tree_sitter_python.language()))
    AVAILABLE = True
except Exception:
    _PARSER = None
    AVAILABLE = False


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

        if nt in ("function_definition", "class_definition"):
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                name = get_text(name_node, source)
                kind = "class" if nt == "class_definition" else "function"
                symbols.append(Symbol(
                    name=name,
                    line=name_node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    kind=kind,
                    signature=first_line(get_text(node, source))[:200],
                ))
            if nt == "class_definition":
                sup = node.child_by_field_name("superclasses")
                if sup is not None:
                    for arg in sup.named_children:
                        if arg.type in ("identifier", "attribute"):
                            base = get_text(arg, source).split(".")[-1]
                            if len(base) >= 2:
                                type_refs.add(base)

        elif nt == "import_statement":
            for child in node.named_children:
                if child.type == "dotted_name":
                    imports.append(ImportRef(path=get_text(child, source)))
                elif child.type == "aliased_import":
                    n = child.child_by_field_name("name")
                    if n is not None:
                        imports.append(ImportRef(path=get_text(n, source)))

        elif nt == "import_from_statement":
            m = node.child_by_field_name("module_name")
            mod = get_text(m, source) if m is not None else ""
            names = []
            for child in node.named_children:
                if m is not None and child.id == m.id:
                    continue
                if child.type == "dotted_name":
                    names.append(get_text(child, source))
                elif child.type == "aliased_import":
                    n = child.child_by_field_name("name")
                    if n is not None:
                        names.append(get_text(n, source))
                elif child.type == "wildcard_import":
                    names.append("*")
            if mod:
                imports.append(ImportRef(path=mod, names=names))

        elif nt == "call":
            fn = node.child_by_field_name("function")
            if fn is not None:
                if fn.type == "identifier":
                    references.add(get_text(fn, source))
                elif fn.type == "attribute":
                    attr = fn.child_by_field_name("attribute")
                    if attr is not None:
                        references.add(get_text(attr, source))

        for child in reversed(node.children):
            stack.append(child)

    # Deduplicate imports on (path, names) while preserving order
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
        references=sorted(references),
        type_refs=sorted(type_refs),
    )
