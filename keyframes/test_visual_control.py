"""Per-song visual control over MIDI: bank program changes + scene-override CCs.

ShowSync (or any gear on the input port) cues Keyframes at song start; this
covers the VisualControl override layer, same-batch freshness through
process_midi_messages, the allowlist in the activation picker, scenes.json
``allow`` parsing, and program-change bank switching including mid-song."""
import json
import os
import queue
from unittest.mock import patch

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')

import mido
import pygame
import pytest

import main
from main import (
    SCENE_CC_ALLOW_ADD,
    SCENE_CC_ENABLED,
    SCENE_CC_PROBABILITY,
    SCENE_CC_RESET,
    SCENE_MIDI_IDS,
    SCENE_REGISTRY,
    ConcentricRingsScene,
    VisualControl,
    apply_program_change,
    load_scenes_config,
    process_midi_messages,
    update_scene_on_trigger,
)


def make_state():
    return {'surface': None, 'surface_media': None, 'video_player': None,
            'note_active': None, 'note_on_time': None, 'hold_until': None,
            'zoom_scale': 1.0, 'inverted': False, 'last_note': None,
            'active_scene': None}


def make_media(color=(255, 0, 0)):
    surface = pygame.Surface((8, 8)).convert_alpha()
    surface.fill(color + (255,))
    return {'type': 'image', 'surface': surface, 'name': 'img.png',
            'path': 'img.png'}


def cc(control, value, channel=0):
    return mido.Message('control_change', control=control, value=value,
                        channel=channel)


def setup_module():
    pygame.init()
    pygame.display.set_mode((320, 240))


def teardown_module():
    pygame.quit()


def test_scene_midi_ids_are_stable_and_complete():
    # These ids are mirrored by ShowSync (showsync/visuals.py) and are
    # APPEND-ONLY: renumbering breaks every setlist already written.
    assert SCENE_MIDI_IDS == {0: 'four-bar-sweep', 1: 'four-bar-sweep-black',
                              2: 'four-bar-sweep-tinted', 3: 'concentric-rings',
                              4: 'concentric-rings-timed'}
    assert set(SCENE_MIDI_IDS.values()) == set(SCENE_REGISTRY)


def test_overrides_layer_over_base_and_reset_restores():
    vc = VisualControl({'enabled': True, 'probability': 0.3})
    assert vc.handle(cc(SCENE_CC_ENABLED, 0))
    assert vc.handle(cc(SCENE_CC_PROBABILITY, 127))
    assert vc.scenes() == {'enabled': False, 'probability': 1.0}
    assert vc.base == {'enabled': True, 'probability': 0.3}  # base untouched
    assert vc.handle(cc(SCENE_CC_RESET, 0))
    assert vc.scenes() == vc.base
    # Boundary: 63 = off, 64 = on; probability quantizes as value/127.
    vc.handle(cc(SCENE_CC_ENABLED, 63))
    assert vc.scenes()['enabled'] is False
    vc.handle(cc(SCENE_CC_ENABLED, 64))
    assert vc.scenes()['enabled'] is True
    vc.handle(cc(SCENE_CC_PROBABILITY, 19))
    assert vc.scenes()['probability'] == pytest.approx(19 / 127)


def test_rebase_keeps_overrides_until_reset():
    vc = VisualControl({'enabled': True, 'probability': 0.05})
    vc.handle(cc(SCENE_CC_ENABLED, 0))
    vc.rebase({'enabled': True, 'probability': 0.5})
    assert vc.scenes() == {'enabled': False, 'probability': 0.5}


def test_allow_add_builds_exclusive_list_and_ignores_unknown_ids():
    vc = VisualControl({'enabled': True, 'probability': 0.05})
    vc.handle(cc(SCENE_CC_ALLOW_ADD, 3))
    vc.handle(cc(SCENE_CC_ALLOW_ADD, 3))  # duplicate adds once
    vc.handle(cc(SCENE_CC_ALLOW_ADD, 2))
    vc.handle(cc(SCENE_CC_ALLOW_ADD, 99))  # unknown id ignored, not an error
    assert vc.scenes()['allow'] == ['concentric-rings', 'four-bar-sweep-tinted']
    vc.handle(cc(SCENE_CC_RESET, 0))
    assert 'allow' not in vc.scenes()


