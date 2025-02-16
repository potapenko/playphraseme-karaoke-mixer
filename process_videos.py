#!/usr/bin/env python3
"""
Script for creating a final video from multiple video files.
Karaoke subtitles + translation (Google Translate) + highlighting only the continuous
sequence of words from --highlite_phrase.
...
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

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def install_dependencies():
    """
    If a requirements.txt file exists in the script's directory, install dependencies from it.
    """
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
    """
    Check if ffmpeg is installed and available in the system PATH.
    Logs an informational message if found; otherwise logs an error and exits.
    """
    try:
        subprocess.run(
            ["ffmpeg", "-version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True
        )
        logging.info("ffmpeg is installed and available.")
    except Exception:
        logging.error("ffmpeg is not installed or not found in the system PATH. "
                      "Please install ffmpeg before running this script.")
        sys.exit(1)

# Check for ffmpeg before proceeding
check_ffmpeg_installed()

# ==================== Configuration (adjust as needed) ====================
# Overlay settings for the main phrase
PHRASE_FONT = "Arial"           # Font for the main phrase
PHRASE_FONT_SIZE = 34           # Font size
PHRASE_COLOR = "white"          # Color for normal words
PHRASE_HIGHLITE_COLOR = "yellow"  # Color for words from the found highlite_phrase
WORD_HIGHLITE_COLOR = "green"  # Karaoke highlight color for the current word

# Positioning for the base phrase
PHRASE_ALIGNMENT = 2  # 2 => bottom center
PHRASE_MARGIN_V = 70  # 70 pixels from the bottom

# Translation settings
TRANSLATION_FONT = "Arial"
TRANSLATION_FONT_SIZE = 24
TRANSLATION_COLOR = "white"

# Positioning for the translation
TRANSLATION_ALIGNMENT = 2  # also bottom center
TRANSLATION_MARGIN_V = 10  # smaller margin

# -------------------- Settings for the website overlay --------------------
WEBSITE_TEXT = "playphrase.me"
WEBSITE_FONT = "Arial"           # Change if needed
WEBSITE_FONT_SIZE = 20
WEBSITE_COLOR = "white"
WEBSITE_ALIGNMENT = 8            # 8 => top center
WEBSITE_MARGIN_V = 10            # Margin from the top

# Google Translate API key (will be overridden by command line arguments)
GOOGLE_API_KEY = ""

def sanitize_filename(filename):
    """Removes all characters from the filename except letters, numbers, underscores, dashes, and dots."""
    return re.sub(r"[^\w\-.]", "_", filename)

def create_filename_from_phrase(phrase):
    """Create a safe filename from a phrase by replacing spaces with '-' and converting to lowercase."""
    filename = phrase.strip().lower().replace(" ", "-")
    return sanitize_filename(filename)

def parse_args():
    parser = argparse.ArgumentParser(
        description="Script for creating video with karaoke subtitles, translation, and highlighting of a continuous sequence of words from highlite_phrase."
    )
    parser.add_argument(
        "--video_folder",
        type=str,
        default=".",
        help="Path to the folder with videos (default is the current folder)"
    )
    parser.add_argument(
        "--video_size",
        type=str,
        default="640x480",
        help="Size of the final video in the format WIDTHxHEIGHT (default 640x480)"
    )
    parser.add_argument(
        "--highlite_phrase",
        type=str,
        default="",
        help="The phrase whose words should be highlighted ONLY when there is a continuous match (case and punctuation insensitive)"
    )
    parser.add_argument(
        "--translate_lang",
        type=str,
        default=None,
        help="Translation language (default: None - do not translate)"
    )
    parser.add_argument(
        "--google_api_key",
        type=str,
        default="",
        help="Google API Key (default empty - do not translate)"
    )
    parser.add_argument(
        "--create_tmp",
        action="store_true",
        default=False,
        help="Create a tmp directory for individual videos (default: no)"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Directory where the final output video file will be saved (default: 'result' subdirectory in the video_folder)"
    )
    args = parser.parse_args()
    logging.info("Command line arguments parsed successfully.")
    return args

def get_video_files(folder):
    exts = [".mp4", ".mkv", ".avi", ".mov"]
    files = []
    for f in os.listdir(folder):
        if os.path.splitext(f)[1].lower() in exts:
            lower = f.lower()
            if lower.startswith("output") or lower.startswith("processed_"):
                continue
            files.append(os.path.join(folder, f))
    files = sorted(files)
    logging.info(f"Found {len(files)} video files in the folder: {folder}")
    return files

def extract_subtitles(video_path, output_srt):
    """
    Extracts the first subtitle track from the video in SRT format.
    Uses -map 0:s:0? to avoid errors if there are no subtitles.
    """
    logging.info(f"Extracting subtitles from {video_path} to {output_srt}")
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error", "-i", video_path,
        "-map", "0:s:0?", output_srt
    ]
    subprocess.run(cmd, check=True)
    logging.info("Subtitles extracted successfully.")

def srt_time_to_seconds(time_str):
    """
    Converts time from the format "HH:MM:SS,ms" to seconds (float).
    """
    h, m, s_ms = time_str.split(":")
    s, ms = s_ms.split(",")
    return int(h)*3600 + int(m)*60 + int(s) + int(ms)/1000.0

def parse_srt(srt_path):
    """
    Parses an SRT file and returns a list of cues.
    Each cue is a dictionary with keys: start, end, text, highlight.
    It is assumed that each word is wrapped in <u>...</u> (for frame highlighting).
    """
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
                    cues.append({
                        "start": start,
                        "end": end,
                        "text": text,
                        "highlight": highlighted[0]
                    })
    logging.info(f"Found {len(cues)} cues in the SRT file.")
    return cues

def clean_text(text):
    """Removes <u> tags from the string."""
    return re.sub(r'</?u>', '', text)

def get_full_phrase_from_cues(cues):
    """
    Returns the full phrase (without tags) – takes the text from the last cue.
    """
    if cues:
        phrase = clean_text(cues[-1]["text"])
        logging.info(f"Extracted full phrase: {phrase}")
        return phrase
    logging.info("No cues found – returning an empty phrase.")
    return ""

def translate_text(text, target_language="ru"):
    """
    Translates the text using the Google Translate API.
    A valid API key is required.
    """
    if not text.strip():
        logging.info("Empty text for translation – returning an empty string.")
        return ""
    logging.info(f"Sending request to translate text: {text}")
    url = "https://translation.googleapis.com/language/translate/v2"
    params = {
        "q": text,
        "target": target_language,
        "key": GOOGLE_API_KEY
    }
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
    """
    Converts a 'simple' color name to ASS format (&HAABBGGRR).
    Defaults to white if the color is not found in the dictionary.
    """
    colors = {
        "white":   "&H00FFFFFF",
        "black":   "&H00000000",
        "yellow":  "&H0031D1FD",
        "red":     "&H000000FF",
        "green":   "&H0000FF00",
        "blue":    "&H00FF0000",
        "cyan":    "&H00FFFF00",
        "gray":    "&H00AAAAAA",
        "transparent": "&HFF000000",
    }
    return colors.get(color_name.lower(), "&H00FFFFFF")

def seconds_to_ass_time(seconds):
    """
    Converts seconds (float) into an ASS time string (H:MM:SS.cc).
    """
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"

def normalize_word(w: str) -> str:
    """
    Removes all punctuation and converts the word to lowercase.
    """
    return re.sub(r"[^\w]+", "", w.lower())

def find_subsequence_indices(phrase_words, highlite_words):
    """
    Attempts to find a *continuous* subsequence of highlite_words
    within phrase_words (both already normalized). Returns a list of indices
    where words in phrase_words should be highlighted.

    If not found, returns an empty list.
    """
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

def generate_ass_subtitles(cues, phrase, translation, video_width, video_height, highlite_phrase):
    """
    Generates the content of an ASS subtitle file.
    """
    logging.info("Starting ASS subtitle generation.")
    if not cues:
        total_start_sec = 0.0
        total_end_sec = 5.0
    else:
        total_start_sec = cues[0]["start"]
        total_end_sec = cues[-1]["end"]

    start_time_ass = seconds_to_ass_time(total_start_sec)
    end_time_ass   = seconds_to_ass_time(total_end_sec)
    logging.info(f"Subtitle time interval: {start_time_ass} - {end_time_ass}")

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
        f"Style: Base,{PHRASE_FONT},{PHRASE_FONT_SIZE},"
        f"{convert_color(PHRASE_COLOR)},{convert_color(PHRASE_COLOR)},"
        "&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,2,0,"
        f"{PHRASE_ALIGNMENT},10,10,{PHRASE_MARGIN_V},1\n"
    )

    ass += (
        f"Style: Highlight,{PHRASE_FONT},{PHRASE_FONT_SIZE},"
        f"{convert_color(WORD_HIGHLITE_COLOR)},{convert_color('transparent')},"
        "&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,2,0,"
        f"{PHRASE_ALIGNMENT},10,10,{PHRASE_MARGIN_V},1\n"
    )

    ass += (
        f"Style: Translation,{TRANSLATION_FONT},{TRANSLATION_FONT_SIZE},"
        f"{convert_color(TRANSLATION_COLOR)},{convert_color(TRANSLATION_COLOR)},"
        "&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,2,0,"
        f"{TRANSLATION_ALIGNMENT},10,10,{TRANSLATION_MARGIN_V},1\n"
    )

    # New style for the website overlay (playphrase.me)
    ass += (
        f"Style: Website,{WEBSITE_FONT},{WEBSITE_FONT_SIZE},"
        f"{convert_color(WEBSITE_COLOR)},{convert_color(WEBSITE_COLOR)},"
        "&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,2,0,"
        f"{WEBSITE_ALIGNMENT},10,10,{WEBSITE_MARGIN_V},1\n"
    )

    ass += "\n[Events]\n"
    ass += "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n"

    # Base layer
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

    # Highlight layer
    n_cues = len(cues)
    n_words = len(words_original)
    n_min = min(n_cues, n_words)
    for i in range(n_min):
        cue = cues[i]
        w_start = seconds_to_ass_time(cue["start"])
        w_end   = seconds_to_ass_time(cue["end"])
        highlight_line_parts = []
        for j, w in enumerate(words_original):
            if j == i:
                highlight_line_parts.append(f"{{\\alpha&H00&}}{w}{{\\alpha&HFF&}}")
            else:
                highlight_line_parts.append(f"{{\\alpha&HFF&}}{w}")
        highlight_line_text = " ".join(highlight_line_parts)
        ass += f"Dialogue: 1,{w_start},{w_end},Highlight,,0,0,0,,{highlight_line_text}\n"

    # Translation layer
    if translation.strip():
        ass += f"Dialogue: 0,{start_time_ass},{end_time_ass},Translation,,0,0,0,,{{\\q3}}{translation}\n"

    # Website overlay (playphrase.me) on top of everything
    ass += f"Dialogue: 2,{start_time_ass},{end_time_ass},Website,,0,0,0,,{WEBSITE_TEXT}\n"

    logging.info("ASS subtitles generated successfully.")
    return ass

def escape_path_for_ffmpeg(path):
    """
    Escapes the file path for use in the ffmpeg subtitles filter.
    On Windows, converts backslashes to forward slashes and escapes the colon after the drive letter.
    The returned string is enclosed in single quotes.
    """
    if os.name == 'nt':
        # Replace backslashes with forward slashes
        path = path.replace('\\', '/')
        # If the path starts with a drive letter, escape the colon (e.g., "C:/" -> "C\:/")
        if re.match(r'^[A-Za-z]:', path):
            path = path[0] + r'\:' + path[2:]
    # Enclose the path in single quotes
    return f"'{path}'"

def copy_processed_videos(processed_videos):
    """
    Copies all processed videos from temporary directories into a new "tmp" directory
    in the current working directory. Returns a list of paths to the copied files.
    """
    new_tmp_dir = os.path.join(os.getcwd(), "tmp")
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

def process_video(video_path, video_size, highlite_phrase, translate_lang):
    """
    Processes a single video:
      1. Extracts subtitles;
      2. Parses the SRT and creates an ASS file with karaoke and translation;
      3. Scales/crops the video and then hardcodes the subtitles.
    Returns a tuple: (processed_video, temporary_directory, full_phrase)
    """
    logging.info(f"Starting processing video: {video_path}")
    base_name = os.path.splitext(os.path.basename(video_path))[0]
    # Sanitize the name for temporary files
    safe_base = sanitize_filename(base_name)
    temp_dir = tempfile.mkdtemp(prefix="video_process_")
    logging.info(f"Temporary directory created: {temp_dir}")
    srt_path = os.path.join(temp_dir, f"{safe_base}.srt")

    try:
        extract_subtitles(video_path, srt_path)
    except Exception as e:
        logging.error(f"Error extracting subtitles from {video_path}: {e}", exc_info=True)
        shutil.rmtree(temp_dir)
        return None

    try:
        cues = parse_srt(srt_path)
    except Exception as e:
        logging.error(f"Error parsing SRT from {video_path}: {e}", exc_info=True)
        shutil.rmtree(temp_dir)
        return None

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

    try:
        ass_content = generate_ass_subtitles(
            cues=cues,
            phrase=phrase,
            translation=translation,
            video_width=width,
            video_height=height,
            highlite_phrase=highlite_phrase
        )
    except Exception as e:
        logging.error(f"Error generating ASS for {video_path}: {e}", exc_info=True)
        shutil.rmtree(temp_dir)
        return None

    ass_path = os.path.join(temp_dir, f"{safe_base}.ass")
    try:
        with open(ass_path, "w", encoding="utf-8") as f:
            f.write(ass_content)
        logging.info(f"ASS file written: {ass_path}")
    except Exception as e:
        logging.error(f"Error writing ASS file for {video_path}: {e}", exc_info=True)
        shutil.rmtree(temp_dir)
        return None

    # Get the escaped ASS file path for ffmpeg
    escaped_ass_path = escape_path_for_ffmpeg(ass_path)
    ffmpeg_filter = (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},"
        f"subtitles={escaped_ass_path}"
    )
    logging.info(f"Starting ffmpeg processing for video: {video_path}")
    output_video = os.path.join(temp_dir, f"processed_{safe_base}.mp4")
    ffmpeg_cmd = [
        "ffmpeg", "-y", "-loglevel", "error", "-i", video_path,
        "-vf", ffmpeg_filter,
        output_video
    ]
    try:
        subprocess.run(ffmpeg_cmd, check=True)
        logging.info(f"Video processed successfully: {output_video}")
    except subprocess.CalledProcessError as e:
        logging.error(f"Error processing video {video_path} when adding subtitles: {e}", exc_info=True)
        shutil.rmtree(temp_dir)
        return None

    return output_video, temp_dir, phrase

def remove_working_temp_files():
    """
    Deletes concat.sh and concat_list.txt from the working directory if they exist.
    """
    for tmp_file in ["concat.sh", "concat_list.txt"]:
        tmp_file_path = os.path.join(os.getcwd(), tmp_file)
        if os.path.exists(tmp_file_path):
            try:
                os.remove(tmp_file_path)
                logging.info(f"Removed temporary file: {tmp_file_path}")
            except Exception as e:
                logging.error(f"Error removing temporary file {tmp_file_path}: {e}", exc_info=True)

def main():
    # Log the start of the script
    logging.info("Starting final video creation process.")
    
    args = parse_args()

    # Remove any leftover temporary files in the working directory.
    remove_working_temp_files()

    # Override Google API key with the one provided in the command line arguments.
    global GOOGLE_API_KEY
    GOOGLE_API_KEY = args.google_api_key

    video_files = get_video_files(args.video_folder)
    total_videos = len(video_files)
    if not video_files:
        logging.info("No suitable video files found in the specified folder.")
        return

    processed_videos = []
    temp_dirs = []
    phrases = []
    for video in video_files:
        logging.info(f"Processing video: {video}")
        result = process_video(video, args.video_size, args.highlite_phrase, args.translate_lang)
        if result:
            processed_video, temp_dir, phrase = result
            processed_videos.append(processed_video)
            temp_dirs.append(temp_dir)
            phrases.append(phrase)
        else:
            logging.error(f"Processing video {video} ended with an error.")

    # Determine the output directory: if --output-dir is given use it;
    # otherwise, default to a "result" subdirectory inside the source video folder.
    if args.output_dir:
        output_dir = args.output_dir
    else:
        output_dir = os.path.join(args.video_folder, "result")
    os.makedirs(output_dir, exist_ok=True)
    
    # Determine final filename from the first non-empty phrase (or "output" if none)
    if phrases:
        chosen_phrase = next((p for p in phrases if p.strip()), "output")
    else:
        chosen_phrase = "output"
    base_filename = create_filename_from_phrase(chosen_phrase)
    final_output = os.path.join(output_dir, base_filename + ".mp4")

    if processed_videos:
        # If the --create_tmp flag is specified, copy videos into the tmp folder and create files there.
        if args.create_tmp:
            copied_videos = copy_processed_videos(processed_videos)
            tmp_dir = os.path.join(os.getcwd(), "tmp")
            # Create a concatenation list file with paths relative to tmp (only the file names)
            concat_list_path = os.path.join(tmp_dir, "concat_list.txt")
            try:
                with open(concat_list_path, "w", encoding="utf-8") as f:
                    for video in copied_videos:
                        f.write(f"file '{os.path.basename(video)}'\n")
                logging.info(f"Concatenation list file created in tmp: {concat_list_path}")
            except Exception as e:
                logging.error(f"Error creating concatenation list file: {e}", exc_info=True)
                concat_list_path = None

            # Create concat.sh in the tmp folder
            old_concat_command = (
                f"ffmpeg -y -loglevel error -f concat -safe 0 -i {os.path.basename(concat_list_path)} "
                f"-c:v libx264 -preset medium -crf 23 -r 30 -c:a aac -b:a 192k {base_filename}.mp4\n"
            )
            concat_sh_path = os.path.join(tmp_dir, "concat.sh")
            try:
                with open(concat_sh_path, "w", encoding="utf-8") as f:
                    f.write(old_concat_command)
                logging.info(f"concat.sh file created: {concat_sh_path}")
            except Exception as e:
                logging.error(f"Error writing concat.sh file: {e}", exc_info=True)
        else:
            # If the --create_tmp flag is not specified, work directly in the working directory.
            copied_videos = processed_videos
            concat_list_path = os.path.join(os.getcwd(), "concat_list.txt")
            try:
                with open(concat_list_path, "w", encoding="utf-8") as f:
                    for video in copied_videos:
                        f.write(f"file '{video}'\n")
                logging.info(f"Concatenation list file created: {concat_list_path}")
            except Exception as e:
                logging.error(f"Error creating concatenation list file: {e}", exc_info=True)
                concat_list_path = None

            # Create concat.sh in the working directory
            old_concat_command = (
                f"ffmpeg -y -loglevel error -f concat -safe 0 -i {os.path.basename(concat_list_path)} "
                f"-c:v libx264 -preset medium -crf 23 -r 30 -c:a aac -b:a 192k {base_filename}.mp4\n"
            )
            concat_sh_path = os.path.join(os.getcwd(), "concat.sh")
            try:
                with open(concat_sh_path, "w", encoding="utf-8") as f:
                    f.write(old_concat_command)
                logging.info(f"concat.sh file created: {concat_sh_path}")
            except Exception as e:
                logging.error(f"Error writing concat.sh file: {e}", exc_info=True)

        # New concatenation method using -filter_complex with the concat filter.
        # To eliminate differences in SAR for each input video, apply setsar=1.
        new_cmd = ["ffmpeg", "-y", "-loglevel", "error"]
        for video in copied_videos:
            new_cmd.extend(["-i", video])
        num_inputs = len(copied_videos)
        filter_complex_parts = []
        # For each input, apply setsar=1 and label the result as [v{i}]
        for i in range(num_inputs):
            filter_complex_parts.append(f"[{i}:v:0]setsar=1[v{i}];")
        # Build inputs for concatenation: for each input [v{i}] and original audio stream [{i}:a:0]
        concat_inputs = ""
        for i in range(num_inputs):
            concat_inputs += f"[v{i}][{i}:a:0]"
        filter_complex_parts.append(f"{concat_inputs}concat=n={num_inputs}:v=1:a=1 [v][a]")
        filter_complex = " ".join(filter_complex_parts)
        new_cmd.extend(["-filter_complex", filter_complex, "-map", "[v]", "-map", "[a]"])
        new_cmd.append(final_output)
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

    # Clean up temporary directories used during processing
    for d in temp_dirs:
        try:
            shutil.rmtree(d)
            logging.info(f"Temporary directory removed: {d}")
        except Exception as e:
            logging.error(f"Error removing temporary directory {d}: {e}", exc_info=True)

    # If files were created in the working directory (i.e. --create_tmp not specified), remove them.
    if not args.create_tmp:
        remove_working_temp_files()

    logging.info("\nExecution log:")
    logging.info(f"Total videos: {total_videos}")
    logging.info(f"Processed videos: {len(processed_videos)}")
    logging.info(f"Broken videos: {total_videos - len(processed_videos)}")

if __name__ == "__main__":
    main()
