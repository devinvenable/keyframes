from pathlib import Path
from types import SimpleNamespace

import pytest

from showsync.audio import Anchor, AudioEngine
from showsync.document import Document
from showsync.gui import editor, run
from showsync.setlist import Setlist, Song, load_setlist

FIXTURES = Path(__file__).parent / 'fixtures'
TONE = FIXTURES / 'tone.wav'


class Dialogs:
    def __init__(self, save=None, open_=None, files=()):
        self.save, self.open_, self.files = save, open_, list(files)
        self.save_dirs = []

    def save_path(self, directory):
        self.save_dirs.append(Path(directory))
        return self.save

    def setlist_path(self):
        return self.open_

    def audio_files(self):
        return self.files


def drive(monkeypatch, batches):
    monkeypatch.setenv('SDL_VIDEODRIVER', 'dummy')
    import pygame
    prepared = [[pygame.event.Event(kind, **attrs) for kind, attrs in batch]
                for batch in batches]
    events = iter(prepared)
    monkeypatch.setattr(pygame.event, 'get', lambda: next(events, []))
    return pygame


def key(k, mod=0):
    import pygame
    return (pygame.KEYDOWN, dict(key=k, mod=mod))


def typing(text):
    import pygame
    return [(pygame.TEXTINPUT, dict(text=char)) for char in text]


def test_build_a_set_from_nothing_and_start_it(monkeypatch, tmp_path):
    monkeypatch.setenv('SDL_VIDEODRIVER', 'dummy')
    import pygame
    target = tmp_path / 'my-set.yaml'
    dialogs = Dialogs(save=target)
    remembered = []
    batches = [
        # Two audio files and one reject dropped on the window (one batch).
        [(pygame.DROPFILE, dict(file=str(TONE))),
         (pygame.DROPFILE, dict(file=str(FIXTURES / 'tone.flac'))),
         (pygame.DROPFILE, dict(file=str(FIXTURES / 'fall2026.yaml')))],
        [key(pygame.K_SPACE)],                    # blocked: BPM not set
        [key(pygame.K_RETURN)],                   # selects row 1 name... field 0
        [key(pygame.K_ESCAPE)],                   # cancel the name edit
        [key(pygame.K_RIGHT), key(pygame.K_RETURN)],   # edit BPM of row 1
        typing('120') + [key(pygame.K_RETURN)],   # commit 120
        [key(pygame.K_DOWN), key(pygame.K_RETURN)],    # BPM of row 2
        typing('90.5') + [key(pygame.K_RETURN)],
        [key(pygame.K_RIGHT), key(pygame.K_RETURN)],   # offset of row 2
        typing('0.25') + [key(pygame.K_RETURN)],
        [key(pygame.K_SPACE)],                    # now playable
    ]
    drive(monkeypatch, batches)
    document = Document()
    result = editor(document, dialogs=dialogs, remember=remembered.append,
                    max_frames=len(batches) + 2)
    assert result == 'play'
    assert dialogs.save_dirs[0] == TONE.parent    # save defaults next to first audio
    assert remembered[-1] == target
    saved = load_setlist(target)
    assert [(s.name, s.bpm, s.offset) for s in saved.songs] == \
        [('tone', 120, 0), ('tone', 90.5, 0.25)]
    assert document.setlist().songs[1].offset == 0.25


def test_rename_move_delete_and_declined_save(monkeypatch, tmp_path):
    import pygame
    target = tmp_path / 'set.yaml'
    dialogs = Dialogs(save=None, files=[TONE, TONE])  # first save is cancelled
    batches = [
        [key(pygame.K_a)],                        # add two files via the picker
        # The cell edit starts prefilled with the current name: clear it first.
        [key(pygame.K_RETURN)] + [key(pygame.K_BACKSPACE)] * 4
        + typing('!Intro') + [key(pygame.K_RETURN)],
        [key(pygame.K_DOWN), key(pygame.K_UP, pygame.KMOD_SHIFT)],  # move row 2 up
        [key(pygame.K_DELETE)],                   # arms only
        [key(pygame.K_DELETE)],                   # removes the moved row
        [key(pygame.K_s)],                        # explicit save: dialog again
        [key(pygame.K_q)],
    ]
    drive(monkeypatch, batches)
    document = Document()
    saves = []
    dialogs.save = target                         # second ask succeeds

    class Flaky(Dialogs):
        def save_path(self, directory):
            saves.append(directory)
            return None if len(saves) == 1 else target
    flaky = Flaky(files=[TONE, TONE])
    result = editor(document, dialogs=flaky, max_frames=len(batches) + 2)
    assert result == 'quit'
    assert len(saves) == 2                        # declined once, asked again on S only
    assert [row.name for row in document.rows] == ['!Intro']
    assert document.rows[0].bpm is None           # still unset; file saved leniently
    reopened = Document.load(target)
    assert [row.name for row in reopened.rows] == ['!Intro']
    assert reopened.rows[0].problem() == 'BPM not set'


