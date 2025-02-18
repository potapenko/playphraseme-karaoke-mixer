#!/usr/bin/env python3
"""
Script for creating a final video from multiple video files.
Karaoke subtitles + translation (Google Translate) + highlighting only the continuous

Note:
  FFmpeg’s subtitles filter needs to load physical TTF files.
  Place your TTF files in a folder named 'fonts' next to this script,
  or provide a full path via the --font parameter.
"""

import os
import subprocess
import sys
import re
import tempfile
import requests
import shutil
import logging
import argparse
import itertools

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def install_dependencies():
    req_file = os.path.join(os.path.dirname(__file__), "requirements.txt")
    if os.path.exists(req_file):
        print("Installing dependencies from requirements.txt...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", req_file])
        except subprocess.CalledProcessError as e:
            print("Error installing dependencies:", e)
            sys.exit(1)

# Automatic installation of dependencies
install_dependencies()

def check_ffmpeg_installed():
    try:
        subprocess.run(["ffmpeg", "-version"],
                       stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL,
                       check=True)
        logging.info("ffmpeg is installed and available.")
    except Exception:
        logging.error("ffmpeg is not installed or not found in the system PATH. Please install ffmpeg before running this script.")
        sys.exit(1)

check_ffmpeg_installed()

# ==================== Configuration (adjust as needed) ====================
# Default fonts and sizes for overlays (default values)
PHRASE_FONT = "Roboto-Regular"           # Default font for main phrase
PHRASE_FONT_SIZE = 34           # Default main phrase font size
PHRASE_COLOR = "white"
PHRASE_HIGHLITE_COLOR = "yellow"
WORD_HIGHLITE_COLOR = "green"

PHRASE_ALIGNMENT = 2          # bottom center
PHRASE_MARGIN_V = 70

TRANSLATION_FONT = "Roboto-Regular"      # Default font for translation
TRANSLATION_FONT_SIZE = 24      # Default translation font size
TRANSLATION_COLOR = "white"
TRANSLATION_ALIGNMENT = 2       # bottom center
TRANSLATION_MARGIN_V = 10

WEBSITE_TEXT = "playphrase.me"
WEBSITE_FONT = "Roboto-Regular"          # Default font for website overlay
WEBSITE_FONT_SIZE = 20          # Default website font size
WEBSITE_COLOR = "white"
WEBSITE_ALIGNMENT = 8           # top center
WEBSITE_MARGIN_V = 10

GOOGLE_API_KEY = ""

# Global variable to hold a custom fonts directory (if a custom font is used)
CUSTOM_FONTS_DIR = None

########################################################################
# New helper: extract the internal font name and units per em from a TTF file using fontTools
########################################################################
def get_internal_font_info(ttf_path):
    try:
        from fontTools.ttLib import TTFont
        font = TTFont(ttf_path)
        units = font["head"].unitsPerEm
        internal_name = None
        # Prefer nameID 4 (Full font name) on Windows
        for record in font['name'].names:
            if record.nameID == 4 and record.platformID == 3 and record.platEncID == 1:
                internal_name = record.toUnicode()
                break
        # Fallback to nameID 1 (Font Family)
        if not internal_name:
            for record in font['name'].names:
                if record.nameID == 1 and record.platformID == 3 and record.platEncID == 1:
                    internal_name = record.toUnicode()
                    break
        return internal_name, units
    except Exception as e:
        logging.error(f"Could not extract internal font info from {ttf_path}: {e}")
    return None, None

