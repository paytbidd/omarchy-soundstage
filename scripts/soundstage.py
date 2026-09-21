#!/usr/bin/env python3
"""Soundstage: media audio follows the screen the player is on."""

from __future__ import annotations

import fcntl
import json
import logging
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

PLUGIN_ID = "payton.soundstage"
SKIP_APPS = {"EasyEffects"}
DEBOUNCE_S = 0.15
POLL_S = 2.0
CMD_TIMEOUT = 2.0

# Chromium --app webapps use class chrome-<host>__-Default (Brave similar).
CLASS_CONTAINS = (
    "youtube.com__",
    "youtu.be__",
    "music.youtube.com__",
    "music.apple.com__",
    "open.spotify.com__",
    "play.spotify.com__",
    "spotify.com__",
    "soundcloud.com__",
    "listen.tidal.com__",
    "music.amazon.",
    "netflix.com__",
    "disneyplus.com__",
    "hulu.com__",
    "max.com__",
    "primevideo.com__",
    "twitch.tv__",
    "app.plex.tv__",
    "plex.tv__",
    "jellyfin.",
    "music.youtube.",
)

# Native players and the official Spotify client.
CLASSES = {
    "mpv",
    "vlc",
    "spotify",
    "org.videolan.vlc",
    "com.spotify.client",
    "io.github.celluloid_player.celluloid",
    "celluloid",
    "org.kde.haruna",
    "org.gnome.totem",
    "io.bassi.amberol",
    "org.kde.elisa",
    "com.github.rafostar.clapper",
    "tauon music box",
    "deadbeef",
    "audacious",
    "strawberry",
    "rhythmbox",
    "org.gnome.rhythmbox3",
    "fooyin",
    "cmus",
    "ncspot",
    "spotube",
    "nuclear",
    "lollypop",
    "org.gnome.lollypop",
    "io.github.quodlibet.quodlibet",
    "quodlibet",
}

BINARIES = {
    "mpv",
    "vlc",
    "spotify",
    "celluloid",
    "haruna",
    "totem",
    "amberol",
    "elisa",
    "clapper",
    "tauon",
    "deadbeef",
    "audacious",
    "strawberry",
    "rhythmbox",
    "fooyin",
    "cmus",
    "ncspot",
    "spotube",
    "lollypop",
    "quodlibet",
}

LABEL_MARKERS = (
    ("music.apple.com__", "Apple Music"),
    ("music.youtube.com__", "YouTube Music"),
    ("youtube.com__", "YouTube"),
    ("youtu.be__", "YouTube"),
    ("spotify", "Spotify"),
    ("soundcloud.com__", "SoundCloud"),
    ("tidal.com__", "Tidal"),
    ("netflix.com__", "Netflix"),
    ("twitch.tv__", "Twitch"),
    ("plex", "Plex"),
    ("jellyfin", "Jellyfin"),
)

USER_CONFIG = Path.home() / ".config/omarchy/soundstage.toml"
OLD_UNIT = "omarchy-monitor-audio.service"
OLD_BIN = Path.home() / ".local/bin/omarchy-monitor-audio"

log = logging.getLogger("soundstage")


def plugin_dir() -> Path:
    return Path(__file__).resolve().parent.parent


def runtime_dir() -> Path:
    return Path(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}")


def lock_path() -> Path:
    return runtime_dir() / "omarchy-soundstage.lock"


