# Soundstage

Media audio follows the screen the player is on.

Park YouTube on the HDMI monitor and it plays from that monitor's speakers. Drag it back to the laptop and it follows. Same for Apple Music, Spotify, mpv, VLC, and other common players.

Laptop speakers stay the default output. Volume keys still control the laptop. Soundstage only moves the media stream that belongs to a matched window.

## Install

```bash
omarchy plugin add https://github.com/paytbidd/omarchy-soundstage.git --enable
~/.config/omarchy/plugins/payton.soundstage/scripts/omarchy-soundstage apply
```

`apply` puts `omarchy-soundstage` on your PATH and retires the earlier one-off `omarchy-monitor-audio` unit if it is present. Enabling the plugin starts the daemon.

## What it matches

**Chromium / Brave webapps** (Omarchy `--app` windows, class like `chrome-youtube.com__-Default`):

YouTube, YouTube Music, Apple Music, Spotify Web, SoundCloud, Tidal, Netflix, Disney+, Hulu, Max, Prime Video, Twitch, Plex, Jellyfin.

**Native players:**

Spotify, mpv, VLC, Celluloid, Haruna, Totem, Amberol, Elisa, Clapper, Strawberry, Rhythmbox, Lollypop, Audacious, Deadbeef, Fooyin, Tauon, cmus, ncspot, Spotube.

It does **not** grab generic Chromium or Firefox tabs. A YouTube tab inside the regular browser shares one audio stream with every other tab, so Soundstage cannot split that.

## Extra apps

`~/.config/omarchy/soundstage.toml`:

```toml
class_contains = ["myplayer.example.com__"]
classes = ["MyPlayer"]
binaries = ["myplayer"]
```

Those lists merge with the built-in catalog. `class_contains` matches a substring of the Hyprland window class. `classes` is an exact class (case-insensitive). `binaries` is `/proc/<pid>/exe` or `comm`.

## Commands

```bash
omarchy-soundstage status   # windows, monitors, and streams
omarchy-soundstage once     # apply routing once
omarchy-soundstage run      # daemon (the plugin service already runs this)
```

## Uninstall

```bash
~/.config/omarchy/plugins/payton.soundstage/scripts/omarchy-soundstage unapply
omarchy plugin remove payton.soundstage
```

`unapply` takes `omarchy-soundstage` off PATH and retires the earlier one-off `omarchy-monitor-audio` unit if it is present. `omarchy plugin remove` uninstalls the plugin.

## Notes

- HDMI volume is independent of the laptop volume keys. If the monitor is quiet, raise that sink (Omarchy audio output switch, or `pactl set-sink-volume`).
- Unplugging the external display restores the laptop speakers as the default output. NVIDIA HDMI audio often stays listed as available after the monitor is gone; Soundstage keys off Hyprland having an external monitor, not that leftover sink, so volume keys keep controlling the laptop.
- Apple Music already uses its own Chromium profile, so it is a distinct stream. YouTube launched as an Omarchy webapp is usually its own process; opening regular Chromium while that window is open can share the process, and then browser audio would follow YouTube.
