# server.py  (UPDATED - patched with missing logic)
import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
from starlette.background import BackgroundTask

import re
import json
import shutil
import random
import requests
import tempfile
import subprocess
import collections
import urllib.parse

import torch
import difflib
import parselmouth  # energy/intensity analysis

from io import BytesIO
from gtts import gTTS
from pydub import AudioSegment
from typing import List, Optional
from difflib import SequenceMatcher
from textgrid import TextGrid

from fastapi import FastAPI, UploadFile, Form, HTTPException, Request
from transformers import AutoTokenizer, T5ForConditionalGeneration
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware

# ========== CONFIG ==========
MFA_DICTIONARY = os.environ.get("MFA_DICTIONARY", "english_mfa")
MFA_ACOUSTIC = os.environ.get("MFA_ACOUSTIC", "english_mfa")
PHONEME_CACHE_DIR = "phoneme_cache"
# Define your settings as constants for easy management.
OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_MODEL = "gemma3:1b"
os.makedirs(PHONEME_CACHE_DIR, exist_ok=True)
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
LAST_SCORE_PATH = "last_score.json"

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
)

# --- G2P Model ---
G2P_TOKENIZER_ID = "google/byt5-small"
G2P_MODEL_ID = "charsiu/g2p_multilingual_byT5_tiny_16_layers_100"

g2p_tokenizer = AutoTokenizer.from_pretrained(G2P_TOKENIZER_ID)
g2p_model = T5ForConditionalGeneration.from_pretrained(G2P_MODEL_ID).to(DEVICE)
print("G2P model loaded ✅ (on device:", DEVICE, ")")

LANG_MAP = {
    "en": "<eng-us>:",
    "es": "<spa-es>:",
    "fr": "<fre-fr>:",
    "de": "<ger-de>:",
    "it": "<ita-it>:",
    "zh": "<cmn-cn>:",
}

COACHING_TIPS = {
    "ɫ": "Try pulling your tongue back a little, like the L in *call*.",
    "θ": "Place your tongue between your teeth, like in *think*.",
    "ð": "Same tongue position as 'th' in *this*, but vibrate your voice.",
    "ɹ": "Curl your tongue slightly back, like in *red*.",
    "r": "Try to avoid rolling the R; relax your tongue.",
    "ʃ": "Make a soft 'sh' sound as in *sheep*.",
    "ʒ": "A softer 'zh' sound, like in *measure*.",
    "ʧ": "A hard 'ch' sound, like in *church*.",
    "ʤ": "The 'j' sound in *judge*.",
    "ŋ": "The 'ng' in *sing* — don't release the 'g'.",
    # --- New Tips ---
    "i": "Make a high, front sound; corners of the mouth should be slightly spread, like in *see*.",
    "ɪ": "A slightly shorter, more relaxed 'i', as in *sit*.",
    "u": "Round your lips tightly and push them forward, like in *blue*.",
    "ʊ": "A shorter, more relaxed 'u', with slightly less lip rounding, as in *put*.",
    "æ": "Drop your jaw wide and flatten your tongue, as in *cat*.",
    "aɪ": "Start with an 'ah' sound, then move your mouth to an 'ee' sound, as in *my*.",
    "v": "Touch your upper teeth lightly to your bottom lip and keep the air flowing, like in *van*.",
    "w": "Round your lips tightly, like you're going to whistle, as in *we*.",
    "z": "Keep your teeth together and vibrate your voice, like a buzzing bee, as in *zoo*.",
}

PHONEME_DESCRIPTIONS = {
    "ɫ": "dark L — velarized 'L', tongue pulled back; common at the end of words like 'full'.",
    "l": "clear L — alveolar lateral approximant, tip of tongue touches alveolar ridge ('leaf').",
    "ə": "schwa — unstressed mid-central vowel (a 'weak' vowel), like the 'a' in 'sofa'.",
    "ɛ": "open-mid front unrounded vowel, as in 'bed'.",
    "oʊ": "diphthong approximating 'oh' as in 'go'.",
    "h": "voiceless glottal fricative, as in 'hat'.",
    "θ": "voiceless 'th' as in 'think' (tongue between teeth).",
    "ð": "voiced 'th' as in 'this' (tongue between teeth, vibrate).",
    "ʃ": "sh sound as in 'she'.",
    "ʒ": "zh sound as in 'measure'.",
    "ŋ": "ng sound as in 'sing'.",
    # --- New Descriptions ---
    "i": "Close front unrounded vowel (long 'e'), as in 'bee' or 'see'.",
    "ɪ": "Near-close near-front unrounded vowel (short 'i'), as in 'bit' or 'sit'.",
    "u": "Close back rounded vowel (long 'u'), as in 'boot' or 'blue'.",
    "ʊ": "Near-close near-back rounded vowel (short 'u'), as in 'book' or 'put'.",
    "eɪ": "Diphthong approximating 'ay' as in 'say'.",
    "aɪ": "Diphthong approximating 'eye' as in 'buy'.",
    "ɔɪ": "Diphthong approximating 'oy' as in 'boy'.",
    "æ": "Near-open front unrounded vowel (short 'a'), as in 'cat'.",
    "ʌ": "Open-mid back unrounded vowel (stressed 'u'), as in 'cut'.",
    "ɑ": "Open back unrounded vowel, as in 'father' (often used for the 'o' in 'hot' in some dialects).",
    "v": "Voiced labiodental fricative, as in 'vote'.",
    "w": "Voiced labial-velar approximant, as in 'wet'.",
    "z": "Voiced alveolar sibilant, as in 'zebra'.",
    "p": "Voiceless bilabial plosive, as in 'pat'.",
    "b": "Voiced bilabial plosive, as in 'bat'.",
    "t": "Voiceless alveolar plosive, as in 'top'.",
    "d": "Voiced alveolar plosive, as in 'dog'.",
    "k": "Voiceless velar plosive, as in 'cat'.",
    "g": "Voiced velar plosive, as in 'go'.",
}

