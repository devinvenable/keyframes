"""Configuration audit / UI exposure registry (T274).

Keys must match the real CLI and YAML schemas. A new setting needs either a
reachable GUI control or an explicit cli_only reason here; tests check both.
Paths identify actual widgets or actions, not aspirational GUI support.

Audit gaps closed: saved and run-only MIDI egress + per-port filters, incoming
transport (source visible, CLI wins at startup), Keyframes setup/per-song cues,
set title, song gap, separate video/mute, MIDI loop length. ShowSync Cues stays
an automatic full-egress port, documented in both routing dialogs; no toggle
is appropriate because no such engine setting exists (D18).

Known boundaries: arbitrary tempo maps remain YAML-only (the table supports
one ramp). Launch/process/capture controls belong to their owning launcher.
Keyframes --note-source landed in T273; ShowSync neither starts nor owns that
process, so its note-source option is deliberately cli_only here. This is not
the integration phase; routing semantics and launch defaults are unchanged.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Exposure:
    gui: str = ''
    cli_only: str = ''


def gui(path):
    return Exposure(gui=path)


def cli_only(reason):
    return Exposure(cli_only=reason)


CLI = {
    'help': cli_only('Console usage; GUI has Help > About.'),
    'setlist': gui('MainWindow.open_action'),
    'audio_device': gui('DeviceDialog.audio'),
    'midi_port': gui('DeviceDialog.midi'),
    'midi_outputs': gui('DeviceDialog.outputs'),
    'list_devices': gui('DeviceDialog.refresh_button'),
    'freeze_gc': cli_only('Startup-only runtime tuning; must run before engines are created.'),
    'editor_screen': cli_only('Initial window placement for launchers; move the editor with the window manager.'),
    'headless': cli_only('Launch without an editor; cannot be an editor preference.'),
    'autostart': cli_only('Unattended launch countdown, not persisted to avoid surprise playback.'),
    'midi_transport': gui('MainWindow.transport_action'),
    'clock_offset': gui('MainWindow.offset_action'),
    'export_bundle': gui('MainWindow.export_bundle'),
    'import_bundle': gui('MainWindow.import_bundle'),
    'keyframes': cli_only('Offline bundle companion media import/export; Keyframes must be closed before installing.'),
}

# identity.application_arguments is Qt argv, not ShowSync's argparse surface.
QT_IDENTITY = {'-name': cli_only('Fixed desktop WM_CLASS identity on Linux; not performer configuration.')}

YAML = {
    'setlist': {
        'title': gui('SetSettingsDialog.title'),
        'audio_root': cli_only('Hand-authored path base; GUI chooses files and writes portable paths relative to it.'),
        'songs': gui('MainWindow.table'),
        'keyframes': gui('SetSettingsDialog.banks'),
        'midi_outputs': gui('SetSettingsDialog.outputs'),
    },
    'song': {
        'name': gui('MainWindow.table'), 'file': gui('MainWindow.replace_button'),
        'bpm': gui('MainWindow.table'), 'offset': gui('MainWindow.table'),
        'trim': gui('MainWindow.table'),
        'gap': gui('SongSettingsDialog.gap'),
        'tempo': cli_only('Single ramps have table controls; arbitrary jumps/multiple events remain an advanced YAML editor feature.'),
        'midi': gui('MainWindow.midi_browse_button'),
        'video': gui('SongSettingsDialog.video'), 'mute': gui('SongSettingsDialog.mute'),
        'restart': cli_only('Legacy inert metadata accepted for compatibility, not a supported playback mode.'),
        'editor': cli_only('Generated timing-review metadata; edited through timing review actions, never raw flags.'),
        'keyframes': gui('SongSettingsDialog.cue'),
    },
    'midi': {
        'file': gui('MainWindow.midi_browse_button'), 'loop': gui('MainWindow.midi_loop'),
        'beats': gui('SongSettingsDialog.midi_beats'),
        'bars': gui('SongSettingsDialog.midi_beats'),  # equivalent units: four beats per bar
        'port': gui('MainWindow.midi_port'),
    },
    'event': {key: cli_only('Arbitrary tempo maps are YAML-only; single-ramp equivalent is in the song table.')
              for key in ('at', 'bpm', 'ramp')},
    'keyframes': {'bank': gui('SongSettingsDialog.bank'), 'scenes': gui('SongSettingsDialog.scenes')},
    'keyframes.scenes': {
        'enabled': gui('SongSettingsDialog.scenes'),
        'probability': gui('SongSettingsDialog.probability'),
        'allow': gui('SongSettingsDialog.allow'),
    },
    'egress': {'port': gui('OutputEditor.table'), 'send': gui('OutputEditor.table')},
    'keyframes.setup': {'banks': gui('SetSettingsDialog.banks'), 'channel': gui('SetSettingsDialog.channel')},
    'editor': {key: cli_only('Generated timing metadata; use detected/current timing actions instead.')
               for key in ('bpm_estimated', 'offset_estimated', 'timing_review')},
}

# Launcher-owned options: never silently turn these into persisted app state.
LAUNCHER_FLAGS = {
    'live.sh': {
        '--bank': cli_only('Selects the separate Keyframes process launch bank.'),
        '--headless': cli_only('Pass-through ShowSync launch mode.'),
        '--no-restart': cli_only('Supervisor process policy, outside ShowSync.'),
        '--help': cli_only('Console launcher usage.'),
    },
    'perform.sh': {
        '--keyframes-only': cli_only('Selects which processes the capture launcher starts.'),
        '--no-postprocess': cli_only('Capture postprocessing policy.'),
        '--headless': cli_only('Pass-through ShowSync launch mode.'),
        '--audio': cli_only('Recording input mix, separate from ShowSync playback output.'),
        '--mixer-source': cli_only('Recording Pulse source, separate from ShowSync playback output.'),
        '--help': cli_only('Console launcher usage.'),
    },
}
LAUNCHER_ENV = {
    'LIVE_PYTHON': cli_only('Interpreter/test hook.'),
    'LIVE_UNAME': cli_only('Platform probe/test hook.'),
    'LIVE_SETTLE_SECONDS': cli_only('Launcher process startup delay.'),
    'LIVE_RESTART_LIMIT': cli_only('Supervisor crash policy.'),
    'LIVE_KEYFRAMES_ARGS': cli_only('Extra options for the separate Keyframes process, including --note-source.'),
    'PERFORM_PYTHON': cli_only('Interpreter/test hook.'),
    'PERFORM_CONF': cli_only('Location of capture mixer configuration.'),
    'PERFORM_MIXER_SOURCE': cli_only('Recording source; overrides perform.conf.'),
    'PERFORM_NO_POSTPROCESS': cli_only('Capture postprocessing policy.'),
    'PERFORM_OUTDIR': cli_only('Capture output directory.'),
    'PERFORM_VIDEO_ENCODER': cli_only('Capture encoder/probe test hook.'),
    'PERFORM_POSTPROCESS_FFMPEG': cli_only('Postprocessing executable/test hook.'),
    'PERFORM_KEYFRAMES_ARGS': cli_only('Extra options for the separate Keyframes process, including --note-source.'),
    'DISPLAY': cli_only('Host display selected before Qt/capture startup.'),
    'TMPDIR': cli_only('Host temporary directory for supervisor bank state.'),
}
PERFORM_CONF = {key: cli_only('Capture mixer source configuration, owned by perform.sh.')
                for key in ('MIXER_SOURCE', 'MIXER_SOURCE_PATTERN')}
PROCESS_ENV = {
    'SHOWSYNC_MARKERS': cli_only('Capture sidecar output path injected by perform.sh.'),
    'SHOWSYNC_MARKERS_EPOCH': cli_only('Capture epoch injected by perform.sh.'),
    'KEYFRAMES_MIDI_LOG': cli_only('Capture MIDI log path injected into Keyframes.'),
    'KEYFRAMES_BANK_STATE': cli_only('Supervisor restart state injected into Keyframes.'),
    'XDG_STATE_HOME': cli_only('Platform state directory override.'),
    'APPDATA': cli_only('Windows platform state directory.'),
}
# Full Keyframes CLI inventory, inspected statically by tests without starting
# pygame. Register future arguments here with a reason or a real UI exposure.
KEYFRAMES_CLI = {key: cli_only('Separate Keyframes process option; set via LIVE_KEYFRAMES_ARGS / PERFORM_KEYFRAMES_ARGS or its CLI.')
                 for key in ('--bank', '--midi-file', '--loop', '--channel', '--port',
                             '--note-source', '--start-note', '--num-keys', '--min-note',
                             '--no-latch', '--bpm', '--zoom-ring', '--windowed',
                             '--display-mode', '--midi-log', '--packaging-smoke-test', '--size')}
# Persistent app files are preferences/derived UI state, not a second set schema.
APP_STATE = {
    'last_setlist': gui('MainWindow.open_action'),
    'clock_offset_ms': gui('MainWindow.offset_action'),
    'midi_output': gui('DeviceDialog.midi'), 'audio_output': gui('DeviceDialog.audio'),
    'send_transport': gui('DeviceDialog.send_transport'),
}
QT_SETTINGS = {
    'receiveMidiTransport': gui('MainWindow.transport_action'),
    'recentSets': gui('MainWindow.recent_menu'),
    'video/geometry': cli_only('Automatically remembered video window geometry.'),
    'video/screen': cli_only('Automatically remembered video window screen.'),
}
