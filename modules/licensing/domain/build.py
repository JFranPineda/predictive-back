"""What a sealed build of PREDICTIVE carries, and how its source is shipped
(v4 Phase 5).

Each delivery is compiled and stamped with the customer code and the version:
the PDFs it produces name them in their metadata, which is how support knows
what runs where and what backs the INDECOPI registration. The source is closed
— the value as native binaries, the rest as bytecode, never readable `.py`.
"""

from __future__ import annotations

from enum import Enum, auto
from pathlib import Path

OWNER = "Industrie Ampel"
PRODUCT = "PREDICTIVE"


class BuildStamp:
    """The customer, version and build of a delivery, with honest fallbacks so
    a plain checkout still produces readable PDF metadata."""

    def __init__(self, tenant: str, version: str, build_id: str) -> None:
        self.tenant = tenant or "desarrollo"
        self.version = version or "sin versión"
        self.build_id = build_id or "desarrollo"

    @property
    def pdf_author(self) -> str:
        return f"{OWNER} — {PRODUCT} · {self.tenant} · {self.version}"

    @property
    def pdf_creator(self) -> str:
        return f"{PRODUCT} {self.version} ({self.build_id})"


class Compilation(Enum):
    NATIVE = auto()    # the value: compiled to a native module (.so)
    BYTECODE = auto()  # Django glue: shipped as .pyc, no source
    ASSET = auto()     # templates, locales, static: shipped as-is


# The value worth compiling to native: the business rules and the use cases.
# Everything Django must read as a package tree (migrations) stays bytecode.
NATIVE_PARTS = ("domain", "application")
TREE_READ_PARTS = ("migrations",)


def source_class(path: Path) -> Compilation:
    if path.suffix != ".py":
        return Compilation.ASSET
    # A package __init__ as a native module does not import as a package.
    if path.name == "__init__.py":
        return Compilation.BYTECODE
    parts = path.parts
    if any(part in TREE_READ_PARTS for part in parts):
        return Compilation.BYTECODE
    if any(part in NATIVE_PARTS for part in parts):
        return Compilation.NATIVE
    return Compilation.BYTECODE