PHONEME_CONFUSION_SCORES = {
    ("ɫ", "l"): 0.7,
    ("l", "ɫ"): 0.7,
    ("oʊ", "ə"): 0.3,
    ("ɛ", "ə"): 0.6,
    ("θ", "s"): 0.4,
    ("ð", "d"): 0.5,
    ("r", "w"): 0.4,
    ("ʃ", "s"): 0.6,
    ("ʒ", "z"): 0.6,
    # --- New Confusions ---
    ("i", "ɪ"): 0.8,
    ("ɪ", "i"): 0.8,
    ("u", "ʊ"): 0.8,
    ("ʊ", "u"): 0.8,
    ("æ", "ɛ"): 0.7,
    ("ɛ", "æ"): 0.7,
    ("ʌ", "ɑ"): 0.6,
    ("ɑ", "ʌ"): 0.6,
    ("v", "w"): 0.4,
    ("w", "v"): 0.4,
    ("p", "b"): 0.8,
    ("b", "p"): 0.8,
    ("t", "d"): 0.8,
    ("d", "t"): 0.8,
    ("k", "g"): 0.8,
    ("g", "k"): 0.8,
    ("ʧ", "ʃ"): 0.7,
    ("ʃ", "ʧ"): 0.7,
    ("z", "s"): 0.7,
    ("s", "z"): 0.7,
}

PHONEME_SIMILARITY_MAP = {
    ("l", "ɫ"): 0.9,
    ("r", "ɹ"): 0.95,
    ("θ", "s"): 0.6,
    ("ð", "z"): 0.6,
    ("t", "d"): 0.7,
    ("p", "b"): 0.7,
    ("f", "v"): 0.8,
    ("ʃ", "s"): 0.7,
    ("ʒ", "ʃ"): 0.9,
    ("ʧ", "ʤ"): 0.85,
    ("k", "g"): 0.7,
    # --- New Similarities ---
    ("i", "ɪ"): 0.9,
    ("u", "ʊ"): 0.9,
    ("p", "t"): 0.6,
    ("f", "s"): 0.6,
    ("eɪ", "i"): 0.7,
    ("oʊ", "u"): 0.7,
}

DEFAULT_PARTIAL = 0.0

PHONEME_TO_TTS = {
    "th": "th as in think", "dh": "th as in the", "t": "t", "d": "d", "k": "k",
    "g": "g", "p": "p", "b": "b", "s": "s", "z": "z", "sh": "sh", "zh": "zh",
    "ch": "ch", "jh": "j", "m": "m", "n": "n", "ng": "ng", "r": "r", "l": "l",
    "w": "w", "y": "y", "aa": "ah", "ae": "a as in cat", "ah": "uh", "ao": "aw",
    "aw": "ow", "ay": "eye", "eh": "eh", "er": "er", "ey": "ay", "ih": "ih",
    "iy": "ee", "ow": "oh", "oy": "oy", "uh": "uh", "uw": "oo",
    "θ": "th as in think", "ð": "th as in the", "ʃ": "sh", "ʒ": "zh", "ŋ": "ng",
    "ɹ": "r", "ɪ": "ih", "i": "ee", "ɑ": "ah", "ə": "uh",
}

COMMON_PHONEME_DIGRAPHS = sorted([
    "oʊ", "aɪ", "eɪ", "ɔɪ", "aʊ", "tʃ", "dʒ", "ʃ", "ʒ", "ŋ", "ɪə", "eə", "ʊə",
    "ɹ", "ɪ", "ə", "ɔ", "ɑ", "æ", "ɔɪ", "əʊ", "ɜː", "oɪ", "ow", "aw", "ay", "ey"
], key=len, reverse=True)

EQUIVALENT_PHONEMES = {
    "ʋ": "w", "ɒ": "ɑ", "ʈ": "t", "ɖ": "d", "ɹ": "r", "ɾ": "r", "ɻ": "r",
    "ʃ": "sh", "ʒ": "zh", "θ": "th", "ð": "dh", "ŋ": "ng", "ɪ": "ih", "ʊ": "uh",
    "ɛ": "eh", "æ": "ae", "ɐ": "uh", "ɜ": "er", "ʌ": "ah", "ɔ": "aw"
}

DEFAULT_PHONEMES = [
  "p","b","t","d","k","g","m","n","ŋ","f","v","θ","ð","s","z",
  "ʃ","ʒ","tʃ","dʒ","h","l","ɫ","r","ɹ","w","j","i","ɪ","e","æ",
  "ɑ","ɒ","ɔ","ʊ","u","ʌ","ə","ɜ","aɪ","aʊ","oɪ","eɪ","oʊ","ɪə"
]

# ------------------- helper functions (unchanged) -------------------
def normalize_equivalent(p: str) -> str:
    return EQUIVALENT_PHONEMES.get(p, p)

def remove_file(path: str) -> None:
    try:
        os.unlink(path)
    except Exception as e:
        print(f"Error removing file {path}: {e}")

