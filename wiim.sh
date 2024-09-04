#!/usr/bin/bash
cd "$(dirname "$0")"
DISPLAY=:0.0
export DISPLAY
xset -display $DISPLAY s off
xset -display $DISPLAY s noblank
xrandr -d $DISPLAY -o right
/usr/bin/python3 wiim.py 

