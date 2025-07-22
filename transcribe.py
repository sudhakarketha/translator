import sys
import speech_recognition as sr

if len(sys.argv) != 2:
    print("Usage: python transcribe.py <audiofile>")
    sys.exit(1)

audio_file = sys.argv[1]
recognizer = sr.Recognizer()

with sr.AudioFile(audio_file) as source:
    audio = recognizer.record(source)

try:
    text = recognizer.recognize_google(audio)
    print("Transcribed Text:")
    print(text)
except sr.UnknownValueError:
    print("Could not understand audio.")
except sr.RequestError as e:
    print(f"Could not request results; {e}") 