########################################################################
# Modified font resolution that only searches the local "fonts" folder
# and uses the internal font name if possible.
########################################################################
def resolve_font(font_arg):
    ttf_path = None
    # If a file path is provided:
    if os.path.exists(font_arg):
        abs_path = os.path.abspath(font_arg)
        logging.info(f"Resolved font path from given value: {abs_path}")
        ttf_path = abs_path
    else:
        script_dir = os.path.dirname(os.path.realpath(__file__))
        fonts_folder = os.path.join(script_dir, "fonts")
        possible_path = os.path.join(fonts_folder, font_arg)
        if os.path.exists(possible_path):
            logging.info(f"Found font in local fonts folder: {possible_path}")
            ttf_path = possible_path
        elif not os.path.splitext(font_arg)[1]:
            possible_path_ttf = os.path.join(fonts_folder, font_arg + ".ttf")
            if os.path.exists(possible_path_ttf):
                logging.info(f"Found font in local fonts folder with .ttf appended: {possible_path_ttf}")
                ttf_path = possible_path_ttf
    if not ttf_path:
        logging.error(f"Font '{font_arg}' not found in the local fonts folder or as a direct file path.")
        return font_arg, None, None

    # Try to extract the internal font name and units.
    internal_name, units = get_internal_font_info(ttf_path)
    if internal_name:
        logging.info(f"Extracted internal font name: {internal_name} with unitsPerEm: {units}")
        font_name = internal_name
    else:
        font_name = os.path.splitext(os.path.basename(ttf_path))[0]
        logging.warning(f"Could not extract internal font name. Using filename: {font_name}")
    return font_name, os.path.dirname(ttf_path), units

########################################################################
# Other utility functions
########################################################################
def sanitize_filename(filename):
    return re.sub(r"[^\w\-.]", "_", filename)

def create_filename_from_phrase(phrase, video_size):
    sanitized = phrase.strip().lower()
    sanitized = re.sub(r"\s+", "-", sanitized)
    sanitized = re.sub(r"[^a-z'\-]", "", sanitized)
    return f"{video_size}-{sanitized}"

def parse_args():
    parser = argparse.ArgumentParser(
        description="Script for creating video with karaoke subtitles, translation, and highlighting of a continuous sequence of words from highlite_phrase."
    )
    parser.add_argument("--video_folder", type=str, default=".", help="Folder with videos (default current folder)")
    parser.add_argument("--video_size", type=str, default="640x480", help="Final video size in WIDTHxHEIGHT (default 640x480)")
    parser.add_argument("--highlite_phrase", type=str, default="", help="Phrase for highlighting (if omitted, calculated from videos)")
    # Add an optional positional argument to help Windows users who may provide the phrase without flag
    parser.add_argument("--translate_lang", type=str, default=None, help="Translation language (default: None)")
    parser.add_argument("--google_api_key", type=str, default="", help="Google API Key (default empty)")
    parser.add_argument("--create_tmp", action="store_true", default=False, help="Create tmp directory for individual videos (default: no)")
    parser.add_argument("--output-dir", type=str, default=None, help="Directory where the final video will be saved")
    parser.add_argument("--font", type=str, default=None, help="Default font name or full path to TTF file for overlays")
    parser.add_argument("--font_size", type=int, default=None, help="Optional font size to use for the main phrase (translation and website sizes will scale proportionally)")
    args = parser.parse_args()
    logging.info("Command line arguments parsed successfully.")
    return args

def get_video_files(folder):
    exts = [".mp4", ".mkv", ".avi", ".mov"]
    files = []
    for f in os.listdir(folder):
        if os.path.splitext(f)[1].lower() in exts:
            if f.lower().startswith("output") or f.lower().startswith("processed_"):
                continue
            files.append(os.path.join(folder, f))
    files = sorted(files)
    logging.info(f"Found {len(files)} video files in the folder: {folder}")
    return files

def extract_subtitles(video_path, output_srt):
    logging.info(f"Extracting subtitles from {video_path} to {output_srt}")
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", video_path, "-map", "0:s:0?", output_srt]
    subprocess.run(cmd, check=True)
    logging.info("Subtitles extracted successfully.")

def srt_time_to_seconds(time_str):
    h, m, s_ms = time_str.split(":")
    s, ms = s_ms.split(",")
    return int(h)*3600 + int(m)*60 + int(s) + int(ms)/1000.0

