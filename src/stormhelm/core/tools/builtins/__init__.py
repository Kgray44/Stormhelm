from stormhelm.core.tools.builtins.clock import ClockTool
from stormhelm.core.tools.builtins.echo import EchoTool
from stormhelm.core.tools.builtins.file_reader import FileReaderTool
from stormhelm.core.tools.builtins.notes import NotesWriteTool
from stormhelm.core.tools.builtins.shell_stub import ShellCommandStubTool
from stormhelm.core.tools.builtins.system_info import SystemInfoTool
from stormhelm.core.tools.builtins.system_state import (
    ActiveAppsTool,
    MachineStatusTool,
    NetworkStatusTool,
    PowerStatusTool,
    RecentFilesTool,
    ResourceStatusTool,
    StorageStatusTool,
)
from stormhelm.core.tools.builtins.workspace_memory import WorkspaceAssembleTool, WorkspaceRestoreTool
from stormhelm.core.tools.builtins.workspace_actions import (
    DeckOpenFileTool,
    DeckOpenUrlTool,
    ExternalOpenFileTool,
    ExternalOpenUrlTool,
)


def register_builtin_tools(registry) -> None:
    registry.register(ClockTool())
    registry.register(SystemInfoTool())
    registry.register(FileReaderTool())
    registry.register(NotesWriteTool())
    registry.register(EchoTool())
    registry.register(ShellCommandStubTool())
    registry.register(DeckOpenUrlTool())
    registry.register(ExternalOpenUrlTool())
    registry.register(DeckOpenFileTool())
    registry.register(ExternalOpenFileTool())
    registry.register(MachineStatusTool())
    registry.register(PowerStatusTool())
    registry.register(ResourceStatusTool())
    registry.register(StorageStatusTool())
    registry.register(NetworkStatusTool())
    registry.register(ActiveAppsTool())
    registry.register(RecentFilesTool())
    registry.register(WorkspaceRestoreTool())
    registry.register(WorkspaceAssembleTool())
