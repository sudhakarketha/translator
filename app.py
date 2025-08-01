import streamlit as st
import speech_recognition as sr
from deep_translator import GoogleTranslator
import tempfile
import math
import os
import json
import urllib.parse
from streamlit_webrtc import webrtc_streamer, AudioProcessorBase, WebRtcMode
import av
import soundfile as sf
import numpy as np

# Remove audiorecorder and mic recording imports and logic
import io
from gtts import gTTS

HISTORY_FILE = "history.json"

# Handle delete query param at the top
query_params = st.query_params
if "delete_idx" in query_params:
    idx = int(query_params["delete_idx"][0])
    if 'history' in st.session_state and 0 <= idx < len(st.session_state['history']):
        st.session_state['history'].pop(idx)
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(st.session_state['history'], f, ensure_ascii=False, indent=2)
    st.query_params.clear()
    st.rerun()

st.set_page_config(page_title="Audio Translator", page_icon="🎤", layout="centered")

# Load history from file
if 'history' not in st.session_state:
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                st.session_state['history'] = json.load(f)
        except Exception:
            st.session_state['history'] = []
    else:
        st.session_state['history'] = []

# Sidebar with instructions and history
st.sidebar.title("How to Use")
st.sidebar.markdown("""
1. Upload an audio file or record from your microphone (using streamlit-webrtc).
2. Select the language for translation.
3. Wait for transcription and translation.
4. Download the results if needed.
""")

# Clear history button
if st.sidebar.button("Clear History"):
    st.session_state['history'] = []
    if os.path.exists(HISTORY_FILE):
        os.remove(HISTORY_FILE)
    st.rerun()

# Custom CSS for delete icon
st.markdown('''
    <style>
    .history-row {
        display: flex;
        align-items: flex-start;
        margin-bottom: 0.2em;
        gap: 0.2em;
    }
    .history-expander {
        flex: 1;
        margin-right: 0.2em;
    }
    .delete-btn-container {
        opacity: 0;
        transition: opacity 0.2s;
        display: flex;
        align-items: center;
        height: 24px;
    }
    .history-row:hover .delete-btn-container {
        opacity: 1;
    }
    /* Remove all border, background, and outline from the button */
    .stButton>button.delete-btn {
        background: none !important;
        border: none !important;
        outline: none !important;
        box-shadow: none !important;
        color: #d9534f !important;
        font-size: 1.2em !important;
        cursor: pointer !important;
        min-width: 0 !important;
        padding: 0 !important;
        margin: 0 !important;
    }
    .stButton>button.delete-btn:focus {
        outline: none !important;
        box-shadow: none !important;
    }
    .stButton>button.delete-btn:hover {
        color: #b52a1d !important;
    }
    </style>
''', unsafe_allow_html=True)

# Show history in sidebar with st.button delete icon, visible only on hover
if st.session_state['history']:
    st.sidebar.markdown("---")
    st.sidebar.subheader("History (persistent)")
    for i, item in enumerate(reversed(st.session_state['history'])):
        idx = len(st.session_state['history']) - 1 - i
        row = st.sidebar.container()
        row.markdown(f'<div class="history-row">', unsafe_allow_html=True)
        cols = row.columns([10, 1], gap="small")
        with cols[0]:
            st.markdown(f'<div class="history-expander">', unsafe_allow_html=True)
            with st.expander(f"{item['filename']} → {item['language']}" ):
                st.markdown("**Transcription:**")
                st.write(item['transcription'])
                st.download_button("Download Transcription", item['transcription'], file_name=f"transcription_{i+1}.txt", key=f"dlt_{i}")
                st.markdown(f"**Translation ({item['language']}):**")
                st.write(item['translation'])
                st.download_button(f"Download Translation ({item['language']})", item['translation'], file_name=f"translation_{item['language']}_{i+1}.txt", key=f"dltl_{i}")
            st.markdown('</div>', unsafe_allow_html=True)
        with cols[1]:
            st.markdown('<div class="delete-btn-container">', unsafe_allow_html=True)
            if st.button("🗑️", key=f"delete_{idx}", help="Delete this entry", type="secondary"):
                st.session_state['history'].pop(idx)
                with open(HISTORY_FILE, "w", encoding="utf-8") as f:
                    json.dump(st.session_state['history'], f, ensure_ascii=False, indent=2)
                st.rerun()
            st.markdown('</div>', unsafe_allow_html=True)
        row.markdown('</div>', unsafe_allow_html=True)

st.title("🎤 Audio/Video Translator")
st.markdown("""
Upload an audio file, or record from your microphone (using streamlit-webrtc), transcribe it to text, and translate it to your chosen language. Supports long files and multiple languages, including Telugu!

**Note:** Microphone recording uses streamlit-webrtc. You can use the file upload or mic recording feature.
""")

input_mode = st.radio("Select input method:", ("Upload file", "Record from mic", "Type text"))

languages = {
    'French': 'fr',
    'Spanish': 'es',
    'German': 'de',
    'Chinese (Simplified)': 'zh-cn',
    'Hindi': 'hi',
    'Arabic': 'ar',
    'Russian': 'ru',
    'Japanese': 'ja',
    'Korean': 'ko',
    'Italian': 'it',
    'Portuguese': 'pt',
    'English': 'en',
    'Telugu': 'te',
}
target_lang = st.selectbox("Translate to:", list(languages.keys()), index=0)