def run(args: list[str], *, timeout: float = CMD_TIMEOUT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def load_user_matchers() -> tuple[tuple[str, ...], set[str], set[str]]:
    extra_contains: list[str] = []
    extra_classes: set[str] = set()
    extra_binaries: set[str] = set()
    if USER_CONFIG.is_file():
        try:
            import tomllib

            data = tomllib.loads(USER_CONFIG.read_text(encoding="utf-8"))
        except Exception as exc:
            log.warning("ignoring %s: %s", USER_CONFIG, exc)
            data = {}
        extra_contains = [str(x) for x in (data.get("class_contains") or [])]
        extra_classes = {str(x).lower() for x in (data.get("classes") or [])}
        extra_binaries = {str(x).lower() for x in (data.get("binaries") or [])}
    contains = CLASS_CONTAINS + tuple(extra_contains)
    classes = {c.lower() for c in CLASSES} | extra_classes
    binaries = {b.lower() for b in BINARIES} | extra_binaries
    return contains, classes, binaries


def class_of(client: dict) -> str:
    return str(client.get("class") or client.get("initialClass") or "")


def process_comm(pid: int) -> str:
    try:
        return Path(f"/proc/{pid}/comm").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def process_binary(pid: int) -> str:
    try:
        return Path(os.readlink(f"/proc/{pid}/exe")).name.lower()
    except OSError:
        return process_comm(pid).lower()


def is_media_client(
    client: dict,
    class_contains: tuple[str, ...],
    classes: set[str],
    binaries: set[str],
) -> bool:
    klass = class_of(client)
    lowered = klass.lower()
    if any(marker.lower() in lowered for marker in class_contains):
        return True
    if lowered in classes:
        return True
    try:
        pid = int(client.get("pid") or 0)
    except (TypeError, ValueError):
        pid = 0
    if pid > 0:
        binary = process_binary(pid)
        if binary in binaries or binary.removesuffix(".bin") in binaries:
            return True
        comm = process_comm(pid).lower()
        if comm in binaries:
            return True
    return False


def label_for(client: dict) -> str:
    klass = class_of(client).lower()
    for marker, label in LABEL_MARKERS:
        if marker in klass:
            return label
    klass_raw = class_of(client)
    if klass_raw:
        return klass_raw
    return "media"


def hypr_json(what: str) -> list | dict | None:
    try:
        proc = run(["hyprctl", "-j", what])
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None


def pactl_json(args: list[str]) -> list | dict | None:
    try:
        proc = run(["pactl", "--format=json", *args])
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None


def laptop_monitor_name(monitors: list[dict]) -> str:
    try:
        proc = run(["omarchy-hyprland-monitor-laptop"])
        name = (proc.stdout or "").strip()
        if name:
            return name
    except (OSError, subprocess.TimeoutExpired):
        pass
    for mon in monitors:
        name = str(mon.get("name") or "")
        if name.startswith(("eDP-", "LVDS-", "DSI-")):
            return name
    return "eDP-1"


def sink_available(sink: dict) -> bool:
    ports = sink.get("ports") or []
    if not ports:
        return True
    return any(p.get("availability") != "not available" for p in ports)


def classify_sinks(sinks: list[dict]) -> tuple[str | None, str | None]:
    analog = None
    hdmi = None
    for sink in sinks:
        if not sink_available(sink):
            continue
        name = sink.get("name") or ""
        props = sink.get("properties") or {}
        profile = str(props.get("device.profile.name") or "")
        form = str(props.get("device.form_factor") or "")
        if form == "internal" or "analog" in profile or ".analog-" in name:
            analog = analog or name
        if "hdmi" in profile.lower() or ".hdmi" in name:
            hdmi = hdmi or name
    return analog, hdmi


def laptop_sink(analog: str | None, hdmi: str | None, default: str | None) -> str | None:
    if default and default != hdmi:
        return default
    return analog


def default_sink_name() -> str | None:
    try:
        proc = run(["pactl", "get-default-sink"])
        return (proc.stdout or "").strip() or None
    except (OSError, subprocess.TimeoutExpired):
        return None


def proc_children() -> dict[int, list[int]]:
    children: dict[int, list[int]] = {}
    try:
        entries = os.listdir("/proc")
    except OSError:
        return children
    for entry in entries:
        if not entry.isdigit():
            continue
        pid = int(entry)
        try:
            with open(f"/proc/{pid}/stat", encoding="utf-8") as fh:
                stat = fh.read()
        except OSError:
            continue
        end = stat.rfind(")")
        if end < 0:
            continue
        parts = stat[end + 2 :].split()
        if len(parts) < 2:
            continue
        try:
            ppid = int(parts[1])
        except ValueError:
            continue
        children.setdefault(ppid, []).append(pid)
    return children


def descendants(root: int, children: dict[int, list[int]]) -> set[int]:
    seen = {root}
    stack = [root]
    while stack:
        pid = stack.pop()
        for child in children.get(pid, ()):
            if child not in seen:
                seen.add(child)
                stack.append(child)
    return seen


def monitor_for_client(client: dict, monitors: list[dict]) -> dict | None:
    by_id = {m.get("id"): m for m in monitors}
    by_name = {m.get("name"): m for m in monitors}
    raw = client.get("monitor")
    if isinstance(raw, int) or (isinstance(raw, str) and raw.isdigit()):
        return by_id.get(int(raw))
    if isinstance(raw, str) and raw:
        return by_name.get(raw)
    return None


def tracked_clients(
    clients: list[dict],
    class_contains: tuple[str, ...] | None = None,
    classes: set[str] | None = None,
    binaries: set[str] | None = None,
) -> list[dict]:
    if class_contains is None or classes is None or binaries is None:
        class_contains, classes, binaries = load_user_matchers()
    return [
        client
        for client in clients
        if is_media_client(client, class_contains, classes, binaries)
    ]


def target_for_monitor(
    mon: dict | None,
    laptop: str,
    hdmi: str | None,
    internal: str | None,
) -> tuple[str | None, str]:
    mon_name = str((mon or {}).get("name") or "")
    disabled = bool((mon or {}).get("disabled"))
    external = bool(mon_name and mon_name != laptop and not disabled and hdmi)
    target = hdmi if external else internal
    return target, mon_name or laptop


def prefer_external(
    existing: tuple[str, str, str] | None,
    candidate: tuple[str, str, str],
    hdmi: str | None,
) -> tuple[str, str, str]:
    if existing is None:
        return candidate
    if hdmi and existing[0] == hdmi:
        return existing
    if hdmi and candidate[0] == hdmi:
        return candidate
    return candidate


def move_input(index: int, sink_name: str) -> bool:
    try:
        proc = run(["pactl", "move-sink-input", str(index), sink_name])
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def apply_once() -> list[str]:
    actions: list[str] = []
    monitors = hypr_json("monitors") or []
    clients = hypr_json("clients") or []
    sinks = pactl_json(["list", "sinks"]) or []
    inputs = pactl_json(["list", "sink-inputs"]) or []
    if not isinstance(monitors, list) or not isinstance(clients, list):
        return actions
    if not isinstance(sinks, list) or not isinstance(inputs, list):
        return actions

    analog, hdmi = classify_sinks(sinks)
    internal = laptop_sink(analog, hdmi, default_sink_name())
    laptop = laptop_monitor_name(monitors)
    sinks_by_index = {s.get("index"): s.get("name") for s in sinks}
    cmap = proc_children()
    contains, classes, binaries = load_user_matchers()

    pid_to_target: dict[int, tuple[str, str, str]] = {}
    for client in tracked_clients(clients, contains, classes, binaries):
        try:
            pid = int(client.get("pid") or 0)
        except (TypeError, ValueError):
            continue
        if pid <= 0:
            continue
        target, mon_name = target_for_monitor(
            monitor_for_client(client, monitors), laptop, hdmi, internal
        )
        if not target:
            continue
        mapping = (target, label_for(client), mon_name)
        for member in descendants(pid, cmap):
            pid_to_target[member] = prefer_external(pid_to_target.get(member), mapping, hdmi)

    for stream in inputs:
        props = stream.get("properties") or {}
        app = props.get("application.name") or ""
        if not app or app in SKIP_APPS:
            continue
        try:
            spid = int(props.get("application.process.id") or 0)
        except (TypeError, ValueError):
            continue
        mapping = pid_to_target.get(spid)
        if not mapping:
            continue
        target, label, mon_name = mapping
        index = stream.get("index")
        current = sinks_by_index.get(stream.get("sink"))
        if index is None or not target or current == target:
            continue
        if move_input(int(index), target):
            msg = f"{label} on {mon_name}: stream #{index} -> {target}"
            actions.append(msg)
            log.info(msg)
    return actions


def status_text() -> str:
    monitors = hypr_json("monitors") or []
    clients = hypr_json("clients") or []
    sinks = pactl_json(["list", "sinks"]) or []
    inputs = pactl_json(["list", "sink-inputs"]) or []
    analog, hdmi = classify_sinks(sinks if isinstance(sinks, list) else [])
    internal = laptop_sink(analog, hdmi, default_sink_name())
    laptop = laptop_monitor_name(monitors if isinstance(monitors, list) else [])
    cmap = proc_children()
    sinks_by_index = {
        s.get("index"): s.get("name") for s in (sinks if isinstance(sinks, list) else [])
    }
    lines = [
        f"laptop monitor: {laptop}",
        f"laptop sink:    {internal or '-'}",
        f"hdmi sink:      {hdmi or '-'}",
        "",
    ]
    if not isinstance(clients, list):
        return "\n".join(lines) + "no hyprland clients\n"
    tracked = tracked_clients(clients)
    if not tracked:
        lines.append("no matching media windows")
        return "\n".join(lines) + "\n"
    for client in tracked:
        try:
            pid = int(client.get("pid") or 0)
        except (TypeError, ValueError):
            pid = 0
        mon = monitor_for_client(client, monitors if isinstance(monitors, list) else [])
        mon_name = str((mon or {}).get("name") or "?")
        tree = descendants(pid, cmap) if pid else set()
        streams = []
        for stream in inputs if isinstance(inputs, list) else []:
            props = stream.get("properties") or {}
            try:
                spid = int(props.get("application.process.id") or 0)
            except (TypeError, ValueError):
                continue
            if spid in tree:
                streams.append(
                    f"#{stream.get('index')} on {sinks_by_index.get(stream.get('sink')) or stream.get('sink')}"
                )
        lines.append(
            f"{label_for(client):<14} pid={pid:<7} monitor={mon_name:<10} "
            f"{', '.join(streams) if streams else 'no stream yet'}"
        )
    return "\n".join(lines) + "\n"


def hypr_socket2() -> Path | None:
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    if sig:
        path = runtime_dir() / "hypr" / sig / ".socket2.sock"
        if path.exists():
            return path
    hypr = runtime_dir() / "hypr"
    if not hypr.is_dir():
        return None
    matches = sorted(hypr.glob("*/.socket2.sock"))
    return matches[-1] if matches else None


def watch_hypr(wake: threading.Event, stop: threading.Event) -> None:
    while not stop.is_set():
        path = hypr_socket2()
        if path is None:
            stop.wait(1.0)
            continue
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.connect(str(path))
            sock.settimeout(1.0)
            buf = b""
            while not stop.is_set():
                try:
                    chunk = sock.recv(4096)
                except socket.timeout:
                    continue
                except OSError:
                    break
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if line:
                        wake.set()
        except OSError:
            stop.wait(1.0)
        finally:
            try:
                sock.close()
            except OSError:
                pass


def watch_pactl(wake: threading.Event, stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            proc = subprocess.Popen(
                ["pactl", "subscribe"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
        except OSError:
            stop.wait(1.0)
            continue
        try:
            assert proc.stdout is not None
            while not stop.is_set():
                line = proc.stdout.readline()
                if not line:
                    break
                if "sink-input" in line or "sink " in line:
                    wake.set()
        finally:
            proc.kill()
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                proc.terminate()


def acquire_lock() -> int:
    fd = os.open(str(lock_path()), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        raise
    os.write(fd, f"{os.getpid()}\n".encode())
    return fd


def run_daemon() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        lock_fd = acquire_lock()
    except BlockingIOError:
        log.error("Soundstage is already running")
        return 1
    wake = threading.Event()
    stop = threading.Event()
    threading.Thread(target=watch_hypr, args=(wake, stop), daemon=True).start()
    threading.Thread(target=watch_pactl, args=(wake, stop), daemon=True).start()
    log.info("Soundstage: media audio follows the player window")
    apply_once()
    last_poll = time.monotonic()
    try:
        while True:
            triggered = wake.wait(timeout=POLL_S)
            if triggered:
                time.sleep(DEBOUNCE_S)
                wake.clear()
            now = time.monotonic()
            if triggered or now - last_poll >= POLL_S:
                last_poll = now
                try:
                    apply_once()
                except Exception:
                    log.exception("failed to apply Soundstage routing")
    except KeyboardInterrupt:
        stop.set()
        return 0
    finally:
        os.close(lock_fd)


def local_bin() -> Path:
    return Path.home() / ".local/bin"


def cli_link() -> Path:
    return local_bin() / "omarchy-soundstage"


def cli_script() -> Path:
    return plugin_dir() / "scripts" / "omarchy-soundstage"


def stop_old_unit() -> None:
    run(["systemctl", "--user", "disable", "--now", OLD_UNIT], timeout=5)
    unit = Path.home() / ".config/systemd/user" / OLD_UNIT
    if unit.is_file():
        unit.unlink()
        run(["systemctl", "--user", "daemon-reload"], timeout=5)
    if OLD_BIN.is_file() or OLD_BIN.is_symlink():
        OLD_BIN.unlink()


def cmd_apply() -> int:
    stop_old_unit()
    local_bin().mkdir(parents=True, exist_ok=True)
    src = cli_script()
    if not src.is_file():
        print(f"missing {src}", file=sys.stderr)
        return 1
    dest = cli_link()
    if dest.exists() or dest.is_symlink():
        dest.unlink()
    dest.symlink_to(src)
    print("Soundstage CLI is on PATH as omarchy-soundstage.")
    print("The plugin service starts the daemon when it is enabled.")
    return 0


def cmd_unapply(*, purge: bool) -> int:
    dest = cli_link()
    if dest.is_symlink():
        try:
            target = str(dest.resolve())
        except OSError:
            target = ""
        if "payton.soundstage" in target or "omarchy-soundstage" in target:
            dest.unlink()
    stop_old_unit()
    if purge:
        run(["omarchy", "plugin", "remove", PLUGIN_ID, "--yes"], timeout=30)
    print("Soundstage unapplied.")
    return 0


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "run"
    if cmd in {"-h", "--help", "help"}:
        print("Usage: omarchy-soundstage [run|once|status|apply|unapply]")
        return 0
    if cmd == "status":
        sys.stdout.write(status_text())
        return 0
    if cmd == "once":
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
        actions = apply_once()
        if not actions:
            sys.stdout.write(status_text())
        return 0
    if cmd == "run":
        return run_daemon()
    if cmd == "apply":
        return cmd_apply()
    if cmd == "unapply":
        return cmd_unapply(purge="--purge" in argv[2:])
    print(f"unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv))
    except subprocess.TimeoutExpired:
        raise SystemExit(1)
