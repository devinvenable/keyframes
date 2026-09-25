"""--editor-screen: screen matching and CLI plumbing (task 138)."""
from types import SimpleNamespace

from showsync import cli
from showsync.gui import place_editor, resolve_screen


def screens(*names):
    return [SimpleNamespace(name=lambda n=n: n,
                            availableGeometry=lambda n=n: SimpleNamespace(
                                topLeft=lambda: f'{n}-corner'))
            for n in names]


class FakeWindow:
    def __init__(self):
        self.screen = self.pos = None

    def setScreen(self, screen):
        self.screen = screen

    def move(self, pos):
        self.pos = pos


def test_place_editor_moves_to_named_screen():
    pool = screens('DP-1', 'HDMI-0')
    window = FakeWindow()
    place_editor(window, pool, 'HDMI-0')
    assert window.screen is pool[1]
    assert window.pos == 'HDMI-0-corner'


def test_place_editor_leaves_default_when_absent_or_unknown(caplog):
    window = FakeWindow()
    place_editor(window, screens('DP-1'), None)
    assert window.screen is None and window.pos is None
    place_editor(window, screens('DP-1'), 'HDMI-0')
    assert window.screen is None and window.pos is None
    assert any('matches no connected screen' in r.message for r in caplog.records)


def test_resolve_by_exact_name():
    pool = screens('DP-3', 'DP-1', 'HDMI-0')
    assert resolve_screen(pool, 'HDMI-0') is pool[2]


def test_resolve_by_index():
    pool = screens('DP-3', 'DP-1', 'HDMI-0')
    assert resolve_screen(pool, '1') is pool[1]


def test_name_wins_over_index():
    pool = screens('1', 'DP-1')
    assert resolve_screen(pool, '1') is pool[0]


def test_no_match_and_out_of_range_return_none():
    pool = screens('DP-1')
    assert resolve_screen(pool, 'HDMI-0') is None
    assert resolve_screen(pool, '5') is None
    assert resolve_screen(pool, None) is None


def test_cli_passes_editor_screen_through(monkeypatch, tmp_path):
    seen = {}

    def fake_loop(document, **kwargs):
        seen.update(kwargs)
        return 0

    monkeypatch.setattr(cli, 'main_loop', fake_loop)
    monkeypatch.setattr(cli, 'last_setlist', lambda: None)
    assert cli.main(['--editor-screen', 'HDMI-0']) == 0
    assert seen['editor_screen'] == 'HDMI-0'


def test_cli_default_is_no_editor_screen(monkeypatch):
    seen = {}

    def fake_loop(document, **kwargs):
        seen.update(kwargs)
        return 0

    monkeypatch.setattr(cli, 'main_loop', fake_loop)
    monkeypatch.setattr(cli, 'last_setlist', lambda: None)
    assert cli.main([]) == 0
    assert seen['editor_screen'] is None


# Task 140: --editor-screen must never drag the projector along. The
# projector resolves its own monitor: remembered name, else primary.

def test_projector_screen_resolves_remembered_name():
    from showsync.video_window import projector_screen
    pool = screens('DP-1', 'HDMI-0')
    assert projector_screen(pool, pool[0], 'HDMI-0') is pool[1]


def test_projector_screen_falls_back_to_primary_never_editor():
    from showsync.video_window import projector_screen
    pool = screens('DP-1', 'HDMI-0')
    primary = pool[0]
    assert projector_screen(pool, primary, '') is primary
    assert projector_screen(pool, primary, 'DP-GONE') is primary
