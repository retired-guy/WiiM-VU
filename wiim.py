#!/usr/bin/python3

import sys
import configparser
import pygame
import pyaudio
import numpy as np
import math
import io
import requests
import xmltodict
import upnpclient
import time
from collections import deque
from datetime import datetime
from pygame.locals import *
from threading import Thread

cfg = configparser.ConfigParser()
cfg.read('config.ini')

# Constants
BGCOLOR = tuple(eval( cfg.get("Defaults","bg_color") )) #(30, 30, 30)
TEXTCOLOR = tuple(eval( cfg.get("Defaults","text_color") )) #(200, 200, 200)
windowsize = tuple(eval( cfg.get("Defaults","window_size") ))
WINDOWWIDTH = windowsize[0]  #1280
WINDOWHEIGHT = windowsize[1] #400
FULLSCREEN = cfg.getboolean("Defaults","fullscreen")

IP_ADDRESS = cfg.get("WiiM","ipaddress")

IMAGE_SIZE = tuple(eval( cfg.get("Defaults","image_size") ))
IMAGE_POSITION = tuple(eval( cfg.get("Defaults","image_pos") ))

LEFT_METER_POSITION = tuple(eval( cfg.get("Defaults","left_meter_pos") )) #(400, 0)
RIGHT_METER_POSITION = tuple(eval( cfg.get("Defaults","right_meter_pos") ))  # (840, 0)
METER_SIZE = tuple(eval( cfg.get("Defaults","meter_size") )) #(440, 280)
current_meter = cfg.get("Defaults","current_meter")
METER_PATH = cfg.get(current_meter,"meter_path")
METER_WINDOW_BOTTOM = cfg.getint(current_meter,"meter_window_bottom")

NEEDLE_COLOR = tuple(eval( cfg.get(current_meter,"needle_color") ))
needle_l_x = LEFT_METER_POSITION[0] + METER_SIZE[0] / 2
needle_r_x = RIGHT_METER_POSITION[0] + METER_SIZE[0] / 2
needle_y = METER_SIZE[1] - cfg.getint(current_meter,"needle_zero_y")
needle_length = cfg.getint(current_meter,"needle_length")

# Needle startpoints and length
startpointL = pygame.math.Vector2(needle_l_x,needle_y) 
startpointR = pygame.math.Vector2(needle_r_x,needle_y) 
endpoint = pygame.math.Vector2(needle_length,0) 

# Total sweep angle of meter face
SWEEP_ANGLE = cfg.getint(current_meter,"sweep_angle") #113
MIN_ANGLE = 270 - SWEEP_ANGLE / 2
MAX_ANGLE = 270 + SWEEP_ANGLE / 2
# Scale from signal levels to angle on meter face
SCALE = SWEEP_ANGLE 

class AudioProcessor:
    def __init__(self, stream, rate, fpb):
        self.stream = stream
        self.rate = rate
        self.frames_per_block = fpb
        self.maxValue = 2 ** 16
        self.queueLength = 12
        self.queueL = deque([0]*self.queueLength,maxlen=self.queueLength)
        self.queueR = deque([0]*self.queueLength,maxlen=self.queueLength)

    def smooth(self, queue):
        ave = 0
        tot = 0
        for i, v in enumerate(queue):
            inc  = len(queue) - i
            tot += inc
            ave += v * inc

        return ave / (tot*0.9)  

    def process_audio(self):
        try:
            left_vu = 0
            right_vu = 0

            data = np.frombuffer(self.stream.read(self.frames_per_block,False),dtype=np.int16)
            ldata = data[0::2]
            rdata = data[1::2]

            ## Get sqrt of average value of buffers
            left_vu =  math.sqrt(np.abs(np.max(ldata)-np.min(ldata))/self.maxValue)
            right_vu =  math.sqrt(np.abs(np.max(rdata)-np.min(rdata))/self.maxValue)

            self.queueL.appendleft(left_vu)
            left_vu = self.smooth(self.queueL)
            self.queueR.appendleft(right_vu)
            right_vu = self.smooth(self.queueR)

            """
            ## We aren't using dB values, but here are the calcs for them
            # Convert VU meter levels to decibels
            left_vu_db = 20 * math.log10(left_vu + 1e-10)
            right_vu_db = 20 * math.log10(right_vu + 1e-10)

            # Limit VU meter levels to -20, +3dB
            left_vu_db = max(left_vu_db, -20)
            left_vu_db = min(left_vu_db, 3)
            right_vu_db = max(right_vu_db, -20)
            right_vu_db = min(right_vu_db, 3)
            """
            return left_vu, right_vu

        except Exception as e:
            print(e)
            return 0, 0

