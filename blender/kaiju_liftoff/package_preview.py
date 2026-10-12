"""Encode and audit the 12 fps draft plus a 24 fps teaser continuation."""
import argparse,hashlib,json,subprocess
from pathlib import Path


def run(args):
    result=subprocess.run(args,capture_output=True,text=True)
    if result.returncode:
        raise RuntimeError(f"Command failed ({result.returncode}): {args[0]}\n{result.stderr}")
    return result.stdout


def probe(path):
    return json.loads(run(['ffprobe','-v','error','-count_frames','-select_streams','v:0',
        '-show_entries','stream=width,height,r_frame_rate,nb_read_frames,duration',
        '-of','json',str(path)]))['streams'][0]


def main():
    p=argparse.ArgumentParser();p.add_argument('--directory',type=Path,required=True)
    p.add_argument('--reference',type=Path,required=True);a=p.parse_args()
    d=a.directory.resolve();seq=d/'encode_sequence';seq.mkdir(exist_ok=True)
    expected=list(range(2,218,2))
    for i,f in enumerate(expected,1):
        source=d/'matched_preview_frames'/f'frame_{f:04}.png'
        if not source.is_file():raise FileNotFoundError(source)
        target=seq/f'frame_{i:04}.png'
        if target.is_symlink():target.unlink()
        target.symlink_to(source)
    preview=d/'kaiju_liftoff_preview.mp4';combined=d/'teaser2_with_liftoff_preview.mp4'
    run(['ffmpeg','-hide_banner','-loglevel','error','-y','-framerate','12',
        '-i',str(seq/'frame_%04d.png'),'-frames:v','108',
        '-vf','pad=ceil(iw/2)*2:ceil(ih/2)*2','-c:v','libx264',
        '-preset','medium','-crf','18','-pix_fmt','yuv420p','-movflags','+faststart',str(preview)])
    reference=probe(a.reference)
    assert int(reference['nb_read_frames'])==436 and reference['r_frame_rate']=='24/1',reference
    # First 436 frames are the original teaser; source frame 1 of the extension
    # is deliberately excluded. Original audio ends at the cut; extension is silent.
    # concat clears frame durations; restore CFR durations and retain the final
    # duplicate explicitly so MP4 decoders do not discard a zero-duration tail.
    filters=(
        '[0:v]scale=960:540:flags=lanczos,setsar=1,setpts=PTS-STARTPTS[v0];'
        '[1:v]fps=24,tpad=stop_mode=clone:stop=1,trim=end_frame=216,'
        'scale=960:540:flags=lanczos,setsar=1,setpts=PTS-STARTPTS[v1];'
        '[v0][v1]concat=n=2:v=1:a=0,fps=24:eof_action=pass,'
        'tpad=stop_mode=clone:stop=1,trim=end_frame=652[v];'
        '[0:a]atrim=duration=18.166666667,asetpts=PTS-STARTPTS,'
        'afade=t=out:st=17.916666667:d=0.25,apad=whole_dur=27.166666667[a]')
    run(['ffmpeg','-hide_banner','-loglevel','error','-y','-i',str(a.reference),
        '-i',str(preview),'-filter_complex',filters,'-map','[v]','-map','[a]',
        '-fps_mode','cfr','-c:v','libx264','-crf','18','-preset','medium','-pix_fmt','yuv420p',
        '-c:a','aac','-b:a','160k','-movflags','+faststart',str(combined)])
    audit={}
    for path,frames,fps in [(preview,108,'12/1'),(combined,652,'24/1')]:
        info=probe(path)
        assert int(info['nb_read_frames'])==frames,(path,info)
        assert info['r_frame_rate']==fps,(path,info)
        run(['ffmpeg','-v','error','-i',str(path),'-f','null','-'])
        info['sha256']=hashlib.sha256(path.read_bytes()).hexdigest();audit[path.name]=info
    audit['status']='PASS';audit['extension_scene_frames']=expected
    audit['audio']='Original teaser audio fades over its last 0.25 s; extension silent.'
    (d/'media_verification.json').write_text(json.dumps(audit,indent=2))
    print(json.dumps(audit,indent=2))


if __name__=='__main__':main()
