import os
import subprocess
import sys
import re
import requests
import shutil
import logging
import argparse
import itertools
from PIL import Image, ImageDraw, ImageFont

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Global constants
CUSTOM_FONTS_DIR = os.path.join(os.path.dirname(os.path.realpath(__file__)), "fonts")
TTF_PATH = None  # Will be set to the resolved TTF file path

# Default font settings
PHRASE_FONT = "Arial"
TRANSLATION_FONT = "Arial"
WEBSITE_FONT = "Arial"
PHRASE_FONT_SIZE = 36
TRANSLATION_FONT_SIZE = 28
WEBSITE_FONT_SIZE = 20
PHRASE_MARGIN_V = 10
TRANSLATION_MARGIN_V = 50
WEBSITE_MARGIN_V = 70
PHRASE_COLOR = "white"
TRANSLATION_COLOR = "yellow"
WEBSITE_COLOR = "cyan"
WORD_HIGHLITE_COLOR = "red"
PHRASE_ALIGNMENT = 2  # Center
TRANSLATION_ALIGNMENT = 2
WEBSITE_ALIGNMENT = 2

# Helper function to install dependencies
def install_dependencies():
    req_file = os.path.join(os.path.dirname(__file__), "requirements.txt")
    if os.path.exists(req_file):
        print("Installing dependencies from requirements.txt...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", req_file])
        except subprocess.CalledProcessError as e:
            print(f"Error installing dependencies: {e}")
            sys.exit(1)

# Placeholder for getting internal font info (simplified)
def get_internal_font_info(ttf_path):
    # This would typically use fontTools to extract internal name and unitsPerEm
    # Here, we'll return None to simplify
    return None, None

# Resolve font and return name, path, and units
def resolve_font(font_arg):
    ttf_path = None
    if os.path.exists(font_arg):
        abs_path = os.path.abspath(font_arg)
        logging.info(f"Resolved font path from given value: {abs_path}")
        ttf_path = abs_path
    else:
        fonts_folder = CUSTOM_FONTS_DIR
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
    internal_name, units = get_internal_font_info(ttf_path)
    if internal_name:
        logging.info(f"Extracted internal font name: {internal_name} with unitsPerEm: {units}")
        font_name = internal_name
    else:
        font_name = os.path.splitext(os.path.basename(ttf_path))[0]
        logging.warning(f"Could not extract internal font name. Using filename: {font_name}")
    return font_name, ttf_path, units

# Convert color to ASS format
def convert_color(color):
    if color == "transparent":
        return "&HFF000000"
    color = re.sub(r'[^0-9a-fA-F]', '', color)
    if len(color) == 6:
        r, g, b = color[0:2], color[2:4], color[4:6]
        return f"&H00{b}{g}{r}"
    return "&H000000FF"  # Default blue

# Measure the number of lines text would take with given font size and width
def measure_lines(text, font_path, font_size, max_width):
    try:
        font = ImageFont.truetype(font_path, font_size)
        draw = ImageDraw.Draw(Image.new('RGB', (1, 1)))
        words = text.split()
        lines = []
        current_line = []
        current_width = 0
        for word in words:
            word_width = draw.textlength(word + " ", font=font)
            if current_width + word_width > max_width:
                if current_line:
                    lines.append(" ".join(current_line))
                    current_line = [word]
                    current_width = draw.textlength(word + " ", font=font)
                else:
                    lines.append(word)
                    current_width = 0
            else:
                current_line.append(word)
                current_width += word_width
        if current_line:
            lines.append(" ".join(current_line))
        return len(lines)
    except Exception as e:
        logging.error(f"Error measuring text lines: {e}")
        return -1  # Indicate error