class DisplayManager:
    def __init__(self, screen):
        self.screen = screen
        self.image = None
        self.meter_img = None
        self.meter_base = None
        self.base_rect = (0,0,0,0)
        self.l_base_pos = (0,0) 
        self.r_base_pos = (0,0)
        self.font_small = pygame.font.Font('freesansbold.ttf', 22)
        self.font_large = pygame.font.Font('freesansbold.ttf', 36)
        self.font_huge = pygame.font.Font('freesansbold.ttf', 256)
        self.load_meters(METER_PATH)
        self.title = ""
        self.album = ""
        self.artist = ""
        self.level_l = 0
        self.level_r = 0

    def load_meters(self, path):
        try:
            self.meter_img = pygame.image.load(path)
            self.meter_img = pygame.transform.scale(self.meter_img, METER_SIZE)
            if METER_WINDOW_BOTTOM > 0:
                self.base_rect = pygame.Rect(0,METER_SIZE[1]-METER_WINDOW_BOTTOM,METER_SIZE[0],METER_WINDOW_BOTTOM)
                self.base_img = self.meter_img.subsurface(self.base_rect) 

                self.l_base_pos = (LEFT_METER_POSITION[0],LEFT_METER_POSITION[1]+METER_SIZE[1]-METER_WINDOW_BOTTOM)
                self.r_base_pos = (RIGHT_METER_POSITION[0],RIGHT_METER_POSITION[1]+METER_SIZE[1]-METER_WINDOW_BOTTOM)
        except Exception as e:
            print(e)

    def set_levels(self, level_l, level_r):
        self.level_l = level_l
        self.level_r = level_r

    def set_metadata(self, title, album, artist):
        self.title = title
        self.album = album
        self.artist = artist

    def draw_text(self, text, font, color, pos):
        rendered_text = font.render(text, 1, color)
        self.screen.blit(rendered_text, (pos[0], pos[1]))

    def update_display(self, level_l, level_r, title, artist, album):
        if title != "":
            self.title = title
        if artist != "":
            self.artist = artist
        if album != "":
            self.album = album

        self.level_l = level_l
        self.level_r = level_r

        self.screen.fill(BGCOLOR)

        if self.image:
            try:
                self.screen.blit(self.image, IMAGE_POSITION)
            except Exception as e:
                print(e)

        if self.meter_img:
            try:
                self.screen.blit(self.meter_img, LEFT_METER_POSITION)
                self.screen.blit(self.meter_img, RIGHT_METER_POSITION)
            except Exception as e:
                print(e)

        # Draw needles
        angle_l = self.level_l * SCALE + MIN_ANGLE
        current_endpoint = startpointL + endpoint.rotate(angle_l)
        pygame.draw.line(self.screen, NEEDLE_COLOR, startpointL, current_endpoint, 4)

        angle_r = level_r * SCALE + MIN_ANGLE
        current_endpoint = startpointR + endpoint.rotate(angle_r)
        pygame.draw.line(self.screen, NEEDLE_COLOR, startpointR, current_endpoint, 4)

        # Draw meter base over needle
        if METER_WINDOW_BOTTOM > 0:
            self.screen.blit(self.base_img, self.l_base_pos)
            self.screen.blit(self.base_img, self.r_base_pos)

        # Draw text
        self.draw_text(self.title, self.font_large, TEXTCOLOR, (410, 290))
        self.draw_text(self.artist, self.font_small, TEXTCOLOR, (410, 340))
        self.draw_text(self.album, self.font_small, TEXTCOLOR, (410, 370))
        pygame.display.update()

    def draw_clock(self):
        self.screen.fill((0, 0, 0))
        now = datetime.now()
        t = now.strftime("%H:%M")
        text = self.font_huge.render(t, 1, (155, 155, 155))
        self.screen.blit(text, (300, 100))
        t = now.strftime("%a %b %d, %Y")
        text = self.font_large.render(t, 1, (155, 155, 155))
        self.screen.blit(text, (500, 350))
        pygame.display.update()


