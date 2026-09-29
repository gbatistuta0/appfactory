#!/bin/sh
# Records a real agent session (vhs docs/demo/demo.tape), then speeds up the waiting part into the README GIF.
set -e
vhs docs/demo/demo.tape
ffmpeg -y -t 40 -i demo-real.mp4 -filter_complex "[0:v]trim=0:8,setpts=PTS-STARTPTS[a];[0:v]trim=8:36,setpts=(PTS-STARTPTS)/4[b];[0:v]trim=36:40,setpts=PTS-STARTPTS[c];[a][b][c]concat=n=3:v=1,tpad=stop_mode=clone:stop_duration=6,fps=12,scale=1100:-1:flags=lanczos,split[x][y];[x]palettegen=max_colors=128[p];[y][p]paletteuse=dither=bayer:bayer_scale=4" docs/demo/demo.gif
