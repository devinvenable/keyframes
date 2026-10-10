"""Bank transactions and real event-loop integration, using SDL's dummy driver."""
import json
import os
import queue

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')

import mido
import pygame
import pytest

import main


@pytest.fixture
def library(tmp_path, monkeypatch):
    pygame.init()
    pygame.display.set_mode((320, 240))
    images = tmp_path / 'images'
    bank = tmp_path / 'banks' / 'other'
    images.mkdir()
    bank.mkdir(parents=True)
    # Same basename/note in both banks must still load distinct media/caches.
    for folder, color in ((images, (200, 10, 20)), (bank, (10, 200, 20))):
        surface = pygame.Surface((8, 8))
        surface.fill(color)
        pygame.image.save(surface, str(folder / 'shared.png'))
    (tmp_path / 'mapping.json').write_text('{"48": "shared.png"}\n')
    (bank / 'mapping.json').write_text('{"48": "shared.png"}\n')
    (tmp_path / 'scenes.json').write_text('{"enabled": false, "probability": 0.3}')
    monkeypatch.setattr(main, 'IMAGES_DIR', str(images))
    monkeypatch.setattr(main, 'MAPPING_PATH', str(tmp_path / 'mapping.json'))
    monkeypatch.setattr(main, 'SCENES_CONFIG_PATH', str(tmp_path / 'scenes.json'))
    monkeypatch.setattr(main, 'BANKS_DIR', tmp_path / 'banks')
    yield tmp_path, main.MediaBanks(36, 99)
    pygame.quit()


def hit(media, state=None, config=None):
    q = queue.Queue()
    q.put(mido.Message('note_on', note=48, velocity=100))
    if state is None:
        state = {'surface': None, 'video_player': None, 'note_active': None}
    return main.process_midi_messages(q, 36, 99, media, (320, 240), state,
                                      scenes_config=config)


def test_discovery_validation_and_default_compatibility(library):
    root, banks = library
    (root / 'banks' / 'aaa').mkdir()
    (root / 'banks' / 'default').mkdir()  # reserved name never shadows master
    (root / 'banks' / 'not-a-bank.txt').touch()
    assert banks.names() == ['default', 'aaa', 'other']
    before = (root / 'mapping.json').read_bytes()
    historical = main.load_media(36, 99)
    media, cells, config = banks.load('default', startup=True)
    assert cells is None  # historical lazy grid
    assert list(media) == list(historical) == [48]
    assert pygame.image.tobytes(media[48]['surface'], 'RGB') == pygame.image.tobytes(
        historical[48]['surface'], 'RGB')
    assert (root / 'mapping.json').read_bytes() == before
    assert main.MAPPING_PATH == str(root / 'mapping.json')
    assert config == {'enabled': False, 'probability': 0.3}
    for name in ('missing', '../images', str(root / 'images')):
        with pytest.raises(ValueError, match='Unknown bank'):
            banks.load(name)


def test_switch_replaces_media_thumbnails_and_preserves_running_scene(library):
    root, banks = library
    before, old_cells, _ = banks.load('default')
    state = hit(before)
    scene = main.FourBarSweepScene(main.SceneMediaSource(state['surface']), 0)
    state['active_scene'] = scene
    old_surface = state['surface']
    after, cells, config = banks.cycle(1)
    assert banks.name == 'other'
    assert after[48] is not before[48]
    assert cells[0]['media'] is after[48]
    assert cells[0]['thumb'] is not old_cells[0]['thumb']
    assert cells[0]['thumb'].get_at((0, 0))[:3] == (10, 200, 20)
    state = hit(after, state, config)
    assert state['surface'].get_at((0, 0))[:3] == (10, 200, 20)
    assert state['active_scene'] is scene
    assert scene.image is old_surface
    # A disabled new-bank config must still let the prior scene finish.
    for now in range(1, 7):
        main.update_scene_on_trigger(state, after[48], now, config)
    assert state['active_scene'] is None
    restored, cells, _ = banks.cycle(1)  # wrap to default
    assert banks.name == 'default'
    assert restored[48]['surface'].get_at((0, 0))[:3] == (200, 10, 20)
    assert main.MAPPING_PATH == str(root / 'mapping.json')


