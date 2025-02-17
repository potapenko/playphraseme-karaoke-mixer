ffmpeg -y -loglevel error -f concat -safe 0 -i concat_list.txt -c:v libx264 -preset medium -crf 23 -r 30 -c:a aac -b:a 192k 640x480-eat-chinese-play-a-little-poker-hit-the-sack.mp4