def ensure_jsonable(obj):
    if isinstance(obj, dict):
        return {k: ensure_jsonable(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple, set)):
        return [ensure_jsonable(i) for i in obj]
    elif hasattr(obj, '__iter__') and not isinstance(obj, (str, bytes)):
        return list(obj)
    else:
        return obj


def get_energy_score(wav_path):
    try:
        sound = parselmouth.Sound(wav_path)
        intensity = sound.to_intensity()
        mean_db = intensity.get_average()
        if mean_db > 80:
            return {"score": 75, "feedback": "A bit loud! Try speaking at a more conversational volume. 🗣️"}
        elif mean_db < 50:
            return {"score": 75, "feedback": "A little quiet! Speak up clearly so the system can hear you well. 🤫"}
        else:
            return {"score": 100, "feedback": "Good volume control! 👍"}
    except Exception as e:
        print(f"Energy analysis failed: {e}")
        return {"score": 0, "feedback": "Could not analyze audio volume."}

# phoneme tts caching helpers
def phoneme_tts_cache_path(lang: str, phoneme: str) -> str:
    safe = re.sub(r'[^a-zA-Z0-9_]', '_', phoneme)
    dirp = os.path.join(PHONEME_CACHE_DIR, lang)
    os.makedirs(dirp, exist_ok=True)
    return os.path.join(dirp, f"{safe}.mp3")


def phoneme_to_tts_text(phoneme: str) -> str:
    if not phoneme:
        return ""
    p = phoneme.strip().lower()
    if p in PHONEME_TO_TTS:
        return PHONEME_TO_TTS[p]
    p_ascii = re.sub(r'[^A-Za-z0-9 ]', ' ', phoneme).strip()
    if p_ascii:
        return p_ascii
    return " ".join(list(p))


def split_phoneme_tokens(s: str) -> List[str]:
    if not s:
        return []
    s = s.strip()
    if " " in s:
        tokens = [tok for tok in s.split() if tok.strip()]
        return tokens
    out = []
    i = 0
    while i < len(s):
        matched = False
        for seq in COMMON_PHONEME_DIGRAPHS:
            if s[i:i + len(seq)] == seq:
                out.append(seq)
                i += len(seq)
                matched = True
                break
        if not matched:
            out.append(s[i])
            i += 1
    return out


def list_edit_distance(a: List[str], b: List[str]) -> int:
    la, lb = len(a), len(b)
    if la == 0:
        return lb
    if lb == 0:
        return la
    dp = [[0] * (lb + 1) for _ in range(la + 1)]
    for i in range(la + 1):
        dp[i][0] = i
    for j in range(lb + 1):
        dp[0][j] = j
    for i in range(1, la + 1):
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            dp[i][j] = min(dp[i - 1][j] + 1, dp[i][j - 1] + 1, dp[i - 1][j - 1] + cost)
    return dp[la][lb]


def normalize_phoneme(p: Optional[str]) -> str:
    if not p:
        return ""
    s = re.sub(r'\d', '', str(p)).lower().strip()
    s = normalize_equivalent(s)
    s = s.replace('ə', 'ə').replace('ʃ', 'ʃ').replace('θ', 'θ').replace('ð', 'ð')
    return s


def phoneme_similarity(p1: str, p2: str) -> float:
    if p1 == p2:
        return 1.0
    if (p1, p2) in PHONEME_SIMILARITY_MAP:
        return PHONEME_SIMILARITY_MAP[(p1, p2)]
    if (p2, p1) in PHONEME_SIMILARITY_MAP:
        return PHONEME_SIMILARITY_MAP[(p2, p1)]
    return SequenceMatcher(None, p1, p2).ratio() * 0.5


def phoneme_similarity_score(expected_list: List[str], actual_list: List[str]) -> float:
    exp_tokens = [normalize_phoneme(p) for e in expected_list for p in split_phoneme_tokens(e)]
    act_tokens = [normalize_phoneme(p) for a in actual_list for p in split_phoneme_tokens(a)]

    if not exp_tokens and not act_tokens:
        return 100.0
    if not exp_tokens or not act_tokens:
        return 0.0

    n = max(len(exp_tokens), len(act_tokens))
    total = 0.0
    for i in range(n):
        p1 = exp_tokens[i] if i < len(exp_tokens) else ''
        p2 = act_tokens[i] if i < len(act_tokens) else ''
        total += phoneme_similarity(p1, p2)
    
    return round((total / n) * 100, 2)


def phoneme_pair_score(expected: Optional[str], actual: Optional[str]) -> float:
    if not expected and not actual:
        return 1.0
    if not expected or not actual:
        return 0.0
    if expected == actual:
        return 1.0
    key = (expected, actual)
    if key in PHONEME_CONFUSION_SCORES:
        return PHONEME_CONFUSION_SCORES[key]
    ne = normalize_phoneme(expected)
    na = normalize_phoneme(actual)
    if (ne, na) in PHONEME_CONFUSION_SCORES:
        return PHONEME_CONFUSION_SCORES[(ne, na)]
    if ne and na and ne[0] == na[0]:
        return 0.4
    return DEFAULT_PARTIAL

