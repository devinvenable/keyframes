"""Headless tests for the contiguous key-zone media model."""
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
    images = tmp_path / 'images'
    images.mkdir()
    monkeypatch.setattr(main, 'IMAGES_DIR', str(images))
    monkeypatch.setattr(main, 'MAPPING_PATH', str(tmp_path / 'mapping.json'))
    return tmp_path


def test_zones_mapping_round_trip_and_normalize_legacy_fragments():
    mapping = {36: 'a.png', 37: 'b.png', 38: 'a.png', 39: 'b.png'}
    raw = main.zones_from_mapping(mapping, 36, 39)
    assert [zone['name'] for zone in raw] == ['a.png', 'b.png', 'a.png', 'b.png']

    zones = main.normalize_zones(raw, 36, 39)
    assert zones == [
        {'name': 'a.png', 'start_note': 36, 'end_note': 37},
        {'name': 'b.png', 'start_note': 38, 'end_note': 39},
    ]
    assert main.validate_zones(zones, 36, 39)
    assert main.mapping_from_zones(zones) == {
        36: 'a.png', 37: 'a.png', 38: 'b.png', 39: 'b.png',
    }


def test_move_zone_boundary_grows_and_shrinks_in_both_directions():
    zones = [
        {'name': 'a.png', 'start_note': 36, 'end_note': 38},
        {'name': 'b.png', 'start_note': 39, 'end_note': 42},
        {'name': 'c.png', 'start_note': 43, 'end_note': 43},
    ]
    trailing = main.move_zone_boundary(zones, 0, 'trailing', 2)
    assert trailing[0]['end_note'] == 40
    assert trailing[1]['start_note'] == 41
    assert main.validate_zones(trailing, 36, 43)

    # Moving B's leading boundary left grows B and shrinks A.
    leading = main.move_zone_boundary(trailing, 1, 'leading', -1)
    assert leading[0]['end_note'] == 39
    assert leading[1]['start_note'] == 40
    assert main.validate_zones(leading, 36, 43)


def test_boundary_move_clamps_at_one_key_per_zone():
    zones = [
        {'name': 'a.png', 'start_note': 36, 'end_note': 38},
        {'name': 'b.png', 'start_note': 39, 'end_note': 42},
    ]
    grown = main.move_zone_boundary(zones, 0, 'trailing', 99)
    assert grown[0]['end_note'] == 41
    assert grown[1]['start_note'] == 42

    shrunk = main.move_zone_boundary(zones, 0, 'trailing', -99)
    assert shrunk[0]['end_note'] == 36
    assert shrunk[1]['start_note'] == 37
    assert main.validate_zones(grown, 36, 42)
    assert main.validate_zones(shrunk, 36, 42)


def test_reconcile_preserves_zones_and_appends_new_file():
    stored = {36: 'a.png', 37: 'a.png', 38: 'a.png', 39: 'a.png',
              40: 'b.png', 41: 'b.png', 42: 'b.png', 43: 'b.png'}
    result = main.reconcile_mapping(stored, ['a.png', 'b.png', 'c.png'], 36, 43)
    zones = main.zones_from_mapping(result, 36, 43)
    assert zones == [
        {'name': 'a.png', 'start_note': 36, 'end_note': 39},
        {'name': 'b.png', 'start_note': 40, 'end_note': 42},
        {'name': 'c.png', 'start_note': 43, 'end_note': 43},
    ]
    assert main.validate_zones(zones, 36, 43)


def test_reconcile_removal_and_surplus_media_never_fragment_or_gap():
    stored = {36: 'a.png', 37: 'a.png', 38: 'b.png'}
    deleted = main.reconcile_mapping(stored, ['a.png'], 36, 38)
    assert main.validate_zones(main.zones_from_mapping(deleted, 36, 38), 36, 38)
    assert set(deleted.values()) == {'a.png'}

    surplus = main.reconcile_mapping({}, ['a.png', 'b.png', 'c.png', 'd.png'], 36, 38)
    zones = main.zones_from_mapping(surplus, 36, 38)
    assert main.validate_zones(zones, 36, 38)
    assert len(zones) == 3  # d.png is safely unassigned: no spare key exists.


def test_every_grid_edit_persists_a_contiguous_mapping(media_dir):
    images = media_dir / 'images'
    for name, color in [('a.png', (255, 0, 0)), ('b.png', (0, 255, 0)),
                        ('c.png', (0, 0, 255))]:
        image = pygame.Surface((8, 8))
        image.fill(color)
        pygame.image.save(image, str(images / name))
    note_to_media = main.load_media(36, 43)
    cells = main.build_grid_cells(note_to_media, (main.GRID_THUMB_W, main.GRID_THUMB_H))

    main.apply_swap(cells[0], cells[-1], note_to_media)
    assert main.validate_zones(main.zones_from_mapping(main.load_mapping(), 36, 43), 36, 43)

    zones = main.zones_from_mapping(main.load_mapping(), 36, 43)
    main.apply_zone_boundary_move(zones, 0, 'trailing', 1, note_to_media)
    assert main.validate_zones(main.zones_from_mapping(main.load_mapping(), 36, 43), 36, 43)

    # Replacing a zone with an already-present file consolidates it, rather
    # than leaving that filename in separated runs.
    cells = main.build_grid_cells(note_to_media, (main.GRID_THUMB_W, main.GRID_THUMB_H))
    assert main.apply_drop(str(images / 'a.png'), cells[-1], note_to_media)
    assert main.validate_zones(main.zones_from_mapping(main.load_mapping(), 36, 43), 36, 43)