class NowPlayingFetcher(Thread):
    def __init__(self, device, display_manager, playing):
        super().__init__(daemon=True)
        self.device = device
        self.playing = playing
        self.display_manager = display_manager
        self.title = ""
        self.old_title = ""
        self.artist = ""
        self.album = ""

    def run(self):
        while True:
            time.sleep(1)
            if not self.playing:
                continue

            try:
                obj = self.device.AVTransport.GetInfoEx(InstanceID=0)
                transport_state = obj['CurrentTransportState']
                if transport_state != 'PLAYING':
                    self.playing = False
                    continue

                self.playing = True
                meta = obj['TrackMetaData']
                data = xmltodict.parse(meta)["DIDL-Lite"]["item"]
                try:
                    self.title = data['dc:title'][:100]
                    if self.title != self.old_title:
                        self.update_track_info(data)
                        self.old_title = self.title
                        self.fetch_album_art(data)
                except Exception as e:
                    print("Title exception:",e)

            except Exception as e:
                print(e)

    def update_playing_status(self, playing):
        self.playing = playing

    def update_track_info(self, data):
        try:
            self.artist = data.get('upnp:artist', '')[:100]
        except Exception as e:
            self.artist = ""

        try:
            self.album = data.get('upnp:album', '')[:100]
        except:
            try:
                self.album = data.get('dc:subtitle', '')[:100]
            except Exception as e:
                self.album = ""

        self.display_manager.set_metadata(self.title,self.artist,self.album)

    def fetch_album_art(self, data):
        try:
            art_url = data["upnp:albumArtURI"]
            if isinstance(art_url, dict):
                art_url = art_url["#text"]

            r = requests.get(art_url, stream=True)
            img = io.BytesIO(r.content)
            image = pygame.image.load(img)
            self.display_manager.image = pygame.transform.scale(image, IMAGE_SIZE)
        except Exception as e:
            print(e)


def main():

    wiimIP = IP_ADDRESS

    # UPnP Device
    dev = upnpclient.Device(f"http://{wiimIP}:49152/description.xml")

    pygame.init()
    pygame.mixer.quit()
    pygame.display.set_caption(dev.friendly_name)

    if FULLSCREEN == True:
        screen = pygame.display.set_mode((WINDOWWIDTH, WINDOWHEIGHT), pygame.FULLSCREEN)
    else:
        screen = pygame.display.set_mode((WINDOWWIDTH, WINDOWHEIGHT))

    pygame.mouse.set_visible(False) # Hide cursor

    display_manager = DisplayManager(screen)
    counter = 0

    # Setup PyAudio
    pa = pyaudio.PyAudio()
    info = pa.get_host_api_info_by_index(0)
    numdevices = info.get('deviceCount')
    print("deviceCount:", numdevices)

    # Discover the Toslink input device
    for i in range(numdevices):
        if pa.get_device_info_by_host_api_device_index(0, i).get('maxInputChannels') == 2:
            info = pa.get_device_info_by_host_api_device_index(0, i)
            print(info)
            break

    RATE = int(info['defaultSampleRate'])
    INPUT_BLOCK_TIME = 0.04
    INPUT_FRAMES_PER_BLOCK = int(RATE * INPUT_BLOCK_TIME)

    index = info['index']
    try:
        stream = pa.open(format=pyaudio.paInt16,
                         channels=2,
                         rate=RATE,
                         input=True,
                         frames_per_buffer=INPUT_FRAMES_PER_BLOCK,
                         input_device_index=index)

        audio_processor = AudioProcessor(stream, rate=RATE, fpb = INPUT_FRAMES_PER_BLOCK)

        now_playing_fetcher = NowPlayingFetcher(dev, display_manager, False)
        now_playing_fetcher.start()

        peak_l = -60
        peak_r = -60

        while True:
            for event in pygame.event.get():
                if event.type == QUIT or (event.type == KEYUP and event.key == K_ESCAPE):
                    pygame.quit()
                    sys.exit()

            level_l, level_r = audio_processor.process_audio()

            ##### Slow decay
            if level_l > peak_l: peak_l = level_l
            elif peak_l > 0: peak_l -= 0.01 
            if level_r > peak_r: peak_r = level_r
            elif peak_r > 0: peak_r -= 0.01

            if peak_l > 0 or  peak_r > 0:
                now_playing_fetcher.update_playing_status(True)
                counter = 0
                ### Fast rise, slow decay
                if (level_l + level_r) > (peak_l + peak_r):
                    peak_l = ( (1*peak_l) + (1*level_l) ) / 2
                    peak_r = ( (1*peak_r) + (1*level_r) ) / 2
                else:
                    peak_l = ( (29*peak_l) + (1*level_l) ) / 30
                    peak_r = ( (29*peak_r) + (1*level_r) ) / 30
     
                display_manager.update_display(peak_l, peak_r, "", "", "")
            else:
                counter += 1
                time.sleep(1)
                if counter > 10:
                    now_playing_fetcher.update_playing_status(False)
                    display_manager.draw_clock()

    except Exception as e:
        print(e)
        return
    finally:
        stream.stop_stream()
        stream.close()
        pa.terminate()

if __name__ == "__main__":
    main()
