from stormhelm.core.tools.builtins.clock import ClockTool
from stormhelm.core.tools.builtins.echo import EchoTool
from stormhelm.core.tools.builtins.file_reader import FileReaderTool
from stormhelm.core.tools.builtins.notes import NotesWriteTool
from stormhelm.core.tools.builtins.shell_stub import ShellCommandStubTool
from stormhelm.core.tools.builtins.system_info import SystemInfoTool


def register_builtin_tools(registry) -> None:
    registry.register(ClockTool())
    registry.register(SystemInfoTool())
    registry.register(FileReaderTool())
    registry.register(NotesWriteTool())
    registry.register(EchoTool())
    registry.register(ShellCommandStubTool())

