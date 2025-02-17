# playphraseme-karaoke-mixer

**A Video Processing Tool for playphrase.me Users**

**playphraseme-karaoke-mixer** is a powerful tool for playphrase.me enthusiasts who want to create engaging video compilations with a unique twist. It automates several key tasks to enhance your video clips by:

- **Karaoke-Style Subtitles:**  
  Extracts subtitles from your videos and generates dynamic, karaoke-like effects. As the video plays, the subtitles are displayed with highlighted words that synchronize perfectly with the audio.

- **Phrase Highlighting:**  
  Allows you to specify a phrase (e.g., "happy birthday") to be highlighted whenever it appears continuously in the subtitles. This makes your chosen phrase stand out and adds a fun element to your video.

- **Optional Translation:**  
  Uses the Google Translate API to translate your subtitle text into another language. This feature is ideal for reaching a broader, international audience or for language learning purposes.

- **Video Processing & Concatenation:**  
  Processes each video individually to add subtitles and effects, then automatically concatenates all processed clips into one seamless final video. There’s also an option to use a dedicated temporary directory (`tmp`) to manage intermediate files and keep your workspace organized.

- **Managing Execution Order:**  
  The script processes video files in alphabetical order. To control the order in which your clips appear in the final video, simply rename your files accordingly (for example, `1.mp4`, `2.mp4`, `3.mp4`, etc.). This simple naming strategy gives you full control over the execution sequence.

Overall, **playphraseme-karaoke-mixer** transforms your playphrase.me clips into a polished, dynamic video with enhanced subtitles, optional translations, and customizable sequencing.

**Important Note:**  
Before using this script, **videos must be downloaded specifically from playphrase.me** by clicking the **"Download Video"** button in the player. This script is only compatible with videos from playphrase.me because they contain the required subtitles in the correct format.

---

## Example

https://private-user-images.githubusercontent.com/612926/413301425-41032466-9742-41ba-af04-c44222eeb523.mp4

---

### Here’s how it works:

1️⃣ Search for a phrase on **Playphrase.me**  
2️⃣ Download the video clips containing that phrase into a folder  
3️⃣ Run the script with your preferred settings  
4️⃣ Get a ready-to-use video, perfectly formatted for social media, educational content, or personal use  

---

## Getting Started

### 1. Downloading the Repository

There are two simple ways to get the repository on your local machine:

1. **Clone the Repository (for users comfortable with Git):**
   ```bash
   git clone https://github.com/potapenko/playphraseme-karaoke-mixer.git
   cd playphraseme-karaoke-mixer
   ```
   *If you don't have Git installed, you can download it from [git-scm.com](https://git-scm.com/) and follow the installation instructions for your operating system.*