# ---------- phoneme TTS generator (unchanged body) ----------
def generate_phoneme_tts(lang: str, phoneme: str) -> str:
    combined_path = phoneme_tts_cache_path(lang, phoneme)
    if os.path.exists(combined_path):
        return combined_path
    tokens = split_phoneme_tokens(phoneme)
    if not tokens:
        tokens = [phoneme]
    token_segments = []
    for tok in tokens:
        tok_text = phoneme_to_tts_text(tok) or tok
        tok_cache_name = phoneme_tts_cache_path(lang, f"tok_{tok}")
        if not os.path.exists(tok_cache_name):
            try:
                gTTS(text=tok_text, lang=lang).save(tok_cache_name)
            except Exception:
                fallback = re.sub(r'[^A-Za-z0-9 ]', ' ', tok).strip() or tok_text
                try:
                    gTTS(text=fallback, lang=lang).save(tok_cache_name)
                except Exception:
                    silence = AudioSegment.silent(duration=150)
                    silence.export(tok_cache_name, format="mp3")
        try:
            seg = AudioSegment.from_file(tok_cache_name)
        except Exception:
            seg = AudioSegment.silent(duration=150)
        token_segments.append(seg)
    out = AudioSegment.silent(duration=0)
    gap = AudioSegment.silent(duration=50)
    for i, seg in enumerate(token_segments):
        out += seg
        if i < len(token_segments) - 1:
            out += gap
    os.makedirs(os.path.dirname(combined_path), exist_ok=True)
    try:
        out.export(combined_path, format="mp3")
    except Exception:
        tmp_wav = combined_path + ".wav"
        out.export(tmp_wav, format="wav")
        try:
            AudioSegment.from_wav(tmp_wav).export(combined_path, format="mp3")
        except Exception:
            combined_path = tmp_wav
    return combined_path

# G2P (per-word)
def text_to_phonemes_g2p(text: str, lang: str) -> List[str]:
    lang_prefix = LANG_MAP.get(lang, LANG_MAP["en"])
    words = text.lower().strip().split()
    if not words:
        return []
    prefixed = [f"{lang_prefix} {w}" for w in words]
    input_ids = g2p_tokenizer(prefixed, padding=True, return_tensors="pt", add_special_tokens=False).input_ids.to(DEVICE)
    g2p_model.to(DEVICE)
    with torch.no_grad():
        preds = g2p_model.generate(input_ids, num_beams=1, max_length=128)
    phones_list = g2p_tokenizer.batch_decode(preds.tolist(), skip_special_tokens=True)
    results = []
    for ph in phones_list:
        ph = ph.replace(".", " ").replace("ˈ", "").replace("ˌ", "").replace("-", " ").strip()
        if " " in ph:
            parts = [p.strip() for p in ph.split() if p.strip()]
            results.extend(parts)
        else:
            results.append(ph)
    return results

# ----------------- OllamaChatbot class & chat endpoint -----------------
import os
import json
import requests

class OllamaChatbot:
    def __init__(self, base_url: str, model: str):
        self.base_url = base_url
        self.model = model
        self.chat_history = self.load_chat_history()
        self.system_prompt = "You are a helpful pronunciation coach and chatbot."
        self.keep_alive = "5m"

    def load_chat_history(self):
        if os.path.exists("chat_history.json"):
            try:
                with open("chat_history.json", "r") as f:
                    return json.load(f)
            except json.JSONDecodeError:
                print("chat_history.json was invalid. Starting fresh.")
                return []
        return []

    def save_chat_history(self):
        with open("chat_history.json", "w") as f:
            json.dump(self.chat_history, f, indent=2)

    def generate_completion(self, prompt: str, system_message="", stream=True):
        headers = {"Content-Type": "application/json"}
        data = {
            "model": self.model,
            "prompt": prompt,
            "system": system_message,
            "stream": stream,
            "keep_alive": self.keep_alive
        }

        try:
            response = requests.post(f"{self.base_url}/api/generate",
                                     headers=headers,
                                     data=json.dumps(data),
                                     stream=stream)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            print(f"Ollama request error: {e}")
            return "Error: Failed to generate LLM feedback."

        if stream:
            # Streaming mode: yield responses piece by piece
            for line in response.iter_lines():
                if line:
                    try:
                        data = json.loads(line.decode("utf-8"))
                        yield data.get("response", "")
                    except (json.JSONDecodeError, KeyError) as e:
                        print("Stream parse error:", e)
                        continue
        else:
            # Non-stream mode: return full response
            try:
                return response.json().get("response", "")
            except json.JSONDecodeError as e:
                print("JSON parse error:", e)
                return ""

    def chat(self, user_input: str, stream=True) -> str:
        self.chat_history.append({"role": "user", "content": user_input})
        prompt = "\n".join([f"{e['role']}: {e['content']}" for e in self.chat_history])
        full_message = ""

        result = self.generate_completion(prompt, self.system_prompt, stream=stream)
        if stream:
            # result is a generator
            for msg in result:
                full_message += msg
        else:
            # result is a string
            full_message = result

        self.chat_history.append({"role": "bot", "content": full_message})
        self.save_chat_history()
        return full_message


# --- Single Instance Initialization ---
# Create the chatbot instance ONCE when the application starts.
chatbot = OllamaChatbot(OLLAMA_BASE_URL, OLLAMA_MODEL)


# ----------------- Chat Endpoint (Refactored) -----------------
@app.post("/chat")
async def chat_endpoint(user_input: str = Form(...)):
    # Use the single, pre-existing chatbot instance.
    reply = chatbot.chat(user_input,sysmsg="You are a helpful pronunciation coach and chatbot.")
    return JSONResponse({"response": reply})



# --- Existing endpoints (health, clip, tts) remain the same with fixes ---
@app.get("/health")
async def health():
    return {"status": "ok", "device": DEVICE, "g2p_loaded": True, "mfa_dictionary": MFA_DICTIONARY}