def test_program_change_is_recorded_and_consumed_once():
    vc = VisualControl({'enabled': True, 'probability': 0.05})
    assert vc.handle(mido.Message('program_change', program=2, channel=9))
    assert vc.take_pending_program() == 2
    assert vc.take_pending_program() is None


def test_unrelated_messages_are_not_consumed():
    vc = VisualControl({'enabled': True, 'probability': 0.05})
    assert not vc.handle(cc(main.MOD_WHEEL_CC, 64))
    assert not vc.handle(mido.Message('note_on', note=48, velocity=100))
    assert vc.overrides == {}


def test_controls_apply_on_any_channel_and_within_the_same_batch():
    """A cue arriving in the same poll as the note it should govern wins,
    and the cue channel is independent of the note-channel filter."""
    media = {48: make_media()}
    state = make_state()
    q = queue.Queue()
    q.put(cc(SCENE_CC_ENABLED, 0, channel=15))  # cue channel != note channel
    q.put(mido.Message('note_on', note=48, velocity=100, channel=0))
    vc = VisualControl({'enabled': True, 'probability': 0.05})
    base = {'enabled': True, 'probability': 0.05}
    with patch('main.random.random', return_value=0.0):
        state = process_midi_messages(q, 36, 99, media, (320, 240), state,
                                      channel=0, scenes_config=base,
                                      visual_control=vc)
    assert state['note_active'] == 48  # the note still displayed normally
    assert state['active_scene'] is None  # ...but the disable cue applied
    q.put(cc(SCENE_CC_ENABLED, 127, channel=3))
    q.put(mido.Message('note_on', note=48, velocity=100, channel=0))
    with patch('main.random.random', return_value=0.0):
        state = process_midi_messages(q, 36, 99, media, (320, 240), state,
                                      channel=0, scenes_config=base,
                                      visual_control=vc)
    assert state['active_scene'] is not None


def test_mod_wheel_still_pans_with_visual_control_installed():
    state = make_state()
    state['pan'] = 0.0
    q = queue.Queue()
    q.put(cc(main.MOD_WHEEL_CC, 127))
    vc = VisualControl({'enabled': True, 'probability': 0.05})
    state = process_midi_messages(q, 36, 99, {}, (320, 240), state,
                                  scenes_config=vc.base, visual_control=vc)
    assert state['pan'] != 0.0
    assert vc.overrides == {}


def test_allowlist_filters_the_activation_picker():
    state = make_state()
    config = {'enabled': True, 'probability': 1.0, 'allow': ['concentric-rings']}
    candidates = []

    def spy(names):
        candidates.append(list(names))
        return names[0]

    with patch('main.random.choice', side_effect=spy):
        update_scene_on_trigger(state, make_media(), 0.0, config, rng=lambda: 0.0)
    assert candidates == [['concentric-rings']]  # picker saw ONLY allowed names
    assert isinstance(state['active_scene'], ConcentricRingsScene)


def test_empty_allowlist_means_no_scenes_at_all():
    state = make_state()
    config = {'enabled': True, 'probability': 1.0, 'allow': []}
    rolled = []
    update_scene_on_trigger(state, make_media(), 0.0, config,
                            rng=lambda: rolled.append(1) or 0.0)
    assert state['active_scene'] is None
    assert not rolled  # short-circuits before even rolling


