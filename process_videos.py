#!/usr/bin/env python3
"""
Script for creating a final video from multiple video files.
Karaoke subtitles + translation (Google Translate, DeepL, or OpenAI) + highlighting only the continuous

Note:
  FFmpeg’s subtitles filter needs to load physical TTF files.
  Place your TTF files in a folder named 'fonts' next to this script,
  or provide a full path via the --font parameter.
"""

import os
import subprocess
import sys
import re
import requests
import shutil
import logging
import argparse
import itertools
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
import openai  # For OpenAI API translation
import threading

# Global flag for face tracking (default disabled)
FACE_TRACKING = False

# Global crop cache and its file (all videos share the same cache)
GLOBAL_CROP_CACHE = {}
GLOBAL_CACHE_FILE = "crop_cache.json"
crop_cache_lock = threading.Lock()

# Set up logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

def install_dependencies():
    req_file = os.path.join(os.path.dirname(__file__), "requirements.txt")
    if os.path.exists(req_file):
        logging.info("Installing dependencies from requirements.txt...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", req_file])
        except subprocess.CalledProcessError as e:
            logging.error("Error installing dependencies: %s", e)
            sys.exit(1)

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

# ==================== Configuration ====================
PHRASE_FONT = "Roboto-Regular"          # Default font for main phrase
PHRASE_FONT_SIZE = 38                   # Default main phrase font size
PHRASE_COLOR = "white"
PHRASE_HIGHLITE_COLOR = "yellow"
WORD_HIGHLITE_COLOR = "green"

PHRASE_ALIGNMENT = 2                    # bottom center
PHRASE_MARGIN_V = 80

TRANSLATION_FONT = "Roboto-Regular"     # Default font for translation
TRANSLATION_FONT_SIZE = 24              # Default translation font size
TRANSLATION_COLOR = "white"
TRANSLATION_ALIGNMENT = 2               # bottom center
TRANSLATION_MARGIN_V = 20

WEBSITE_TEXT = "playphrase.me"
WEBSITE_FONT = "Roboto-Regular"         # Default font for website overlay
WEBSITE_FONT_SIZE = 20                  # Default website font size
WEBSITE_COLOR = "white"
WEBSITE_ALIGNMENT = 8                   # top center
WEBSITE_MARGIN_V = 10

GOOGLE_API_KEY = ""
DEEPL_API_KEY = ""
OPENAI_API_KEY = ""
LANGUAGE_MAP = {
    "af": "Afrikaans", "sq": "Albanian", "am": "Amharic", "ar": "Arabic",
    "hy": "Armenian", "az": "Azeerbaijani", "eu": "Basque", "be": "Belarusian",
    "bn": "Bengali", "bs": "Bosnian", "bg": "Bulgarian", "ca": "Catalan",
    "ceb": "Cebuano", "ny": "Chichewa", "zh-CN": "Chinese (Simplified)",
    "zh-TW": "Chinese (Traditional)", "co": "Corsican", "hr": "Croatian",
    "cs": "Czech", "da": "Danish", "nl": "Dutch", "en": "English",
    "eo": "Esperanto", "et": "Estonian", "tl": "Filipino", "fi": "Finnish",
    "fr": "French", "fy": "Frisian", "gl": "Galician", "ka": "Georgian",
    "de": "German", "el": "Greek", "gu": "Gujarati", "ht": "Haitian Creole",
    "ha": "Hausa", "haw": "Hawaiian", "iw": "Hebrew", "he": "Hebrew",
    "hi": "Hindi", "hmn": "Hmong", "hu": "Hungarian", "is": "Icelandic",
    "ig": "Igbo", "id": "Indonesian", "ga": "Irish", "it": "Italian",
    "ja": "Japanese", "jw": "Javanese", "kn": "Kannada", "kk": "Kazakh",
    "km": "Khmer", "ko": "Korean", "ku": "Kurdish", "ky": "Kyrgyz",
    "lo": "Lao", "la": "Latin", "lv": "Latvian", "lt": "Lithuanian",
    "lb": "Luxembourgish", "mk": "Macedonian", "mg": "Malagasy",
    "ms": "Malay", "ml": "Malayalam", "mt": "Maltese", "mi": "Maori",
    "mr": "Marathi", "mn": "Mongolian", "my": "Burmese", "ne": "Nepali",
    "no": "Norwegian", "ps": "Pashto", "fa": "Persian", "pl": "Polish",
    "pt": "Portuguese", "ma": "Punjabi", "ro": "Romanian", "ru": "Russian",
    "sm": "Samoan", "gd": "Scots Gaelic", "sr": "Serbian", "st": "Sesotho",
    "sn": "Shona", "sd": "Sindhi", "si": "Sinhala", "sk": "Slovak",
    "sl": "Slovenian", "so": "Somali", "es": "Spanish", "su": "Sundanese",
    "sw": "Swahili", "sv": "Swedish", "tg": "Tajik", "ta": "Tamil",
    "te": "Telugu", "th": "Thai", "tr": "Turkish", "uk": "Ukrainian",
    "ur": "Urdu", "uz": "Uzbek", "vi": "Vietnamese", "cy": "Welsh",
    "xh": "Xhosa", "yi": "Yiddish", "yo": "Yoruba", "zu": "Zulu",
}

CUSTOM_FONTS_DIR = None  # Global variable for custom fonts directory

# --- Global Crop Cache Functions using GLOBAL_CROP_CACHE ---

