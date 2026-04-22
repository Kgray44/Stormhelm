from __future__ import annotations

from dataclasses import dataclass

from stormhelm.core.intelligence.language import normalize_phrase
from stormhelm.core.software_control.models import SoftwareTarget


@dataclass(frozen=True, slots=True)
class SoftwareCatalogEntry:
    canonical_name: str
    display_name: str
    aliases: tuple[str, ...]
    package_ids: dict[str, str]
    vendor_url: str
    browser_query: str
    launch_names: tuple[str, ...] = ()
    description: str | None = None


_CATALOG: dict[str, SoftwareCatalogEntry] = {
    "firefox": SoftwareCatalogEntry(
        canonical_name="firefox",
        display_name="Firefox",
        aliases=("firefox", "mozilla firefox", "mozilla"),
        package_ids={
            "winget": "Mozilla.Firefox",
            "chocolatey": "firefox",
        },
        vendor_url="https://www.mozilla.org/firefox/new/",
        browser_query="Firefox download",
        launch_names=("firefox",),
        description="Mozilla Firefox web browser.",
    ),
    "chrome": SoftwareCatalogEntry(
        canonical_name="chrome",
        display_name="Chrome",
        aliases=("chrome", "google chrome"),
        package_ids={
            "winget": "Google.Chrome",
            "chocolatey": "googlechrome",
        },
        vendor_url="https://www.google.com/chrome/",
        browser_query="Google Chrome download",
        launch_names=("chrome", "google chrome"),
        description="Google Chrome web browser.",
    ),
    "vscode": SoftwareCatalogEntry(
        canonical_name="vscode",
        display_name="VS Code",
        aliases=("vscode", "vs code", "visual studio code"),
        package_ids={
            "winget": "Microsoft.VisualStudioCode",
            "chocolatey": "vscode",
        },
        vendor_url="https://code.visualstudio.com/download",
        browser_query="VS Code download",
        launch_names=("code", "vscode"),
        description="Visual Studio Code editor.",
    ),
    "discord": SoftwareCatalogEntry(
        canonical_name="discord",
        display_name="Discord",
        aliases=("discord",),
        package_ids={
            "winget": "Discord.Discord",
            "chocolatey": "discord",
        },
        vendor_url="https://discord.com/download",
        browser_query="Discord download",
        launch_names=("discord",),
        description="Discord desktop client.",
    ),
    "minecraft": SoftwareCatalogEntry(
        canonical_name="minecraft",
        display_name="Minecraft",
        aliases=("minecraft", "minecraft launcher", "mojang minecraft"),
        package_ids={
            "winget": "Mojang.MinecraftLauncher",
        },
        vendor_url="https://launcher.mojang.com/download/MinecraftInstaller.msi",
        browser_query="Minecraft download",
        launch_names=("minecraft", "minecraftlauncher"),
        description="Minecraft Launcher from Mojang.",
    ),
    "obs": SoftwareCatalogEntry(
        canonical_name="obs",
        display_name="OBS Studio",
        aliases=("obs", "obs studio", "open broadcaster software"),
        package_ids={
            "winget": "OBSProject.OBSStudio",
        },
        vendor_url="https://obsproject.com/download",
        browser_query="OBS Studio download",
        launch_names=("obs64", "obs"),
        description="OBS Studio livestreaming and recording suite.",
    ),
    "git": SoftwareCatalogEntry(
        canonical_name="git",
        display_name="Git",
        aliases=("git", "git for windows"),
        package_ids={
            "winget": "Git.Git",
        },
        vendor_url="https://git-scm.com/download/win",
        browser_query="Git for Windows download",
        launch_names=("git",),
        description="Git command-line version control client.",
    ),
    "node": SoftwareCatalogEntry(
        canonical_name="node",
        display_name="Node.js",
        aliases=("node", "nodejs", "node.js"),
        package_ids={
            "winget": "OpenJS.NodeJS.LTS",
        },
        vendor_url="https://nodejs.org/en/download",
        browser_query="Node.js LTS download",
        launch_names=("node",),
        description="Node.js LTS runtime.",
    ),
    "python": SoftwareCatalogEntry(
        canonical_name="python",
        display_name="Python",
        aliases=("python", "python 3", "python3"),
        package_ids={},
        vendor_url="https://www.python.org/downloads/windows/",
        browser_query="Python Windows download",
        launch_names=("python", "py"),
        description="Python programming language runtime.",
    ),
}


def find_catalog_target(name: str) -> SoftwareTarget | None:
    normalized = normalize_phrase(name)
    if not normalized:
        return None
    for entry in _CATALOG.values():
        aliases = {normalize_phrase(alias) for alias in entry.aliases}
        if normalized == entry.canonical_name or normalized in aliases:
            return SoftwareTarget(
                canonical_name=entry.canonical_name,
                display_name=entry.display_name,
                aliases=list(entry.aliases),
                package_ids=dict(entry.package_ids),
                vendor_url=entry.vendor_url,
                browser_query=entry.browser_query,
                launch_names=list(entry.launch_names),
                description=entry.description,
            )
    return None


def resolve_catalog_target(name: str) -> SoftwareTarget | None:
    target = find_catalog_target(name)
    if target is not None:
        return target
    normalized = normalize_phrase(name)
    if not normalized:
        return None
    display_name = " ".join(part.capitalize() for part in normalized.split())
    return SoftwareTarget(
        canonical_name=normalized,
        display_name=display_name or normalized,
        aliases=[normalized],
        package_ids={},
        browser_query=f"{display_name or normalized} download",
        launch_names=[normalized],
    )
