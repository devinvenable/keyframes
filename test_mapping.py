"""Headless tests for the persistent note->media mapping manifest (mapping.json).

Run with SDL's dummy video driver so no window is needed:
    SDL_VIDEODRIVER=dummy python3 -m pytest test_mapping.py
"""
import json
import os

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')

import pygame
import pytest

import main


@pytest.fixture(scope='module', autouse=True)
def _pygame_init():
    pygame.init()
    pygame.display.set_mode((320, 240))
    yield
    pygame.quit()


@pytest.fixture
def media_dir(tmp_path, monkeypatch):
    """Point main at an isolated images/ dir and mapping.json under tmp_path."""
    images = tmp_path / 'images'
    images.mkdir()
    monkeypatch.setattr(main, 'IMAGES_DIR', str(images))
    monkeypatch.setattr(main, 'MAPPING_PATH', str(tmp_path / 'mapping.json'))
    return tmp_path


def _make_png(path):
    surf = pygame.Surface((8, 8))
    surf.fill((10, 20, 30))
    pygame.image.save(surf, str(path))


def _write_images(images_dir, names):
    for name in names:
        _make_png(images_dir / name)


# --- load_mapping / save_mapping roundtrip ----------------------------------

def test_save_load_roundtrip(media_dir):
    path = str(media_dir / 'm.json')
    mapping = {36: 'a.png', 40: 'b.png', 100: 'c.png'}
    main.save_mapping(mapping, path)
    assert main.load_mapping(path) == mapping


def test_saved_file_is_human_readable_with_string_keys(media_dir):
    path = str(media_dir / 'm.json')
    main.save_mapping({40: 'b.png', 36: 'a.png'}, path)
    text = open(path, encoding='utf-8').read()
    # Indented (multi-line) and keys sorted numerically as strings.
    assert '\n' in text
    raw = json.loads(text)
    assert list(raw.keys()) == ['36', '40']
    assert all(isinstance(k, str) for k in raw)


def test_load_missing_file_returns_empty(media_dir):
    assert main.load_mapping(str(media_dir / 'nope.json')) == {}


def test_load_skips_malformed_entries(media_dir):
    path = str(media_dir / 'm.json')
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump({'36': 'a.png', 'oops': 'b.png', '40': 123}, fh)
    # Bad key and non-string value dropped; good entry survives.
    assert main.load_mapping(path) == {36: 'a.png'}


def test_load_corrupt_json_returns_empty(media_dir):
    path = str(media_dir / 'm.json')
    open(path, 'w').write('{not json')
    assert main.load_mapping(path) == {}


# --- reconcile_mapping -------------------------------------------------------

def test_reconcile_preserves_stored_assignment(media_dir):
    # The regression this whole task fixes: a stored pin must NOT be clobbered
    # by even-distribution.
    present = ['a.png', 'b.png', 'c.png']
    stored = {36: 'c.png'}  # deliberately NOT what distribution would pick
    result = main.reconcile_mapping(stored, present, 36, 99)
    assert result[36] == 'c.png'


def test_reconcile_drops_missing_file_and_seeds_hole(media_dir):
    present = ['a.png', 'b.png']
    stored = {36: 'gone.png'}  # file no longer on disk
    result = main.reconcile_mapping(stored, present, 36, 99)
    assert result[36] != 'gone.png'
    assert result[36] in present


def test_reconcile_surfaces_new_file(media_dir):
    # 2 notes, 1 stored file -> note 37 duplicates via seed; a new file should
    # take over that unpinned duplicate rather than vanish.
    present = ['a.png', 'new.png']
    stored = {36: 'a.png'}
    result = main.reconcile_mapping(stored, present, 36, 37)
    assert result[36] == 'a.png'          # pin kept
    assert 'new.png' in result.values()   # new file surfaced


def test_reconcile_preserves_out_of_range_stored(media_dir):
    present = ['a.png', 'b.png']
    stored = {200: 'b.png'}  # outside 36-99, file still exists
    result = main.reconcile_mapping(stored, present, 36, 99)
    assert result[200] == 'b.png'


def test_reconcile_drops_out_of_range_missing_file(media_dir):
    present = ['a.png']
    stored = {200: 'gone.png'}
    result = main.reconcile_mapping(stored, present, 36, 99)
    assert 200 not in result


# --- load_media integration --------------------------------------------------

def test_load_media_seeds_manifest_when_absent(media_dir):
    _write_images(media_dir / 'images', ['a.png', 'b.png'])
    assert not os.path.exists(main.MAPPING_PATH)
    note_to_media = main.load_media(36, 99)
    assert note_to_media is not None
    # The manifest was written on first launch.
    assert os.path.exists(main.MAPPING_PATH)
    saved = main.load_mapping()
    assert saved  # non-empty
    assert set(saved.values()) <= {'a.png', 'b.png'}


def test_load_media_honors_manifest_over_distribution(media_dir):
    # THE keystone guarantee: a pinned note survives restart and is not
    # recomputed by even-distribution.
    _write_images(media_dir / 'images', ['a.png', 'b.png', 'c.png'])
    main.save_mapping({36: 'c.png'})  # pin note 36 to c.png
    note_to_media = main.load_media(36, 99)
    # note 36's media must come from c.png. Verify via the reconciled file too.
    assert main.load_mapping()[36] == 'c.png'
    # Shared-object invariant: notes mapped to the same file share one dict, so
    # the grid view collapses them correctly.
    per_file = {}
    for note, media in note_to_media.items():
        per_file.setdefault(id(media), set())
    # Two notes pointing at the same filename must be the same object.
    saved = main.load_mapping()
    same_file_notes = [n for n, f in saved.items()
                       if f == saved[36] and 36 <= n <= 99]
    ids = {id(note_to_media[n]) for n in same_file_notes if n in note_to_media}
    assert len(ids) == 1


def test_load_media_survives_restart(media_dir):
    _write_images(media_dir / 'images', ['a.png', 'b.png', 'c.png'])
    first = main.load_media(36, 99)
    snapshot = dict(main.load_mapping())
    second = main.load_media(36, 99)
    # The manifest is stable across a second launch (no churn).
    assert main.load_mapping() == snapshot
    assert set(first) == set(second)


def test_load_media_none_when_empty(media_dir):
    assert main.load_media(36, 99) is None


def test_load_media_reconciles_deleted_file(media_dir):
    images = media_dir / 'images'
    _write_images(images, ['a.png', 'b.png'])
    main.load_media(36, 99)
    # Delete b.png, relaunch: manifest should no longer reference it.
    os.remove(images / 'b.png')
    main.load_media(36, 99)
    assert 'b.png' not in main.load_mapping().values()
