"""Copy the deployable static assets from the sibling frontend checkout."""

from pathlib import Path
from shutil import copyfile

PUBLIC_ASSETS = (
    "admin.css", "admin.html", "chat.css", "chat.js", "config.js", "icons.svg", "index.html",
    "login.css", "login.html", "login.js", "stats.html",
)


def stage() -> None:
    backend = Path(__file__).resolve().parent
    frontend = backend.parent / "FrontEnd_ChatBot"
    destination = backend / "web"
    assets = [frontend / name for name in PUBLIC_ASSETS]
    if not all(asset.is_file() for asset in assets):
        raise SystemExit("Complete the sibling FrontEnd_ChatBot checkout first.")

    destination.mkdir(exist_ok=True)
    unexpected = {asset.name for asset in destination.iterdir()} - set(PUBLIC_ASSETS)
    if unexpected:
        raise SystemExit(f"Unexpected files in web/: {', '.join(sorted(unexpected))}")
    for asset in assets:
        copyfile(asset, destination / asset.name)
    print(f"Staged {len(assets)} public assets under {destination}")


if __name__ == "__main__":
    stage()