def parse_srt(srt_path):
    logging.info(f"Parsing SRT file: {srt_path}")
    cues = []
    try:
        with open(srt_path, encoding='utf-8') as f:
            content = f.read().strip()
    except Exception as e:
        logging.error(f"Error reading SRT file: {e}")
        return cues
    if not content:
        return cues
    parts = re.split(r'\n\s*\n', content)
    for part in parts:
        lines = part.strip().splitlines()
        if len(lines) >= 3:
            time_line = lines[1]
            text = " ".join(lines[2:])
            m = re.match(r'(\d+:\d+:\d+,\d+)\s*-->\s*(\d+:\d+:\d+,\d+)', time_line)
            if m:
                start = srt_time_to_seconds(m.group(1))
                end = srt_time_to_seconds(m.group(2))
                highlighted = re.findall(r'<u>(.*?)</u>', text)
                if highlighted:
                    cues.append({"start": start, "end": end, "text": text, "highlight": highlighted[0]})
    logging.info(f"Found {len(cues)} cues in the SRT file.")
    return cues

def clean_text(text):
    return re.sub(r'</?u>', '', text)

def get_full_phrase_from_cues(cues):
    if cues:
        phrase = clean_text(cues[-1]["text"])
        logging.info(f"Extracted full phrase: {phrase}")
        return phrase
    logging.info("No cues found – returning an empty phrase.")
    return ""

def translate_text(text, target_language="ru"):
    if not text.strip():
        logging.info("Empty text for translation – returning an empty string.")
        return ""
    logging.info(f"Sending request to translate text: {text}")
    url = "https://translation.googleapis.com/language/translate/v2"
    params = {"q": text, "target": target_language, "key": GOOGLE_API_KEY}
    response = requests.post(url, data=params)
    if response.status_code == 200:
        data = response.json()
        translated_text = data["data"]["translations"][0]["translatedText"]
        logging.info(f"Translation received: {translated_text}")
        return translated_text
    else:
        logging.error(f"Translate API error: {response.text}")
        return ""

def convert_color(color_name):
    colors = {
        "white": "&H00FFFFFF",
        "black": "&H00000000",
        "yellow": "&H0031D1FD",
        "red": "&H000000FF",
        "green": "&H0000FF00",
        "blue": "&H00FF0000",
        "cyan": "&H00FFFF00",
        "gray": "&H00AAAAAA",
        "transparent": "&HFF000000",
    }
    return colors.get(color_name.lower(), "&H00FFFFFF")

