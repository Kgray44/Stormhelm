from typing import TYPE_CHECKING

from stormhelm.core.workspace.indexer import WorkspaceIndexer
from stormhelm.core.workspace.repository import WorkspaceRepository

if TYPE_CHECKING:
    from stormhelm.core.workspace.service import WorkspaceService

__all__ = ["WorkspaceIndexer", "WorkspaceRepository", "WorkspaceService"]


def __getattr__(name: str) -> object:
    if name == "WorkspaceService":
        from stormhelm.core.workspace.service import WorkspaceService

        return WorkspaceService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
