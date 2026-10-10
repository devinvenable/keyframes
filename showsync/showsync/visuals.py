"""Per-song Keyframes cues, emitted on the clock port at each song start.

The vocabulary (docs/visual-control-midi.md): a Program Change selects the
Keyframes bank by index into Keyframes' deterministic bank order — program 0
is the default bank, programs 1..N are the banks/ folder names sorted — and
four CCs in the undefined 102-119 range steer scene activation. The setlist's
top-level ``keyframes.banks`` list must therefore be the COMPLETE, sorted
list of bank folders; the loader rejects an unsorted list, but only Keyframes
knows whether it is complete, so add new bank folders to the setlist too.

Keyframes accepts these messages on any channel; the channel here
(``keyframes.channel``, default 16) just keeps the cues off the performance
channels for other listeners on the port.
"""
from dataclasses import dataclass

# Mirror of Keyframes' SCENE_MIDI_IDS (keyframes/main.py). Ids are
# APPEND-ONLY on both sides: new scenes get new numbers, existing ones are
# never renumbered, so old setlists stay valid as the registry grows.
KEYFRAMES_SCENES = {
    'four-bar-sweep': 0,
    'four-bar-sweep-black': 1,
    'four-bar-sweep-tinted': 2,
    'concentric-rings': 3,
    'concentric-rings-timed': 4,
}

CC_RESET = 102        # any value: drop all per-song overrides
CC_ENABLED = 103      # 0 = scenes off, 127 = on
CC_PROBABILITY = 104  # value/127 -> probability (~0.8% steps: 0.05 -> 6/127 = 0.047)
CC_ALLOW_ADD = 105    # value = scene id; first add starts an exclusive allowlist
DEFAULT_CHANNEL = 16


@dataclass(frozen=True)
class KeyframesCue:
    """One song's validated ``keyframes:`` block; None fields were omitted."""
    bank: str | None = None
    enabled: bool | None = None
    probability: float | None = None
    allow: tuple[str, ...] | None = None


def song_controls(setlist):
    """Per-song message tuples for ClockEngine, parallel to setlist.songs.

    A song with no ``keyframes:`` block emits nothing — the previous song's
    bank and overrides persist. A cue-bearing song emits the bank program
    first (so the reset lands on the new bank's defaults), then CC_RESET, then
    only the values the block actually sets.
    """
    channel = setlist.keyframes_channel - 1
    program_status, control_status = 0xC0 | channel, 0xB0 | channel
    controls = []
    for song in setlist.songs:
        cue = song.keyframes
        messages = []
        if cue is not None:
            if cue.bank is not None:
                program = (0 if cue.bank == 'default'
                           else 1 + setlist.keyframes_banks.index(cue.bank))
                messages.append((program_status, program))
            messages.append((control_status, CC_RESET, 0))
            if cue.enabled is not None:
                messages.append((control_status, CC_ENABLED,
                                 127 if cue.enabled else 0))
            if cue.probability is not None:
                messages.append((control_status, CC_PROBABILITY,
                                 round(cue.probability * 127)))
            for name in cue.allow or ():
                messages.append((control_status, CC_ALLOW_ADD,
                                 KEYFRAMES_SCENES[name]))
        controls.append(tuple(messages))
    return tuple(controls)