def load_global_crop_cache():
    global GLOBAL_CROP_CACHE
    try:
        with open(GLOBAL_CACHE_FILE, "r", encoding="utf-8") as f:
            GLOBAL_CROP_CACHE = json.load(f)
        logging.debug("Loaded global crop cache with keys: %s", list(GLOBAL_CROP_CACHE.keys()))
    except Exception:
        GLOBAL_CROP_CACHE = {}
        logging.debug("No existing global crop cache found. Starting with empty cache.")

def save_global_crop_cache():
    try:
        with open(GLOBAL_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(GLOBAL_CROP_CACHE, f, ensure_ascii=False, indent=2)
        logging.info("Global crop cache saved with keys: %s", list(GLOBAL_CROP_CACHE.keys()))
    except Exception as e:
        logging.error("Error saving global crop cache: %s", e)

def get_cached_crop_filter(video_path, target_width, target_height):
    cache_key = f"{os.path.basename(video_path)}-{target_width}x{target_height}"
    with crop_cache_lock:
        if cache_key in GLOBAL_CROP_CACHE:
            crop_coords = GLOBAL_CROP_CACHE[cache_key]
            logging.info("Using cached crop for key %s: %s", cache_key, crop_coords)
            return f"crop={target_width}:{target_height}:{crop_coords['x']}:{crop_coords['y']}"
        else:
            logging.info("Cache key %s not found.", cache_key)
            return None

def update_crop_cache(video_path, target_width, target_height, crop_x, crop_y):
    cache_key = f"{os.path.basename(video_path)}-{target_width}x{target_height}"
    with crop_cache_lock:
        GLOBAL_CROP_CACHE[cache_key] = {"x": crop_x, "y": crop_y}
        logging.info("Updated global crop cache for key %s with values: %s", cache_key, GLOBAL_CROP_CACHE[cache_key])
        save_global_crop_cache()

# --- End Global Crop Cache Functions ---

########################################################################
# Helper: extract internal font name and units per em using fontTools
########################################################################
def get_internal_font_info(ttf_path):
    try:
        from fontTools.ttLib import TTFont
        font = TTFont(ttf_path)
        units = font["head"].unitsPerEm
        internal_name = None
        for record in font['name'].names:
            if record.nameID == 4 and record.platformID == 3 and record.platEncID == 1:
                internal_name = record.toUnicode()
                break
        if not internal_name:
            for record in font['name'].names:
                if record.nameID == 1 and record.platformID == 3 and record.platEncID == 1:
                    internal_name = record.toUnicode()
                    break
        return internal_name, units
    except Exception as e:
        logging.error("Could not extract internal font info from %s: %s", ttf_path, e)
    return None, None

########################################################################
# Font resolution: search the local "fonts" folder and use internal font name if possible
########################################################################
def resolve_font(font_arg):
    ttf_path = None
    if os.path.exists(font_arg):
        abs_path = os.path.abspath(font_arg)
        logging.info("Resolved font path from given value: %s", abs_path)
        ttf_path = abs_path
    else:
        script_dir = os.path.dirname(os.path.realpath(__file__))
        fonts_folder = os.path.join(script_dir, "fonts")
        possible_path = os.path.join(fonts_folder, font_arg)
        if os.path.exists(possible_path):
            logging.info("Found font in local fonts folder: %s", possible_path)
            ttf_path = possible_path
        elif not os.path.splitext(font_arg)[1]:
            possible_path_ttf = os.path.join(fonts_folder, font_arg + ".ttf")
            if os.path.exists(possible_path_ttf):
                logging.info("Found font in local fonts folder with .ttf appended: %s", possible_path_ttf)
                ttf_path = possible_path_ttf
    if not ttf_path:
        logging.error("Font '%s' not found in the local fonts folder or as a direct file path.", font_arg)
        return font_arg, None, None

    internal_name, units = get_internal_font_info(ttf_path)
    if internal_name:
        logging.info("Extracted internal font name: %s with unitsPerEm: %s", internal_name, units)
        font_name = internal_name
    else:
        font_name = os.path.splitext(os.path.basename(ttf_path))[0]
        logging.warning("Could not extract internal font name. Using filename: %s", font_name)
    return font_name, os.path.dirname(ttf_path), units

########################################################################
# Simple clamp function
########################################################################
def clamp(value, min_value, max_value):
    return max(min_value, min(value, max_value))

########################################################################
# Face detection using OpenCV (Haar cascades)
########################################################################
def detect_face_bounds(video_path):
    try:
        import cv2
    except ImportError:
        logging.error("OpenCV is not installed. Face tracking requires opencv-python.")
        return None
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        logging.error("Cannot open video file: %s", video_path)
        return None
    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    duration = total_frames / fps if fps > 0 else 0
    target_time = 1.0 if duration >= 1.0 else 0.0
    cap.set(cv2.CAP_PROP_POS_MSEC, target_time * 1000)
    ret, frame = cap.read()
    if not ret:
        logging.error("Failed to read frame for face detection.")
        cap.release()
        return None
    orig_h, orig_w = frame.shape[:2]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
    cap.release()
    if len(faces) == 0:
        logging.info("No faces detected in the video frame.")
        return None
    x, y, w, h = faces[0]
    logging.info("Detected face at: x=%s, y=%s, w=%s, h=%s in original resolution %sx%s", x, y, w, h, orig_w, orig_h)
    return (x, y, w, h), (orig_w, orig_h)

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
        description="Script for creating video with karaoke subtitles, translation, and highlighting of a continuous sequence of words."
    )
    parser.add_argument("--video_folder", type=str, default=".", help="Folder with videos (default current folder)")
    parser.add_argument("--video_size", type=str, default="640x480", help="Final video size in WIDTHxHEIGHT (default 640x480)")
    parser.add_argument("--highlite_phrase", type=str, default="", help="Phrase for highlighting (if omitted, calculated from videos)")
    parser.add_argument("--translate_lang", type=str, default=None,
                        help="Translation language code or comma separated list of codes (e.g., 'ru' or 'ru,es,de'). Default: None")
    parser.add_argument("--google_api_key", type=str, default="", help="Google API Key (default empty)")
    parser.add_argument("--deepl_api_key", type=str, default="", help="DeepL API Key (default empty)")
    parser.add_argument("--openai_api_key", type=str, default="", help="OpenAI API Key for translation using OpenAI API")
    parser.add_argument("--output-dir", type=str, default=None, help="Directory where the final video(s) will be saved")
    parser.add_argument("--font", type=str, default=None, help="Default font name or full path to TTF file for overlays")
    parser.add_argument("--font_size", type=int, default=None, help="Optional font size to use for the main phrase (others scale proportionally)")
    parser.add_argument("--focus", action="store_true", help="Enable focus mode: only the highlighted phrase plus paddings will play, with audio fade-in/out")
    parser.add_argument("--face-tracking", action="store_true", help="Enable face tracking to center the face in the video crop")
    args = parser.parse_args()
    logging.info("Command line arguments parsed successfully.")
    return args

