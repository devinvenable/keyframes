"""Self-contained overnight render, encode, audit and PM completion notification.

Copy this script, render_final.py, package_final.py, package_preview.py and
asset_hashes.json into the output's render_job_306 directory before launching.
The job does not depend on a surviving dev worktree or terminal session.
"""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
from pathlib import Path
import subprocess
import traceback


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_originals(scripts):
    for name, expected in json.loads((scripts/'asset_hashes.json').read_text()).items():
        assert sha(Path(name)) == expected['sha256'], f'Original asset changed: {name}'


def preflight(directory, scripts):
    check_originals(scripts)
    qa = json.loads((directory/'cinematic_verification.json').read_text())
    assert qa['status'] == 'PASS' and qa['lock_matrix_max_error'] == 0
    assert qa['non_camera_frames_identical'] == 217
    assert len(qa['negative_controls']) == 4, 'Negative controls must pass before final render'
    assert qa['candidate_sha256'] == sha(directory/'kaiju_liftoff_cinematic.blend')
    media = json.loads((directory/'media_verification.json').read_text())
    assert media['status'] == 'PASS'
    for name, count in [('kaiju_liftoff_preview.mp4', 108), ('teaser2_with_liftoff_preview.mp4', 652)]:
        assert int(media[name]['nb_read_frames']) == count
        assert media[name]['sha256'] == sha(directory/name), 'Preview changed since audit'


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--directory', type=Path, required=True)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--reference', type=Path, required=True)
    p.add_argument('--blender', type=Path, required=True)
    p.add_argument('--axon', type=Path, required=True)
    p.add_argument('--notify-project', type=Path, required=True)
    p.add_argument('--pm', default='pm-midi-1')
    p.add_argument('--commit', action='append', required=True)
    p.add_argument('--preflight-only', action='store_true')
    a = p.parse_args()
    scripts = Path(__file__).resolve().parent
    d = a.directory.resolve()
    if a.preflight_only:
        preflight(d, scripts)
        print('PREFLIGHT PASS', flush=True)
        return
    lock = (d/'final_job.lock').open('w')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    state = {'commits': a.commit, 'started': datetime.now(timezone.utc).isoformat(),
             'approval': 'Devin pre-approval relayed by pm-midi-1, 2026-10-11',
             'verification': str(d/'final_media_verification.json')}

    def update(phase, **extra):
        state.update(phase=phase, updated=datetime.now(timezone.utc).isoformat(), **extra)
        temporary = d/'final_job_status.pending.json'
        temporary.write_text(json.dumps(state, indent=2))
        temporary.replace(d/'final_job_status.json')
        print('JOB', phase, flush=True)

    def notify(message):
        result = subprocess.run([str(a.axon), 'send', a.pm, message], cwd=a.notify_project)
        state['notification_exit_code'] = result.returncode
        update(state['phase'])

    try:
        update('PREFLIGHT')
        preflight(d, scripts)
        update('RENDERING')
        subprocess.run([str(a.blender), '-b', '--python-exit-code', '1', '--python',
                        str(scripts/'render_final.py'), '--', '--source', str(a.source),
                        '--candidate', str(d/'kaiju_liftoff_cinematic.blend'),
                        '--output', str(d/'cinematic_final_frames'),
                        '--save-scene', str(d/'kaiju_liftoff_final.blend')], check=True)
        update('ENCODING')
        subprocess.run(['python3', str(scripts/'package_final.py'), '--directory', str(d),
                        '--reference', str(a.reference)], check=True)
        check_originals(scripts)
        preflight(d, scripts)
        audit = json.loads((d/'final_media_verification.json').read_text())
        assert audit['status'] == 'PASS' and audit['joined_frames'] == 652
        assert audit['render_settings']['candidate_sha256'] == sha(d/'kaiju_liftoff_cinematic.blend'), \
            'Camera candidate changed during final render'
        quality = audit['render_settings']['quality']
        assert quality['samples'] == 4096 and abs(quality['adaptive_threshold']-.01) < 1e-6
        assert quality['volume_step_rate'] == 1 and quality['volume_max_steps'] == 1024
        update('COMPLETE', final=str(d/'teaser2_with_liftoff_final.mp4'))
    except Exception as error:
        traceback.print_exc()
        update('FAILED', error=str(error))
        notify(f'T306 FINAL JOB FAILED: {error}. Status/logs: {d}. Resume instructions in README; no completion claimed.')
        raise
    notify(f'T306 FINAL COMPLETE under Devin pre-approval: {d}/teaser2_with_liftoff_final.mp4. '
           f'Native 1080p24; 216 extension / 652 joined frames; decode/hash/source-quality audit PASS: '
           f'{d}/final_media_verification.json. Original assets unchanged. Commits: {", ".join(a.commit)}.')


if __name__ == '__main__':
    main()
