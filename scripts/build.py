#!/usr/bin/env python3
"""Build the native amd64 FPK from the package sources and locked Debian inputs."""
import argparse
import base64
import concurrent.futures
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tarfile
import tempfile
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor" / "novnc"


def download(pkg, cache):
    archive = cache / Path(pkg["path"]).name
    urls = (
        "https://deb.debian.org/debian/" + pkg["path"],
        "https://snapshot.debian.org/file/" + pkg["snapshot"],
    )
    if archive.is_file() and hashlib.sha256(archive.read_bytes()).hexdigest() == pkg["sha256"]:
        return archive
    for url in urls:
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                content = response.read()
            if hashlib.sha256(content).hexdigest() != pkg["sha256"]:
                raise ValueError("SHA-256 mismatch: " + url)
            with tempfile.NamedTemporaryFile(dir=cache, delete=False) as output:
                output.write(content)
            Path(output.name).replace(archive)
            return archive
        except (OSError, ValueError) as exc:
            print(f"{archive.name}: {exc}", flush=True)
    raise RuntimeError("Could not obtain the pinned archive: " + archive.name)


def destination(path, name):
    if path.parent == PurePosixPath("usr/bin") and path.name in ("Xtigervnc", "openbox"):
        return Path("bin") / path.name
    library_roots = ("usr/lib/x86_64-linux-gnu", "lib/x86_64-linux-gnu")
    if path.name == "testfilter.so":
        return None
    if any(path.is_relative_to(root) for root in library_roots) and ".so" in path.name:
        return Path("lib") / path.name
    if path.is_relative_to("usr/lib/python3/dist-packages"):
        return Path("python") / path.relative_to("usr/lib/python3/dist-packages")
    if path == PurePosixPath("usr/share/doc", name, "copyright"):
        return Path("licenses") / name
    for directory in ("usr/share/openbox", "usr/share/themes/Clearlooks", "usr/share/tigervnc"):
        if path.is_relative_to(directory):
            return Path("share") / path.relative_to("usr/share")
    return None


def unpack(pkg, archive, runtime):
    # ar is provided by binutils on Linux and by the developer tools on macOS.
    members = subprocess.check_output(["ar", "t", archive], text=True).splitlines()
    member = next(m for m in members if m.startswith("data.tar"))
    data = subprocess.check_output(["ar", "p", archive, member])
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        for item in tar:
            path = PurePosixPath(item.name)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError(f"Unexpected archive path: {path}")
            rel = destination(path, pkg["name"])
            if rel is None or not (item.isfile() or (item.issym() and rel.parent == Path("lib"))):
                continue
            target = runtime / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(item) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            target.chmod(0o755 if item.mode & 0o111 else 0o644)


def build(fnpack, cache, out):
    packages = json.loads((ROOT / "scripts/runtime-lock.json").read_text())
    cache.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        package = work / "fnos-qq"
        shutil.copytree(ROOT / "package", package)
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            archives = pool.map(lambda pkg: download(pkg, cache), packages)
            for pkg, archive in zip(packages, archives):
                unpack(pkg, archive, package / "app/runtime")

        native = package / "app/native"
        css = (native / "screen.css").read_text()
        icon = base64.b64encode((native / "penguin.png").read_bytes()).decode()
        bundle = (VENDOR / "rfb.min.js").read_text()
        for name in ("setup.html", "index.html"):
            path = native / name
            page = path.read_text().replace("{{SCREEN_CSS}}", css).replace("{{PENGUIN_URI}}", "data:image/png;base64," + icon)
            path.write_text(page.replace("{{NOVNC_BUNDLE}}", bundle))
        (native / "screen.css").unlink()
        (native / "penguin.png").unlink()
        shutil.copy2(VENDOR / "COPYRIGHT", native / "noVNC-LICENSE")
        shutil.copy2(ROOT / "scripts/runtime-lock.json", package / "app/runtime/licenses/packages.json")

        manifest = dict(line.split("=", 1) for line in (package / "manifest").read_text().splitlines() if "=" in line)
        version = {k.strip(): v.strip() for k, v in manifest.items()}["version"]
        subprocess.run([fnpack, "build", "-d", str(package)], cwd=work, check=True)
        artifact = out / f"fnos-qq-{version}-amd64.fpk"
        shutil.copyfile(work / "fnos-qq.fpk", artifact)
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        artifact.with_suffix(".fpk.sha256").write_text(f"{digest}  {artifact.name}\n")
        print(artifact)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fnpack", default=os.environ.get("FNPACK", "fnpack"))
    parser.add_argument("--cache", type=Path, default=ROOT / ".cache")
    parser.add_argument("--out", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    tool = shutil.which(args.fnpack)
    if not tool:
        parser.error("fnpack is required; see README.md")
    build(str(Path(tool).resolve()), args.cache.resolve(), args.out.resolve())
