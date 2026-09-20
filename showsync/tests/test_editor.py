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


@pytest.mark.parametrize('source', ['load', 'drop', 'picker'])
def test_async_bpm_suggestion_is_rendered_saved_and_confirmed(monkeypatch, tmp_path, source):
    import threading
    import pygame
    from showsync import gui
    monkeypatch.setenv('SDL_VIDEODRIVER', 'dummy')
    target = tmp_path / 'suggestions.yaml'
    target.write_text(f'songs:\n  - name: Existing\n    file: {TONE}\n    bpm: 99\n')
    document = Document.load(target)
    if source == 'load':
        target.write_text(target.read_text() + f'  - name: Blank\n    file: {TONE}\n')
        document = Document.load(target)
    entered, release = threading.Event(), threading.Event()
    instances, calls, rendered = [], [], []
    class Worker(gui.Suggestions):
        def __init__(self, estimator):
            super().__init__(estimator)
            instances.append(self)
    monkeypatch.setattr(gui, 'Suggestions', Worker)
    original_text = gui._text
    def text(*args):
        draw = original_text(*args)
        def capture(value, *args, **kwargs):
            rendered.append(value)
            return draw(value, *args, **kwargs)
        return capture
    monkeypatch.setattr(gui, '_text', text)
    def estimator(path, *, cancelled):
        calls.append(path)
        entered.set()
        assert release.wait(2)
        return 118.5
    frame = 0
    def events():
        nonlocal frame
        frame += 1
        if frame == 1:
            if source == 'drop':
                return [pygame.event.Event(pygame.DROPFILE, file=str(TONE))]
            if source == 'picker':
                return [pygame.event.Event(pygame.KEYDOWN, key=pygame.K_a)]
        if frame == 3:
            assert entered.wait(2)
            assert any(value.startswith('...') for value in rendered)
            release.set()
            instances[0].worker.join(2)
        if frame == 5:
            assert document.rows[1].bpm == 118.5
            assert '~118.5' in rendered
            assert Document.load(target).rows[1].bpm == 118.5
            return [pygame.event.Event(pygame.KEYDOWN, key=k) for k in
                    (pygame.K_DOWN, pygame.K_RIGHT, pygame.K_RETURN, pygame.K_ESCAPE)]
        if frame == 6:
            assert instances[0].state(document.rows[1]) == 'manual'
            assert gui.bpm_cell(document.rows[1], 'manual') == '118.5'
            return [pygame.event.Event(pygame.KEYDOWN, key=pygame.K_q)]
        return []
    monkeypatch.setattr(pygame.event, 'get', events)
    try:
        assert gui.editor(document, dialogs=Dialogs(files=[TONE]), estimator=estimator,
                          max_frames=8) == 'quit'
    finally:
        release.set()
    assert calls == [TONE.resolve()]
    assert document.rows[0].bpm == 99
    assert not instances[0].worker.is_alive()


def test_editor_manual_bpm_wins_and_play_cancels_detection(monkeypatch):
    import threading
    import pygame
    from showsync.bpmdetect import Cancelled
    entered, exited = threading.Event(), threading.Event()
    def estimator(path, *, cancelled):
        entered.set()
        while not cancelled():
            exited.wait(.001)
        exited.set()
        raise Cancelled
    document = Document()
    document.add_files([TONE])
    batches = [[], [key(pygame.K_RIGHT), key(pygame.K_RETURN)],
               typing('123') + [key(pygame.K_RETURN)], [key(pygame.K_SPACE)]]
    drive(monkeypatch, batches)
    assert editor(document, estimator=estimator, max_frames=6) == 'play'
    assert entered.is_set() and exited.is_set()
    assert document.rows[0].bpm == 123


def test_editor_inconclusive_notice_stays_unplayable(monkeypatch):
    import pygame
    from showsync import gui
    document = Document()
    document.add_files([TONE])
    workers, rendered = [], []
    class Worker(gui.Suggestions):
        def __init__(self, estimator):
            super().__init__(estimator)
            workers.append(self)
    monkeypatch.setattr(gui, 'Suggestions', Worker)
    monkeypatch.setattr(gui, '_text', lambda *args: lambda value, *a, **k: rendered.append(value))
    drive(monkeypatch, [])
    frame = 0
    def events():
        nonlocal frame
        frame += 1
        if frame == 1:
            workers[0].worker.join(2)
        return [pygame.event.Event(pygame.KEYDOWN, key=pygame.K_SPACE)]
    monkeypatch.setattr(pygame.event, 'get', events)
    assert editor(document, estimator=lambda path, **kw: None, max_frames=3) == 'quit'
    assert document.rows[0].bpm is None
    assert any('No estimate' in value for value in rendered)
    assert any("CAN'T START" in value for value in rendered)