def seconds_to_ass_time(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"

def normalize_word(w: str) -> str:
    return re.sub(r"[^\w]+", "", w.lower())

def find_subsequence_indices(phrase_words, highlite_words):
    if not highlite_words or not phrase_words:
        return []
    L = len(highlite_words)
    N = len(phrase_words)
    for start_idx in range(N - L + 1):
        if all(phrase_words[start_idx + j] == highlite_words[j] for j in range(L)):
            logging.info(f"Found subsequence starting at index {start_idx}")
            return list(range(start_idx, start_idx + L))
    logging.info("Continuous subsequence not found.")
    return []

def contains_contiguous_subsequence(lst, sub):
    L = len(sub)
    for i in range(len(lst) - L + 1):
        if lst[i:i+L] == sub:
            return True
    return False

def common_contiguous_subsequence(normalized_lists):
    first = normalized_lists[0]
    n = len(first)
    for length in range(n, 0, -1):
        for start in range(0, n - length + 1):
            candidate = first[start:start+length]
            if all(contains_contiguous_subsequence(other, candidate) for other in normalized_lists[1:]):
                candidate_str = " ".join(candidate)
                return candidate_str
    return ""

def calculate_highlight_phrase(phrases):
    if not phrases:
        return ""
    normalized_phrases = []
    for p in phrases:
        words = [normalize_word(w) for w in p.split() if normalize_word(w)]
        if words:
            normalized_phrases.append(words)
    if not normalized_phrases:
        return ""
    if len(normalized_phrases) == 1:
        return " ".join(normalized_phrases[0])
    candidate = common_contiguous_subsequence(normalized_phrases)
    if candidate:
        logging.info(f"Found common contiguous subsequence for all phrases: '{candidate}'")
        return candidate
    total = len(normalized_phrases)
    for r in range(total - 1, 1, -1):
        best_candidate = ""
        for subset in itertools.combinations(normalized_phrases, r):
            candidate = common_contiguous_subsequence(list(subset))
            if candidate and len(candidate.split()) > len(best_candidate.split()):
                best_candidate = candidate
        if best_candidate:
            logging.info(f"Found common contiguous subsequence for a subset of size {r}: '{best_candidate}'")
            return best_candidate
    logging.info("No common contiguous subsequence found even in subsets.")
    return ""

def generate_ass_subtitles(cues, phrase, translation, video_width, video_height, highlite_phrase):
    logging.info("Starting ASS subtitle generation.")
    if not cues:
        total_start_sec = 0.0
        total_end_sec = 5.0
    else:
        total_start_sec = cues[0]["start"]
        total_end_sec = cues[-1]["end"]
    start_time_ass = seconds_to_ass_time(total_start_sec)
    end_time_ass = seconds_to_ass_time(total_end_sec)
    logging.info(f"Subtitle time interval: {start_time_ass} - {end_time_ass}")
    scale = video_width / 640.0
    scaled_phrase_font_size = int(round(PHRASE_FONT_SIZE * scale))
    scaled_phrase_margin_v = int(round(PHRASE_MARGIN_V * scale))
    scaled_translation_font_size = int(round(TRANSLATION_FONT_SIZE * scale))
    scaled_translation_margin_v = int(round(TRANSLATION_MARGIN_V * scale))
    scaled_website_font_size = int(round(WEBSITE_FONT_SIZE * scale))
    scaled_website_margin_v = int(round(WEBSITE_MARGIN_V * scale))
    scaled_margin_lr = int(round(10 * scale))
    scaled_outline = int(round(2 * scale))
    words_original = phrase.split()
    words_normalized = [normalize_word(w) for w in words_original]
    highlite_words_raw = highlite_phrase.split()
    highlite_words_normalized = [normalize_word(w) for w in highlite_words_raw if w.strip()]
    highlight_indices = []
    if highlite_words_normalized:
        highlight_indices = find_subsequence_indices(words_normalized, highlite_words_normalized)
    logging.info(f"Highlighted word indices: {highlight_indices}")
    ass = "[Script Info]\n"
    ass += "ScriptType: v4.00+\n"
    ass += f"PlayResX: {video_width}\n"
    ass += f"PlayResY: {video_height}\n"
    ass += "ScaledBorderAndShadow: yes\n"
    ass += "WrapStyle: 3\n\n"
    ass += "[V4+ Styles]\n"
    ass += ("Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,"
            "Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,"
            "Alignment,MarginL,MarginR,MarginV,Encoding\n")
    ass += (
        f"Style: Base,{PHRASE_FONT},{scaled_phrase_font_size},"
        f"{convert_color(PHRASE_COLOR)},{convert_color(PHRASE_COLOR)},"
        "&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,"
        f"{scaled_outline},0,{PHRASE_ALIGNMENT},{scaled_margin_lr},{scaled_margin_lr},{scaled_phrase_margin_v},1\n"
    )
    ass += (
        f"Style: Highlight,{PHRASE_FONT},{scaled_phrase_font_size},"
        f"{convert_color(WORD_HIGHLITE_COLOR)},{convert_color('transparent')},"
        "&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,"
        f"{scaled_outline},0,{PHRASE_ALIGNMENT},{scaled_margin_lr},{scaled_margin_lr},{scaled_phrase_margin_v},1\n"
    )
    ass += (
        f"Style: Translation,{TRANSLATION_FONT},{scaled_translation_font_size},"
        f"{convert_color(TRANSLATION_COLOR)},{convert_color(TRANSLATION_COLOR)},"
        "&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,"
        f"{scaled_outline},0,{TRANSLATION_ALIGNMENT},{scaled_margin_lr},{scaled_margin_lr},{scaled_translation_margin_v},1\n"
    )
    ass += (
        f"Style: Website,{WEBSITE_FONT},{scaled_website_font_size},"
        f"{convert_color(WEBSITE_COLOR)},{convert_color(WEBSITE_COLOR)},"
        "&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,"
        f"{scaled_outline},0,{WEBSITE_ALIGNMENT},{scaled_margin_lr},{scaled_margin_lr},{scaled_website_margin_v},1\n"
    )
    ass += "\n[Events]\n"
    ass += "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n"
    base_color_ass = convert_color(PHRASE_COLOR)
    highlite_color_ass = convert_color(PHRASE_HIGHLITE_COLOR)
    base_line_parts = []
    for i, w in enumerate(words_original):
        if i in highlight_indices:
            part = f"{{\\c{highlite_color_ass}}}{w}{{\\c{base_color_ass}}}"
        else:
            part = w
        base_line_parts.append(part)
    base_line_text = " ".join(base_line_parts)
    ass += f"Dialogue: 0,{start_time_ass},{end_time_ass},Base,,0,0,0,,{base_line_text}\n"
    n_cues = len(cues)
    n_words = len(words_original)
    n_min = min(n_cues, n_words)
    for i in range(n_min):
        cue = cues[i]
        w_start = seconds_to_ass_time(cue["start"])
        w_end = seconds_to_ass_time(cue["end"])
        highlight_line_parts = []
        for j, w in enumerate(words_original):
            if j == i:
                highlight_line_parts.append(f"{{\\alpha&H00&}}{w}{{\\alpha&HFF&}}")
            else:
                highlight_line_parts.append(f"{{\\alpha&HFF&}}{w}")
        highlight_line_text = " ".join(highlight_line_parts)
        ass += f"Dialogue: 1,{w_start},{w_end},Highlight,,0,0,0,,{highlight_line_text}\n"
    if translation.strip():
        ass += f"Dialogue: 0,{start_time_ass},{end_time_ass},Translation,,0,0,0,,{{\\q3}}{translation}\n"
    ass += f"Dialogue: 2,{start_time_ass},{end_time_ass},Website,,0,0,0,,{WEBSITE_TEXT}\n"
    logging.info("ASS subtitles generated successfully.")
    logging.debug("Generated ASS file content:\n" + ass)
    return ass

def escape_path_for_ffmpeg(path):
    # Convert to absolute path and replace backslashes with forward slashes.
    path = os.path.abspath(path)
    path = path.replace('\\', '/')
    if os.name == 'nt':
        # Escape the colon after the drive letter (e.g. "C:" -> "C\:")
        path = re.sub(r'^([A-Za-z]):', r'\1\\:', path)
        return path
    return f"'{path}'"

def copy_processed_videos(processed_videos, output_dir):
    new_tmp_dir = os.path.join(output_dir, "tmp")
    if not os.path.exists(new_tmp_dir):
        os.makedirs(new_tmp_dir)
        logging.info(f"Created directory for copied videos: {new_tmp_dir}")
    new_processed_videos = []
    for video in processed_videos:
        dest_video = os.path.join(new_tmp_dir, os.path.basename(video))
        try:
            shutil.copy2(video, dest_video)
            logging.info(f"Video {video} copied to {dest_video}")
            new_processed_videos.append(dest_video)
        except Exception as e:
            logging.error(f"Error copying {video} to {dest_video}: {e}", exc_info=True)
    return new_processed_videos

def remove_working_temp_files():
    for tmp_file in ["concat.sh", "concat_list.txt"]:
        tmp_file_path = os.path.join(os.getcwd(), tmp_file)
        if os.path.exists(tmp_file_path):
            try:
                os.remove(tmp_file_path)
                logging.info(f"Removed temporary file: {tmp_file_path}")
            except Exception as e:
                logging.error(f"Error removing temporary file {tmp_file_path}: {e}", exc_info=True)

########################################################################
# Two-pass processing functions
########################################################################
def extract_video_metadata(video_path, video_size, translate_lang):
    logging.info(f"Extracting metadata from video: {video_path}")
    base_name = os.path.splitext(os.path.basename(video_path))[0]
    safe_base = sanitize_filename(base_name)
    temp_dir = tempfile.mkdtemp(prefix="video_process_")
    srt_path = os.path.join(temp_dir, f"{safe_base}.srt")
    try:
        extract_subtitles(video_path, srt_path)
    except Exception as e:
        logging.error(f"Error extracting subtitles from {video_path}: {e}", exc_info=True)
        shutil.rmtree(temp_dir)
        return None
    cues = parse_srt(srt_path)
    if not cues:
        logging.info(f"Video {video_path} does not contain subtitles or cues – skipping.")
        shutil.rmtree(temp_dir)
        return None
    phrase = get_full_phrase_from_cues(cues)
    if translate_lang:
        translation = translate_text(phrase, target_language=translate_lang)
    else:
        translation = ""
    try:
        w_str, h_str = video_size.split("x")
        width = int(w_str)
        height = int(h_str)
        logging.info(f"Video size: {width}x{height}")
    except Exception as e:
        logging.error(f"Error parsing video_size '{video_size}': {e}. Defaulting to 640x480.", exc_info=True)
        width, height = 640, 480
    return {"video_path": video_path, "temp_dir": temp_dir, "cues": cues, "phrase": phrase,
            "translation": translation, "width": width, "height": height, "safe_base": safe_base}

def process_video_with_metadata(data, highlite_phrase):
    logging.info(f"Processing video with metadata: {data['video_path']}")
    try:
        ass_content = generate_ass_subtitles(cues=data["cues"],
                                             phrase=data["phrase"],
                                             translation=data["translation"],
                                             video_width=data["width"],
                                             video_height=data["height"],
                                             highlite_phrase=highlite_phrase)
    except Exception as e:
        logging.error(f"Error generating ASS for {data['video_path']}: {e}", exc_info=True)
        shutil.rmtree(data["temp_dir"])
        return None
    ass_path = os.path.join(data["temp_dir"], f"{data['safe_base']}.ass")
    try:
        with open(ass_path, "w", encoding="utf-8") as f:
            f.write(ass_content)
        logging.info(f"ASS file written: {ass_path}")
    except Exception as e:
        logging.error(f"Error writing ASS file for {data['video_path']}: {e}", exc_info=True)
        shutil.rmtree(data["temp_dir"])
        return None
    escaped_ass_path = escape_path_for_ffmpeg(ass_path)
    if CUSTOM_FONTS_DIR:
        fonts_dir = CUSTOM_FONTS_DIR
    else:
        script_dir = os.path.dirname(os.path.realpath(__file__))
        fonts_dir = os.path.join(script_dir, "fonts")
    if os.path.isdir(fonts_dir):
        fonts_dir_escaped = escape_path_for_ffmpeg(fonts_dir)
        fonts_option = f":fontsdir={fonts_dir_escaped}"
    else:
        fonts_option = ""
    logging.info(f"Using fonts directory for ffmpeg: {fonts_dir}")
    logging.info(f"ASS file path (escaped): {escaped_ass_path}")
    ffmpeg_filter = (
        f"scale={data['width']}:{data['height']}:force_original_aspect_ratio=increase,"
        f"crop={data['width']}:{data['height']},"
        f"subtitles={escaped_ass_path}{fonts_option}"
    )
    logging.info(f"FFmpeg filter string: {ffmpeg_filter}")
    output_video = os.path.join(data["temp_dir"], f"processed_{data['safe_base']}.mp4")
    ffmpeg_cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", data["video_path"],
                  "-vf", ffmpeg_filter, output_video]
    logging.info("Executing FFmpeg command: " + " ".join(ffmpeg_cmd))
    try:
        subprocess.run(ffmpeg_cmd, check=True)
        logging.info(f"Video processed successfully: {output_video}")
    except subprocess.CalledProcessError as e:
        logging.error(f"Error processing video {data['video_path']} when adding subtitles: {e}", exc_info=True)
        shutil.rmtree(data["temp_dir"])
        return None
    return output_video

