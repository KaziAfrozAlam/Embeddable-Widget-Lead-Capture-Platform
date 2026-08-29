import hashlib
from pathlib import Path

_RENDERER = Path(__file__).parent / "renderer" / "widget.js"


def _bundle_hash() -> str:
    return hashlib.sha1(_RENDERER.read_bytes()).hexdigest()[:10]


# New renderer release = new URL (e.g. w<sha1>), so browsers can cache the
# bundle forever without ever serving stale code.
WIDGET_SCRIPT_VERSION = "w" + _bundle_hash()