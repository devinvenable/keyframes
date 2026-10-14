"""Build a decoded motion sheet and validate the final review's local links."""
import argparse
from html.parser import HTMLParser
import json
from pathlib import Path
import subprocess

from PIL import Image, ImageDraw, ImageFont


def main(root):
    report = json.loads((root/'final_verification.json').read_text())
    assert report['status'] == 'PASS'
    frames = list(range(1, 193, 3)) + [192]
    sheet = Image.new('RGB', (1920, 210*((len(frames)+5)//6)), '#17191c')
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 20)
    with (root/'motion_decode.log').open('w') as err:
        proc = subprocess.Popen([
            'ffmpeg', '-v', 'error', '-xerror', '-i', str(root/'unified_flight_impact_final.mp4'),
            '-vf', r'select=not(mod(n\,3))+eq(n\,191),scale=320:180',
            '-vsync', '0', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'],
            stdout=subprocess.PIPE, stderr=err)
        try:
            for index, frame in enumerate(frames):
                raw = proc.stdout.read(320*180*3)
                assert len(raw) == 320*180*3, f'Missing motion sample {frame}'
                x, y = (index % 6)*320, (index // 6)*210
                sheet.paste(Image.frombytes('RGB', (320, 180), raw), (x, y+30))
                draw.text((x+8, y+4), f'Frame {frame}', fill='white', font=font)
            assert proc.stdout.read(1) == b'', 'Extra motion samples'
            assert proc.wait() == 0, 'Motion sample decode failed'
        finally:
            proc.stdout.close()
            if proc.poll() is None:
                proc.kill(); proc.wait()
    sheet.save(root/'final_motion.jpg', quality=95)
    page = root/'review.html'
    html = page.read_text()
    if 'final_motion.jpg' not in html:
        html += '<p><a href="final_motion.jpg">Motion sheet — every third frame and final settle</a></p>\n'
        page.write_text(html)

    class Links(HTMLParser):
        def handle_starttag(self, tag, attrs):
            for key, value in attrs:
                if key in ('href', 'src'):
                    assert value and (root/value).is_file(), 'Missing review artifact: ' + str(value)
                    links.append(value)
    links = []
    Links().feed(html)
    result = {'status': 'PASS', 'decoded_motion_frames': frames, 'checked_local_links': links}
    (root/'review_qa.json').write_text(json.dumps(result, indent=2)+'\n')
    print('REVIEW_READY', root/'review.html')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', type=Path, required=True)
    main(parser.parse_args().directory.resolve())