@app.post("/clip")
async def clip_audio(file: UploadFile, start: float = Form(...), end: float = Form(...)):
    data = await file.read()
    try:
        audio = AudioSegment.from_file(BytesIO(data))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not decode audio: {e}")
    start_ms = int(max(0.0, start) * 1000)
    end_ms = int(max(start_ms + 1, end * 1000))
    seg = audio[start_ms:end_ms]
    buf = BytesIO()
    seg.export(buf, format="wav")
    buf.seek(0)
    return FileResponse(buf, media_type="audio/wav")

@app.post("/tts_sentence")
async def tts_sentence(request: Request):
    data = await request.json()
    text, lang = data.get("text"), data.get("lang", "en")
    if not text:
        raise HTTPException(status_code=400, detail="No text provided")
    tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
    gTTS(text=text, lang=lang).save(tmp_file.name)
    return FileResponse(tmp_file.name, media_type="audio/mpeg", background=BackgroundTask(remove_file, tmp_file.name))

@app.post("/tts_word")
async def tts_word(request: Request):
    data = await request.json()
    text, lang = data.get("text"), data.get("lang", "en")
    if not text:
        raise HTTPException(status_code=400, detail="No text provided")
    tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
    gTTS(text=text, lang=lang).save(tmp_file.name)
    return FileResponse(tmp_file.name, media_type="audio/mpeg", background=BackgroundTask(remove_file, tmp_file.name))

# Fixed phoneme endpoints to use generate_phoneme_tts cache
@app.get("/phoneme_tts/{lang}/{phoneme}")
async def phoneme_tts(lang: str, phoneme: str):
    phoneme_dec = urllib.parse.unquote(phoneme)
    try:
        filepath = f"../assets/phoneme/{phoneme_dec}.mp3"
        # fallback logic
        if not os.path.exists(filepath):
            filepath = generate_phoneme_tts(lang, phoneme_dec)
        return FileResponse(filepath, media_type="audio/mp3")
    except Exception as e:
        print(f"phoneme_tts error: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate phoneme TTS")


@app.get("/tts_phoneme/{lang}/{phoneme}")
async def tts_phoneme_alias(lang: str, phoneme: str):
    if not phoneme:
        raise HTTPException(status_code=400, detail="No phoneme provided")
    return RedirectResponse(url=f"/phoneme_tts/{lang}/{phoneme}", status_code=307)

# lightweight phoneme audio alias (same as phoneme_tts) - used by frontend as /phoneme_audio
@app.get("/phoneme_audio/{lang}/{phoneme}")
async def phoneme_audio(lang: str, phoneme: str):
    phoneme_dec = urllib.parse.unquote(phoneme)
    path = generate_phoneme_tts(lang, phoneme_dec)
    return FileResponse(path, media_type="audio/mpeg")

