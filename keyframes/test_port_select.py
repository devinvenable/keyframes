"""MIDI input selection — ShowSync's virtual cue port is always listened to.

ShowSync mirrors its clock/transport/visual-cue egress onto a virtual port
named 'ShowSync Cues' (task 259) so cues arrive with no hardware return loop.
Auto-select used to skip every virtual-looking port; the cue port must be the
one exception, picked up by name on top of whatever else is selected.
"""
import os

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')

from main import select_midi_ports

CUE = 'ShowSync:ShowSync Cues 128:0'
HARDWARE = ['Arturia KeyStep 32:KeyStep 32 28:0',
            'MIDIPLUS TBOX 2x2:MIDIPLUS TBOX 2x2 Midi In 1 36:0']
SOFTWARE = ['Midi Through:Midi Through Port-0 14:0']


def test_auto_select_adds_the_cue_port_to_hardware():
    assert select_midi_ports(HARDWARE + SOFTWARE + [CUE]) == HARDWARE + [CUE]


def test_other_virtual_ports_stay_skipped():
    assert select_midi_ports(HARDWARE + SOFTWARE) == HARDWARE


def test_cue_port_alone_is_selected_without_hardware():
    assert select_midi_ports(SOFTWARE + [CUE]) == [CUE]


def test_port_filter_still_gets_the_cue_port():
    assert select_midi_ports(HARDWARE + [CUE], 'keystep') == [HARDWARE[0], CUE]


def test_non_matching_filter_still_hears_cues():
    assert select_midi_ports(HARDWARE + [CUE], 'no-such-port') == [CUE]


def test_filter_matching_the_cue_port_does_not_duplicate_it():
    assert select_midi_ports(HARDWARE + [CUE], 'showsync') == [CUE]


def test_no_ports_returns_empty():
    assert select_midi_ports([]) == []


def test_all_virtual_fallback_unchanged_without_cue_port():
    assert select_midi_ports(SOFTWARE) == SOFTWARE


# --- cue-port refresh (survives a ShowSync crash + relaunch) ---

from main import cue_port_refresh


def test_refresh_reopens_the_cue_port_even_under_the_same_name():
    # ALSA reuses freed client ids and CoreMIDI names carry no id, so a
    # relaunched ShowSync usually reappears under the SAME name while the old
    # subscription is dead — an unchanged name must still be reopened.
    assert cue_port_refresh([CUE] + HARDWARE, HARDWARE + [CUE]) == ([CUE], [CUE])


def test_refresh_follows_a_renamed_cue_port_and_a_vanished_one():
    renamed = 'ShowSync:ShowSync Cues 129:0'
    assert cue_port_refresh([CUE], HARDWARE + [renamed]) == ([CUE], [renamed])
    assert cue_port_refresh([CUE], HARDWARE) == ([CUE], [])


def test_refresh_never_touches_hardware_ports():
    assert cue_port_refresh(HARDWARE, HARDWARE + [CUE]) == ([], [CUE])
    assert cue_port_refresh(HARDWARE, HARDWARE) == ([], [])


def test_reattach_across_sender_relaunch_with_real_ports():
    """The full mechanism: a stale subscription hears nothing after the cue
    sender is relaunched; one refresh pass rebinds and cues flow again."""
    import time
    import mido

    def refresh(inports):
        stale, fresh = cue_port_refresh([p.name for p in inports],
                                        mido.get_input_names())
        for name in stale:
            gone = next(p for p in inports if p.name == name)
            inports.remove(gone)
            gone.close()
        for name in fresh:
            inports.append(mido.open_input(name))

    def drain(inports, wait=.3):
        time.sleep(wait)
        return [m for p in inports for m in p.iter_pending()]

    sender = mido.open_output('ShowSync Cues', virtual=True)
    inports = []
    try:
        time.sleep(.2)
        refresh(inports)
        assert inports, 'virtual cue port not visible to mido'
        sender.send(mido.Message('program_change', program=2))
        assert any(m.type == 'program_change' for m in drain(inports))
        # "Crash": the sender client disappears; a new one takes its place.
        sender.close()
        time.sleep(.2)
        sender = mido.open_output('ShowSync Cues', virtual=True)
        time.sleep(.2)
        sender.send(mido.Message('program_change', program=1))
        assert drain(inports) == []  # the stale subscription is deaf
        refresh(inports)             # one rescan interval later...
        sender.send(mido.Message('program_change', program=1))
        received = drain(inports)
        assert any(m.type == 'program_change' and m.program == 1 for m in received)
    finally:
        sender.close()
        for p in inports:
            p.close()
