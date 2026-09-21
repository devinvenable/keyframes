# showsync icon

Original hand-drawn SVG: a mint metronome with an amber pendulum on a dark slate
rounded tile. Bold shapes keep it legible at 16 px. Edit `showsync.svg`, then run
`python3 showsync/scripts/generate_icons.py` from the repository root.
ImageMagick 6/7 is required only for regeneration; its built-in MSVG renderer
avoids optional Inkscape delegates. Generated assets are checked in.

Linux: the Qt runtime loads 16–256 px PNGs. Future desktop packaging should install
PNGs under hicolor/<size>x<size>/apps/showsync.png and provide showsync.desktop
with Name=showsync, Icon=showsync, StartupWMClass=showsync and Exec=showsync.
The desktop file name and Linux WM_CLASS are already wired in the runtime.

Windows: showsync.ico contains 16, 24, 32, 48, 64, 128 and 256 px frames, ready
for a future PyInstaller `--icon` setting. Bundle the icons directory as data.

macOS: stage an iconset directory with icon_16x16.png, icon_16x16@2x.png,
icon_32x32.png, icon_32x32@2x.png, icon_128x128.png, icon_128x128@2x.png,
icon_256x256.png, icon_256x256@2x.png, icon_512x512.png and
icon_512x512@2x.png, copying the matching pixel-size PNG for each. Run
`iconutil -c icns showsync.iconset` on macOS and set the bundle icon in packaging.
No Windows or macOS packaging changes are activated by this task.
