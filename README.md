# AI For Language 💬✨

Learn words, master pronunciation, and speak confidently — a lightweight Electron app that combines speech recognition, phoneme analysis, and AI-generated feedback.

---

**Quick summary:** This repo contains a small Electron-based frontend and a Python backend for phoneme/tips support and analytics.

**Project structure**

```
main.js
preload.js
package.json
renderer/
    index.html
    renderer.js
    style.css
assets/
    sample_sentences.json
    phoneme/
backend/
    server.py
    requirements.txt
    phoneme_tips.json
    chat_history.json
    last_score.json
```

---

## Prerequisites

- Node.js (v16+ recommended) and npm
- Python 3.8+ and pip

Optional: create a Python virtual environment for the backend.

---

## Install & Run (Development)

1. Install backend dependencies and start the backend server:

```powershell
cd backend
python -m venv .venv   # optional
.\.venv\Scripts\Activate  # on Windows
pip install -r requirements.txt
python server.py
```

2. Install frontend dependencies and start the Electron app:

```powershell
cd ..
npm install
npm start
```

The app window is frameless; window controls are implemented via `preload.js` and IPC handlers in `main.js`.

---

## Features

- Real-time pronunciation scoring (STT + phoneme analysis)
- Phoneme-level tips (backend JSON + heuristics)
- Simple vocabulary/usage examples in `assets/sample_sentences.json`

---

## Development Notes

- Frontend: `renderer/` — HTML, CSS, and client JS for UI.
- Electron main process: `main.js` — window creation and IPC handlers.
- Preload: `preload.js` — exposes safe APIs for window controls.
- Backend: `backend/server.py` — lightweight API serving phoneme tips and history.

If you change backend ports or endpoints, update `renderer/renderer.js` accordingly.

---

## Contributing

1. Fork and create a branch
2. Make changes and add tests where appropriate
3. Open a PR with a clear description

---

## License

This project is licensed under the MIT License — see [LICENSE](LICENSE) for details.