def natural_sort_key(s):
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s)]

def get_video_files(folder):
    exts = [".mp4", ".mkv", ".avi", ".mov"]
    files = []
    for f in os.listdir(folder):
        if os.path.splitext(f)[1].lower() in exts:
            if f.lower().startswith("output") or f.lower().startswith("processed_"):
                continue
            files.append(f)
    files = sorted(files, key=natural_sort_key)
    logging.info("Found %s video files in the folder: %s", len(files), folder)
    return files

def extract_subtitles(video_path, output_srt):
    logging.info("Extracting subtitles from %s to %s", video_path, output_srt)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", video_path, "-map", "0:s:0?", output_srt]
    subprocess.run(cmd, check=True)
    logging.info("Subtitles extracted successfully.")

def srt_time_to_seconds(time_str):
    h, m, s_ms = time_str.split(":")
    s, ms = s_ms.split(",")
    return int(h)*3600 + int(m)*60 + int(s) + int(ms)/1000.0

def clean_tags_except_u(text):
    u_contents = []
    def preserve_u(match):
        u_contents.append(match.group(0))
        return f"__PRESERVE_U_{len(u_contents)-1}__"
    text_with_placeholders = re.sub(r'<u>.*?</u>', preserve_u, text, flags=re.DOTALL)
    clean_text = re.sub(r'</?[a-zA-Z]+[^<>]*>', '', text_with_placeholders)
    for i, content in enumerate(u_contents):
        clean_text = clean_text.replace(f"__PRESERVE_U_{i}__", content)
    return clean_text

def parse_srt(srt_path):
    logging.info("Parsing SRT file: %s", srt_path)
    cues = []
    try:
        with open(srt_path, encoding='utf-8') as f:
            content = f.read().strip()
    except Exception as e:
        logging.error("Error reading SRT file: %s", e)
        return cues
    if not content:
        return cues
    parts = re.split(r'\n\s*\n', content)
    for part in parts:
        lines = part.strip().splitlines()
        if len(lines) >= 3:
            time_line = lines[1]
            text = " ".join(lines[2:])
            text = clean_tags_except_u(text)
            m = re.match(r'(\d+:\d+:\d+,\d+)\s*-->\s*(\d+:\d+:\d+,\d+)', time_line)
            if m:
                start = srt_time_to_seconds(m.group(1))
                end = srt_time_to_seconds(m.group(2))
                highlighted = re.findall(r'<u>(.*?)</u>', text)
                if highlighted:
                    cues.append({"start": start, "end": end, "text": text, "highlight": highlighted[0]})
    logging.info("Found %s cues in the SRT file.", len(cues))
    return cues

def clean_text(text):
    return re.sub(r'<[^>]+>', '', text)

def get_full_phrase_from_cues(cues):
    if cues:
        phrase = clean_text(cues[-1]["text"])
        logging.info("Extracted full phrase: %s", phrase)
        return phrase
    logging.info("No cues found – returning an empty phrase.")
    return ""

def translate_text(text, target_language="ru"):
    if not text.strip():
        logging.info("Empty text for translation – returning an empty string.")
        return ""
    
    cache_file = os.path.join(os.getcwd(), "translation_cache.json")
    try:
        with open(cache_file, "r", encoding="utf-8") as f:
            cache = json.load(f)
    except Exception:
        cache = {}
    if target_language not in cache:
        cache[target_language] = {}
    if text in cache[target_language]:
        logging.info("Returning cached translation for '%s': %s", target_language, text)
        return cache[target_language][text]
    
    translation = ""
    if OPENAI_API_KEY:
        language_name = LANGUAGE_MAP.get(target_language, target_language)
        logging.info("Using OpenAI for translation to %s: %s", language_name, text)
        openai.api_key = OPENAI_API_KEY
        try:
            response = openai.ChatCompletion.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": f"You are a translation assistant. Translate the following text into {language_name}."},
                    {"role": "user", "content": text}
                ]
            )
            translation = response.choices[0].message.content.strip()
            logging.info("Translation received: %s", translation)
        except Exception as e:
            logging.error("OpenAI Translate API error: %s", e)
            return ""
    elif GOOGLE_API_KEY:
        logging.info("Using Google Translate for translation to %s: %s", target_language, text)
        url = "https://translation.googleapis.com/language/translate/v2"
        params = {"q": text, "target": target_language, "key": GOOGLE_API_KEY}
        response = requests.post(url, data=params)
        if response.status_code == 200:
            data = response.json()
            translation = data["data"]["translations"][0]["translatedText"]
            logging.info("Translation received: %s", translation)
        else:
            logging.error("Translate API error: %s", response.text)
            return ""
    elif DEEPL_API_KEY:
        logging.info("Using DeepL for translation to %s: %s", target_language, text)
        url = "https://api.deepl.com/v2/translate"
        params = {"text": text, "target_lang": target_language.upper(), "auth_key": DEEPL_API_KEY, "formality": "less"}
        response = requests.post(url, data=params)
        if response.status_code == 200:
            data = response.json()
            translation = data["translations"][0]["text"]
            logging.info("Translation received: %s", translation)
        else:
            logging.error("DeepL Translate API error: %s", response.text)
            return ""
    else:
        logging.error("No translation API key provided. Cannot translate text.")
        return ""
    
    if translation:
        cache[target_language][text] = translation
        try:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False, indent=2)
            logging.debug("Updated translation cache keys: %s", list(cache[target_language].keys()))
        except Exception as e:
            logging.error("Error updating translation cache: %s", e)
    return translation