# Generate ASS subtitles with font size adjustment
def generate_ass_subtitles(cues, phrase, translation, video_width, video_height, highlite_phrase):
    scale = video_width / 640.0
    scaled_phrase_font_size = int(round(PHRASE_FONT_SIZE * scale))
    scaled_translation_font_size = int(round(TRANSLATION_FONT_SIZE * scale))
    scaled_website_font_size = int(round(WEBSITE_FONT_SIZE * scale))
    scaled_phrase_margin_v = int(round(PHRASE_MARGIN_V * scale))
    scaled_translation_margin_v = int(round(TRANSLATION_MARGIN_V * scale))
    scaled_website_margin_v = int(round(WEBSITE_MARGIN_V * scale))
    scaled_margin_lr = int(round(10 * scale))
    scaled_outline = int(round(2 * scale))

    # Adjust font sizes to fit within two lines
    W = video_width - 2 * scaled_margin_lr
    if 'TTF_PATH' in globals() and os.path.exists(TTF_PATH):
        lines_phrase = measure_lines(phrase, TTF_PATH, scaled_phrase_font_size, W)
        lines_trans = measure_lines(translation, TTF_PATH, scaled_translation_font_size, W)
        if lines_phrase > 2 or lines_trans > 2:
            k = 1.0
            step = 0.05
            while k > 0.1:
                test_S_phrase = int(round(scaled_phrase_font_size * k))
                test_S_trans = int(round(scaled_translation_font_size * k))
                lines_phrase = measure_lines(phrase, TTF_PATH, test_S_phrase, W)
                lines_trans = measure_lines(translation, TTF_PATH, test_S_trans, W)
                if lines_phrase <= 2 and lines_trans <= 2:
                    break
                k -= step
            if k <= 0.1:
                k = 0.1  # Minimum scaling factor
            final_phrase_font_size = int(round(scaled_phrase_font_size * k))
            final_translation_font_size = int(round(scaled_translation_font_size * k))
        else:
            final_phrase_font_size = scaled_phrase_font_size
            final_translation_font_size = scaled_translation_font_size
    else:
        # Fallback to approximation
        C = 0.5  # Average character width factor
        k_phrase = 1
        k_trans = 1
        if phrase:
            N_phrase = len(phrase)
            max_S_phrase = (2.5 * W) / (N_phrase * C)
            k_phrase = min(1, max_S_phrase / scaled_phrase_font_size)
        if translation:
            N_trans = len(translation)
            max_S_trans = (2.5 * W) / (N_trans * C)
            k_trans = min(1, max_S_trans / scaled_translation_font_size)
        k = min(k_phrase, k_trans)
        final_phrase_font_size = int(round(scaled_phrase_font_size * k))
        final_translation_font_size = int(round(scaled_translation_font_size * k))

    # Ensure minimum font size
    final_phrase_font_size = max(10, final_phrase_font_size)
    final_translation_font_size = max(10, final_translation_font_size)

    # ASS header
    ass = f"""[Script Info]
Title: Subtitles
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: Yes
PlayResX: {video_width}
PlayResY: {video_height}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Base,{PHRASE_FONT},{final_phrase_font_size},{convert_color(PHRASE_COLOR)},{convert_color(PHRASE_COLOR)},&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,{scaled_outline},0,{PHRASE_ALIGNMENT},{scaled_margin_lr},{scaled_margin_lr},{scaled_phrase_margin_v},1
Style: Highlight,{PHRASE_FONT},{final_phrase_font_size},{convert_color(WORD_HIGHLITE_COLOR)},{convert_color('transparent')},&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,{scaled_outline},0,{PHRASE_ALIGNMENT},{scaled_margin_lr},{scaled_margin_lr},{scaled_phrase_margin_v},1
Style: Translation,{TRANSLATION_FONT},{final_translation_font_size},{convert_color(TRANSLATION_COLOR)},{convert_color(TRANSLATION_COLOR)},&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,{scaled_outline},0,{TRANSLATION_ALIGNMENT},{scaled_margin_lr},{scaled_margin_lr},{scaled_translation_margin_v},1
Style: Website,{WEBSITE_FONT},{scaled_website_font_size},{convert_color(WEBSITE_COLOR)},{convert_color(WEBSITE_COLOR)},&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,{scaled_outline},0,{WEBSITE_ALIGNMENT},{scaled_margin_lr},{scaled_margin_lr},{scaled_website_margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    # Add dialogue (simplified example)
    for cue in cues:
        start = cue['start']
        end = cue['end']
        text = cue['text']
        ass += f"Dialogue: 0,{start},{end},Base,,0,0,0,,{text}\n"
    ass += f"Dialogue: 0,0:00:00.00,0:00:10.00,Base,,0,0,0,,{phrase}\n"
    ass += f"Dialogue: 0,0:00:00.00,0:00:10.00,Translation,,0,0,0,,{translation}\n"
    ass += f"Dialogue: 0,0:00:00.00,0:00:10.00,Website,,0,0,0,,Example.com\n"

    return ass

# Parse command-line arguments
def parse_args():
    parser = argparse.ArgumentParser(description="Generate video subtitles.")
    parser.add_argument("--font", help="Font file or name to use for subtitles.")
    parser.add_argument("--font-size", type=int, help="Custom base font size for phrases.")
    return parser.parse_args()

# Main execution
def main():
    install_dependencies()
    args = parse_args()

    global PHRASE_FONT, TRANSLATION_FONT, WEBSITE_FONT, PHRASE_FONT_SIZE, TTF_PATH

    if args.font:
        resolved_font_name, resolved_ttf_path, resolved_units = resolve_font(args.font)
        if resolved_ttf_path:
            PHRASE_FONT = resolved_font_name
            TRANSLATION_FONT = resolved_font_name
            WEBSITE_FONT = resolved_font_name
            CUSTOM_FONTS_DIR = os.path.dirname(resolved_ttf_path)
            globals()['TTF_PATH'] = resolved_ttf_path
            if args.font_size:
                PHRASE_FONT_SIZE = args.font_size
            elif resolved_units and resolved_units != 2048:
                scale_factor = 2048 / resolved_units
                PHRASE_FONT_SIZE = int(round(PHRASE_FONT_SIZE * scale_factor))
                logging.info(f"Adjusted phrase font size for custom font with unitsPerEm {resolved_units}: {PHRASE_FONT_SIZE}")
        else:
            logging.error("Font resolution failed; using default font settings.")

    # Example usage
    cues = [{'start': '0:00:01.00', 'end': '0:00:02.00', 'text': 'Hello'}]
    phrase = "This is a very long phrase that might span multiple lines if not adjusted properly"
    translation = "This is an equally long translation that needs to fit within two lines as well"
    video_width = 1280
    video_height = 720
    highlite_phrase = False

    ass_content = generate_ass_subtitles(cues, phrase, translation, video_width, video_height, highlite_phrase)
    with open("subtitles.ass", "w", encoding='utf-8') as f:
        f.write(ass_content)
    logging.info("Subtitles generated at 'subtitles.ass'")

if __name__ == "__main__":
    main()