2. **Download the ZIP File (for non-programmers):**  
   Simply go to the [GitHub repository page](https://github.com/potapenko/playphraseme-karaoke-mixer), click on the green "Code" button, and select "Download ZIP". Then, extract the ZIP file into your desired folder.

---

### 2. Installing Python and ffmpeg

#### **For Windows**

- **Python:**
  1. Go to [python.org/downloads](https://www.python.org/downloads/) and download the latest installer.
  2. Run the installer. **Important:** Check the “Add Python to PATH” option before clicking "Install Now".
  3. Verify installation by opening Command Prompt and running:
     ```bash
     python --version
     ```

- **ffmpeg:**
  1. Visit the [ffmpeg download page](https://ffmpeg.org/download.html) and follow the Windows instructions (for example, download a static build from [gyan.dev](https://www.gyan.dev/ffmpeg/builds/)).
  2. Extract the downloaded folder.
  3. Add the `bin` directory (inside the extracted folder) to your system PATH:
     - Open **Control Panel → System and Security → System → Advanced system settings**.
     - Click **Environment Variables** and edit the `Path` variable under **System variables**.
     - Add the full path to the `bin` folder.
  4. Verify by running:
     ```bash
     ffmpeg -version
     ```

#### **For macOS**

- **Python:**
  1. Although macOS comes with Python pre-installed, it is recommended to install the latest version.
  2. Install [Homebrew](https://brew.sh/) if you haven’t already:
     ```bash
     /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
     ```
  3. Install Python via Homebrew:
     ```bash
     brew install python
     ```
  4. Verify by running:
     ```bash
     python3 --version
     ```

- **ffmpeg:**
  1. Install ffmpeg using Homebrew:
     ```bash
     brew install ffmpeg
     ```
  2. Verify by running:
     ```bash
     ffmpeg -version
     ```

---

### 3. Installing the Necessary pip Libraries

This script uses standard Python libraries and one external library: **requests**. You can install the required library using:

```bash
pip install requests
```

If you use Python 3 and have both Python 2 and 3 installed, you might need:

```bash
pip3 install requests
```

Alternatively, if you use the provided [requirements.txt](./requirements.txt) file, the script can automatically install dependencies on startup.

---

### 4. Obtaining a Google Translate API Key

The script uses Google’s Cloud Translation API for translation. Follow these steps to get your API key:

1. **Sign Up for Google Cloud:**
   - Go to [Google Cloud](https://cloud.google.com/) and sign up for a free trial if you’re a new user.
   - Follow the prompts to set up your account and billing (Google offers free credits for new users).

2. **Create a New Project:**
   - In the Google Cloud Console, click on the project dropdown and select “New Project.”
   - Give your project a name and click “Create.”

3. **Enable the Cloud Translation API:**
   - With your project selected, navigate to **APIs & Services → Library**.
   - Search for “Cloud Translation API” and enable it.

4. **Create API Credentials:**
   - Navigate to **APIs & Services → Credentials**.
   - Click **Create Credentials** and select **API key**.
   - Your API key will be displayed. **Copy this key** for later use.

---

### 5. Example Script Executions

Assume the script is saved as `process_videos.py`.

#### **Example 1: Basic Processing (No Translation, No tmp Folder)**
```bash
python process_videos.py --video_folder "C:\Videos" --video_size "640x480" --highlite_phrase "hello world"
```
**Description:**  
Processes all videos in the folder `C:\Videos` with a resolution of 640×480, highlighting the phrase “hello world” in the subtitles.

#### **Example 2: With Translation to Russian and a Google API Key**
```bash
python process_videos.py --video_folder "/Users/yourname/Videos" --video_size "1280x720" --highlite_phrase "good morning" --translate_lang "ru" --google_api_key "YOUR_API_KEY"
```
**Description:**  
Processes videos in `/Users/yourname/Videos` at 1280×720 resolution, highlighting “good morning” and translating the subtitle text to Russian using your Google API key.

#### **Example 3: Using Temporary Files (tmp Directory)**
```bash
python process_videos.py --video_folder "./my_videos" --video_size "640x480" --highlite_phrase "happy birthday" --create_tmp
```
**Description:**  
Processes videos in the `./my_videos` folder and creates a `tmp` directory containing the processed videos along with temporary concatenation files (`concat.sh` and `concat_list.txt`). The paths in `concat_list.txt` are relative to the `tmp` directory.

## Video Size Examples

You can specify the final video resolution using the `--video_size` parameter (format: `WIDTHxHEIGHT`). For example:

- **Facebook Feed:** `640x480`
- **Facebook Reels:** `1080x1920`
- **Instagram:** `1080x1080`
- **TikTok:** `1080x1920`

---

## Command-line Arguments

- `--video_folder` (optional):  
  Path to the folder containing videos (default: current folder).

- `--video_size` (optional):  
  Final video resolution in the format `WIDTHxHEIGHT` (default: `640x480`).

- `--highlite_phrase` (optional):  
  Phrase to highlight in the subtitles (exact continuous match, case and punctuation insensitive). If not provided, the script may compute a common phrase from the video subtitles.

- `--translate_lang` (optional):  
  Target language code for subtitle translation (e.g., `es` for Spanish). If omitted, no translation will occur.

- `--google_api_key` (optional):  
  Your Google Translate API key. **Required only if translation is desired.**

- `--create_tmp` (optional flag):  
  Flag to create a temporary directory for intermediate processed videos.

- `--output-dir` (optional):  
  Directory where the final output video will be saved (default: `result` subdirectory inside the video folder).

---

## Contributing

Contributions are welcome! Feel free to open an issue or submit a pull request if you have improvements or bug fixes.

---

## License

This project is licensed under the **MIT License**.