def convert_color(color_name):
    colors = {
        "white": "&H00FFFFFF", "black": "&H00000000", "yellow": "&H0031D1FD",
        "red": "&H000000FF", "green": "&H0000FF00", "blue": "&H00FF0000",
        "cyan": "&H00FFFF00", "gray": "&H00AAAAAA", "transparent": "&HFF000000",
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
            logging.info("Found subsequence starting at index %s", start_idx)
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
        logging.info("Found common contiguous subsequence for all phrases: '%s'", candidate)
        return candidate
    total = len(normalized_phrases)
    for r in range(total - 1, 1, -1):
        best_candidate = ""
        for subset in itertools.combinations(normalized_phrases, r):
            candidate = common_contiguous_subsequence(list(subset))
            if candidate and len(candidate.split()) > len(best_candidate.split()):
                best_candidate = candidate
        if best_candidate:
            logging.info("Found common contiguous subsequence for a subset of size %s: '%s'", r, best_candidate)
            return best_candidate
    logging.info("No common contiguous subsequence found even in subsets.")
    return ""

def generate_ass_subtitles(cues, phrase, translation, video_width, video_height, highlite_phrase, translation_rtl=False):
    logging.info("Starting ASS subtitle generation.")
    if not cues:
        total_start_sec = 0.0
        total_end_sec = 5.0
    else:
        total_start_sec = cues[0]["start"]
        total_end_sec = cues[-1]["end"]
    start_time_ass = seconds_to_ass_time(total_start_sec)
    end_time_ass = seconds_to_ass_time(total_end_sec)
    logging.info("Subtitle time interval: %s - %s", start_time_ass, end_time_ass)

    scale = video_width / 640.0
    scaled_phrase_font_size = int(round(PHRASE_FONT_SIZE * scale))
    scaled_translation_font_size = int(round(TRANSLATION_FONT_SIZE * scale))
    scaled_website_font_size = int(round(WEBSITE_FONT_SIZE * scale))
    scaled_phrase_margin_v = int(round(PHRASE_MARGIN_V * scale))
    scaled_translation_margin_v = int(round(TRANSLATION_MARGIN_V * scale))
    scaled_website_margin_v = int(round(WEBSITE_MARGIN_V * scale))
    scaled_margin_lr = int(round(10 * scale))
    scaled_outline = int(round(2 * scale))

    if phrase:
        N_phrase = len(phrase)
        max_S_phrase = 5 * video_width / N_phrase
        scaling_factor_phrase = min(1, max_S_phrase / scaled_phrase_font_size)
    else:
        scaling_factor_phrase = 1

    if translation:
        N_trans = len(translation)
        max_S_trans = 5 * video_width / N_trans
        scaling_factor_trans = min(1, max_S_trans / scaled_translation_font_size)
    else:
        scaling_factor_trans = 1

    overall_scaling_factor = min(scaling_factor_phrase, scaling_factor_trans)
    final_phrase_font_size = int(round(scaled_phrase_font_size * overall_scaling_factor))
    final_translation_font_size = int(round(scaled_translation_font_size * overall_scaling_factor))

    words_original = phrase.split()
    words_normalized = [normalize_word(w) for w in words_original]
    highlite_words_raw = highlite_phrase.split()
    highlite_words_normalized = [normalize_word(w) for w in highlite_words_raw if w.strip()]
    highlight_indices = []
    if highlite_words_normalized:
        highlight_indices = find_subsequence_indices(words_normalized, highlite_words_normalized)
    logging.info("Highlighted word indices: %s", highlight_indices)

    phrase_margin_v = scaled_translation_margin_v if not translation.strip() else scaled_phrase_margin_v

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
        f"Style: Base,{PHRASE_FONT},{final_phrase_font_size},"
        f"{convert_color(PHRASE_COLOR)},{convert_color(PHRASE_COLOR)},"
        "&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,"
        f"{scaled_outline},0,{PHRASE_ALIGNMENT},{scaled_margin_lr},{scaled_margin_lr},{phrase_margin_v},1\n"
    )
    ass += (
        f"Style: Highlight,{PHRASE_FONT},{final_phrase_font_size},"
        f"{convert_color(WORD_HIGHLITE_COLOR)},{convert_color('transparent')},"
        "&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,"
        f"{scaled_outline},0,{PHRASE_ALIGNMENT},{scaled_margin_lr},{scaled_margin_lr},{phrase_margin_v},1\n"
    )
    trans_alignment = TRANSLATION_ALIGNMENT
    ass += (
        f"Style: Translation,{TRANSLATION_FONT},{final_translation_font_size},"
        f"{convert_color(TRANSLATION_COLOR)},{convert_color(TRANSLATION_COLOR)},"
        "&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,"
        f"{scaled_outline},0,{trans_alignment},{scaled_margin_lr},{scaled_margin_lr},{scaled_translation_margin_v},1\n"
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
        if translation_rtl:
            translation = "\u202B" + translation + "\u202C"
        ass += f"Dialogue: 0,{start_time_ass},{end_time_ass},Translation,,0,0,0,,{{\\q3}}{translation}\n"

    ass += f"Dialogue: 2,{start_time_ass},{end_time_ass},Website,,0,0,0,,{WEBSITE_TEXT}\n"

    logging.info("ASS subtitles generated successfully.")
    logging.debug("Generated ASS file content:\n%s", ass)
    return ass

def escape_path_for_ffmpeg(path):
    rel_path = os.path.relpath(path, start=os.getcwd())
    return rel_path.replace('\\', '/')

def copy_processed_videos(processed_videos, output_dir):
    new_tmp_dir = os.path.join(output_dir, "tmp")
    if not os.path.exists(new_tmp_dir):
        os.makedirs(new_tmp_dir)
        logging.info("Created directory for copied videos: %s", new_tmp_dir)
    new_processed_videos = []
    for video in processed_videos:
        dest_video = os.path.join(new_tmp_dir, os.path.basename(video))
        try:
            shutil.copy2(video, dest_video)
            logging.info("Video %s copied to %s", video, dest_video)
            new_processed_videos.append(dest_video)
        except Exception as e:
            logging.error("Error copying %s to %s: %s", video, dest_video, e, exc_info=True)
    return new_processed_videos

def remove_working_temp_files(tmp_base_dir):
    for tmp_file in ["concat.sh", "concat_list.txt"]:
        tmp_file_path = os.path.join(tmp_base_dir, tmp_file)
        if os.path.exists(tmp_file_path):
            try:
                os.remove(tmp_file_path)
                logging.info("Removed temporary file: %s", tmp_file_path)
            except Exception as e:
                logging.error("Error removing temporary file %s: %s", tmp_file_path, e, exc_info=True)

def concatenate_processed_videos(processed_videos, final_output, base_tmp_dir, video_size):
    if processed_videos:
        concat_list_path = os.path.join(base_tmp_dir, "concat_list.txt")
        try:
            with open(concat_list_path, "w", encoding="utf-8") as f:
                for video in processed_videos:
                    f.write(f"file '{video}'\n")
            logging.info("Concatenation list file created: %s", concat_list_path)
        except Exception as e:
            logging.error("Error creating concatenation list file: %s", e, exc_info=True)
            concat_list_path = None

        concat_sh_path = os.path.join(base_tmp_dir, "concat.sh")
        old_concat_command = (
            f"ffmpeg -y -loglevel error -f concat -safe 0 -i {os.path.basename(concat_list_path)} "
            f"-c:v libx264 -preset slow -crf 20 -pix_fmt yuv420p "
            f"-colorspace bt709 -color_primaries bt709 -color_trc bt709 -color_range tv "
            f"-r 30 -c:a aac -b:a 192k {os.path.basename(final_output)}\n"
        )
        try:
            with open(concat_sh_path, "w", encoding="utf-8") as f:
                f.write(old_concat_command)
            logging.info("concat.sh file created: %s", concat_sh_path)
        except Exception as e:
            logging.error("Error writing concat.sh file: %s", e, exc_info=True)

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
        new_cmd.extend([
            "-filter_complex", filter_complex,
            "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-preset", "slow", "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-colorspace", "bt709", "-color_primaries", "bt709",
            "-color_trc", "bt709", "-color_range", "tv",
            "-r", "30",
            "-c:a", "aac", "-b:a", "192k",
            final_output
        ])
        logging.info("Executing final concatenation FFmpeg command: %s", " ".join(new_cmd))
        try:
            subprocess.run(new_cmd, check=True)
            logging.info("Final video created: %s", final_output)
        except subprocess.CalledProcessError as e:
            logging.error("Error during video concatenation: %s", e, exc_info=True)
    else:
        logging.info("No processed videos, creating an empty final video.")
        try:
            w_str, h_str = video_size.split("x")
            width = int(w_str)
            height = int(h_str)
        except Exception:
            width, height = 640, 480
        color_filter = f"color=c=black:s={width}x{height}:d=5"
        try:
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", color_filter, final_output], check=True)
            logging.info("Final video created (empty video): %s", final_output)
        except subprocess.CalledProcessError as e:
            logging.error("Error creating empty video: %s", e, exc_info=True)

def apply_focus_trimming(processed_video_path, data, chosen_phrase):
    fade_time = 0.5         # Audio fade time
    ideal_padding = 1.5     # Video padding (seconds)
    edge_volume = 0.5       # Volume at edges

    cues = data["cues"]
    if not cues:
        logging.info("No cues available for focus trimming. Skipping trimming.")
        return processed_video_path

    words_original = data["phrase"].split()
    words_normalized = [normalize_word(w) for w in words_original]
    highlite_words_normalized = [normalize_word(w) for w in chosen_phrase.split() if w.strip()]
    highlight_indices = find_subsequence_indices(words_normalized, highlite_words_normalized)
    if highlight_indices:
        phrase_start = cues[highlight_indices[0]]["start"]
        phrase_end = cues[highlight_indices[-1]]["end"]
    else:
        phrase_start = cues[0]["start"]
        phrase_end = cues[-1]["end"]

    pad_before = ideal_padding if phrase_start >= ideal_padding else phrase_start
    pad_after = ideal_padding if (phrase_end + ideal_padding <= cues[-1]["end"]) else (cues[-1]["end"] - phrase_end)
    segment_start = phrase_start - pad_before
    segment_end = phrase_end + pad_after
    segment_duration = segment_end - segment_start

    logging.info("Focus trimming: segment from %s to %s seconds (pad before: %s, pad after: %s)", segment_start, segment_end, pad_before, pad_after)

    base, ext = os.path.splitext(processed_video_path)
    focused_video = base + "_focus" + ext

    epsilon = 0.0001
    fade_in_duration = min(fade_time, pad_before) if fade_time > 0 else 0
    fade_out_duration = min(fade_time, pad_after) if fade_time > 0 else 0
    safe_fade_in = max(fade_in_duration, epsilon)
    safe_fade_out = max(fade_out_duration, epsilon)
    fade_out_start = segment_duration - safe_fade_out

    volume_expr = None
    fade_in_delta = 1 - edge_volume
    if fade_in_duration > 0 and fade_out_duration > 0:
        volume_expr = (f"if(lt(t,{fade_in_duration}), {edge_volume}+{fade_in_delta}*t/{safe_fade_in}, "
                       f"if(gt(t,{fade_out_start}), 1-{fade_in_delta}*(t-{fade_out_start})/{safe_fade_out}, 1))")
    elif fade_in_duration > 0:
        volume_expr = f"if(lt(t,{fade_in_duration}), {edge_volume}+{fade_in_delta}*t/{safe_fade_in}, 1)"
    elif fade_out_duration > 0:
        volume_expr = f"if(gt(t,{fade_out_start}), 1-{fade_in_delta}*(t-{fade_out_start})/{safe_fade_out}, 1)"
    if volume_expr:
        volume_expr = f"min({volume_expr},1)"

    ffmpeg_cmd = [
         "ffmpeg", "-y", "-loglevel", "error",
         "-i", processed_video_path,
         "-ss", str(segment_start),
         "-to", str(segment_end),
         "-vf", "setpts=PTS-STARTPTS",
    ]
    if volume_expr:
         ffmpeg_cmd.extend(["-af", f"volume='{volume_expr}':eval=frame"])
    ffmpeg_cmd.append(focused_video)

    logging.info("Applying focus trimming with command: %s", " ".join(ffmpeg_cmd))
    try:
         subprocess.run(ffmpeg_cmd, check=True)
         logging.info("Focus trimmed video created: %s", focused_video)
         return focused_video
    except subprocess.CalledProcessError as e:
         logging.error("Error applying focus trimming: %s", e, exc_info=True)
         return processed_video_path

def extract_video_metadata(video_path, video_size, translate_lang, base_tmp_dir):
    logging.info("Extracting metadata from video: %s", video_path)
    base_name = os.path.splitext(os.path.basename(video_path))[0]
    safe_base = sanitize_filename(base_name)
    temp_dir = os.path.join(base_tmp_dir, f"video_process_{safe_base}")
    os.makedirs(temp_dir, exist_ok=True)
    srt_path = os.path.join(temp_dir, f"{safe_base}.srt")
    try:
        extract_subtitles(video_path, srt_path)
    except Exception as e:
        logging.error("Error extracting subtitles from %s: %s", video_path, e, exc_info=True)
        shutil.rmtree(temp_dir)
        return None
    cues = parse_srt(srt_path)
    if not cues:
        logging.info("Video %s does not contain subtitles or cues – skipping.", video_path)
        shutil.rmtree(temp_dir)
        return None
    phrase = get_full_phrase_from_cues(cues)
    translation = translate_text(phrase, target_language=translate_lang) if translate_lang else ""
    try:
        w_str, h_str = video_size.split("x")
        width = int(w_str)
        height = int(h_str)
        logging.info("Video size: %sx%s", width, height)
    except Exception as e:
        logging.error("Error parsing video_size '%s': %s. Defaulting to 640x480.", video_size, e, exc_info=True)
        width, height = 640, 480
    return {"video_path": video_path, "temp_dir": temp_dir, "cues": cues, "phrase": phrase,
            "translation": translation, "width": width, "height": height, "safe_base": safe_base}

def process_video_with_metadata(data, highlite_phrase, translation_override=None, lang_code=""):
    logging.info("Processing video: %s", data["video_path"])
    translation_text = translation_override if translation_override is not None else data["translation"]
    try:
        ass_content = generate_ass_subtitles(cues=data["cues"],
                                             phrase=data["phrase"],
                                             translation=translation_text,
                                             video_width=data["width"],
                                             video_height=data["height"],
                                             highlite_phrase=highlite_phrase,
                                             translation_rtl=(lang_code in ['ar', 'he', 'iw', 'fa', 'ur', 'ps', 'ckb', 'sd', 'ug', 'dv']))
    except Exception as e:
        logging.error("Error generating ASS for %s: %s", data["video_path"], e, exc_info=True)
        shutil.rmtree(data["temp_dir"])
        return None
    suffix = f"_{lang_code}" if lang_code else ""
    ass_path = os.path.join(data["temp_dir"], f"{data['safe_base']}{suffix}.ass")
    try:
        with open(ass_path, "w", encoding="utf-8") as f:
            f.write(ass_content)
        logging.info("ASS file written: %s", ass_path)
    except Exception as e:
        logging.error("Error writing ASS file for %s: %s", data["video_path"], e, exc_info=True)
        shutil.rmtree(data["temp_dir"])
        return None

    ass_path_escaped = escape_path_for_ffmpeg(ass_path)
    if CUSTOM_FONTS_DIR:
        fonts_dir = CUSTOM_FONTS_DIR
    else:
        fonts_dir = os.path.join(os.getcwd(), "tmp-dir", "fonts")
    fonts_option = f":fontsdir={escape_path_for_ffmpeg(fonts_dir)}" if os.path.isdir(fonts_dir) else ""
    logging.info("Using fonts directory for ffmpeg: %s", fonts_dir)
    logging.info("ASS file path (escaped): %s", ass_path_escaped)

    target_width = data['width']
    target_height = data['height']
    if FACE_TRACKING:
        cached_crop_filter = get_cached_crop_filter(data["video_path"], target_width, target_height)
        if cached_crop_filter:
            crop_filter = cached_crop_filter
        else:
            result = detect_face_bounds(data["video_path"])
            if result is not None:
                (face_x, face_y, face_w, face_h), (orig_w, orig_h) = result
                scale_factor = max(target_width / orig_w, target_height / orig_h)
                scaled_w = orig_w * scale_factor
                scaled_h = orig_h * scale_factor
                face_center_x = face_x + face_w / 2
                face_center_y = face_y + face_h / 2
                face_center_scaled_x = face_center_x * scale_factor
                face_center_scaled_y = face_center_y * scale_factor
                crop_x = int(clamp(face_center_scaled_x - target_width / 2, 0, scaled_w - target_width))
                crop_y = int(clamp(face_center_scaled_y - target_height / 2, 0, scaled_h - target_height))
                logging.info("Using face tracking: calculated crop offsets: x=%s, y=%s", crop_x, crop_y)
                crop_filter = f"crop={target_width}:{target_height}:{crop_x}:{crop_y}"
                update_crop_cache(data["video_path"], target_width, target_height, crop_x, crop_y)
            else:
                logging.info("Face tracking enabled but no face detected; using default center crop with zero offsets.")
                crop_filter = f"crop={target_width}:{target_height}"
                update_crop_cache(data["video_path"], target_width, target_height, 0, 0)
    else:
        crop_filter = f"crop={target_width}:{target_height}"
        
    ffmpeg_filter = f"scale={target_width}:{target_height}:force_original_aspect_ratio=increase,{crop_filter},subtitles={ass_path_escaped}{fonts_option}"
    logging.info("FFmpeg filter string: %s", ffmpeg_filter)
    processed_filename = f"processed_{data['safe_base']}{suffix}.mp4"
    output_video = os.path.join(data["temp_dir"], processed_filename)
    ffmpeg_cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", data["video_path"],
        "-vf", ffmpeg_filter,
        "-af", "dynaudnorm",
        "-c:v", "libx264", "-preset", "slow", "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-colorspace", "bt709", "-color_primaries", "bt709",
        "-color_trc", "bt709", "-color_range", "tv",
        output_video
    ]
    logging.info("Executing FFmpeg command: %s", " ".join(ffmpeg_cmd))
    try:
        subprocess.run(ffmpeg_cmd, check=True)
        logging.info("Video processed successfully: %s", output_video)
    except subprocess.CalledProcessError as e:
        logging.error("Error processing video %s when adding subtitles: %s", data["video_path"], e, exc_info=True)
        shutil.rmtree(data["temp_dir"])
        return None
    return output_video