def test_active_bank_reconcile_assign_unmap_and_drop_are_isolated(library):
    root, banks = library
    master = (root / 'mapping.json').read_bytes()
    bank = root / 'banks' / 'other'
    # Force reconciliation to discard a deleted file in the BANK manifest.
    (bank / 'mapping.json').write_text('{"48": "shared.png", "49": "gone.png"}')
    media, cells, _ = banks.load('other')
    assert json.loads((bank / 'mapping.json').read_text()) == {'48': 'shared.png'}
    main.assign_cell_note(cells[0], 50, media)
    assert main.load_mapping() == {50: 'shared.png'}
    assert json.loads((bank / 'mapping.json').read_text()) == {'50': 'shared.png'}
    cells = main.build_grid_cells(media, (40, 40))
    source = root / 'replacement.png'
    pygame.image.save(pygame.Surface((8, 8)), str(source))
    assert main.apply_drop(str(source), cells[0], media)
    assert (bank / 'replacement.png').exists()
    assert not (bank / 'shared.png').exists()
    assert (root / 'images' / 'shared.png').exists()
    assert not (root / 'images' / 'replacement.png').exists()
    assert main.load_mapping() == {50: 'replacement.png'}
    cells = main.build_grid_cells(media, (40, 40))
    main.unmap_cell(cells[0], media)
    assert json.loads((bank / 'mapping.json').read_text()) == {}
    assert (root / 'mapping.json').read_bytes() == master


def test_failed_staging_keeps_active_paths_and_caches(library, monkeypatch):
    root, banks = library
    media, cells, config = banks.load('default')
    paths = (main.IMAGES_DIR, main.MAPPING_PATH, main.SCENES_CONFIG_PATH)
    thumbnail = main.make_thumbnail

    def fail_new_bank(entry, size):
        # Even DURING staging, all default helpers must still target old bank.
        assert (main.IMAGES_DIR, main.MAPPING_PATH, main.SCENES_CONFIG_PATH) == paths
        if entry['surface'].get_at((0, 0))[:3] == (10, 200, 20):
            raise pygame.error('decode failed')
        return thumbnail(entry, size)

    monkeypatch.setattr(main, 'make_thumbnail', fail_new_bank)
    with pytest.raises(pygame.error, match='decode failed'):
        banks.cycle(1)
    assert banks.name == 'default'
    assert (main.IMAGES_DIR, main.MAPPING_PATH, main.SCENES_CONFIG_PATH) == paths
    assert cells[0]['media'] is media[48]
    assert hit(media)['surface'].get_at((0, 0))[:3] == (200, 10, 20)
    assert banks.notice_until == 0


def test_scene_override_and_global_fallback_after_switch_back(library):
    root, banks = library
    _, _, config = banks.load('other')
    assert config == {'enabled': False, 'probability': 0.3}
    (root / 'banks' / 'other' / 'scenes.json').write_text(
        '{"enabled": true, "probability": 0.9}')
    _, _, config = banks.load('other')
    assert config == {'enabled': True, 'probability': 0.9}
    _, _, config = banks.load('default')
    assert config == {'enabled': False, 'probability': 0.3}
    (root / 'banks' / 'other' / 'scenes.json').unlink()
    _, _, config = banks.load('other')
    assert config == {'enabled': False, 'probability': 0.3}


