"""Run from repository root: python3 blender/clockdivider/render_all.py.
Requires Blender 5.1+, FFmpeg. Produces PNG RGBA, ProRes 4444, black H.264.
"""
import argparse
from pathlib import Path
import subprocess
from concurrent.futures import ThreadPoolExecutor

p=argparse.ArgumentParser()
p.add_argument('--package-only',action='store_true')
p.add_argument('--format',choices=['wide','square','all'],default='all')
p.add_argument('--jobs',type=int,default=1,help='Concurrent render jobs; 3 works on a 12GB GPU')
p.add_argument('--output',type=Path,default=Path('generated/clockdivider'))
a=p.parse_args()
base=Path(__file__).resolve().parent
def render_variant(variant):
        treatment,aspect=variant
        name=f'{treatment}-{aspect}'
        out=a.output.resolve()/name
        out.mkdir(parents=True,exist_ok=True)
        if not a.package_only:
            with (out/'render.log').open('w') as log:
                subprocess.run(['blender','-b','-t','4','--python-exit-code','1','--python',str(base/'build.py'),
                                '--','--treatment',treatment,'--format',aspect,'--output',str(a.output),'--render','--resume'],
                               stdout=log,stderr=subprocess.STDOUT,check=True)
        frames=sorted((out/'png').glob('frame_*.png'))
        assert len(frames)==180, (name,len(frames))
        inp=['-framerate','30','-start_number','1','-i',str(out/'png/frame_%04d.png')]
        subprocess.run(['ffmpeg','-v','error','-y',*inp,'-c:v','prores_ks','-profile:v','4',
                        '-pix_fmt','yuva444p10le','-alpha_bits','16','-threads','4',
                        str(out/f'{name}-alpha.mov')],check=True)
        w=1920 if aspect=='wide' else 1080
        subprocess.run(['ffmpeg','-v','error','-y',*inp,'-f','lavfi','-i',f'color=c=black:s={w}x1080:r=30',
                        '-filter_complex','[1:v][0:v]overlay=shortest=1:format=auto,format=yuv420p[v]',
                        '-map','[v]','-c:v','libx264','-crf','18','-preset','fast','-threads','4',
                        '-movflags','+faststart',str(out/f'{name}-preview.mp4')],check=True)
        print('FINISHED',name,flush=True)

with ThreadPoolExecutor(max_workers=a.jobs) as pool:
    list(pool.map(render_variant,[(t,f) for t in ['laser','fly','orbit'] for f in (['wide','square'] if a.format=='all' else [a.format])]))
