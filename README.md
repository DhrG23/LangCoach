# AI For Language💬✨

> **"Learn words, master pronunciation, and speak confidently — powered by AI!"**

Welcome to **Our App**, an AI-driven language learning companion that helps you discover new words, understand their meanings, and perfect your pronunciation with *real-time feedback* and *interactive learning* 🎧📚  

---

## 🌟 Overview

**Our App** combines the power of **AI**, **Speech Recognition**, and **Phoneme Analysis** to make learning languages *fun*, *inclusive*, and *impactful*.  
It helps learners of all levels speak naturally by identifying pronunciation errors and providing instant, friendly feedback.  

Whether you’re learning **Japanese**, **Korean**, **Spanish**, or **English**, Our App becomes your personal pronunciation coach 🗣️💡  

---

## 🧠 

### 🎧 Real-Time Pronunciation Feedback
- Speak words and get instant accuracy scores.
- AI compares your pronunciation to native-level references.
- Get phoneme-level correction:  
  _“Try rolling the R softly!”_ 💬

### 📚 Smart Vocabulary Trainer
- Learn new words daily with meaning, usage, and examples.
- Context-based examples make memorization easy.

### 🧠 Adaptive Learning System
- Tracks your weak sounds and focuses on improving them.
- Personalized practice sessions that evolve with your progress.

### 💬 Conversational Mode (Optional)
- Talk with your AI buddy in the target language.
- Receive gentle corrections during casual conversations.

### 🎙️ TTS & STT Integration
- Listen to perfect pronunciation via **TTS (Text-to-Speech)**.
- Speak and get transcribed using **Whisper (STT)**.

### 🎭 Dual Persona Modes
- 🌸 **Angel Mode:** Encouraging and polite feedback.  
- 🔥 **Demon Mode:** Playfully challenges you to improve!

---

## 🧩 Tech Stack

| Component | Technology |
|------------|-------------|
| **Frontend** | Flask / Streamlit / React (optional) |
| **Backend** | Python (FastAPI / Flask) |
| **Speech Recognition** | Whisper / Whisper.cpp |
| **Text-to-Speech** | Piper / Jenny / ElevenLabs |
| **Phoneme Extraction** | Phonemizer / Montreal Forced Aligner |
| **Feedback Logic** | Dynamic Time Warping (DTW) + Mini LLM |
| **Database** | SQLite / JSON |
| **AI Model** | Mistral / Phi-3 / Gemma (via Ollama or API) |

---

## 🧭 System Flow

```mermaid
flowchart TD
    subgraph Input
        A[User Speaks Word 🎙️]
    end

    subgraph Reference
        Z[Word Text (e.g., "Hello") 📝] --> Z1[Target Phonemes (from Dictionary) 🎯]
    end

    A --> B{Whisper STT / Speech Intent 🧠}
    B --> Z
    
    A --> C[Phoneme Extractor / Forced Aligner 🔊➡️🔡]
    Z --> C
    
    C --> D[User Phonemes (Acoustic Features) 🗣️]
    Z1 --> E[Phoneme Comparison DTW ⚖️]
    D --> E
    
    E --> F[LLM Feedback Generator 💬]
    F --> G[UI Response ✨]
```