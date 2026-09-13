# Hardware compatibility

The plugin is portable across Omarchy laptops whose infrared camera appears as a
standard V4L2 capture device. It is not tied to a laptop model, USB vendor ID,
video-node number, account name, UID, group, or home directory.

`scripts/detect-ir-camera` enumerates `/dev/video*`, asks `v4l2-ctl` for advertised
capture formats, and accepts nodes only when every format is greyscale (`GREY` or
supported Y8–Y16 variants). It prefers a persistent `/dev/v4l/by-path` link when
one exists. This conservative rule avoids silently enrolling from the RGB camera.

The detector will stop on hardware that presents IR as MJPEG, shares RGB and IR
formats on one node, requires a proprietary emitter driver, or exposes no stable
Linux capture interface. A maintainer can add a reviewed device-specific detector
later; do not work around the stop by guessing `/dev/videoN`.

OpenCV 5.0 may print `Targets are not supported by the new graph engine for now`
during recognition. Howdy Next documents this as a harmless upstream warning;
the OpenCV fix is expected in 5.1. A successful or failed authentication result
remains authoritative.

Some supported cameras need the optional `linux-enable-ir-emitter` package.
That driver is intentionally not installed automatically because emitter control
is hardware-specific.

The RGB and IR interfaces of one physical webcam may be usable simultaneously if
its firmware and driver support independent streams. Many laptop cameras cannot
do this reliably. A busy IR node causes face authentication to fail closed and
leave password authentication available; the plugin does not kill or restart the
other camera application.

To inspect a machine without capturing frames:

```bash
./scripts/detect-ir-camera
v4l2-ctl --device /dev/videoN --list-formats-ext
```

The installer is currently single-user. It records the installing account in a
root-owned file and refuses face authentication for another UID. Remote sessions,
display-manager login, disk unlock, and multi-user enrollment are unsupported.