def test_cli_hotkeys_grid_reset_and_switch_overlay(library, monkeypatch):
    root, _ = library
    monkeypatch.setattr(main.sys, 'argv', ['main.py', '--bank', 'other', '--windowed'])
    monkeypatch.setattr(main.mido, 'get_input_names', lambda: [])
    key = lambda k: pygame.event.Event(pygame.KEYDOWN, key=k, mod=0)
    x, y = main.cell_rect(0, main.grid_layout(1, 0, (1280, 720)))
    cell_pos = (x + 10, y + 10)
    batches = iter([
        [key(pygame.K_z)],  # startup flag really selects the other bank
        [key(pygame.K_TAB)],
        [pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=cell_pos),
         pygame.event.Event(pygame.MOUSEBUTTONUP, button=1, pos=cell_pos)],
        [key(pygame.K_F5), key(pygame.K_z)],  # selection must not remap old cell
        [key(pygame.K_TAB), key(pygame.K_F6), key(pygame.K_z)],
        [pygame.event.Event(pygame.QUIT)],
    ])
    monkeypatch.setattr(main.pygame.event, 'get', lambda: next(batches))
    performances, grids, notices, triggered = [], [], [], []
    original_frame = main.draw_performance_frame
    original_grid = main.render_grid
    original_text = main.draw_text_outlined
    original_process = main.process_midi_messages

    def process(*args, **kwargs):
        state = original_process(*args, **kwargs)
        triggered.append(state['surface'].get_at((0, 0))[:3])
        return state

    def frame(screen, state, *args):
        if state['surface'] is not None:
            performances.append((state['surface'].get_at((0, 0))[:3], state['inverted']))
        return original_frame(screen, state, *args)

    def grid(screen, cells, scroll, fonts, active, flashes, now, selected):
        grids.append((cells[0]['thumb'].get_at((0, 0))[:3], selected, active))
        return original_grid(screen, cells, scroll, fonts, active, flashes, now, selected)

    def text(screen, message, *args, **kwargs):
        notices.append(message)
        return original_text(screen, message, *args, **kwargs)

    monkeypatch.setattr(main, 'draw_performance_frame', frame)
    monkeypatch.setattr(main, 'render_grid', grid)
    monkeypatch.setattr(main, 'draw_text_outlined', text)
    monkeypatch.setattr(main, 'process_midi_messages', process)
    main.main()
    assert performances[0] == ((10, 200, 20), False)
    assert performances[-1] == ((10, 200, 20), False)
    assert grids[-2][1] == 0  # prove the click armed an actual cell
    assert grids[-1] == ((200, 10, 20), None, 48)
    assert triggered[3:5] == [(200, 10, 20), (10, 200, 20)]
    assert 'Bank: default' in notices and 'Bank: other' in notices
    assert json.loads((root / 'mapping.json').read_text()) == {'48': 'shared.png'}
    assert not set(main.BANK_KEYS) & set(main.KEY_TO_NOTE)


def test_empty_bank_and_expiring_notice(library, monkeypatch):
    root, banks = library
    (root / 'banks' / 'aaa').mkdir()
    monkeypatch.setattr(main.time, 'monotonic', lambda: 10)
    media, cells, config = banks.cycle(1)
    assert banks.name == 'aaa'
    assert media is None and cells == []
    drawn = []
    monkeypatch.setattr(main, 'draw_text_outlined', lambda *a, **kw: drawn.append(a[1]))
    banks.draw_notice(pygame.display.get_surface(), 10)
    assert drawn == ['Bank: aaa']
    banks.draw_notice(pygame.display.get_surface(), 10 + main.BANK_NOTICE_SECONDS)
    assert len(drawn) == 1


def test_bank_state_published_on_load_and_cycle(library, monkeypatch, tmp_path):
    """KEYFRAMES_BANK_STATE always holds the active bank (live.sh restarts)."""
    root, banks = library
    state = tmp_path / 'bank_state'
    monkeypatch.setenv('KEYFRAMES_BANK_STATE', str(state))
    banks.load('default', startup=True)
    assert state.read_text() == 'default\n'
    banks.cycle(1)  # -> 'other'
    assert state.read_text() == 'other\n'
    assert not state.with_name(state.name + '.tmp').exists()


def test_bank_state_absent_env_and_write_failure_are_harmless(library, monkeypatch, tmp_path):
    root, banks = library
    monkeypatch.delenv('KEYFRAMES_BANK_STATE', raising=False)
    banks.load('other')  # no env: no file, no error
    assert not (tmp_path / 'bank_state').exists()
    # Unwritable destination must not break the switch itself.
    monkeypatch.setenv('KEYFRAMES_BANK_STATE',
                       str(tmp_path / 'missing-dir' / 'bank_state'))
    media, _, _ = banks.load('default')
    assert banks.name == 'default'