uploaded_file = None
recorded_audio = None
tmp_file_path = None

def extract_audio_from_video(video_path, audio_path):
    try:
        from moviepy.editor import VideoFileClip
        clip = VideoFileClip(video_path)
        clip.audio.write_audiofile(audio_path, codec='pcm_s16le')
        clip.close()
        return True
    except ImportError:
        st.error("moviepy is required for video file support. Please install it with 'pip install moviepy'.")
        return False
    except Exception as e:
        st.error(f"moviepy or one of its dependencies failed: {e}")
        return False

def get_uploaded_audio_path(uploaded_file):
    file_ext = os.path.splitext(uploaded_file.name)[1].lower()
    is_video = file_ext in [".mp4", ".avi", ".mov"]
    with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp_file:
        tmp_file.write(uploaded_file.read())
        tmp_file_path = tmp_file.name
    if is_video:
        audio_temp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        audio_temp.close()
        if not extract_audio_from_video(tmp_file_path, audio_temp.name):
            return None, None
        return audio_temp.name, tmp_file_path
    else:
        return tmp_file_path, tmp_file_path

if input_mode == "Upload file":
    uploaded_file = st.file_uploader("Choose an audio or video file", type=["wav", "flac", "mp3", "m4a", "mp4", "avi", "mov"])
elif input_mode == "Record from mic":
    st.warning("Microphone recording is not supported in this deployment. Please record audio on your device and upload the file.")
elif input_mode == "Type text":
    typed_text = st.text_area("Enter text to convert to speech:")
    if st.button("🔊 Listen to Typed Text", key="tts_typed_text"):
        if typed_text.strip():
            tts = gTTS(typed_text)
            tts_fp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
            tts.save(tts_fp.name)
            st.audio(tts_fp.name, format="audio/mp3")
        else:
            st.warning("Please enter some text to convert to speech.")

# When processing, use st.session_state['recorded_audio_path'] as the audio file for transcription if present
if uploaded_file is not None or 'recorded_audio_path' in st.session_state:
    audio_path = None
    cleanup_files = []
    if uploaded_file is not None:
        audio_path, tmp_file_path = get_uploaded_audio_path(uploaded_file)
        if audio_path is None:
            st.stop()
        cleanup_files.append(tmp_file_path)
        if audio_path != tmp_file_path:
            cleanup_files.append(audio_path)
    elif 'recorded_audio_path' in st.session_state:
        audio_path = st.session_state['recorded_audio_path']
        cleanup_files.append(audio_path)

    if audio_path is not None:
        recognizer = sr.Recognizer()
        with sr.AudioFile(audio_path) as source:
            duration = source.DURATION
            chunk_length = 60  # seconds
            num_chunks = math.ceil(duration / chunk_length)
            texts = []
            progress_bar = st.progress(0, text="Transcribing audio...")
            for i in range(num_chunks):
                audio = recognizer.record(source, duration=chunk_length)
                try:
                    chunk_text = recognizer.recognize_google(audio)
                except sr.UnknownValueError:
                    chunk_text = "[Unrecognized audio]"
                except sr.RequestError as e:
                    chunk_text = f"[Request error: {e}]"
                texts.append(chunk_text)
                progress_bar.progress((i+1)/num_chunks, text=f"Transcribing chunk {i+1} of {num_chunks}...")
            progress_bar.empty()
            text = ' '.join(texts)

        col1, col2 = st.columns(2)
        with col1:
            with st.expander("Transcription", expanded=True):
                st.write(text)
                st.download_button("Download Transcription", text, file_name="transcription.txt")
                if st.button("🔊 Listen to Transcription", key="tts_transcription"):
                    tts = gTTS(text)
                    tts_fp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
                    tts.save(tts_fp.name)
                    st.audio(tts_fp.name, format="audio/mp3")
        with col2:
            if target_lang.lower() == 'en' or target_lang.lower() == 'english':
                st.info("Translation is disabled because the target language is the same as the transcription language (English). Please select a different language to enable translation.")
            else:
                st.info(f"Translating to {target_lang}...")
                try:
                    translation = GoogleTranslator(source='auto', target=target_lang).translate(text)
                except Exception as e:
                    st.error(f"An error occurred during translation: {e}")
                    translation = ""
                st.write(translation)
                st.download_button(f"Download Translation ({target_lang})", translation, file_name=f"translation_{target_lang}.txt")
                if st.button("🔊 Listen to Translation", key="tts_translation"):
                    tts = gTTS(translation, lang=target_lang)
                    tts_fp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
                    tts.save(tts_fp.name)
                    st.audio(tts_fp.name, format="audio/mp3")
                # Add to history and save to file
                st.session_state['history'].append({
                    'filename': uploaded_file.name if uploaded_file else 'mic_recording.wav',
                    'language': target_lang,
                    'transcription': text,
                    'translation': translation
                })
                with open(HISTORY_FILE, "w", encoding="utf-8") as f:
                    json.dump(st.session_state['history'], f, ensure_ascii=False, indent=2)

        # Clean up temp files
        for f in cleanup_files:
            try:
                os.remove(f)
            except Exception:
                pass 