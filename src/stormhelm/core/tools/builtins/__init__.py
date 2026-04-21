from stormhelm.core.tools.builtins.context_actions import ContextActionTool
from stormhelm.core.tools.builtins.clock import ClockTool
from stormhelm.core.tools.builtins.echo import EchoTool
from stormhelm.core.tools.builtins.environment_intelligence import ActivitySummaryTool, BrowserContextTool
from stormhelm.core.tools.builtins.file_reader import FileReaderTool
from stormhelm.core.tools.builtins.notes import NotesWriteTool
from stormhelm.core.tools.builtins.operational_diagnostics import (
    PowerDiagnosisTool,
    ResourceDiagnosisTool,
    StorageDiagnosisTool,
)
from stormhelm.core.tools.builtins.shell_stub import ShellCommandStubTool
from stormhelm.core.tools.builtins.system_info import SystemInfoTool
from stormhelm.core.tools.builtins.system_state import (
    ActiveAppsTool,
    AppControlTool,
    ControlCapabilitiesTool,
    LocationStatusTool,
    MachineStatusTool,
    NetworkDiagnosisTool,
    NetworkStatusTool,
    PowerProjectionTool,
    PowerStatusTool,
    RecentFilesTool,
    ResourceStatusTool,
    SaveLocationTool,
    SavedLocationsTool,
    StorageStatusTool,
    WeatherCurrentTool,
    WindowControlTool,
    WindowStatusTool,
)
from stormhelm.core.tools.builtins.workflow_power import (
    DesktopSearchTool,
    RepairActionTool,
    WorkflowExecuteTool,
)
from stormhelm.core.tools.builtins.long_tail_power import (
    FileOperationTool,
    MaintenanceActionTool,
    RoutineExecuteTool,
    RoutineSaveTool,
    TrustedHookExecuteTool,
    TrustedHookRegisterTool,
)
from stormhelm.core.tools.builtins.workspace_memory import (
    WorkspaceArchiveTool,
    WorkspaceAssembleTool,
    WorkspaceClearTool,
    WorkspaceListTool,
    WorkspaceNextStepsTool,
    WorkspaceRenameTool,
    WorkspaceRestoreTool,
    WorkspaceSaveTool,
    WorkspaceTagTool,
    WorkspaceWhereLeftOffTool,
)
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
    registry.register(BrowserContextTool())
    registry.register(ActivitySummaryTool())
    registry.register(ShellCommandStubTool())
    registry.register(DeckOpenUrlTool())
    registry.register(ExternalOpenUrlTool())
    registry.register(DeckOpenFileTool())
    registry.register(ExternalOpenFileTool())
    registry.register(MachineStatusTool())
    registry.register(PowerStatusTool())
    registry.register(PowerProjectionTool())
    registry.register(PowerDiagnosisTool())
    registry.register(ResourceStatusTool())
    registry.register(StorageStatusTool())
    registry.register(ResourceDiagnosisTool())
    registry.register(StorageDiagnosisTool())
    registry.register(NetworkStatusTool())
    registry.register(NetworkDiagnosisTool())
    registry.register(ActiveAppsTool())
    registry.register(AppControlTool())
    registry.register(WindowStatusTool())
    registry.register(WindowControlTool())
    registry.register(ControlCapabilitiesTool())
    registry.register(RecentFilesTool())
    registry.register(DesktopSearchTool())
    registry.register(WorkflowExecuteTool())
    registry.register(RepairActionTool())
    registry.register(RoutineExecuteTool())
    registry.register(RoutineSaveTool())
    registry.register(TrustedHookRegisterTool())
    registry.register(TrustedHookExecuteTool())
    registry.register(FileOperationTool())
    registry.register(MaintenanceActionTool())
    registry.register(ContextActionTool())
    registry.register(LocationStatusTool())
    registry.register(SavedLocationsTool())
    registry.register(SaveLocationTool())
    registry.register(WeatherCurrentTool())
    registry.register(WorkspaceRestoreTool())
    registry.register(WorkspaceAssembleTool())
    registry.register(WorkspaceSaveTool())
    registry.register(WorkspaceClearTool())
    registry.register(WorkspaceArchiveTool())
    registry.register(WorkspaceRenameTool())
    registry.register(WorkspaceTagTool())
    registry.register(WorkspaceListTool())
    registry.register(WorkspaceWhereLeftOffTool())
    registry.register(WorkspaceNextStepsTool())
