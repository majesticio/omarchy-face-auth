import QtQuick
import QtQuick.Controls
import qs.Commons

Column {
  id: root
  property var status: ({known: false})
  property bool busy: false
  property string message: ""
  signal toggleRequested()
  spacing: Style.space(14)

  Text {
    text: "Face authentication"
    color: Color.foreground
    font.family: Style.font.family
    font.pixelSize: Style.font.heading
    font.bold: true
  }
  Text {
    width: parent.width
    text: !root.status.known ? "Status unavailable" : !root.status.enabled ? "Off · password only" : !root.status.available ? "Needs attention" : "On · ready when you authenticate"
    color: Color.foreground
    font.family: Style.font.family
    font.pixelSize: Style.font.body
    wrapMode: Text.WordWrap
  }
  Rectangle { width: parent.width; height: 1; color: Color.foreground; opacity: 0.18 }
  Repeater {
    model: [
      ["Screen unlock", root.status.screen ? "Face scan · F8" : "Password"],
      ["Sudo", root.status.sudo ? (root.status.confirmation ? "Face + approval" : "Face scan") : "Password"],
      ["IR camera", root.status.camera ? "Connected" : "Unavailable"],
      ["Face profile", root.status.enrolled ? "Enrolled" : "Missing"]
    ]
    delegate: Row {
      required property var modelData
      width: root.width
      Text {
        width: parent.width * 0.43
        text: modelData[0]
        color: Color.foreground
        opacity: 0.65
        font.family: Style.font.family
        font.pixelSize: Style.font.body
      }
      Text {
        width: parent.width * 0.57
        text: root.status.known ? modelData[1] : "Unknown"
        horizontalAlignment: Text.AlignRight
        color: Color.foreground
        font.family: Style.font.family
        font.pixelSize: Style.font.body
        wrapMode: Text.WordWrap
      }
    }
  }
  Button {
    width: parent.width
    height: Style.space(42)
    enabled: root.status.known === true && !root.busy
    text: root.busy ? "Settings open…" : "Profiles & settings…"
    onClicked: root.toggleRequested()
    background: Rectangle {
      radius: Style.space(6)
      color: parent.down ? Qt.darker(Color.accent, 1.15) : Color.accent
      opacity: parent.enabled ? 1 : 0.4
    }
    contentItem: Text {
      text: parent.text
      color: Color.background
      font.family: Style.font.family
      font.pixelSize: Style.font.body
      horizontalAlignment: Text.AlignHCenter
      verticalAlignment: Text.AlignVCenter
    }
  }
  Text {
    width: parent.width
    text: root.message || "Enroll or remove profiles, and choose where face authentication is enabled. Changes require your password."
    color: Color.foreground
    opacity: 0.65
    font.family: Style.font.family
    font.pixelSize: Style.font.bodySmall
    wrapMode: Text.WordWrap
  }
}
