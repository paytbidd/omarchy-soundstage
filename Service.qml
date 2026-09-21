import QtQuick
import Quickshell.Io

// Headless host. The Python daemon routes media streams to the
// speakers of the monitor the player window is on.
Item {
  id: root

  readonly property string pluginDir: {
    var s = String(Qt.resolvedUrl("./"))
    if (s.indexOf("file://") === 0)
      s = s.substring(7)
    return s
  }

  Process {
    id: daemon
    running: true
    command: [root.pluginDir + "scripts/omarchy-soundstage", "run"]
    onExited: restart.restart()
  }

  Timer {
    id: restart
    interval: 1500
    repeat: false
    onTriggered: daemon.running = true
  }
}