# ---------- SCORE endpoint (full sentence) ----------
@app.post("/score")
async def score_pronunciation(audio: UploadFile, sentence: str = Form(...), lang: str = Form("en"), use_cuda: bool = Form(True), debug: bool = Form(False)):
    if not sentence.strip(): raise HTTPException(status_code=400, detail="Sentence is required.")
    device = "cuda" if (use_cuda and torch.cuda.is_available()) else "cpu"
    debug_info = {}
    with tempfile.TemporaryDirectory() as tmpdir:
        corpus_dir = os.path.join(tmpdir, "corpus"); os.makedirs(corpus_dir, exist_ok=True)
        base = "input"; wav_path = os.path.join(corpus_dir, f"{base}.wav")
        content = await audio.read()
        with open(wav_path, "wb") as f: f.write(content)
        try:
            AudioSegment.from_file(wav_path).set_channels(1).set_frame_rate(16000).export(wav_path, format="wav")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Audio conversion failed: {e}")
        with open(os.path.join(corpus_dir, f"{base}.txt"), "w", encoding="utf-8") as tf:
            tf.write(sentence.strip())
        mfa_out = os.path.join(tmpdir, "mfa_out"); os.makedirs(mfa_out, exist_ok=True)
        try:
            proc = subprocess.run(["mfa","align", corpus_dir, MFA_DICTIONARY, MFA_ACOUSTIC, mfa_out, "--clean"], check=True, capture_output=True, text=True)
            if debug: debug_info["mfa_stdout"] = proc.stdout; debug_info["mfa_stderr"] = proc.stderr
        except subprocess.CalledProcessError as e:
            stderr = e.stderr if e.stderr else str(e)
            if debug:
                raise HTTPException(status_code=500, detail=f"MFA failed: {stderr}")
            raise HTTPException(status_code=500, detail="MFA alignment failed.")
        tg_path = os.path.join(mfa_out, f"{base}.TextGrid")
        if not os.path.exists(tg_path): raise HTTPException(status_code=500, detail="MFA did not produce TextGrid.")
        try:
            tg = TextGrid.fromFile(tg_path)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Parsing TextGrid failed: {e}")

        try: word_tier = tg.getFirst("words")
        except Exception: word_tier = None
        try: phone_tier = tg.getFirst("phones")
        except Exception: phone_tier = None
        if not word_tier or not phone_tier:
            word_tier = word_tier or (tg.tiers[0] if len(tg.tiers)>0 else None)
            phone_tier = phone_tier or (tg.tiers[1] if len(tg.tiers)>1 else None)
        if not word_tier or not phone_tier:
            raise HTTPException(status_code=500, detail="Could not find word/phone tiers in TextGrid.")

        word_intervals = []
        for i in word_tier:
            mark = (i.mark or "").strip()
            if not mark or mark.lower() in ["<unk>","sp"]: continue
            word_intervals.append({"word": mark, "start": i.minTime, "end": i.maxTime})

        phoneme_intervals = []
        for i in phone_tier:
            mark = (i.mark or "").strip()
            if not mark or mark.lower() in ["<sil>","sp"]: continue
            phoneme_intervals.append({"phoneme": mark, "start": i.minTime, "end": i.maxTime})

        if not word_intervals:
            raise HTTPException(status_code=422, detail="No word intervals from MFA.")

        expected_phonemes_per_word = {}
        for w in [w["word"].lower().strip() for w in word_intervals]:
            try: expected_phonemes_per_word[w] = text_to_phonemes_g2p(w, lang)
            except Exception: expected_phonemes_per_word[w] = []

        words_output = []
        phoneme_error_summary = []

        for w_interval in word_intervals:
            w_text = w_interval["word"]
            actual_phs = []
            for p in phoneme_intervals:
                center = (p["start"] + p["end"]) / 2.0
                if center >= w_interval["start"] - 1e-6 and center <= w_interval["end"] + 1e-6:
                    actual_phs.append(p)
            expected_list = expected_phonemes_per_word.get(w_text.lower(), [])
            actual_tokens = [p["phoneme"] for p in actual_phs]
            word_score = phoneme_similarity_score(expected_list, actual_tokens)
            exp_seq = []
            for e in expected_list: exp_seq.extend(split_phoneme_tokens(e))
            act_seq = []
            for a in actual_tokens: act_seq.extend(split_phoneme_tokens(a))
            actual_token_intervals = []
            for idx_ph, p in enumerate(actual_phs):
                toks = split_phoneme_tokens(p["phoneme"])
                for t in toks:
                    actual_token_intervals.append({"token": t, "start": p["start"], "end": p["end"]})

            matcher = difflib.SequenceMatcher(None, [normalize_phoneme(x) for x in exp_seq],
                                              [normalize_phoneme(x) for x in act_seq], autojunk=False)
            phoneme_results = []
            coaching = None
            for tag, i1, i2, j1, j2 in matcher.get_opcodes():
                maxlen = max(i2 - i1, j2 - j1)
                for k in range(maxlen):
                    e_tok = exp_seq[i1 + k] if (i1 + k) < len(exp_seq) else None
                    a_tok = act_seq[j1 + k] if (j1 + k) < len(act_seq) else None
                    interval_item = actual_token_intervals[j1 + k] if (j1 + k) < len(actual_token_intervals) else {}
                    p_score = phoneme_pair_score(e_tok, a_tok)
                    p_score_pct = round(p_score * 100.0, 1)
                    phoneme_results.append({
                        "expected": e_tok,
                        "actual": a_tok,
                        "score": p_score_pct,
                        "start": interval_item.get("start"),
                        "end": interval_item.get("end"),
                        "expected_description": PHONEME_DESCRIPTIONS.get(e_tok),
                        "actual_description": PHONEME_DESCRIPTIONS.get(a_tok)
                    })
                    if p_score < 0.9:
                        phoneme_error_summary.append({"word": w_text, "expected": e_tok, "actual": a_tok, "score": p_score_pct})
                    if not coaching and e_tok:
                        key = (normalize_phoneme(e_tok), normalize_phoneme(a_tok))
                        if key in COACHING_TIPS:
                            coaching = COACHING_TIPS[key]
                        elif normalize_phoneme(e_tok) in COACHING_TIPS:
                            coaching = COACHING_TIPS[normalize_phoneme(e_tok)]

            if phoneme_results:
                phoneme_acc = round(sum(p["score"] for p in phoneme_results) / len(phoneme_results), 1)
            else:
                phoneme_acc = 0.0

            words_output.append({
                "word": w_text,
                "start": w_interval["start"],
                "end": w_interval["end"],
                "score": round(word_score, 1),
                "phoneme_accuracy": phoneme_acc,
                "phones": phoneme_results,
                "coaching": coaching
            })

        overall_score = round(sum(w["score"] for w in words_output) / len(words_output), 1) if words_output else 0.0
        all_ph_scores = [pr["score"] for w in words_output for pr in w["phones"]]
        overall_phoneme_accuracy = round(sum(all_ph_scores) / len(all_ph_scores), 1) if all_ph_scores else 0.0

        phoneme_set = set()
        for w in words_output:
            for p in w["phones"]:
                if p.get("expected"): phoneme_set.add(p["expected"])
                if p.get("actual"): phoneme_set.add(p["actual"])
        phoneme_tts_map = { ph: f"/phoneme_tts/{lang}/{urllib.parse.quote(ph, safe='')}" for ph in phoneme_set if ph }

        llm_feedback = None; suggested_next_sentence = None
        try:
            top_errs = sorted(phoneme_error_summary, key=lambda x: x["score"])[:6]
            lines = [f"{e['word']}: expected {e['expected']} got {e['actual']} ({e['score']}%)" for e in top_errs]
            
            prompt = "User completed a pronunciation exercise. Provide a short actionable summary, 2 drills, and one suggested next sentence focusing on the worst phonemes.\n"
            if lines:
                prompt += "Errors:\n" + "\n".join(lines) + "\n"
            
            # Use the SAME chatbot instance for a one-off completion.
            # This call does not use or affect the conversational chat_history.
            resp = chatbot.generate_completion(prompt, chatbot.system_prompt, stream=False)
            llm_feedback = resp
            
            m = re.search(r'[\"“](.+?)[\"”]', resp) if resp else None
            if m:
                suggested_next_sentence = m.group(1)
                
        except Exception as e:
            print("LLM error (nonfatal):", e)

        if isinstance(words_output, collections.abc.Generator):
            words_output = list(words_output)
        if debug and isinstance(debug_info, collections.abc.Generator):
            debug_info = list(debug_info)

        result = {
            "overall_score": overall_score,
            "energy_analysis": {"score": 100, "feedback":"(volume check omitted)"},
            "language_used": lang,
            "words": words_output,
            "phoneme_tts_map": phoneme_tts_map,
            "overall_phoneme_accuracy": overall_phoneme_accuracy,
            "llm_feedback": llm_feedback,
            "suggested_next_sentence": suggested_next_sentence
        }
        if debug: result["debug"] = debug_info

        result = ensure_jsonable(result)

        # save last score to disk for drill endpoint
        try:
            with open(LAST_SCORE_PATH, "w", encoding="utf-8") as f:
                json.dump(result, f)
        except Exception as e:
            print("Could not save last score:", e)

        return JSONResponse(result)
    
