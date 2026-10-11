from __future__ import annotations


class DomainError(Exception):
    """Base for every expected domain failure. Maps to HTTP 4xx."""

    code = "domain_error"


class MissingDependency(DomainError):
    code = "missing_dependency"

    def __init__(self, module_code: str) -> None:
        super().__init__(f"Módulo desconocido: '{module_code}'")
        self.module_code = module_code


class CircularDependency(DomainError):
    code = "circular_dependency"

    def __init__(self, module_code: str) -> None:
        super().__init__(f"Dependencia circular alrededor de '{module_code}'")
        self.module_code = module_code


class ModuleInUse(DomainError):
    code = "module_in_use"

    def __init__(self, module_code: str, blockers: tuple[str, ...]) -> None:
        super().__init__(f"'{module_code}' lo necesitan: {', '.join(blockers)}")
        self.module_code = module_code
        self.blockers = blockers


class TenantMismatch(DomainError):
    code = "tenant_mismatch"