def main():
    args = parse_args()
    global FACE_TRACKING, CUSTOM_FONTS_DIR
    FACE_TRACKING = args.face_tracking
    global DEEPL_API_KEY, GOOGLE_API_KEY, OPENAI_API_KEY
    DEEPL_API_KEY = args.deepl_api_key
    GOOGLE_API_KEY = args.google_api_key
    OPENAI_API_KEY = args.openai_api_key

    video_folder = os.path.abspath(args.video_folder)
    os.chdir(video_folder)
    logging.info("Changed working directory to: %s", video_folder)

    # Load global crop cache once
    load_global_crop_cache()

    base_tmp_dir = os.path.join(os.getcwd(), "tmp-dir")
    os.makedirs(base_tmp_dir, exist_ok=True)
    logging.info("Temporary files will be stored in: %s", base_tmp_dir)

    script_dir = os.path.dirname(os.path.realpath(__file__))
    src_fonts_dir = os.path.join(script_dir, "fonts")
    if os.path.isdir(src_fonts_dir):
        dest_fonts_dir = os.path.join(base_tmp_dir, "fonts")
        if os.path.exists(dest_fonts_dir):
            shutil.rmtree(dest_fonts_dir)
        shutil.copytree(src_fonts_dir, dest_fonts_dir)
        logging.info("Copied fonts folder from %s to %s", src_fonts_dir, dest_fonts_dir)
        if CUSTOM_FONTS_DIR is None:
            CUSTOM_FONTS_DIR = dest_fonts_dir

    remove_working_temp_files(base_tmp_dir)

    if args.font_size is not None:
        PHRASE_FONT_SIZE = args.font_size
        TRANSLATION_FONT_SIZE = int(round(args.font_size * 24 / 34))
        WEBSITE_FONT_SIZE = int(round(args.font_size * 20 / 34))
        logging.info("Using font size %s for main phrase; translation: %s, website: %s", args.font_size, TRANSLATION_FONT_SIZE, WEBSITE_FONT_SIZE)

    if args.font:
        resolved_font_name, resolved_font_dir, resolved_units = resolve_font(args.font)
        PHRASE_FONT = resolved_font_name
        TRANSLATION_FONT = resolved_font_name
        WEBSITE_FONT = resolved_font_name
        if resolved_font_dir:
            CUSTOM_FONTS_DIR = resolved_font_dir
            logging.info("Using default font: %s from directory: %s", resolved_font_name, resolved_font_dir)
        else:
            logging.error("Font resolution failed; using default font settings.")
        if args.font_size is None and resolved_units is not None and resolved_units != 2048:
            scale_factor = 2048 / resolved_units
            PHRASE_FONT_SIZE = int(round(PHRASE_FONT_SIZE * scale_factor))
            logging.info("Adjusted phrase font size for custom font with unitsPerEm %s: %s", resolved_units, PHRASE_FONT_SIZE)

    video_files = get_video_files(os.getcwd())
    total_videos = len(video_files)
    if not video_files:
        logging.info("No suitable video files found in the specified folder.")
        return

    if args.translate_lang:
        languages = [lang.strip() for lang in args.translate_lang.split(',') if lang.strip()]
    else:
        languages = []

    video_data = []
    with ThreadPoolExecutor() as executor:
        futures = {}
        for video in video_files:
            lang_for_extract = languages[0] if languages and len(languages)==1 else None
            futures[executor.submit(extract_video_metadata, video, args.video_size, lang_for_extract, base_tmp_dir)] = video
        for future in as_completed(futures):
            video = futures[future]
            try:
                data = future.result()
                if data:
                    video_data.append(data)
                else:
                    logging.error("Metadata extraction failed for %s.", video)
            except Exception as e:
                logging.error("Error processing video %s: %s", video, e, exc_info=True)
    if not video_data:
        logging.info("No videos with valid subtitles found; exiting.")
        return

    phrases = [d['phrase'] for d in video_data]
    if args.highlite_phrase.strip():
        chosen_phrase = args.highlite_phrase.lower()
        logging.info("Using provided highlite_phrase: '%s'", chosen_phrase)
    else:
        computed = calculate_highlight_phrase(phrases)
        if computed.strip():
            logging.info("Calculated common highlite_phrase: '%s'", computed)
        else:
            logging.info("No common contiguous sequence found; falling back to first non-empty video phrase.")
        chosen_phrase = computed if computed.strip() else next((p for p in phrases if p.strip()), "output").lower()

    def process_single_video(data, chosen_phrase, translation_override=None, lang_code=""):
        processed = process_video_with_metadata(data, chosen_phrase, translation_override=translation_override, lang_code=lang_code)
        if processed and args.focus:
            processed = apply_focus_trimming(processed, data, chosen_phrase)
        return processed

    if languages:
        output_dir = args.output_dir if args.output_dir else os.path.join(os.getcwd(), "result")
        os.makedirs(output_dir, exist_ok=True)
        for lang in languages:
            logging.info("Processing final video for language: %s", lang)
            processed_videos_lang = []
            with ThreadPoolExecutor() as executor:
                futures = {}
                for data in video_data:
                    translation_override = translate_text(data["phrase"], target_language=lang)
                    futures[executor.submit(process_single_video, data, chosen_phrase, translation_override, lang)] = data
                for future in as_completed(futures):
                    try:
                        processed_video = future.result()
                        if processed_video:
                            processed_videos_lang.append(processed_video)
                    except Exception as e:
                        logging.error("Error processing video for language %s: %s", lang, e, exc_info=True)
            processed_videos_lang = sorted(processed_videos_lang, key=lambda x: natural_sort_key(os.path.basename(x)))
            base_filename = create_filename_from_phrase(chosen_phrase, args.video_size)
            base_filename = f"{lang}-{base_filename}"
            final_output = os.path.join(output_dir, base_filename + ".mp4")
            concatenate_processed_videos(processed_videos_lang, final_output, base_tmp_dir, args.video_size)
    else:
        processed_videos = []
        with ThreadPoolExecutor() as executor:
            futures = {}
            for data in video_data:
                futures[executor.submit(process_single_video, data, chosen_phrase)] = data
            for future in as_completed(futures):
                try:
                    processed_video = future.result()
                    if processed_video:
                        processed_videos.append(processed_video)
                except Exception as e:
                    logging.error("Error processing video: %s", e, exc_info=True)
        processed_videos = sorted(processed_videos, key=lambda x: natural_sort_key(os.path.basename(x)))
        output_dir = args.output_dir if args.output_dir else os.path.join(os.getcwd(), "result")
        os.makedirs(output_dir, exist_ok=True)
        base_filename = create_filename_from_phrase(chosen_phrase, args.video_size)
        final_output = os.path.join(output_dir, base_filename + ".mp4")
        concatenate_processed_videos(processed_videos, final_output, base_tmp_dir, args.video_size)

    for data in video_data:
        try:
            shutil.rmtree(data["temp_dir"])
            logging.info("Temporary directory removed: %s", data["temp_dir"])
        except Exception as e:
            logging.error("Error removing temporary directory %s: %s", data["temp_dir"], e, exc_info=True)
    remove_working_temp_files(base_tmp_dir)
    try:
        shutil.rmtree(base_tmp_dir)
        logging.info("Deleted base temporary directory: %s", base_tmp_dir)
    except Exception as e:
        logging.error("Error deleting temporary directory %s: %s", base_tmp_dir, e, exc_info=True)

    logging.info("\nExecution log:")
    logging.info("Total videos: %s", total_videos)
    logging.info("Processing completed.")

if __name__ == "__main__":
    main()