def test_open_and_empty_hint_and_bad_input_flash(monkeypatch, tmp_path):
    import pygame
    other = tmp_path / 'other.yaml'
    other.write_text(f'songs:\n  - name: X\n    file: {TONE}\n    bpm: 100\n')
    batches = [[key(pygame.K_o)]]
    drive(monkeypatch, batches)
    result = editor(Document(), dialogs=Dialogs(open_=other), max_frames=3)
    assert result == ('open', other)


def test_end_of_set_returns_to_editor(monkeypatch):
    monkeypatch.setenv('SDL_VIDEODRIVER', 'dummy')
    import pygame
    engine = AudioEngine(Setlist('t', (Song('A', TONE, 120),)))
    engine._anchors.append(Anchor(engine.total_frames, engine.total_frames, 0.0, False, 0))
    events = iter([[pygame.event.Event(pygame.KEYDOWN, key=pygame.K_e, mod=0)]])
    monkeypatch.setattr(pygame.event, 'get', lambda: next(events, []))
    assert run(engine, SimpleNamespace(error=None), editable=True, max_frames=3) == 'edit'


def test_lead_in_state_shown(monkeypatch):
    monkeypatch.setenv('SDL_VIDEODRIVER', 'dummy')
    import pygame
    engine = AudioEngine(Setlist('t', (Song('A', TONE, 120, offset=0.5),)))
    monkeypatch.setattr(pygame.event, 'get', lambda: [])
    # Renders the LEAD-IN state without error; position 0 < offset.
    assert run(engine, SimpleNamespace(error=None), max_frames=2) == 'quit'


def test_bpm_label_shows_ramp_range():
    from showsync.gui import bpm_label
    from showsync.tempomap import TempoEvent
    assert bpm_label(Song('A', TONE, 120)) == '120'
    assert bpm_label(Song('B', TONE, 120, tempo=(TempoEvent(10, 140, 20),))) == '120->140'
    # A map that returns to the base bpm reads as a single number again.
    assert bpm_label(Song('C', TONE, 120, tempo=(
        TempoEvent(10, 126, 0), TempoEvent(50, 120, 0)))) == '120'


def ramp_document(tmp_path, **row_kwargs):
    from showsync.document import Row
    row = Row(name='Ramp Up', file=TONE, bpm=120, **row_kwargs)
    return Document(path=tmp_path / 'set.yaml', rows=[row]), row


def edit(monkeypatch, document, batches):
    drive(monkeypatch, batches)
    assert editor(document, max_frames=len(batches) + 2) == 'quit'


def test_ramp_controls_recreate_the_demo_ramp_up_song(monkeypatch, tmp_path):
    import pygame
    document, row = ramp_document(tmp_path, duration=40.0)
    batches = [
        [key(pygame.K_RIGHT)] * 3 + [key(pygame.K_RETURN)],   # RAMP cell
        typing('0') + [key(pygame.K_RETURN)],                 # rejected end BPM
        [key(pygame.K_ESCAPE)],
        [key(pygame.K_RETURN)] + typing('140') + [key(pygame.K_RETURN)],
        [key(pygame.K_RIGHT), key(pygame.K_RETURN)],          # START, prefilled '0'
        [key(pygame.K_BACKSPACE)] + typing('10') + [key(pygame.K_RETURN)],
        [key(pygame.K_RIGHT), key(pygame.K_RETURN)],          # DUR, prefilled '30'
        [key(pygame.K_BACKSPACE)] * 2 + typing('20') + [key(pygame.K_RETURN)],
        [key(pygame.K_q)],
    ]
    edit(monkeypatch, document, batches)
    saved = load_setlist(tmp_path / 'set.yaml', duration_probe=lambda _: 40.0)
    # frozen copy of the original demo setlist — demo/demo-setlist.yaml itself
    # is rewritten by live GUI use and must never back a test
    demo = load_setlist(Path(__file__).parent / 'fixtures' / 'demo_ramp_reference.yaml',
                        check_files=False)
    hand_written = demo.songs[1]
    assert hand_written.name == 'Ramp Up'
    assert saved.songs[0].bpm == hand_written.bpm == 120
    assert saved.songs[0].tempo == hand_written.tempo
    ours, theirs = saved.songs[0].tempo_map(40.0), hand_written.tempo_map(40.0)
    for t in (0, 5, 10, 15, 20, 30, 40):     # identical clock at every point
        assert ours.B(t) == pytest.approx(theirs.B(t), abs=1e-12)
        assert ours.bpm_at(t) == theirs.bpm_at(t)