# ---------- SCORE_WORD endpoint (word-level practice) ----------
@app.post("/score_word")
async def score_word(audio: UploadFile, expected_word: str = Form(...), lang: str = Form("en"), debug: bool = Form(False)):
    if not expected_word.strip(): raise HTTPException(status_code=400, detail="expected_word required")
    with tempfile.TemporaryDirectory() as tmpdir:
        wav_path = os.path.join(tmpdir, "word.wav")
        content = await audio.read()
        with open(wav_path, "wb") as f: f.write(content)
        try:
            AudioSegment.from_file(wav_path).set_channels(1).set_frame_rate(16000).export(wav_path, format="wav")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Audio conversion failed: {e}")
        
        corpus_dir = os.path.join(tmpdir, "corpus"); os.makedirs(corpus_dir, exist_ok=True)
        with open(os.path.join(corpus_dir, "input.txt"), "w", encoding="utf-8") as f:
            f.write(expected_word)
        shutil.copy(wav_path, os.path.join(corpus_dir, "input.wav"))
        
        mfa_out = os.path.join(tmpdir, "mfa_out"); os.makedirs(mfa_out, exist_ok=True)
        
        phoneme_intervals = []
        actual_tokens = []
        phoneme_results = []
        score_pct = 0.0

        try:
            # Run MFA alignment
            subprocess.run(["mfa", "align", corpus_dir, MFA_DICTIONARY, MFA_ACOUSTIC, mfa_out, "--clean"], check=True, capture_output=True, text=True)
            tg_path = os.path.join(mfa_out, "input.TextGrid")
            if os.path.exists(tg_path):
                tg = TextGrid.fromFile(tg_path)
                phone_tier = tg.getFirst("phones")
                if phone_tier:
                    for i in phone_tier:
                        mark = (i.mark or "").strip()
                        if mark and mark.lower() not in ["<sil>", "sp"]:
                            phoneme_intervals.append({"phoneme": mark, "start": i.minTime, "end": i.maxTime})
                    actual_tokens = [p["phoneme"] for p in phoneme_intervals]
        except (subprocess.CalledProcessError, Exception) as e:
            print(f"MFA failed for score_word, proceeding without alignment: {e}")

        # Always generate expected phonemes
        expected_list = text_to_phonemes_g2p(expected_word, lang)
        score_pct = phoneme_similarity_score(expected_list, actual_tokens)

        # Align expected vs actual
        exp_seq = [t for e in expected_list for t in split_phoneme_tokens(e)]
        matcher = difflib.SequenceMatcher(None, exp_seq, actual_tokens, autojunk=False)

        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == 'equal':
                for i in range(i1, i2):
                    phoneme_results.append({"expected": exp_seq[i], "actual": exp_seq[i], "score": 100.0})
            else: # replace, delete, insert
                for i in range(max(i2 - i1, j2 - j1)):
                    e_tok = exp_seq[i1 + i] if (i1 + i) < len(exp_seq) else None
                    a_tok = actual_tokens[j1 + i] if (j1 + i) < len(actual_tokens) else None
                    p_score = round(phoneme_pair_score(e_tok, a_tok) * 100, 1)
                    phoneme_results.append({
                        "expected": e_tok, "actual": a_tok, "score": p_score,
                        "expected_description": PHONEME_DESCRIPTIONS.get(e_tok),
                        "actual_description": PHONEME_DESCRIPTIONS.get(a_tok)
                    })
        
        # --- LLM Feedback Logic ---
        llm_feedback = None
        try:
            lines = [f"expected {e['expected']} got {e['actual']} ({e['score']}%)" for e in phoneme_results if e['score'] < 95]
            if lines:
                prompt = f"User practiced the word '{expected_word}'. Give a 1-sentence summary and 2 concrete drills based on these errors.\nErrors:\n" + "\n".join(lines)
                
                # --- CORRECTED LINE ---
                # Use keyword arguments for clarity and correctness
                resp = chatbot.generate_completion(prompt=prompt, system_message=chatbot.system_prompt, stream=False)
                llm_feedback = resp
        except Exception as e:
            print(f"LLM error in score_word (nonfatal): {e}")

        return JSONResponse({
            "word": expected_word,
            "phoneme_accuracy": score_pct,
            "phones": phoneme_results,
            "llm_feedback": llm_feedback
        })
