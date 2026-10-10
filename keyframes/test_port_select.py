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
