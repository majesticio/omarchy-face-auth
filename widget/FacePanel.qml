import QtQuick
import QtQuick.Effects
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui
import "." as FaceComponents

Panel {
  id: root
  moduleName: "io.github.majesticio.face-auth"
  ipcTarget: moduleName
  manageIpc: false
  property var authStatus: ({known: false})
  property string message: ""
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  function refresh() { if (!statusProcess.running) statusProcess.running = true }
  function changeEnabled() {
    if (!authStatus.known || changeProcess.running) return
    message = ""
    changeProcess.command = ["/usr/bin/pkexec", "/usr/lib/omarchy-face-auth/backend.py", "manage"]
    root.close()
    changeProcess.running = true
  }
  IpcHandler {
    target: root.ipcTarget
    function open(): void { root.open() }
    function close(): void { root.close() }
    function toggle(): void { root.toggle() }
    function status(): string { return JSON.stringify(root.authStatus) }
  }
  Component.onCompleted: refresh()
  onOpenedChanged: if (opened) refresh()

  Process {
    id: statusProcess
    command: ["/usr/bin/python3", Qt.resolvedUrl("status.py").toString().replace("file://", "")]
    stdout: StdioCollector {
      onStreamFinished: {
        try { root.authStatus = JSON.parse(text) }
        catch (e) { root.authStatus = ({known: false}) }
      }
    }
    onExited: function(code) { if (code !== 0) root.authStatus = ({known: false}) }
  }
  Process {
    id: changeProcess
    onExited: function(code) {
      root.message = code === 0 ? "" : "Could not open face settings. Your current setting is shown above."
      root.refresh()
    }
  }
  // Keep the icon reasonably fresh without starting a Python status reader six
  // times a minute. Opening the panel and every settings exit refresh immediately.
  Timer { interval: 30000; running: true; repeat: true; onTriggered: root.refresh() }

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    tooltipText: !root.authStatus.known ? "Face authentication · status unavailable" : root.authStatus.enabled ? "Face authentication · on" : "Face authentication · off"
    Accessible.name: tooltipText
    onPressed: function(b) { if (b === Qt.LeftButton) root.toggle(); else if (b === Qt.MiddleButton) root.refresh() }
    iconComponent: Component {
      Item {
        Image {
          id: faceIcon
          anchors.centerIn: parent
          width: Style.space(20); height: width
          source: Qt.resolvedUrl("icon.svg")
          sourceSize.width: 48; sourceSize.height: 48
          visible: false
        }
        MultiEffect {
          anchors.fill: faceIcon
          source: faceIcon
          colorization: 1
          colorizationColor: root.barForeground
          opacity: root.authStatus.known && root.authStatus.enabled ? 1 : 0.45
        }
      }
    }
  }
  KeyboardPanel {
    id: popup
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: card
    contentWidth: fittedContentWidth(Style.space(350))
    contentHeight: fittedContentHeight(card.implicitHeight, Style.space(500))
    FaceComponents.StatusCard {
      id: card
      width: parent.width
      status: root.authStatus
      busy: changeProcess.running
      message: root.message
      onToggleRequested: root.changeEnabled()
      Keys.onEscapePressed: root.close()
    }
  }
}