########################################################################
# Main function
########################################################################
def main():
    global PHRASE_FONT, TRANSLATION_FONT, WEBSITE_FONT, CUSTOM_FONTS_DIR
    global PHRASE_FONT_SIZE, TRANSLATION_FONT_SIZE, WEBSITE_FONT_SIZE, GOOGLE_API_KEY

    logging.info("Starting final video creation process.")
    args = parse_args()

    # If --font_size is provided, update the font sizes accordingly.
    if args.font_size is not None:
        PHRASE_FONT_SIZE = args.font_size
        # Use the original ratios (default: 34:24:20) to set translation and website sizes
        TRANSLATION_FONT_SIZE = int(round(args.font_size * 24 / 34))
        WEBSITE_FONT_SIZE = int(round(args.font_size * 20 / 34))
        logging.info(f"Using font size {args.font_size} for main phrase; translation: {TRANSLATION_FONT_SIZE}, website: {WEBSITE_FONT_SIZE}.")

    if args.font:
        resolved_font_name, resolved_font_dir, resolved_units = resolve_font(args.font)
        PHRASE_FONT = resolved_font_name
        TRANSLATION_FONT = resolved_font_name
        WEBSITE_FONT = resolved_font_name
        if resolved_font_dir:
            CUSTOM_FONTS_DIR = resolved_font_dir
            logging.info(f"Using default font: {resolved_font_name} from directory: {resolved_font_dir}")
        else:
            logging.error("Font resolution failed; using default font settings.")
        # If no explicit --font_size is provided, adjust only the phrase font based on the custom font's unitsPerEm.
        if args.font_size is None and resolved_units is not None and resolved_units != 2048:
            scale_factor = 2048 / resolved_units
            PHRASE_FONT_SIZE = int(round(PHRASE_FONT_SIZE * scale_factor))
            logging.info(f"Adjusted phrase font size for custom font with unitsPerEm {resolved_units}: phrase: {PHRASE_FONT_SIZE} (translation remains: {TRANSLATION_FONT_SIZE}, website remains: {WEBSITE_FONT_SIZE})")

    remove_working_temp_files()
    GOOGLE_API_KEY = args.google_api_key
    video_files = get_video_files(args.video_folder)
    total_videos = len(video_files)
    if not video_files:
        logging.info("No suitable video files found in the specified folder.")
        return
    video_data = []
    for video in video_files:
        logging.info(f"Extracting metadata from video: {video}")
        data = extract_video_metadata(video, args.video_size, args.translate_lang)
        if data:
            video_data.append(data)
        else:
            logging.error(f"Metadata extraction failed for {video}.")
    if not video_data:
        logging.info("No videos with valid subtitles found; exiting.")
        return
    phrases = [d['phrase'] for d in video_data]
    if args.highlite_phrase.strip():
        chosen_phrase = args.highlite_phrase.lower()
        logging.info(f"Using provided highlite_phrase: '{chosen_phrase}'")
    else:
        computed = calculate_highlight_phrase(phrases)
        if computed.strip():
            logging.info(f"Calculated common highlite_phrase: '{computed}'")
        else:
            logging.info("No common contiguous sequence found; falling back to first non-empty video phrase.")
        chosen_phrase = computed if computed.strip() else next((p for p in phrases if p.strip()), "output").lower()
    processed_videos = []
    temp_dirs = []
    for data in video_data:
        processed_video = process_video_with_metadata(data, chosen_phrase)
        if processed_video:
            processed_videos.append(processed_video)
            temp_dirs.append(data["temp_dir"])
        else:
            logging.error(f"Processing video {data['video_path']} ended with an error.")
    if args.output_dir:
        output_dir = args.output_dir
    else:
        output_dir = os.path.join(args.video_folder, "result")
    os.makedirs(output_dir, exist_ok=True)
    base_filename = create_filename_from_phrase(chosen_phrase, args.video_size)
    final_output = os.path.join(output_dir, base_filename + ".mp4")
    if processed_videos:
        concat_list_path = os.path.join(os.getcwd(), "concat_list.txt")
        try:
            with open(concat_list_path, "w", encoding="utf-8") as f:
                for video in processed_videos:
                    f.write(f"file '{video}'\n")
            logging.info(f"Concatenation list file created: {concat_list_path}")
        except Exception as e:
            logging.error(f"Error creating concatenation list file: {e}", exc_info=True)
            concat_list_path = None
        concat_sh_path = os.path.join(os.getcwd(), "concat.sh")
        old_concat_command = (
            f"ffmpeg -y -loglevel error -f concat -safe 0 -i {os.path.basename(concat_list_path)} "
            f"-c:v libx264 -preset medium -crf 23 -r 30 -c:a aac -b:a 192k {base_filename}.mp4\n"
        )
        try:
            with open(concat_sh_path, "w", encoding="utf-8") as f:
                f.write(old_concat_command)
            logging.info(f"concat.sh file created: {concat_sh_path}")
        except Exception as e:
            logging.error(f"Error writing concat.sh file: {e}", exc_info=True)
        new_cmd = ["ffmpeg", "-y", "-loglevel", "error"]
        for video in processed_videos:
            new_cmd.extend(["-i", video])
        num_inputs = len(processed_videos)
        filter_complex_parts = []
        for i in range(num_inputs):
            filter_complex_parts.append(f"[{i}:v:0]setsar=1[v{i}];")
        concat_inputs = ""
        for i in range(num_inputs):
            concat_inputs += f"[v{i}][{i}:a:0]"
        filter_complex_parts.append(f"{concat_inputs}concat=n={num_inputs}:v=1:a=1 [v][a]")
        filter_complex = " ".join(filter_complex_parts)
        new_cmd.extend(["-filter_complex", filter_complex, "-map", "[v]", "-map", "[a]"])
        new_cmd.append(final_output)
        logging.info("Executing final concatenation FFmpeg command: " + " ".join(new_cmd))
        try:
            subprocess.run(new_cmd, check=True)
            logging.info(f"Final video created (filter_complex method): {final_output}")
        except subprocess.CalledProcessError as e:
            logging.error(f"Error during video concatenation (filter_complex): {e}", exc_info=True)
    else:
        logging.info("No processed videos, creating an empty final video.")
        try:
            width, height = map(int, args.video_size.split("x"))
        except Exception:
            width, height = 640, 480
        color_filter = f"color=c=black:s={width}x{height}:d=5"
        try:
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", color_filter, final_output], check=True)
            logging.info(f"Final video created: {final_output}")
        except subprocess.CalledProcessError as e:
            logging.error(f"Error creating empty video: {e}", exc_info=True)
    for d in temp_dirs:
        try:
            shutil.rmtree(d)
            logging.info(f"Temporary directory removed: {d}")
        except Exception as e:
            logging.error(f"Error removing temporary directory {d}: {e}", exc_info=True)
    if not args.create_tmp:
        remove_working_temp_files()
    logging.info("\nExecution log:")
    logging.info(f"Total videos: {total_videos}")
    logging.info(f"Processed videos: {len(processed_videos)}")
    logging.info(f"Broken videos: {total_videos - len(processed_videos)}")

if __name__ == "__main__":
    main()
