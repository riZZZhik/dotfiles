"""Initialize iTerm once, then export selected portable preferences."""

from __future__ import annotations

import json
import plistlib
import re
import subprocess
import tempfile
import uuid
from copy import deepcopy
from pathlib import Path
from urllib.parse import quote
from urllib.request import urlopen

from ..config import path
from .base import STATE, App, write_if_changed


class ITerm(App):
    NAME = "iterm"

    def __init__(self):
        super().__init__()
        self.DOMAIN = self.CONFIG["domain"]
        self.DESTINATION = path(self.CONFIG["destination"])
        self.THEME_LIBRARY = self.CONFIG["theme_library"]
        self.PREFERENCES = Path.home() / "Library/Preferences" / (self.DOMAIN + ".plist")
        self.WATCH_PATHS = (self.PREFERENCES, self.DESTINATION.parent)

    def install(self, *, copy_settings: bool = True) -> None:
        self.install_once(
            self.copy_settings, configured=not copy_settings or self.DESTINATION.exists()
        )

    def read_preferences(self) -> tuple[dict, bytes]:
        raw = subprocess.run(
            ["defaults", "export", self.DOMAIN, "-"], check=True, capture_output=True
        ).stdout
        # Native conversion preserves control characters in hotkey definitions.
        exported = subprocess.run(
            ["plutil", "-convert", "binary1", "-o", "-", "-"],
            input=raw,
            check=True,
            capture_output=True,
        ).stdout
        original = plistlib.loads(exported)
        if not original.get("New Bookmarks"):
            raise RuntimeError("Open iTerm once, then quit it normally and rerun ./install.")
        return original, exported

    def copy_settings(self) -> None:
        original, exported = self.read_preferences()
        if original.get("LoadPrefsFromCustomFolder"):
            raise RuntimeError("Disable iTerm's custom preferences folder before copying presets.")
        running = subprocess.run(
            ["pgrep", "-x", self.CONFIG["process"]], stdout=subprocess.DEVNULL, check=False
        )
        if running.returncode == 0:
            raise RuntimeError(
                "Quit iTerm normally before its first settings copy, then rerun ./install."
            )
        if running.returncode != 1:
            running.check_returncode()
        preferences, profiles = self.build_preferences(original)
        self.save_backup(exported, "preferences", ".plist")
        with tempfile.NamedTemporaryFile(suffix=".plist") as merged:
            merged.write(plistlib.dumps(preferences, fmt=plistlib.FMT_BINARY))
            merged.flush()
            subprocess.run(["defaults", "import", self.DOMAIN, merged.name], check=True)
        if profiles is not None:
            self.write(self.DESTINATION, json.dumps(profiles, indent=2) + "\n")

    def sync(self) -> None:
        original, _ = self.read_preferences()
        profiles = original["New Bookmarks"]
        if not profiles:
            raise ValueError("iTerm has no native profile; keeping its exported settings.")
        known = {profile.get("Guid") for profile in profiles}
        for source in sorted(self.DESTINATION.parent.glob("*.json")):
            for profile in json.loads(source.read_text()).get("Profiles", []):
                if profile.get("Guid") not in known:
                    profiles.append(profile)
                    known.add(profile.get("Guid"))
        guids = {
            profile["Guid"]: f"profile-{index + 1}"
            for index, profile in enumerate(profiles)
            if "Guid" in profile
        }
        # The complete native snapshot stays local, including private commands and paths.
        write_if_changed(
            STATE / "iterm/preferences.plist", plistlib.dumps(original, fmt=plistlib.FMT_BINARY)
        )
        portable = self.portable(original, guids)
        write_if_changed(
            self.SHARED / "settings.json",
            json.dumps({"Preferences": portable}, indent=2, ensure_ascii=False) + "\n",
        )

    def portable(self, data, guids: dict[str, str], key=""):
        if isinstance(data, dict):
            if "Action" in data and isinstance(data.get("Text"), str):
                text = data["Text"]
                if (
                    text not in guids
                    and len(text) > 1
                    and not re.fullmatch(r"(?:0x[0-9a-fA-F]+\s*)+", text)
                ):
                    return None
            result = {}
            private_keys = {
                "Command",
                "Custom Directory",
                "Working Directory",
                "Bound Hosts",
                "Triggers",
                "Initial Text",
                "Environment",
                "Badge Text",
                "Dynamic Profile",
                "PrefsCustomFolder",
                "LoadPrefsFromCustomFolder",
                "Screen",
                "Space",
                "Window Frame",
                "Window Position",
                "Window Size",
                "Window Arrangements",
                "Default Arrangement Name",
                "iTerm Version",
                "HotkeyMigratedFromSingleToMulti",
                "AitermURL",
            }
            for name, value in data.items():
                if (
                    name in private_keys
                    or self.sensitive_key(name)
                    or name.startswith(("NoSync", "NS", "SU", "Apple"))
                ):
                    continue
                exported = self.portable(value, guids, name)
                if exported is not None:
                    result[name] = exported
            return result
        if isinstance(data, list):
            return [
                value for item in data if (value := self.portable(item, guids, key)) is not None
            ]
        if isinstance(data, str):
            if data in guids:
                return guids[data]
            if (
                self.local_data(data)
                or data.startswith(("/", "~/", "file://"))
                or "guid" in key.lower()
                or re.search(r"[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}", data)
            ):
                return None
            return data
        return data if isinstance(data, (int, float, bool)) else None

    def restore_preferences(self, current: dict, saved: dict) -> dict:
        existing = {
            profile.get("Name"): profile
            for profile in current["New Bookmarks"]
            if not profile.get("Dynamic Profile")
        }
        profiles = saved.get("New Bookmarks", [])
        identities = {
            profile["Guid"]: existing.get(profile.get("Name"), {}).get(
                "Guid", str(uuid.uuid4()).upper()
            )
            for profile in profiles
            if "Guid" in profile
        }

        def remap(value):
            if isinstance(value, dict):
                return {key: remap(item) for key, item in value.items()}
            if isinstance(value, list):
                return [remap(item) for item in value]
            return identities.get(value, value) if isinstance(value, str) else value

        def merge(local, shared):
            if isinstance(local, dict) and isinstance(shared, dict):
                return {
                    key: merge(local.get(key), value) if key in shared else value
                    for key, value in (local | shared).items()
                }
            return deepcopy(shared)

        portable = remap(saved)
        restored = merge(
            current, {key: value for key, value in portable.items() if key != "New Bookmarks"}
        )
        imported = [
            merge(existing.get(profile.get("Name"), {}), profile)
            for profile in portable.get("New Bookmarks", [])
        ]
        imported_ids = {profile.get("Guid") for profile in imported}
        restored["New Bookmarks"] = imported + [
            profile
            for profile in current["New Bookmarks"]
            if profile.get("Guid") not in imported_ids
        ]
        return restored

    def build_preferences(self, preferences: dict) -> tuple[dict, dict | None]:
        preferences = deepcopy(preferences)
        settings = json.loads((self.SHARED / "settings.json").read_text())
        if "Preferences" in settings:
            return self.restore_preferences(preferences, settings["Preferences"]), None
        native = [
            profile
            for profile in preferences.get("New Bookmarks", [])
            if profile.get("Guid") != settings["Remote"]["Guid"]
            and not profile.get("Dynamic Profile")
        ]
        if not native:
            raise ValueError("Open iTerm once to create its default profile, then retry.")
        theme = settings.get("Colors") or self.load_theme(preferences, settings["Theme"])
        common = {**settings["Profile"], **theme}
        parent = next(
            (
                profile
                for profile in native
                if profile["Guid"] == preferences.get("Default Bookmark Guid")
            ),
            native[0],
        )
        hotkeys = [profile for profile in native if profile.get("Has Hotkey")]
        if not hotkeys and settings["Hotkey"].get("Has Hotkey", True):
            hotkey = deepcopy(parent)
            hotkey.update({"Name": "Hotkey Window", "Guid": str(uuid.uuid4()).upper()})
            preferences["New Bookmarks"].append(hotkey)
            native.append(hotkey)
            hotkeys.append(hotkey)
        for profile in native:
            self.apply_profile_settings(profile, common)
        for profile in hotkeys:
            self.apply_profile_settings(profile, settings["Hotkey"])
        global_settings = deepcopy(settings["Global"])
        keymap = global_settings.pop("GlobalKeyMap", {})
        preferences.update(global_settings)
        preferences.setdefault("GlobalKeyMap", {}).update(keymap)
        preferences.setdefault("Custom Color Presets", {})[settings["Theme"]] = theme
        remote = {**common, **settings["Remote"]}
        remote["Dynamic Profile Parent GUID"] = parent["Guid"]
        return preferences, {"Profiles": [remote]}

    def apply_profile_settings(self, profile: dict, settings: dict) -> None:
        values = deepcopy(settings)
        keymap = values.pop("Keyboard Map", {})
        for action in keymap.values():
            if action.get("Text") == "$PROFILE_GUID":
                action["Text"] = profile["Guid"]
        profile.update(values)
        profile.setdefault("Keyboard Map", {}).update(keymap)

    def load_theme(self, preferences: dict, name: str) -> dict:
        preset = preferences.get("Custom Color Presets", {}).get(name)
        if preset is not None:
            return preset
        cache = STATE / self.CONFIG["theme_cache"] / f"{quote(name, safe='')}.json"
        if cache.exists():
            return json.loads(cache.read_text())
        with urlopen(
            f"{self.THEME_LIBRARY}{quote(name)}.itermcolors",
            timeout=self.CONFIG["theme_timeout_seconds"],
        ) as response:
            theme = plistlib.loads(response.read())
        write_if_changed(cache, json.dumps(theme))
        return theme
