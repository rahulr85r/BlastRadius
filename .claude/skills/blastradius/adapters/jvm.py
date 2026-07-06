"""JVM-family adapter (Java + Kotlin) for BlastRadius.

Java and Kotlin share enough AST structure that one adapter handles both,
dispatching to the right grammar by file extension.

Beyond TokenHack's version this adapter captures:
  - the declared `package` (the key to precise import resolution),
  - imports as raw dotted paths with wildcard/static/alias handling,
  - type references (type_identifier usage + `new Foo()`) for
    same-package and wildcard-import edge resolution,
  - symbol kinds (class / interface / enum / record / method / ...).
"""
from ._base import Symbol, ImportRef, ExtractResult, get_text, first_line, head_keyword

LANGUAGE_NAME = "jvm"
FILE_EXTENSIONS = [".java", ".kt", ".kts"]

try:
    from tree_sitter import Parser, Language
    import tree_sitter_java
    _JAVA_PARSER = Parser(Language(tree_sitter_java.language()))
    JAVA_AVAILABLE = True
except Exception:
    _JAVA_PARSER = None
    JAVA_AVAILABLE = False

try:
    from tree_sitter import Parser, Language
    import tree_sitter_kotlin
    _KOTLIN_PARSER = Parser(Language(tree_sitter_kotlin.language()))
    KOTLIN_AVAILABLE = True
except Exception:
    _KOTLIN_PARSER = None
    KOTLIN_AVAILABLE = False

AVAILABLE = JAVA_AVAILABLE or KOTLIN_AVAILABLE

_JAVA_EXTS = (".java",)
_KOTLIN_EXTS = (".kt", ".kts")

_KIND_BY_TYPE = {
    # Java
    "class_declaration": "class",
    "interface_declaration": "interface",
    "enum_declaration": "enum",
    "record_declaration": "record",
    "annotation_type_declaration": "annotation",
    "method_declaration": "method",
    "constructor_declaration": "method",
    # Kotlin
    "function_declaration": "function",
    "object_declaration": "object",
    "property_declaration": "property",
    "secondary_constructor": "method",
}

_DEF_TYPES = set(_KIND_BY_TYPE)
# Kotlin grammar versions differ: older tree-sitter-kotlin emits
# `import_header`/`package_header`, newer emits `import`/`package_header`.
_IMPORT_TYPES = {"import_declaration", "import_header", "import"}
_PACKAGE_TYPES = {"package_declaration", "package_header"}
_NAME_FALLBACK_TYPES = ("simple_identifier", "identifier", "type_identifier")

# Kotlin reuses class_declaration for several declaration kinds — classify
# by the keyword in the declaration head.
_KOTLIN_CLASS_KEYWORDS = {"interface": "interface", "enum": "enum", "class": "class"}


def _parser_for(filepath: str):
    low = filepath.lower()
    if low.endswith(_JAVA_EXTS):
        return _JAVA_PARSER if JAVA_AVAILABLE else None
    if low.endswith(_KOTLIN_EXTS):
        return _KOTLIN_PARSER if KOTLIN_AVAILABLE else None
    return None


def _find_name(node):
    n = node.child_by_field_name("name")
    if n is not None:
        return n
    for child in node.named_children:
        if child.type in _NAME_FALLBACK_TYPES:
            return child
    return None


def _kind_of(node, source) -> str:
    kind = _KIND_BY_TYPE.get(node.type, "def")
    if node.type == "class_declaration":
        kw = head_keyword(node, source, _KOTLIN_CLASS_KEYWORDS)
        if kw:
            kind = _KOTLIN_CLASS_KEYWORDS[kw]
    return kind


def _parse_import_text(node, source):
    """Text-parse an import node — robust across Java/Kotlin grammar shapes.

    'import static com.foo.Bar.baz;'  → 'com.foo.Bar.baz'
    'import com.foo.*'                → 'com.foo.*'
    'import com.foo.Bar as Baz'       → 'com.foo.Bar'
    """
    text = " ".join(get_text(node, source).split()).rstrip(";").strip()
    if text.startswith("import"):
        text = text[len("import"):].strip()
    if text.startswith("static "):
        text = text[len("static"):].strip()
    if " as " in text:  # Kotlin alias
        text = text.split(" as ", 1)[0].strip()
    return text


def extract(source: bytes, filepath: str) -> ExtractResult:
    parser = _parser_for(filepath)
    if parser is None:
        return ExtractResult()

    tree = parser.parse(source)
    root = tree.root_node

    symbols = []
    imports = []
    references = set()
    type_refs = set()
    package = ""

    stack = [root]
    while stack:
        node = stack.pop()
        nt = node.type

        if nt in _DEF_TYPES:
            name_node = _find_name(node)
            if name_node is not None:
                name = get_text(name_node, source)
                if name:
                    symbols.append(Symbol(
                        name=name,
                        line=name_node.start_point[0] + 1,
                        end_line=node.end_point[0] + 1,
                        kind=_kind_of(node, source),
                        signature=first_line(get_text(node, source))[:200],
                    ))

        elif nt in _IMPORT_TYPES:
            path = _parse_import_text(node, source)
            if path:
                imports.append(ImportRef(path=path))

        elif nt in _PACKAGE_TYPES:
            text = " ".join(get_text(node, source).split()).rstrip(";").strip()
            if text.startswith("package"):
                package = text[len("package"):].strip()

        elif nt == "type_identifier":
            t = get_text(node, source)
            if len(t) >= 2:
                type_refs.add(t)

        elif nt == "object_creation_expression":  # Java `new Foo()`
            t = node.child_by_field_name("type")
            if t is not None:
                name = get_text(t, source).split(".")[-1].split("<")[0]
                if len(name) >= 2:
                    type_refs.add(name)

        elif nt == "method_invocation":  # Java
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                references.add(get_text(name_node, source))

        elif nt == "call_expression":  # Kotlin
            for child in node.named_children:
                if child.type in _NAME_FALLBACK_TYPES + ("navigation_expression",):
                    name = get_text(child, source).split(".")[-1]
                    references.add(name)
                    # Kotlin constructor calls are bare identifiers —
                    # `Bar()` — with no type_identifier node. Uppercase-
                    # initial call targets are almost always type uses.
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
        package=package,
    )
