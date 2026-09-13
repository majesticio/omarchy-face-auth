import QtQuick
import Quickshell.Services.Pam
import "FaceFlow.js" as Flow

Item {
  id: root
  required property string userName
  property bool allowed: false
  property string phase: "idle"
  readonly property bool busy: phase !== "idle" || pam.active
  signal authenticated()
  signal failed(string reason)

  function cancel() {
    deadline.stop()
    phase = Flow.transition(phase, "cancel")
    if (pam.active) pam.abort()
  }

  function start() {
    if (!allowed || busy) return
    phase = Flow.transition(phase, "start")
    deadline.interval = 12000
    deadline.restart()
    if (!pam.start()) {
      cancel()
      failed("Face scan unavailable. Use your password.")
    }
  }

  function checkPrompt() {
    if (!pam.active || !pam.responseRequired) return
    // Screen recognition is non-interactive. Never answer an unexpected PAM
    // challenge or supply the lock password to a different authentication flow.
    cancel()
    failed("Unexpected face prompt. Use your password.")
  }

  onAllowedChanged: { if (!allowed) cancel() }

  Timer {
    id: deadline
    repeat: false
    onTriggered: {
      root.cancel()
      root.failed("Face authentication timed out. Use your password.")
    }
  }

  PamContext {
    id: pam
    config: "omarchy-lock-face"
    user: root.userName
    onPamMessage: Qt.callLater(root.checkPrompt)
    onResponseRequiredChanged: Qt.callLater(root.checkPrompt)
    onCompleted: function(result) {
      var accepted = Flow.mayUnlock(root.phase, result === PamResult.Success, root.allowed)
      var attempted = root.phase !== "idle"
      deadline.stop()
      root.phase = "idle"
      if (accepted) root.authenticated()
      else if (attempted) root.failed("Face authentication failed. Use your password.")
    }
    onError: function(error) {
      var attempted = root.phase !== "idle"
      root.cancel()
      if (attempted) root.failed("Face scan unavailable. Use your password.")
    }
  }
}