# ---------- WORD_DRILL endpoint (returns tokens + urls) ----------
@app.post("/word_drill")
async def word_drill(sentence: str = Form(...), word_index: int = Form(...), lang: str = Form("en")):
    words = [w.strip() for w in sentence.strip().split()]
    if word_index < 0 or word_index >= len(words): raise HTTPException(status_code=400, detail="word_index out of range")
    w = words[word_index]
    expected = text_to_phonemes_g2p(w, lang)
    tokens = []
    for p in expected:
        for t in split_phoneme_tokens(p):
            tokens.append({"phoneme": t, "description": PHONEME_DESCRIPTIONS.get(t), "tts_url": f"/phoneme_tts/{lang}/{urllib.parse.quote(t, safe='')}", "audio_url": f"/phoneme_audio/{lang}/{urllib.parse.quote(t, safe='')}"})
    return JSONResponse({"word": w, "expected": tokens})

# ---------- NEW: phoneme_feedback endpoint ----------
@app.post("/phoneme_feedback")
async def phoneme_feedback(request: Request):
    data = await request.json()
    expected = data.get("expected")
    actual = data.get("actual")
    # prefer explicit coaching tips
    hint = None
    if expected and expected in COACHING_TIPS:
        hint = COACHING_TIPS[expected]
    elif expected and normalize_phoneme(expected) in COACHING_TIPS:
        hint = COACHING_TIPS[normalize_phoneme(expected)]
    elif expected and expected in PHONEME_DESCRIPTIONS:
        hint = PHONEME_DESCRIPTIONS[expected]
    else:
        if not actual:
            hint = "We did not detect this sound; try exaggerating the target sound for clarity."
        else:
            if expected and actual and expected[0] == actual[0]:
                hint = "Close — you have the same place of articulation. Try adjusting voicing or tongue height."
            else:
                hint = "Try slowing down and emphasizing the target sound. Small adjustments will help!"
    return JSONResponse({"hint": hint})

# ---------- NEW: chat_feedback endpoint (LLM suggestion based on score) ----------
@app.post("/chat_feedback")
async def chat_feedback(request: Request):
    """
    Provides LLM-generated feedback based on pronunciation errors.
    """
    try:
        body = await request.json()
        words = body.get("words", []) # Default to empty list for safety
        
        # --- Build the list of errors ---
        top_errs = []
        if words:
            for w in words:
                for p in w.get('phones', []):
                    # Check if 'score' exists and is below the threshold
                    if p.get('score') is not None and p['score'] < 90:
                        error_detail = (
                            f"{w.get('word')}: "
                            f"expected {p.get('expected')} "
                            f"got {p.get('actual')} ({p.get('score')}%)"
                        )
                        top_errs.append(error_detail)

        # --- Construct the prompt ---
        prompt = "You are a concise pronunciation coach. Give a 2-sentence summary and 3 concrete drills for the user based on these errors.\n"
        if top_errs:
            # Limit to the top 8 errors to keep the prompt focused
            prompt += "Errors:\n" + "\n".join(top_errs[:8])
        else:
            # Handle the case with no significant errors
            prompt = "The user had excellent pronunciation with no significant errors. Provide a short, encouraging message."

        # --- CORRECTED LINE ---
        # Use a keyword argument to correctly set stream=False
        resp = chatbot.chat(prompt,stream=True)

        print(resp,type(resp))
        # If somehow it's still a generator, join it into a string
        if hasattr(resp, '__iter__') and not isinstance(resp, str):
            resp = "".join(resp)

        return JSONResponse({"response": resp})

    except Exception as e:
        print("chat_feedback error:", e)
        raise HTTPException(status_code=500, detail="LLM feedback failed")

# ---------- NEW: drill_next endpoint ----------
@app.get("/drill_next")
async def drill_next():
    # Try to read last saved score
    if os.path.exists(LAST_SCORE_PATH):
        try:
            with open(LAST_SCORE_PATH, "r", encoding="utf-8") as f:
                last = json.load(f)
            # examine words -> phones to find worst phoneme
            worst = None
            worst_score = 101
            for w in last.get('words', []):
                for p in w.get('phones', []):
                    sc = p.get('score', 100)
                    if sc < worst_score and p.get('expected'):
                        worst_score = sc
                        worst = p.get('expected')
            if worst:
                return JSONResponse({"target": {"type": "phoneme", "value": worst}})
            # fallback to worst word
            worst_word = None
            worst_wscore = 101
            for w in last.get('words', []):
                if w.get('score', 100) < worst_wscore:
                    worst_wscore = w.get('score', 100)
                    worst_word = w.get('word')
            if worst_word:
                return JSONResponse({"target": {"type": "word", "value": worst_word}})
        except Exception as e:
            print("drill_next read failed:", e)
    # fallback: random phoneme
    pn = random.choice(DEFAULT_PHONEMES)
    return JSONResponse({"target": {"type": "phoneme", "value": pn}})

# ---------- NEW: coach_tts endpoint ----------
@app.post("/coach_tts")
async def coach_tts(request: Request):
    data = await request.json()
    text = data.get('text')
    lang = data.get('lang', 'en')
    if not text:
        raise HTTPException(status_code=400, detail='No text provided')
    tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.mp3')
    gTTS(text=text, lang=lang).save(tmp_file.name)
    return FileResponse(tmp_file.name, media_type='audio/mpeg', background=BackgroundTask(remove_file, tmp_file.name))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=5000)
