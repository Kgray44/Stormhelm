from __future__ import annotations

import ctypes
import json
import os
import platform
import shutil
import socket
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from stormhelm.config.models import AppConfig


@dataclass(slots=True)
class SystemProbe:
    config: AppConfig

    def machine_status(self) -> dict[str, Any]:
        now = datetime.now().astimezone()
        return {
            "machine_name": os.environ.get("COMPUTERNAME") or platform.node(),
            "platform": platform.platform(),
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "python_version": platform.python_version(),
            "local_time": now.isoformat(),
            "timezone": str(now.tzinfo),
        }

    def power_status(self) -> dict[str, Any]:
        class SYSTEM_POWER_STATUS(ctypes.Structure):
            _fields_ = [
                ("ACLineStatus", ctypes.c_byte),
                ("BatteryFlag", ctypes.c_byte),
                ("BatteryLifePercent", ctypes.c_byte),
                ("Reserved1", ctypes.c_byte),
                ("BatteryLifeTime", ctypes.c_uint32),
                ("BatteryFullLifeTime", ctypes.c_uint32),
            ]

        status = SYSTEM_POWER_STATUS()
        if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):
            return {"available": False}
        percent = None if status.BatteryLifePercent == 255 else int(status.BatteryLifePercent)
        return {
            "available": True,
            "ac_line_status": {0: "offline", 1: "online"}.get(int(status.ACLineStatus), "unknown"),
            "battery_percent": percent,
            "battery_flag": int(status.BatteryFlag),
            "battery_saver": bool(int(status.BatteryFlag) & 8),
            "seconds_remaining": None if status.BatteryLifeTime == 0xFFFFFFFF else int(status.BatteryLifeTime),
        }

    def resource_status(self) -> dict[str, Any]:
        details = self._run_powershell_json(
            """
            $cpu = Get-CimInstance Win32_Processor | Select-Object -First 1 Name, NumberOfCores, NumberOfLogicalProcessors, MaxClockSpeed
            $os = Get-CimInstance Win32_OperatingSystem | Select-Object TotalVisibleMemorySize, FreePhysicalMemory
            $gpu = Get-CimInstance Win32_VideoController | Select-Object Name, AdapterRAM, DriverVersion
            [pscustomobject]@{ cpu = $cpu; os = $os; gpu = $gpu } | ConvertTo-Json -Compress -Depth 5
            """
        ) or {}
        os_block = details.get("os") or {}
        total_kb = int(os_block.get("TotalVisibleMemorySize") or 0)
        free_kb = int(os_block.get("FreePhysicalMemory") or 0)
        return {
            "cpu": {
                "name": (details.get("cpu") or {}).get("Name", platform.processor()),
                "cores": int((details.get("cpu") or {}).get("NumberOfCores") or 0),
                "logical_processors": int((details.get("cpu") or {}).get("NumberOfLogicalProcessors") or (os.cpu_count() or 0)),
                "max_clock_mhz": int((details.get("cpu") or {}).get("MaxClockSpeed") or 0),
            },
            "memory": {
                "total_bytes": total_kb * 1024,
                "free_bytes": free_kb * 1024,
                "used_bytes": max(total_kb - free_kb, 0) * 1024,
            },
            "gpu": [
                {
                    "name": str(item.get("Name", "")),
                    "adapter_ram": int(item.get("AdapterRAM") or 0),
                    "driver_version": str(item.get("DriverVersion", "")),
                }
                for item in self._ensure_list(details.get("gpu"))
                if isinstance(item, dict)
            ],
        }

    def storage_status(self) -> dict[str, Any]:
        drives = list(os.listdrives()) if hasattr(os, "listdrives") else [str(self.config.project_root.drive) + "\\"]
        entries: list[dict[str, Any]] = []
        for drive in drives:
            try:
                usage = shutil.disk_usage(drive)
            except OSError:
                continue
            entries.append(
                {
                    "drive": drive,
                    "total_bytes": usage.total,
                    "used_bytes": usage.used,
                    "free_bytes": usage.free,
                }
            )
        entries.sort(key=lambda item: item["drive"])
        return {"drives": entries}

    def network_status(self) -> dict[str, Any]:
        profiles = self._run_powershell_json(
            """
            Get-NetIPConfiguration | Where-Object { $_.NetAdapter.Status -eq 'Up' } | ForEach-Object {
                [pscustomobject]@{
                    interface_alias = $_.InterfaceAlias
                    profile = $_.NetProfile.Name
                    status = $_.NetAdapter.Status
                    ipv4 = @($_.IPv4Address | ForEach-Object { $_.IPv4Address })
                    gateway = @($_.IPv4DefaultGateway | ForEach-Object { $_.NextHop })
                }
            } | ConvertTo-Json -Compress -Depth 5
            """
        )
        return {
            "hostname": socket.gethostname(),
            "fqdn": socket.getfqdn(),
            "interfaces": [item for item in self._ensure_list(profiles) if isinstance(item, dict)],
        }

    def active_apps(self) -> dict[str, Any]:
        payload = self._run_powershell_json(
            """
            Get-Process | Where-Object { $_.MainWindowTitle } | Sort-Object CPU -Descending | Select-Object -First 12 ProcessName, MainWindowTitle, Id | ConvertTo-Json -Compress
            """
        )
        items = [
            {
                "process_name": str(item.get("ProcessName", "")),
                "window_title": str(item.get("MainWindowTitle", "")),
                "pid": int(item.get("Id") or 0),
            }
            for item in self._ensure_list(payload)
            if isinstance(item, dict)
        ]
        return {"applications": items}

    def recent_files(self, limit: int = 12) -> dict[str, Any]:
        roots = [Path(path) for path in self.config.safety.allowed_read_dirs if Path(path).exists()]
        entries: list[dict[str, Any]] = []
        visited = 0
        skip_names = {".git", ".venv", "__pycache__", "node_modules", "dist", "build", ".runtime", "release"}
        for root in roots:
            for current_root, dirnames, filenames in os.walk(root):
                dirnames[:] = [name for name in dirnames if name not in skip_names and not name.startswith(".")]
                for filename in filenames:
                    visited += 1
                    if visited > 4000:
                        break
                    path = Path(current_root) / filename
                    try:
                        stat = path.stat()
                    except OSError:
                        continue
                    entries.append(
                        {
                            "path": str(path),
                            "name": path.name,
                            "modified_at": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(),
                            "size_bytes": stat.st_size,
                        }
                    )
                if visited > 4000:
                    break
            if visited > 4000:
                break
        entries.sort(key=lambda item: item["modified_at"], reverse=True)
        return {"files": entries[:limit]}

    def _run_powershell_json(self, script: str) -> Any:
        try:
            completed = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                capture_output=True,
                text=True,
                timeout=6,
                check=False,
            )
        except Exception:
            return None
        if completed.returncode != 0:
            return None
        output = completed.stdout.strip()
        if not output:
            return None
        try:
            return json.loads(output)
        except json.JSONDecodeError:
            return None

    def _ensure_list(self, value: Any) -> list[Any]:
        if value is None:
            return []
        if isinstance(value, list):
            return value
        return [value]
