"""Main-thread, 30 fps performer dashboard. No engine writes from rendering."""
import time


def timestamp(seconds):
    minutes, seconds = divmod(max(0, int(seconds)), 60)
    return f'{minutes:02d}:{seconds:02d}'


def run(audio, clock, *, persist=None, max_frames=None):
    import pygame
    pygame.display.init()
    pygame.font.init()
    screen = pygame.display.set_mode((1000, 600))
    pygame.display.set_caption('ShowSync')
    fonts = [pygame.font.Font(None, size) for size in (30, 42, 64)]
    ticker = pygame.time.Clock()
    running, frames = True, 0
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
            buttons = ([('R RESTART', 'restart'), ('Q quit', 'quit')] if p.ended else
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
                elif action == 'quit':
                    running = False
            song = songs[p.song_index]
            tempo = audio.maps[p.song_index]
            paused = not p.playing and not p.ended
            bg, fg = ((40, 29, 12), (190, 137, 58)) if paused else ((12, 18, 28), (225, 237, 245))
            dim = tuple(bg[i] + (fg[i] - bg[i]) // 2 for i in range(3))
            screen.fill(bg)

            def text(value, xy, size=0, center=False, color=None):
                font = fonts[size]
                # Long performer-authored names remain fully visible.
                surface = font.render(value, True, color or fg)
                if surface.get_width() > 920:
                    surface = pygame.transform.smoothscale(surface, (920, round(surface.get_height() * 920 / surface.get_width())))
                rect = surface.get_rect(center=xy) if center else surface.get_rect(topleft=xy)
                screen.blit(surface, rect)

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
                    text(f'{marker} {i + 1:>2}  {entry.name}  ({entry.bpm:g} BPM)', (90, y),
                         color=fg if movable else dim)
                text('UP/DOWN select   SHIFT+UP/DOWN move   TAB close', (500, 475), center=True, color=dim)
            else:
                text(song.name, (500, 155), 2, True)
                target = tempo.ramp_target(p.song_time)
                bpm = f'{tempo.bpm_at(p.song_time):.1f} BPM'
                if target is not None:
                    bpm += f'  (ramping to {target:g})'
                text(bpm, (500, 255), 2, True)
                state = 'END OF SET' if p.ended else ('PAUSED' if paused else ('GAP' if p.gap else 'PLAYING'))
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
                    text(f'NEXT: {upcoming.name}  ({upcoming.bpm:g} BPM)' if upcoming else 'NEXT: end of set', (55, 425), 1)
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
        pygame.quit()
