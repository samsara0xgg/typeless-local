"""What a fresh install needs before the first F5 does anything useful.

Both concerns here exist only because the app is now handed to people who did
not build it. Without them the first dictation either fails with an opaque
"Retry" because no API key was ever set, or appears to hang for several minutes
while 1.5 GB of Whisper weights download with nothing on screen.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import threading
from typing import Callable

LOGGER = logging.getLogger(__name__)


def write_env_value(path: Path, key: str, value: str) -> None:
    """Set ``KEY=value`` in the env file, replacing any existing line for KEY."""

    lines: list[str] = []
    if path.exists():
        lines = [
            line
            for line in path.read_text(encoding="utf-8").splitlines()
            if not line.strip().startswith(f"{key}=")
        ]
    lines.append(f"{key}={value}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    # The file holds an API key, so it must not be world-readable.
    path.chmod(0o600)


def prompt_for_api_key(env_name: str, model: str, *, existing: bool = False) -> str | None:
    """Ask for the key in a modal alert. None when the user cancels or clears it."""

    from AppKit import (
        NSAlert,
        NSAlertFirstButtonReturn,
        NSApp,
        NSMakeRect,
        NSSecureTextField,
    )

    from typeless_local.brand import display_name, join
    from typeless_local.i18n import t

    alert = NSAlert.alloc().init()
    alert.setMessageText_(
        t("更换 API Key", "Change API Key") if existing else join(display_name(), t("需要一个 API Key", "needs an API key"))
    )
    alert.setInformativeText_(
        t(
            f"润色读取 {env_name}。\n\nKey 存在这台 Mac 的钥匙串里，只会发给模型服务商。",
            f"Refinement reads {env_name}.\n\n"
            "The key is kept in this Mac's keychain and only sent to the model's provider.",
        )
    )
    alert.addButtonWithTitle_(t("保存", "Save"))
    alert.addButtonWithTitle_(t("取消", "Cancel"))
    field = NSSecureTextField.alloc().initWithFrame_(NSMakeRect(0, 0, 320, 24))
    field.setPlaceholderString_(env_name)
    alert.setAccessoryView_(field)
    # An accessory app owns no windows, so its alert opens behind whatever the
    # user is looking at unless the app is pulled forward first.
    NSApp.activateIgnoringOtherApps_(True)
    alert.window().setInitialFirstResponder_(field)
    if alert.runModal() != NSAlertFirstButtonReturn:
        return None
    return str(field.stringValue() or "").strip() or None


def ensure_api_key(env_name: str, model: str, env_path: Path) -> bool:
    """Make ``os.environ[env_name]`` usable, asking once when it is missing."""

    if os.environ.get(env_name):
        return True
    key = prompt_for_api_key(env_name, model)
    if not key:
        LOGGER.warning("No %s provided; refinement fails until one is set.", env_name)
        return False
    return _store_api_key(env_name, key, env_path)


def set_api_key(env_name: str, model: str, env_path: Path) -> bool:
    """Prompt for a replacement key even when one is already set."""

    key = prompt_for_api_key(env_name, model, existing=bool(os.environ.get(env_name)))
    if not key:
        return False
    return _store_api_key(env_name, key, env_path)


def remove_env_value(path: Path, key: str) -> None:
    """Drop ``KEY=`` lines from the env file, so an old key there can't come back."""

    if not path.exists():
        return
    lines = path.read_text(encoding="utf-8").splitlines()
    kept = [line for line in lines if not line.strip().startswith(f"{key}=")]
    if len(kept) != len(lines):
        path.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
        path.chmod(0o600)


def _store_api_key(env_name: str, key: str, env_path: Path) -> bool:
    """Keep the key in the login keychain, or in the env file where there is no keychain."""

    from typeless_local import keychain

    os.environ[env_name] = key
    try:
        if keychain.available() and keychain.is_valid_key(key) and keychain.store_key(env_name, key):
            # The env file is read first at launch, so an older key left there
            # would win over the one just saved.
            remove_env_value(env_path, env_name)
            return True
    except Exception:
        LOGGER.warning("Could not save %s to the keychain; using %s", env_name, env_path, exc_info=True)
    try:
        write_env_value(env_path, env_name, key)
    except OSError:
        # The key still works for this session; only persistence was lost.
        LOGGER.exception("Could not persist %s to %s", env_name, env_path)
    return True


def model_is_cached(repo_id: str) -> bool:
    """Whether the weights are already local, i.e. no download is needed."""

    try:
        from huggingface_hub import snapshot_download

        snapshot_download(repo_id, local_files_only=True)
        return True
    except Exception:
        return False


def download_model(repo_id: str, on_progress: Callable[[float], None]) -> None:
    """Fetch the ASR weights, reporting 0..1 progress until they are in place."""

    from huggingface_hub import snapshot_download

    total = _expected_size(repo_id)
    cache_dir = _cache_dir(repo_id)
    done = threading.Event()
    failure: list[BaseException] = []

    def run() -> None:
        try:
            snapshot_download(repo_id, endpoint=_endpoint())
        except BaseException as exc:  # reported on the caller's thread below
            failure.append(exc)
        finally:
            done.set()

    threading.Thread(target=run, daemon=True, name="model-download").start()

    # ponytail: polls the cache directory rather than hooking hf_hub's tqdm,
    # whose internals move between releases and split per file. Switch to
    # tqdm_class if the byte count ever has to be exact.
    while not done.wait(0.5):
        if total:
            on_progress(min(0.99, _dir_size(cache_dir) / total))
    if failure:
        raise failure[0]
    on_progress(1.0)


def _expected_size(repo_id: str) -> int:
    """Total bytes of the repo's files, or 0 when the API will not say."""

    try:
        from huggingface_hub import HfApi

        info = HfApi(endpoint=_endpoint()).model_info(repo_id, files_metadata=True)
        return sum(int(sibling.size or 0) for sibling in (info.siblings or []))
    except Exception:
        LOGGER.debug("Could not read %s file sizes; progress stays indeterminate", repo_id)
        return 0


def _endpoint() -> str | None:
    """The download source reach.use_model_source picked (Hugging Face or its mirror)."""

    return os.environ.get("HF_ENDPOINT") or None


def _cache_dir(repo_id: str) -> Path:
    try:
        from huggingface_hub.constants import HF_HUB_CACHE

        root = Path(HF_HUB_CACHE)
    except Exception:
        root = Path.home() / ".cache" / "huggingface" / "hub"
    return root / ("models--" + repo_id.replace("/", "--"))


def _dir_size(path: Path) -> int:
    """Bytes currently on disk under ``path``; 0 while it does not exist yet."""

    total = 0
    if not path.exists():
        return 0
    for entry in path.rglob("*"):
        try:
            if entry.is_file():
                total += entry.stat().st_size
        except OSError:
            continue
    return total