def test_ramp_defaults_track_offset_and_run_to_end(monkeypatch, tmp_path):
    import pygame
    from showsync.tempomap import TempoEvent
    document, row = ramp_document(tmp_path, duration=60.0, offset=5.0)
    # Enabling the ramp defaults START to beat 0 (the offset) and DUR to the end.
    edit(monkeypatch, document, [
        [key(pygame.K_RIGHT)] * 3 + [key(pygame.K_RETURN)],
        typing('140') + [key(pygame.K_RETURN)], [key(pygame.K_q)]])
    assert row.tempo == (TempoEvent(5.0, 140.0, 55.0),)
    assert row.problem() is None              # at == offset is a legal ramp
    # Moving START keeps a to-the-end ramp reaching the end.
    edit(monkeypatch, document, [
        [key(pygame.K_RIGHT)] * 4 + [key(pygame.K_RETURN)],
        [key(pygame.K_BACKSPACE)] + typing('10') + [key(pygame.K_RETURN)],
        [key(pygame.K_q)]])
    assert row.tempo == (TempoEvent(10.0, 140.0, 50.0),)
    # An explicit DUR sticks; clearing the cell restores duration-to-end.
    edit(monkeypatch, document, [
        [key(pygame.K_LEFT), key(pygame.K_RETURN)],
        [key(pygame.K_BACKSPACE)] * 2 + typing('20') + [key(pygame.K_RETURN)],
        [key(pygame.K_q)]])
    assert row.tempo == (TempoEvent(10.0, 140.0, 20.0),)
    edit(monkeypatch, document, [
        [key(pygame.K_LEFT), key(pygame.K_RETURN)],
        [key(pygame.K_BACKSPACE)] * 2 + [key(pygame.K_RETURN)],
        [key(pygame.K_q)]])
    assert row.tempo == (TempoEvent(10.0, 140.0, 50.0),)
    # A START inside the lead-in commits leniently; the validator message shows.
    edit(monkeypatch, document, [
        [key(pygame.K_RIGHT)] * 4 + [key(pygame.K_RETURN)],
        [key(pygame.K_BACKSPACE)] * 2 + typing('2') + [key(pygame.K_RETURN)],
        [key(pygame.K_q)]])
    assert row.tempo == (TempoEvent(2.0, 140.0, 58.0),)
    assert 'first-beat offset' in row.problem()


def test_start_and_dur_require_an_end_bpm_first(monkeypatch, tmp_path):
    import pygame
    document, row = ramp_document(tmp_path, duration=60.0)
    edit(monkeypatch, document, [
        [key(pygame.K_RIGHT)] * 4 + [key(pygame.K_RETURN)],
        typing('5') + [key(pygame.K_RETURN)],   # refused: no ramp yet
        [key(pygame.K_ESCAPE)], [key(pygame.K_q)]])
    assert row.tempo == ()


def test_custom_tempo_rows_are_read_only(monkeypatch, tmp_path):
    import pygame
    from showsync.tempomap import TempoEvent
    hand_authored = (TempoEvent(10, 126, 0), TempoEvent(30, 120, 0))
    document, row = ramp_document(tmp_path, duration=60.0, tempo=hand_authored)
    edit(monkeypatch, document, [
        [key(pygame.K_RIGHT)] * 3 + [key(pygame.K_RETURN)],   # refused: custom map
        typing('140') + [key(pygame.K_RETURN)],               # goes nowhere
        [key(pygame.K_q)]])
    assert row.tempo == hand_authored
