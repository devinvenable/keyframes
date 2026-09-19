"""Main-thread, 30 fps performer dashboard. No engine writes from rendering."""
import time


def timestamp(seconds):
    minutes, seconds = divmod(max(0, int(seconds)), 60)
    return f'{minutes:02d}:{seconds:02d}'


def run(audio, clock, *, max_frames=None):
    import pygame
    pygame.display.init()
    pygame.font.init()
    screen = pygame.display.set_mode((1000, 600))
    pygame.display.set_caption('ShowSync')
    fonts = [pygame.font.Font(None, size) for size in (30, 42, 64)]
    ticker = pygame.time.Clock()
    buttons = [pygame.Rect(55 + i * 315, 500, 280, 65) for i in range(3)]
    running, frames = True, 0
    warning_until, last_underruns = 0, 0
    try:
        while running:
            for event in pygame.event.get():
                action = None
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    action = {pygame.K_SPACE: 0, pygame.K_n: 1, pygame.K_q: 2}.get(event.key)
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    action = next((i for i, rect in enumerate(buttons) if rect.collidepoint(event.pos)), None)
                if action == 0:
                    audio.toggle_pause()
                elif action == 1:
                    audio.skip()
                elif action == 2:
                    running = False
            p = audio.position()
            song = audio.setlist.songs[p.song_index]
            tempo = audio.maps[p.song_index]
            paused = not p.playing
            bg, fg = ((40, 29, 12), (190, 137, 58)) if paused else ((12, 18, 28), (225, 237, 245))
            screen.fill(bg)

            def text(value, xy, size=0, center=False):
                font = fonts[size]
                # Long performer-authored names remain fully visible.
                surface = font.render(value, True, fg)
                if surface.get_width() > 920:
                    surface = pygame.transform.smoothscale(surface, (920, round(surface.get_height() * 920 / surface.get_width())))
                rect = surface.get_rect(center=xy) if center else surface.get_rect(topleft=xy)
                screen.blit(surface, rect)

            text(audio.setlist.title, (40, 28))
            text(f'{p.song_index + 1}/{len(audio.setlist.songs)} songs', (800, 28))
            text(song.name, (500, 155), 2, True)
            target = tempo.ramp_target(p.song_time)
            bpm = f'{tempo.bpm_at(p.song_time):.1f} BPM'
            if target is not None:
                bpm += f'  (ramping → {target:g})'
            text(bpm, (500, 255), 2, True)
            state = 'END OF SET' if p.ended else ('PAUSED' if paused else ('GAP' if p.gap else 'PLAYING'))
            text(state, (500, 305), center=True)
            elapsed = min(p.song_time, audio.durations[p.song_index])
            progress = elapsed / audio.durations[p.song_index]
            pygame.draw.rect(screen, (65, 65, 65), (180, 355, 640, 8))
            pygame.draw.rect(screen, fg, (180, 355, round(640 * progress), 8))
            text(timestamp(elapsed), (65, 345))
            text('-' + timestamp(audio.durations[p.song_index] - elapsed), (845, 345))
            upcoming = audio.setlist.songs[p.song_index + 1] if p.song_index + 1 < len(audio.setlist.songs) else None
            text(f'NEXT: {upcoming.name}  ({upcoming.bpm:g} BPM)' if upcoming else 'NEXT: end of set', (55, 425), 1)
            labels = ['SPACE resume' if paused else 'SPACE pause', 'N skip', 'Q quit']
            for rect, label in zip(buttons, labels):
                pygame.draw.rect(screen, fg, rect, width=2, border_radius=8)
                text(label, rect.center, center=True)
            if audio.underruns != last_underruns:
                warning_until, last_underruns = time.monotonic() + 2, audio.underruns
            if time.monotonic() < warning_until:
                text(f'AUDIO UNDERRUN ({audio.underruns})', (500, 390), center=True)
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
