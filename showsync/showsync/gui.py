"""Main-thread GUI: pre-show setlist editor + 30 fps performer dashboard.

The editor owns a mutable Document (add/remove/rename songs, BPM, first-beat
offset) and never touches audio or MIDI; engines are built only when the show
starts, and closed again if the performer returns to the editor at the end of
the set. No engine writes happen from rendering.
"""
from pathlib import Path
import time

from .bpmdetect import Suggestions, estimate_bpm
from .document import Document
from .setlist import SetlistError
from .tempomap import TempoEvent

FIELDS = ('name', 'bpm', 'offset', 'ramp', 'start', 'dur')
EMPTY_HINT = 'Drop audio files here, or press O to open a setlist'
CUSTOM_TEMPO = 'custom tempo map (edit in YAML)'


def bpm_label(song):
    """'120' alone, or '120->140' when the tempo map leaves the base bpm."""
    final = song.tempo[-1].bpm if song.tempo else song.bpm
    return f'{song.bpm:g}' if final == song.bpm else f'{song.bpm:g}->{final:g}'


def timestamp(seconds):
    minutes, seconds = divmod(max(0, int(seconds)), 60)
    return f'{minutes:02d}:{seconds:02d}'


def _screen():
    import pygame
    pygame.display.init()
    pygame.font.init()
    screen = pygame.display.set_mode((1000, 600))
    pygame.display.set_caption('ShowSync')
    return screen


def _text(screen, fonts, fg):
    import pygame

    def text(value, xy, size=0, center=False, color=None):
        font = fonts[size]
        # Long performer-authored names remain fully visible.
        surface = font.render(value, True, color or fg)
        if surface.get_width() > 920:
            surface = pygame.transform.smoothscale(surface, (920, round(surface.get_height() * 920 / surface.get_width())))
        rect = surface.get_rect(center=xy) if center else surface.get_rect(topleft=xy)
        screen.blit(surface, rect)
    return text


def bpm_cell(row, state):
    if row.bpm is not None:
        return ('~' if state == 'estimated' else '') + f'{row.bpm:g}'
    if state == 'analyzing':
        return '...' + '|/-\\'[int(time.monotonic() * 6) % 4]
    return {'queued': 'queued', 'no estimate': 'none'}.get(state, '—')


