"""Base types and utilities shared by all BlastRadius language adapters."""
from dataclasses import dataclass, field, asdict
from typing import List


@dataclass
class Symbol:
    name: str
    line: int
    # class | interface | struct | enum | record | annotation | protocol |
    # object | actor | extension | function | method | property | def
    kind: str
    end_line: int = 0
    signature: str = ""

    def to_dict(self):
        return asdict(self)


@dataclass
class ImportRef:
    """One import statement, structured.

    path:  the import path exactly as written — 'a.b.c' (Python),
           './utils/auth' (JS), 'com.foo.Bar' or 'com.foo.*' (JVM),
           '..pkg.mod' (Python relative — leading dots preserved).
    names: the symbol names the statement imports, when the syntax exposes
           them ('from a import b, c' → ['b', 'c']; 'import { x } from ...'
           → ['x']). Used for symbol-level edge labeling ('via'). '*' means
           a wildcard import.
    """
    path: str
    names: List[str] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)


@dataclass
class ExtractResult:
    symbols: List[Symbol] = field(default_factory=list)
    imports: List[ImportRef] = field(default_factory=list)
    references: List[str] = field(default_factory=list)  # called function/method names
    type_refs: List[str] = field(default_factory=list)   # referenced TYPE names — drive class-level edges
    package: str = ""  # declared namespace (JVM 'package com.foo'); empty elsewhere


def get_text(node, source: bytes) -> str:
    """Return the UTF-8 text of a tree-sitter node, replacing invalid bytes."""
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def first_line(text: str) -> str:
    return text.strip().split("\n", 1)[0].strip()


def head_keyword(node, source: bytes, keywords) -> str:
    """Return the first of `keywords` appearing as a word in the node's first
    line (declaration head). Used to classify grammars that reuse one node
    type for several declaration kinds (Kotlin/Swift 'class_declaration'
    covering class/interface/struct/enum/...)."""
    head = first_line(get_text(node, source))
    for word in head.replace("(", " ").replace(":", " ").split():
        if word in keywords:
            return word
    return ""