def test_scenes_json_allow_parsing(tmp_path):
    path = tmp_path / 'scenes.json'
    path.write_text(json.dumps({'allow': ['concentric-rings', 'bogus']}))
    assert load_scenes_config(str(path))['allow'] == ['concentric-rings']
    path.write_text(json.dumps({'allow': []}))
    assert load_scenes_config(str(path))['allow'] == []
    path.write_text(json.dumps({'allow': ['bogus-only']}))
    assert 'allow' not in load_scenes_config(str(path))  # typo'd file ignored
    path.write_text(json.dumps({'allow': 'four-bar-sweep'}))
    assert 'allow' not in load_scenes_config(str(path))


@pytest.fixture
def library(tmp_path, monkeypatch):
    images = tmp_path / 'images'
    bank = tmp_path / 'banks' / 'other'
    images.mkdir()
    bank.mkdir(parents=True)
    for folder, color in ((images, (200, 10, 20)), (bank, (10, 200, 20))):
        surface = pygame.Surface((8, 8))
        surface.fill(color)
        pygame.image.save(surface, str(folder / 'shared.png'))
    (tmp_path / 'mapping.json').write_text('{"48": "shared.png"}\n')
    (bank / 'mapping.json').write_text('{"48": "shared.png"}\n')
    (tmp_path / 'scenes.json').write_text('{"enabled": true, "probability": 0.1}')
    (bank / 'scenes.json').write_text('{"enabled": true, "probability": 0.9}')
    monkeypatch.setattr(main, 'IMAGES_DIR', str(images))
    monkeypatch.setattr(main, 'MAPPING_PATH', str(tmp_path / 'mapping.json'))
    monkeypatch.setattr(main, 'SCENES_CONFIG_PATH', str(tmp_path / 'scenes.json'))
    monkeypatch.setattr(main, 'BANKS_DIR', tmp_path / 'banks')
    return main.MediaBanks(36, 99)


def hit(media, state, vc, base):
    q = queue.Queue()
    q.put(mido.Message('note_on', note=48, velocity=100))
    return process_midi_messages(q, 36, 99, media, (320, 240), state,
                                 scenes_config=base, visual_control=vc)


def test_program_change_switches_bank_mid_song(library):
    banks = library
    media, _, config = banks.load('default')
    vc = VisualControl(config)
    adopted = []

    def adopt(loaded):
        nonlocal media, config
        media, _, config = loaded
        vc.rebase(config)
        adopted.append(banks.name)

    state = hit(media, make_state(), vc, config)
    first = pygame.image.tobytes(state['surface'], 'RGB')
    # Mid-song cue: the program change rides the same queue as notes.
    q = queue.Queue()
    q.put(mido.Message('program_change', program=1, channel=5))
    process_midi_messages(q, 36, 99, media, (320, 240), state,
                          scenes_config=config, visual_control=vc)
    apply_program_change(vc, banks, adopt)
    assert adopted == ['other'] and banks.name == 'other'
    assert vc.base == {'enabled': True, 'probability': 0.9}
    state = hit(media, state, vc, config)
    assert pygame.image.tobytes(state['surface'], 'RGB') != first


def test_program_change_to_live_bank_is_a_noop(library):
    banks = library
    _, _, config = banks.load('other')
    vc = VisualControl(config)
    vc.pending_program = 1  # banks.names() == ['default', 'other']
    adopted = []
    apply_program_change(vc, banks, adopted.append)
    assert not adopted and banks.name == 'other'
    assert vc.take_pending_program() is None  # consumed, not left pending


def test_out_of_range_program_sets_notice_and_keeps_bank(library):
    banks = library
    banks.load('default')
    vc = VisualControl({'enabled': True, 'probability': 0.1})
    vc.pending_program = 9
    adopted = []
    apply_program_change(vc, banks, adopted.append)
    assert not adopted and banks.name == 'default'
    assert 'No bank for program 9' in banks.notice


def test_no_pending_program_does_nothing(library):
    banks = library
    banks.load('default')
    vc = VisualControl({'enabled': True, 'probability': 0.1})
    apply_program_change(vc, banks, lambda loaded: pytest.fail('adopted'))
    assert banks.name == 'default'