def editor(document, *, dialogs=None, remember=None, notice='', max_frames=None,
           quit_on_exit=True, estimator=estimate_bpm):
    """Edit the set until the performer starts it; the show never sees this UI.

    Returns 'play', 'quit', or ('open', path). Every successful edit saves
    through the document (ruamel round trip); a set with no path yet asks
    where once, then stays silent until an explicit S if that was declined.
    """
    import pygame
    screen = _screen()
    fonts = [pygame.font.Font(None, size) for size in (30, 42, 64)]
    bg, fg = (12, 18, 28), (225, 237, 245)
    dim = tuple(bg[i] + (fg[i] - bg[i]) // 2 for i in range(3))
    alert = (235, 160, 120)
    text = _text(screen, fonts, fg)
    ticker = pygame.time.Clock()
    selected, field = 0, 0
    buffer = None  # None = browsing; str = editing the selected cell
    flash, flash_until = notice, time.monotonic() + 6 if notice else 0
    save_declined = False
    delete_armed_until = 0
    frames = 0
    suggestions = Suggestions(estimator)

    def show(message, seconds=4):
        nonlocal flash, flash_until
        flash, flash_until = message, time.monotonic() + seconds

    def autosave(explicit=False):
        if document.path is None:
            nonlocal save_declined
            if save_declined and not explicit:
                return
            target = None
            if dialogs:
                try:
                    target = dialogs.save_path(document.default_save_directory())
                except Exception as exc:
                    show(f'SAVE DIALOG UNAVAILABLE: {exc}', 6)
                    save_declined = True
                    return
            if not target:
                save_declined = True
                show('NOT SAVED YET — press S to choose a file', 6)
                return
            document.path = Path(target).expanduser().resolve()
        try:
            document.save()
            if remember:
                remember(document.path)
            if explicit:
                show(f'SAVED {document.path.name}', 2)
        except Exception as exc:
            show(f'SAVE FAILED: {exc}', 6)

    def commit():
        nonlocal buffer
        row, name = document.rows[selected], FIELDS[field]
        value = buffer.strip()
        if name in ('ramp', 'start', 'dur') and row.custom_tempo:
            show(CUSTOM_TEMPO)  # unreachable via ENTER, which refuses the edit
            return
        if name == 'name':
            if not value:
                show('name must not be empty')
                return
            row.name = value
        elif name == 'bpm':
            if not value:
                row.bpm = None
            else:
                try:
                    bpm = float(value)
                    if not 0 < bpm < 1000:
                        raise ValueError
                except ValueError:
                    show('BPM must be a number between 0 and 1000')
                    return
                row.bpm = bpm
        elif name == 'offset':
            try:
                offset = float(value or 0)
                if offset < 0:
                    raise ValueError
            except ValueError:
                show('offset must be nonnegative seconds')
                return
            if row.duration is not None and offset >= row.duration:
                show(f'offset must be under the file length ({row.duration:g}s)')
                return
            row.offset = offset
        elif name == 'ramp':
            if not value:
                row.tempo = ()
            else:
                try:
                    end = float(value)
                    if not 0 < end < 1000:
                        raise ValueError
                except ValueError:
                    show('end BPM must be a number between 0 and 1000')
                    return
                if row.ramp:
                    row.tempo = (TempoEvent(row.ramp.at, end, row.ramp.ramp),)
                elif row.duration is None:
                    show('cannot add a ramp: the file duration is unknown')
                    return
                elif row.offset >= row.duration:
                    show('fix the first-beat offset first — it is past the end of the file')
                    return
                else:
                    # New ramps run from beat 0 (the offset) to the end of the file.
                    row.tempo = (TempoEvent(row.offset, end, row.duration - row.offset),)
        else:
            event = row.ramp
            if event is None:
                show('set an end BPM first to add a ramp')
                return
            if name == 'start':
                try:
                    start = float(value or 0)
                    if start < 0:
                        raise ValueError
                except ValueError:
                    show('ramp start must be nonnegative seconds')
                    return
                # A ramp that reached the end of the file keeps doing so.
                to_end = row.duration is not None and event.at + event.ramp == row.duration
                length = row.duration - start if to_end and start < row.duration else event.ramp
                row.tempo = (TempoEvent(start, event.bpm, length),)
            else:
                if not value:
                    if row.duration is None or event.at >= row.duration:
                        show('cannot reach the end of the file from this ramp start')
                        return
                    length = row.duration - event.at
                else:
                    try:
                        length = float(value)
                        if length <= 0:
                            raise ValueError
                    except ValueError:
                        show('ramp duration must be positive seconds')
                        return
                row.tempo = (TempoEvent(event.at, event.bpm, length),)
        buffer = None
        pygame.key.stop_text_input()
        autosave()

    def add_paths(paths):
        added, rejected = document.add_files(paths)
        for path, reason in rejected:
            show(f'SKIPPED {path.name}: {reason}', 6)
        if added:
            autosave()

    try:
        while True:
            rows = document.rows
            if suggestions.update(rows):
                autosave()
            selected = max(0, min(selected, len(rows) - 1))
            buttons = [('A ADD SONGS', 'add'), ('S SAVE', 'save'),
                       ('SPACE START', 'play'), ('Q QUIT', 'quit')]
            rects = [pygame.Rect(45 + i * 232, 520, 216, 56) for i in range(len(buttons))]
            dropped = []
            for event in pygame.event.get():
                action = None
                if event.type == pygame.QUIT:
                    action = 'quit'
                elif event.type == pygame.DROPFILE:
                    dropped.append(event.file)
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and buffer is None:
                    action = next((act for rect, (_, act) in zip(rects, buttons)
                                   if rect.collidepoint(event.pos)), None)
                elif event.type == pygame.TEXTINPUT and buffer is not None:
                    buffer += event.text
                elif event.type == pygame.KEYDOWN and buffer is not None:
                    if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                        commit()
                    elif event.key == pygame.K_ESCAPE:
                        buffer = None
                        pygame.key.stop_text_input()
                    elif event.key == pygame.K_BACKSPACE:
                        buffer = buffer[:-1]
                elif event.type == pygame.KEYDOWN:
                    shift = getattr(event, 'mod', 0) & pygame.KMOD_SHIFT
                    if event.key == pygame.K_q:
                        action = 'quit'
                    elif event.key == pygame.K_SPACE:
                        action = 'play'
                    elif event.key == pygame.K_a:
                        action = 'add'
                    elif event.key == pygame.K_s:
                        action = 'save'
                    elif event.key == pygame.K_o:
                        action = 'open'
                    elif event.key in (pygame.K_UP, pygame.K_DOWN) and rows:
                        step = -1 if event.key == pygame.K_UP else 1
                        if shift:
                            target = selected + step
                            if 0 <= target < len(rows):
                                rows[selected], rows[target] = rows[target], rows[selected]
                                selected = target
                                autosave()
                        else:
                            selected = max(0, min(len(rows) - 1, selected + step))
                    elif event.key in (pygame.K_LEFT, pygame.K_RIGHT) and rows:
                        field = (field + (1 if event.key == pygame.K_RIGHT else -1)) % len(FIELDS)
                    elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER) and rows:
                        row = rows[selected]
                        if FIELDS[field] == 'bpm':
                            suggestions.manual(row)
                        if field >= 3 and row.custom_tempo:
                            show(CUSTOM_TEMPO)
                        else:
                            ramp = row.ramp
                            current = {'name': row.name,
                                       'bpm': '' if row.bpm is None else f'{row.bpm:g}',
                                       'offset': f'{row.offset:g}',
                                       'ramp': '' if ramp is None else f'{ramp.bpm:g}',
                                       'start': '' if ramp is None else f'{ramp.at:g}',
                                       'dur': '' if ramp is None else f'{ramp.ramp:g}'}[FIELDS[field]]
                            buffer = current
                            pygame.key.start_text_input()
                    elif event.key == pygame.K_DELETE and rows:
                        if time.monotonic() < delete_armed_until:
                            removed = rows.pop(selected)
                            delete_armed_until = 0
                            show(f'REMOVED {removed.name}', 3)
                            autosave()
                        else:
                            delete_armed_until = time.monotonic() + 3
                if action == 'quit':
                    return 'quit'
                elif action == 'play':
                    blocked = document.first_problem()
                    if blocked:
                        row, message = blocked
                        show(f"CAN'T START — {f'{row.name}: ' if row else ''}{message}", 5)
                    else:
                        return 'play'
                elif action == 'add':
                    if dialogs is None:
                        show('file dialogs unavailable — drop audio files onto the window', 6)
                    else:
                        try:
                            picked = dialogs.audio_files()
                        except Exception as exc:
                            show(f'FILE DIALOG UNAVAILABLE: {exc} — drop files instead', 6)
                        else:
                            add_paths(picked)
                elif action == 'save':
                    if rows or document.path:
                        autosave(explicit=True)
                elif action == 'open':
                    if dialogs is None:
                        show('file dialogs unavailable', 6)
                    else:
                        try:
                            target = dialogs.setlist_path()
                        except Exception as exc:
                            show(f'FILE DIALOG UNAVAILABLE: {exc}', 6)
                        else:
                            if target:
                                return ('open', target)
            if dropped:
                add_paths(dropped)

            screen.fill(bg)
            text(document.display_title, (40, 28))
            text(document.path.name if document.path else 'UNSAVED SET', (800, 28), color=dim)
            text('SETLIST EDITOR', (500, 80), 1, True)
            if not rows:
                text(EMPTY_HINT, (500, 240), 1, True)
                text('A add songs · O open · Q quit', (500, 300), center=True, color=dim)
            else:
                xs = (90, 350, 445, 555, 655, 760)
                for x, label in zip(xs + (880,),
                                    ('SONG', 'BPM', 'OFFSET', 'RAMP', 'START', 'DUR', '')):
                    text(label, (x, 108), color=dim)
                top = 140
                row_height = min(46, 340 // len(rows))
                cells = {0: (70, 270), 1: (340, 95), 2: (435, 110),
                         3: (545, 100), 4: (645, 105), 5: (750, 110)}
                for i, row in enumerate(rows):
                    y = top + i * row_height
                    if i == selected:
                        x0, width = cells[field]
                        pygame.draw.rect(screen, dim, (x0, y - 4, width, row_height - 2),
                                         width=0 if buffer is not None else 2, border_radius=6)
                    problem = row.problem()
                    name = row.name if len(row.name) <= 20 else row.name[:19] + '…'
                    ramp = row.ramp
                    display = [f'{i + 1:>2}  {name}',
                               bpm_cell(row, suggestions.state(row)),
                               f'{row.offset:g}s',
                               'custom' if row.custom_tempo else
                               '—' if ramp is None else f'->{ramp.bpm:g}',
                               '' if ramp is None else f'{ramp.at:g}s',
                               '' if ramp is None else f'{ramp.ramp:g}s']
                    colors = [None, alert if row.bpm is None else None, None,
                              dim if ramp is None else None, None, None]
                    editing_here = buffer is not None and i == selected
                    for j, x in enumerate(xs):
                        if editing_here and field == j:
                            value, color = buffer + '|', None
                            if j == 0:
                                value = f'{i + 1:>2}  {value}'
                        else:
                            value, color = display[j], colors[j]
                        if value:
                            text(value, (x, y), color=color)
                    if problem:
                        text('!', (885, y), color=alert)
                problem = rows[selected].problem()
                status = suggestions.state(rows[selected])
                if (status in ('analyzing', 'no estimate', 'estimated')
                        and problem in (None, 'BPM not set')):
                    problem = {'analyzing': 'Analyzing BPM…',
                               'no estimate': 'No estimate — enter BPM manually',
                               'estimated': 'Estimated BPM (~) — Enter to confirm or edit'}[status]
                if problem:
                    text(f'{rows[selected].name}: {problem}', (500, 468), center=True, color=alert)
                elif rows[selected].custom_tempo and field >= 3:
                    text(CUSTOM_TEMPO, (500, 468), center=True, color=dim)
                text('ENTER edit · LEFT/RIGHT field · SHIFT+UP/DOWN move · DEL DEL remove · '
                     'RAMP end BPM, START/DUR seconds',
                     (500, 495), center=True, color=dim)
            for rect, (label, _) in zip(rects, buttons):
                pygame.draw.rect(screen, fg, rect, width=2, border_radius=8)
                text(label, rect.center, center=True)
            if time.monotonic() < delete_armed_until and rows:
                text(f'PRESS DELETE AGAIN TO REMOVE {rows[selected].name}', (500, 110), 1, True)
            if time.monotonic() < flash_until:
                text(flash, (500, 592), center=True)
            pygame.display.flip()
            ticker.tick(30)
            frames += 1
            if max_frames is not None and frames >= max_frames:
                return 'quit'
    finally:
        suggestions.close()
        if quit_on_exit:
            pygame.quit()


def run(audio, clock, *, persist=None, max_frames=None, editable=False,
        quit_on_exit=True):
    """Performance dashboard; returns 'quit', or 'edit' from the ended state."""
    import pygame
    screen = _screen()
    fonts = [pygame.font.Font(None, size) for size in (30, 42, 64)]
    ticker = pygame.time.Clock()
    running, frames = True, 0
    result = 'quit'
    warning_until, last_underruns = 0, 0
    setlist_view, selected = False, 0
    confirm_until = 0
    flash, flash_until = '', 0

    def attempt_move(delta):
        nonlocal selected, flash, flash_until
        target = audio.move(selected, delta)
        if target is None:
            flash, flash_until = "CAN'T MOVE THAT SONG NOW", time.monotonic() + 2
            return
        selected = target
        if persist:
            try:
                persist(audio.order)
            except Exception as exc:
                flash, flash_until = f'ORDER NOT SAVED: {exc}', time.monotonic() + 6

    try:
        while running:
            p = audio.position()
            songs = audio.setlist.songs
            first_movable = 0 if p.ended else p.song_index + 1
            buttons = ([('R RESTART', 'restart')] +
                       ([('E EDIT SET', 'edit')] if editable else []) +
                       [('Q quit', 'quit')] if p.ended else
                       [('SPACE resume' if not p.playing else 'SPACE pause', 'pause'),
                        ('N skip', 'skip'), ('Q quit', 'quit')])
            rects = [pygame.Rect(55 + i * 315, 500, 280, 65) for i in range(len(buttons))]
            for event in pygame.event.get():
                action = None
                if event.type == pygame.QUIT:
                    action = 'quit'
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    action = next((act for rect, (_, act) in zip(rects, buttons)
                                   if rect.collidepoint(event.pos)), None)
                elif event.type == pygame.KEYDOWN:
                    shift = getattr(event, 'mod', 0) & pygame.KMOD_SHIFT
                    if event.key == pygame.K_q:
                        action = 'quit'
                    elif event.key == pygame.K_SPACE and not p.ended:
                        action = 'pause'
                    elif event.key == pygame.K_n and not p.ended:
                        action = 'skip'
                    elif event.key == pygame.K_r:
                        action = 'restart'
                    elif event.key == pygame.K_e and p.ended and editable:
                        action = 'edit'
                    elif event.key == pygame.K_TAB or (event.key == pygame.K_ESCAPE and setlist_view):
                        setlist_view = not setlist_view
                        selected = min(first_movable, len(songs) - 1)
                    elif setlist_view and event.key in (pygame.K_UP, pygame.K_DOWN):
                        step = -1 if event.key == pygame.K_UP else 1
                        if shift:
                            attempt_move(step)
                        else:
                            selected = max(0, min(len(songs) - 1, selected + step))
                if action == 'pause':
                    audio.toggle_pause()
                elif action == 'skip':
                    audio.skip()
                elif action == 'restart':
                    # Single keypress only from the ended state; live, a stray R
                    # must not blow up the show, so it arms a 3 s confirm window.
                    if p.ended or time.monotonic() < confirm_until:
                        audio.restart()
                        confirm_until = 0
                    else:
                        confirm_until = time.monotonic() + 3
                elif action == 'edit':
                    result = 'edit'
                    running = False
                elif action == 'quit':
                    running = False
            song = songs[p.song_index]
            tempo = audio.maps[p.song_index]
            paused = not p.playing and not p.ended
            bg, fg = ((40, 29, 12), (190, 137, 58)) if paused else ((12, 18, 28), (225, 237, 245))
            dim = tuple(bg[i] + (fg[i] - bg[i]) // 2 for i in range(3))
            screen.fill(bg)
            text = _text(screen, fonts, fg)

            text(audio.setlist.title, (40, 28))
            text(f'{p.song_index + 1}/{len(songs)} songs', (800, 28))
            if setlist_view:
                text('SETLIST', (500, 90), 1, True)
                top, row_height = 130, min(46, 330 // max(1, len(songs)))
                for i, entry in enumerate(songs):
                    y = top + i * row_height
                    movable = i >= first_movable
                    if i == selected:
                        pygame.draw.rect(screen, dim, (70, y - 4, 860, row_height - 2), border_radius=6)
                    # '>' rather than '▶': pygame's bundled font has no glyph for it.
                    marker = '>' if i == p.song_index and not p.ended else ' '
                    text(f'{marker} {i + 1:>2}  {entry.name}  ({bpm_label(entry)} BPM)', (90, y),
                         color=fg if movable else dim)
                text('UP/DOWN select   SHIFT+UP/DOWN move   TAB close', (500, 475), center=True, color=dim)
            else:
                text(song.name, (500, 155), 2, True)
                target = tempo.ramp_target(p.song_time)
                bpm = f'{tempo.bpm_at(p.song_time):.1f} BPM'
                if target is not None:
                    bpm += f'  (ramping to {target:g})'
                text(bpm, (500, 255), 2, True)
                state = ('END OF SET' if p.ended else
                         'PAUSED' if paused else
                         'GAP' if p.gap else
                         'LEAD-IN' if p.song_time < song.offset else 'PLAYING')
                text(state, (500, 305), center=True)
                elapsed = min(p.song_time, audio.durations[p.song_index])
                progress = elapsed / audio.durations[p.song_index]
                pygame.draw.rect(screen, (65, 65, 65), (180, 355, 640, 8))
                pygame.draw.rect(screen, fg, (180, 355, round(640 * progress), 8))
                text(timestamp(elapsed), (65, 345))
                text('-' + timestamp(audio.durations[p.song_index] - elapsed), (845, 345))
                upcoming = songs[p.song_index + 1] if p.song_index + 1 < len(songs) else None
                if p.ended:
                    text('NEXT: press R to restart from the top', (55, 425), 1)
                else:
                    text(f'NEXT: {upcoming.name}  ({bpm_label(upcoming)} BPM)' if upcoming else 'NEXT: end of set', (55, 425), 1)
            for rect, (label, _) in zip(rects, buttons):
                pygame.draw.rect(screen, fg, rect, width=2, border_radius=8)
                text(label, rect.center, center=True)
            if audio.underruns != last_underruns:
                warning_until, last_underruns = time.monotonic() + 2, audio.underruns
            if time.monotonic() < warning_until:
                text(f'AUDIO UNDERRUN ({audio.underruns})', (500, 390), center=True)
            if time.monotonic() < confirm_until:
                text('PRESS R AGAIN TO RESTART THE SET', (500, 110), 1, True)
            if time.monotonic() < flash_until:
                text(flash, (500, 583), center=True)
            error = audio.error or clock.error
            if error:
                raise RuntimeError(error)
            pygame.display.flip()
            ticker.tick(30)
            frames += 1
            if max_frames is not None and frames >= max_frames:
                running = False
    finally:
        if quit_on_exit:
            pygame.quit()
    return result


def main_loop(document, *, start_engines, dialogs=None, remember=None,
              autoplay=False, notice=''):
    """Alternate editor and show phases over one document until quit.

    `start_engines(setlist)` returns (audio, clock, close); engines exist only
    while the show phase runs, so editing never holds audio or MIDI devices.
    """
    import pygame
    try:
        while True:
            if not autoplay:
                result = editor(document, dialogs=dialogs, remember=remember,
                                notice=notice, quit_on_exit=False)
                notice = ''
                if result == 'quit':
                    return 0
                if isinstance(result, tuple):
                    try:
                        replacement = Document.load(result[1])
                    except SetlistError as exc:
                        notice = f'OPEN FAILED: {exc}'
                    else:
                        document = replacement
                        if remember:
                            remember(document.path)
                    continue
            autoplay = False
            try:
                audio, clock, close = start_engines(document.setlist())
            except Exception as exc:
                notice = f"COULD NOT START THE SHOW: {exc}"
                continue
            baseline = list(document.rows)

            def persist(order):
                document.rows = [baseline[i] for i in order]
                document.save()

            try:
                result = run(audio, clock, persist=persist, editable=True,
                             quit_on_exit=False)
            finally:
                close()
            if result != 'edit':
                return 0
    finally:
        pygame.quit()
