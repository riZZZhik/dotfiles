"""Install Ubuntu packages and upstream CLI release binaries."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import pwd
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

from .config import ROOT, Package

# Upstream release assets avoid Ubuntu's older shell-integration interfaces.
REPOSITORIES = {
    "atuin": "atuinsh/atuin",
    "fzf": "junegunn/fzf",
    "sheldon": "rossmacarthur/sheldon",
    "starship": "starship/starship",
    "zoxide": "ajeetdsouza/zoxide",
    "delta": "dandavison/delta",
    "lazygit": "jesseduffield/lazygit",
    "dust": "bootandy/dust",
}


def privileged(*command: str) -> None:
    prefix = [] if os.geteuid() == 0 else ["sudo"]
    subprocess.run([*prefix, *command], check=True)


def set_zsh_default() -> None:
    shell = Path("/usr/bin/zsh")
    if not os.access(shell, os.X_OK):
        raise RuntimeError("Install zsh before setting it as the default shell.")
    account = pwd.getpwuid(os.getuid())
    # /bin/zsh and /usr/bin/zsh can refer to the same Ubuntu executable.
    if Path(account.pw_shell).resolve() == shell.resolve():
        return
    privileged("chsh", "-s", str(shell), account.pw_name)
    print("Default shell set to zsh. Open a new terminal to use it.")


def asset_name(tool: str, version: str, architecture: str) -> str:
    machine = {"x86_64": "x86_64", "aarch64": "aarch64", "arm64": "aarch64"}.get(architecture)
    if machine is None:
        raise ValueError(f"Unsupported Linux architecture: {architecture}")
    short = "amd64" if machine == "x86_64" else "arm64"
    if tool == "fzf":
        return f"fzf-{version.removeprefix('v')}-linux_{short}.tar.gz"
    if tool == "lazygit":
        return f"lazygit_{version.removeprefix('v')}_linux_{short if short == 'arm64' else 'x86_64'}.tar.gz"
    if tool == "dust":
        return f"dust-{version}-{machine}-unknown-linux-gnu.tar.gz"
    if tool in {"atuin", "delta"}:
        return f"{tool}-{version.removeprefix('v') + '-' if tool == 'delta' else ''}{machine}-unknown-linux-gnu.tar.gz"
    if tool == "starship":
        return f"starship-{machine}-unknown-linux-musl.tar.gz"
    return f"{tool}-{version.removeprefix('v')}-{machine}-unknown-linux-musl.tar.gz"


def download(url: str, target: Path) -> None:
    subprocess.run(
        [
            "curl",
            "--fail",
            "--location",
            "--retry",
            "3",
            "--silent",
            "--show-error",
            url,
            "-o",
            str(target),
        ],
        check=True,
    )


def install_release(tool: str) -> None:
    destination = Path.home() / ".local/bin" / tool
    state = Path.home() / ".local/state/dotfiles/packages" / (tool + ".json")
    if destination.is_file() and state.exists():
        return
    if tool == "codex":
        # The supported installer includes sandbox/code-mode helpers and owns
        # atomic package selection; installing only the CLI binary is incomplete.
        with tempfile.TemporaryDirectory(prefix="dotfiles-codex-") as directory:
            script = Path(directory) / "install.sh"
            download("https://chatgpt.com/codex/install.sh", script)
            subprocess.run(
                ["sh", str(script)],
                check=True,
                env={
                    **os.environ,
                    "CODEX_NON_INTERACTIVE": "1",
                    "CODEX_INSTALL_DIR": str(destination.parent),
                    # Match the other CLI downloads; the alternate mirror can
                    # time out even when GitHub Releases is reachable.
                    "CODEX_INSTALLER_USE_RELEASES_OPENAI_COM": os.environ.get(
                        "CODEX_INSTALLER_USE_RELEASES_OPENAI_COM", "0"
                    ),
                },
            )
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(json.dumps({"installer": "official"}) + "\n")
        return
    repository = REPOSITORIES[tool]
    with tempfile.TemporaryDirectory(prefix="dotfiles-release-") as directory:
        temporary = Path(directory)
        metadata = temporary / "release.json"
        download(f"https://api.github.com/repos/{repository}/releases/latest", metadata)
        release = json.loads(metadata.read_text())
        name = asset_name(tool, release["tag_name"], platform.machine())
        asset = next((item for item in release["assets"] if item["name"] == name), None)
        if asset is None:
            raise RuntimeError(f"No {name} in {repository} release {release['tag_name']}")
        print(f"Downloading {tool} {release['tag_name']}", flush=True)
        archive = temporary / "release.tar.gz"
        download(asset["browser_download_url"], archive)
        digest = asset.get("digest")
        if digest and digest != "sha256:" + hashlib.sha256(archive.read_bytes()).hexdigest():
            raise RuntimeError(f"Checksum mismatch for {name}")
        with tarfile.open(archive) as bundle:
            binaries = [
                member
                for member in bundle.getmembers()
                if member.isfile() and (Path(member.name).name == tool)
            ]
            if len(binaries) != 1:
                raise RuntimeError(f"Expected one {tool} executable in {name}")
            binary = temporary / tool
            with bundle.extractfile(binaries[0]) as source, binary.open("wb") as output:
                shutil.copyfileobj(source, output)
        binary.chmod(0o755)
        subprocess.run([str(binary), "--version"], check=True, stdout=subprocess.DEVNULL)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() or destination.is_symlink():
            directory = ROOT / ".private/backups/packages"
            directory.mkdir(parents=True, exist_ok=True)
            backup = Path(tempfile.mkdtemp(prefix="backup-", dir=directory)) / tool
            shutil.copy2(destination, backup, follow_symlinks=False)
            print(f"Preserved {destination} at {backup}")
        # Copy within the destination filesystem before atomic replacement.
        with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as output:
            pending = Path(output.name)
        try:
            shutil.copy2(binary, pending)
            pending.replace(destination)
        finally:
            pending.unlink(missing_ok=True)
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(json.dumps({"version": release["tag_name"], "asset": name}) + "\n")
        print(f"Installed {tool} {release['tag_name']}")


def install_packages(packages: tuple[Package, ...]) -> None:
    ubuntu = platform.freedesktop_os_release()
    if ubuntu.get("ID") != "ubuntu":
        raise RuntimeError("Linux installation currently supports Ubuntu only.")
    apt = [package.name for package in packages if package.kind == "apt"]
    if apt:
        privileged("apt-get", "install", "-y", *apt)
    # Debian/Ubuntu rename these commands. Keep aliases local, never alter /usr/bin.
    binary_directory = Path.home() / ".local/bin"
    binary_directory.mkdir(parents=True, exist_ok=True)
    for name, actual in (("fd", "fdfind"), ("bat", "batcat")):
        destination = binary_directory / name
        if not shutil.which(name) and (source := shutil.which(actual)):
            destination.symlink_to(source)
    for package in packages:
        if package.kind == "release":
            install_release(package.name)
