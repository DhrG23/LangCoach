// renderer.js (Corrected and Verified)
// Full frontend logic: recording, scoring, drill mode, LLM chat integration, progress chart, phoneme playback.

document.addEventListener('DOMContentLoaded', () => {
  // Elements
  const sentenceTextEl = document.getElementById('sentenceText');
  const recordBtn = document.getElementById('recordBtn');
  const stopRecordBtn = document.getElementById('stopRecordBtn');
  const playExampleBtn = document.getElementById('playExampleBtn');
  const summaryEl = document.getElementById('summary');
  const wordListContainer = document.getElementById('wordListContainer');
  const langSelect = document.getElementById('lang');
  const modal = document.getElementById('feedbackModal');
  const modalBody = document.getElementById('modalBody');
  const modalCloseBtn = document.getElementById('modalCloseBtn');
  const chatHistoryEl = document.getElementById('chat-history');
  const chatInput = document.getElementById('chat-input');
  const chatSend = document.getElementById('chat-send');
  const autoFeedbackToggle = document.getElementById('auto-feedback-toggle');
  const copyCoachBtn = document.getElementById('copy-coach');
  const drillModeToggle = document.getElementById('drillModeToggle');
  const drillPanel = document.getElementById('drillPanel');
  const drillTargetEl = document.getElementById('drillTarget');
  const drillRepeatBtn = document.getElementById('drillRepeat');
  const drillNextBtn = document.getElementById('drillNext');
  const drillAutoAdvanceBtn = document.getElementById('drillAutoAdvance');
  const phonemeHeatmapEl = document.getElementById('phonemeHeatmap');


  // State
  const API_BASE = "http://127.0.0.1:5000";
  let mediaRecorder, audioChunks = [];
  let lastRecordedBlob = null; // Stores user's last full recording blob
  const audioContext = new (window.AudioContext || window.webkitAudioContext)();
  let phonemePlaybackQueue = Promise.resolve(); // Ensures sequential phoneme playback
  let progressChart = null;
  let lastLLMReply = '';
  let lastScoreData = null;
  let autoFeedback = false;
  let drillMode = false;
  let drillAutoAdvance = false;
  let currentDrillTarget = null; // { type: 'word'|'phoneme', value: '...' }

  // Safe helpers
  const safeNumber = (n, fallback = 0) => (typeof n === 'number' && !isNaN(n)) ? n : fallback;

  function logChat(role, text) {
    const msgDiv = document.createElement('div');
    msgDiv.className = role === 'user' ? 'chat-user' : 'chat-bot';
    msgDiv.textContent = (role === 'user' ? 'YOU: ' : 'BOT: ') + text;
    chatHistoryEl.appendChild(msgDiv);
    chatHistoryEl.scrollTop = chatHistoryEl.scrollHeight;
  }

  // Event bindings
  playExampleBtn.onclick = () => playAudioFromTTS('tts_sentence', { text: sentenceTextEl.value, lang: langSelect.value });
  recordBtn.onclick = startRecording;
  stopRecordBtn.onclick = stopRecording;

  modalCloseBtn.onclick = () => {
    modal.style.display = 'none';
    document.body.classList.remove('modal-open');
  };
  window.onclick = (event) => {
    if (event.target === modal) {
      modal.style.display = 'none';
      document.body.classList.remove('modal-open');
    }
  };

  chatSend.onclick = async () => {
    const text = chatInput.value.trim();
    if (!text) return;
    logChat('user', text);
    chatInput.value = '';
    try {
      const res = await fetch(`${API_BASE}/chat`, {
        method: 'POST',
        body: new URLSearchParams({ 'user_input': text })
      });
      if (!res.ok) throw new Error('Chat failed');
      const data = await res.json();
      const reply = data.response || 'No response';
      //reply = reply.replace(/^bot:\s*/i, '');
      lastLLMReply = reply;
      logChat('bot', reply);
    } catch (e) {
      logChat('bot', 'Error: Could not get response.');
      console.error(e);
    }
  };

  copyCoachBtn.onclick = async () => {
    if (!lastLLMReply) return alert('No coach tip yet.');
    try {
      await navigator.clipboard.writeText(lastLLMReply);
      alert('Coach tip copied 👍');
    } catch {
      alert('Clipboard failed');
    }
  };

  autoFeedbackToggle.onclick = () => {
    autoFeedback = !autoFeedback;
    autoFeedbackToggle.textContent = `🌀 Auto-Feedback: ${autoFeedback ? 'ON' : 'OFF'}`;
    autoFeedbackToggle.classList.toggle('active', autoFeedback);
  };

  // Drill mode UI
  drillModeToggle.onchange = (e) => {
    drillMode = e.target.checked;
    drillPanel.style.display = drillMode ? 'block' : 'none';
    if (drillMode) activateDrillMode();
  };

  drillRepeatBtn.onclick = () => {
    if (!currentDrillTarget) return;
    if (currentDrillTarget.type === 'word') {
      playExampleWord(currentDrillTarget.value);
    } else {
      playPhonemeAudio(langSelect.value, currentDrillTarget.value);
    }
  };

  drillNextBtn.onclick = () => requestNextDrillTarget();

  drillAutoAdvanceBtn.onclick = () => {
    drillAutoAdvance = !drillAutoAdvance;
    drillAutoAdvanceBtn.textContent = `Auto Advance: ${drillAutoAdvance ? 'ON' : 'OFF'}`;
    drillAutoAdvanceBtn.classList.toggle('active', drillAutoAdvance);
  };

  // Recording
  async function startRecording() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      mediaRecorder = new MediaRecorder(stream);
      audioChunks = [];
      mediaRecorder.ondataavailable = e => audioChunks.push(e.data);
      mediaRecorder.onstop = async () => {
        // **FIXED:** Assign to the single, top-level lastRecordedBlob variable.
        lastRecordedBlob = new Blob(audioChunks, { type: 'audio/webm' });
        stream.getTracks().forEach(track => track.stop());
        await uploadAndScore(lastRecordedBlob);
      };
      mediaRecorder.start();
      setRecordingState(true);
    } catch (err) {
      console.error("Error starting recording:", err);
      alert("Could not start recording. Please ensure microphone access.");
    }
  }

  function stopRecording() {
    if (mediaRecorder && mediaRecorder.state !== 'inactive') {
      mediaRecorder.stop();
    }
    setRecordingState(false);
  }

  function setRecordingState(isRecording) {
    recordBtn.disabled = isRecording;
    recordBtn.textContent = isRecording ? "Recording..." : "🎙️ START SEQUENCE";
    recordBtn.classList.toggle("recording", isRecording);
    stopRecordBtn.disabled = !isRecording;
  }

  // Upload & score
  async function uploadAndScore(blob) {
    summaryEl.innerHTML = "Processing and scoring your audio... 🧠";
    wordListContainer.innerHTML = '';

    const fd = new FormData();
    fd.append('audio', blob, 'recording.webm');
    fd.append('sentence', sentenceTextEl.value || '');
    fd.append('lang', langSelect.value || 'en');

    try {
      const res = await fetch(`${API_BASE}/score`, { method: 'POST', body: fd });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({ detail: 'Failed to score audio.' }));
        throw new Error(errData.detail);
      }
      const data = await res.json();
      lastScoreData = data;
      renderResult(data);
      updateProgressTracker(safeNumber(data.overall_score, 0));
      showFeedbackModal(data);

      if (autoFeedback) {
        triggerAutoFeedback(data);
      }

      if (drillMode && drillAutoAdvance) {
        // **FIXED:** Use corrected drill logic.
        autoSelectNextDrillFromScore(data);
      }
    } catch (err) {
      console.error(err);
      summaryEl.innerHTML = `<strong class="score-bad">Error:</strong> ${err.message}`;
    }
  }

  async function triggerAutoFeedback(data) {
    try {
      const fbRes = await fetch(`${API_BASE}/chat_feedback`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          score: data.overall_score,
        
          words: data.words,
          sentence: sentenceTextEl.value
        })
      });
      if (fbRes.ok) {
        const fbData = await fbRes.json();
        if (fbData && fbData.response) {
          logChat('bot', fbData.response);
          lastLLMReply = fbData.response;
        }
      }
    } catch (err) {
      console.warn('chat_feedback failed', err);
    }
  }

  // Result Rendering
  function renderResult(data) {
    if (!data) return;
    const overall = safeNumber(data.overall_score, 0);
    summaryEl.innerHTML = `<strong>Overall Score:</strong>
      <span class="${getScoreClass(overall)}">${overall.toFixed(1)}%</span>
      | ${data.energy_analysis?.feedback || ''}`;

    wordListContainer.innerHTML = '';
    const phonemeSet = new Set();

    (data.words || []).forEach(word => {
      const wc = document.createElement('div');
      wc.className = 'word-card';
      wc.style.borderLeft = `4px solid ${getScoreColor(safeNumber(word.score, 0))}`;

      wc.innerHTML = `
        <div class="word-header">
          <span class="word-text">${word.word}</span>
          <span class="word-score">${safeNumber(word.score, 0).toFixed(1)}%</span>
        </div>
        <div class="word-actions">
          <button class="play-user-word">▶️ Your Audio</button>
          <button class="play-example-word">🔊 Example</button>
          <button class="play-phoneme-sequence">🎶 Phono-Seq</button>
          <button class="toggle-phonemes">🧩 Show Phonemes</button>
        </div>
        <div class="phonemes-container" style="display: none; margin-top: 8px;"></div>
      `;

      const phonemeContainer = wc.querySelector('.phonemes-container');
      (word.phones || []).forEach(p => {
        const expected = p.expected || '-';
        const actual = p.actual || '-';
        phonemeSet.add(expected);
        if (actual !== '-') phonemeSet.add(actual);

        const scorePct = safeNumber(p.score, 0);
        const scoreEmoji = scorePct >= 90 ? '✅' : scorePct >= 60 ? '⚠️' : '❌';
        
        const phonemeEl = document.createElement('div');
        phonemeEl.className = 'phoneme-entry';
        phonemeEl.innerHTML = `
          <div class="phoneme-line">
            <div class="phoneme-text">Expected: <strong>${expected}</strong></div>
            <div class="phoneme-text">Actual: <strong>${actual}</strong></div>
            <div class="phoneme-score">${scoreEmoji} ${scorePct}%</div>
            <button class="play-user-phoneme" title="Play your audio for this phoneme">▶️</button>
            <button class="play-example-phoneme" title="Play example audio for expected phoneme">🔊</button>
          </div>
          ${(p.expected_description || p.coaching) ? `<div class="phoneme-hint">${p.coaching || p.expected_description}</div>` : ''}
        `;
        phonemeContainer.appendChild(phonemeEl);

        // **FIXED:** Attach listeners with correct scope
        const playUserBtn = phonemeEl.querySelector('.play-user-phoneme');
        if (isFinite(p.start) && isFinite(p.end)) {
            playUserBtn.onclick = () => playUserAudioSlice(p.start, p.end);
        } else {
            playUserBtn.disabled = true;
        }

        const playExampleBtn = phonemeEl.querySelector('.play-example-phoneme');
        if (expected !== '-') {
            playExampleBtn.onclick = () => playPhonemeAudio(langSelect.value, expected);
        } else {
            playExampleBtn.disabled = true;
        }
      });
      
      // **FIXED:** Attach listeners for word-level actions
      // Inside renderResult(), for each word card
        wc.querySelector('.play-user-word').onclick = () => {
        if (isFinite(word.start) && isFinite(word.end)) {
            playUserAudioSlice(word.start, word.end);
        } else {
            alert("No timing info for this word.");
        }
        };

      wc.querySelector('.play-example-word').onclick = () => playExampleWord(word.word);
      wc.querySelector('.play-phoneme-sequence').onclick = () => {
        const expectedPhonemes = (word.phones || []).map(p => p.expected).filter(Boolean);
        playWordPhonemesInSequence(langSelect.value, expectedPhonemes);
      };
      const toggleBtn = wc.querySelector('.toggle-phonemes');
      toggleBtn.onclick = () => {
        const visible = phonemeContainer.style.display === 'block';
        phonemeContainer.style.display = visible ? 'none' : 'block';
        toggleBtn.textContent = visible ? '🧩 Show Phonemes' : '⬆️ Hide Phonemes';
      };

      wordListContainer.appendChild(wc);
    });

    const phonemeList = phonemeSet.size > 0 ? Array.from(phonemeSet) : defaultPhonemeList();
    renderPhonemeHeatmap(phonemeList);
  }

  // Playback helpers
  async function playAudioFromURL(url) {
    try {
        const res = await fetch(url);
        if (!res.ok) throw new Error(`Fetch failed for ${url}`);
        const blob = await res.blob();
        const audio = new Audio(URL.createObjectURL(blob));
        await new Promise((resolve, reject) => {
            audio.onended = resolve;
            audio.onerror = reject;
            audio.play().catch(reject);
        });
    } catch (err) {
        console.error(`Could not play audio from ${url}:`, err);
    }
  }
  
  async function playAudioFromTTS(endpoint, body) {
    try {
      const res = await fetch(`${API_BASE}/${endpoint}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });
      if (!res.ok) throw new Error("TTS fetch failed");
      const blob = await res.blob();
      new Audio(URL.createObjectURL(blob)).play();
    } catch (err) {
      console.error(err);
      alert("Could not play example audio. Is backend running?");
    }
  }

  const playExampleWord = (word) => playAudioFromTTS('tts_word', { text: word, lang: langSelect.value });

  async function playPhonemeAudio(lang, phoneme) {
    if (!phoneme || phoneme === '-') return;
    const encoded = encodeURIComponent(phoneme);
    await playAudioFromURL(`${API_BASE}/phoneme_tts/${lang}/${encoded}`);
  }

  async function playWordPhonemesInSequence(lang, phonemes) {
    if (!phonemes || phonemes.length === 0) return;
    phonemePlaybackQueue = phonemePlaybackQueue.then(async () => {
      for (const ph of phonemes) {
        if (ph && ph !== '-') {
          await playPhonemeAudio(lang, ph);
          await new Promise(r => setTimeout(r, 100)); // Pause between phonemes
        }
      }
    });
    await phonemePlaybackQueue;
  }

 async function playUserAudioSlice(startTime, endTime) {
  if (!lastRecordedBlob) {
    alert("No recording available. Please record first!");
    return;
  }
  if (!isFinite(startTime) || !isFinite(endTime) || endTime <= startTime) {
    console.error("Invalid audio slice times:", startTime, endTime);
    return;
  }
  try {
    console.log("Playing slice from:", startTime, "to", endTime); 
    const arrayBuffer = await lastRecordedBlob.arrayBuffer();
    const audioBuffer = await audioContext.decodeAudioData(arrayBuffer);

    const startSample = Math.floor(startTime * audioBuffer.sampleRate);
    const endSample = Math.floor(endTime * audioBuffer.sampleRate);
    const length = endSample - startSample;
    if (length <= 0) return;

    const segmentBuffer = audioContext.createBuffer(
      audioBuffer.numberOfChannels,
      length,
      audioBuffer.sampleRate
    );

    for (let ch = 0; ch < audioBuffer.numberOfChannels; ch++) {
      segmentBuffer.copyToChannel(audioBuffer.getChannelData(ch).slice(startSample, endSample), ch, 0);
    }

    const source = audioContext.createBufferSource();
    source.buffer = segmentBuffer;
    source.connect(audioContext.destination);
    source.start();
  } catch (err) {
    console.error("playUserAudioSlice error:", err);
  }
}


  // Modal
  function showFeedbackModal(data) {
    const score = safeNumber(data.overall_score, 0);
    const emoji = score >= 80 ? '🎉' : score >= 50 ? '👍' : '🤔';
    modalBody.innerHTML = `
      <h2>${emoji} Analysis Complete!</h2>
      <p>Your overall score is <strong>${score.toFixed(1)}%</strong>.</p>
      <p><strong>Volume Check:</strong> ${data.energy_analysis?.feedback || '(unknown)'}</p>
      <hr>
      <p>Review the detailed feedback below to improve specific sounds.</p>
    `;
    modal.style.display = 'block';
    document.body.classList.add('modal-open');
  }

  // Progress tracker (Chart.js)
  function renderProgressChart() {
    const history = JSON.parse(localStorage.getItem('pronunciationHistory')) || [];
    const canvas = document.getElementById('progressChart');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (progressChart) progressChart.destroy();
    progressChart = new Chart(ctx, {
      type: 'line',
      data: {
        labels: history.map(h => h.time),
        datasets: [{
          label: 'Score Over Time',
          data: history.map(h => h.score),
          tension: 0.4,
          fill: true,
          borderColor: '#3498db',
          backgroundColor: 'rgba(52, 152, 219, 0.2)'
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: { y: { beginAtZero: true, max: 100 } }
      }
    });
  }
  function updateProgressTracker(newScore) {
    if (isNaN(newScore)) return;
    let history = JSON.parse(localStorage.getItem('pronunciationHistory')) || [];
    if (history.length >= 50) history.shift();
    history.push({ time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }), score: newScore });
    localStorage.setItem('pronunciationHistory', JSON.stringify(history));
    renderProgressChart();
  }

  // Drill helpers
  function activateDrillMode() {
    requestNextDrillTarget();
  }

  async function requestNextDrillTarget() {
    try {
      const res = await fetch(`${API_BASE}/drill_next`);
      if (res.ok) {
        const json = await res.json();
        if (json && json.target) {
          updateDrillTarget(json.target);
          return;
        }
      }
    } catch (e) {
      console.warn("Could not fetch next drill target from backend, using local fallback.");
    }
    // Fallback if API fails or isn't available
    autoSelectNextDrillFromScore(lastScoreData);
  }
  
  function updateDrillTarget(target) {
    currentDrillTarget = target;
    drillTargetEl.textContent = `${target.type}: ${target.value}`;
  }

  // **FIXED:** Merged duplicate functions into one correct implementation.
  function autoSelectNextDrillFromScore(scoreData) {
    let nextTarget = null;
    if (scoreData && scoreData.words) {
      const phonemeErrors = [];
      scoreData.words.forEach(w => {
        (w.phones || []).forEach(ph => {
          if (ph.expected) {
            phonemeErrors.push({ phoneme: ph.expected, score: safeNumber(ph.score, 100) });
          }
        });
      });
      if (phonemeErrors.length > 0) {
        phonemeErrors.sort((a, b) => a.score - b.score);
        nextTarget = { type: 'phoneme', value: phonemeErrors[0].phoneme };
      }
    }
    
    if (!nextTarget) { // Fallback if no errors or no score data
        const firstWord = (sentenceTextEl.value || '').split(/\s+/)[0];
        nextTarget = { type: 'word', value: firstWord || 'hello' };
    }

    updateDrillTarget(nextTarget);

    if (drillAutoAdvance) {
        setTimeout(() => { // Small delay to not be jarring
            if (nextTarget.type === 'word') playExampleWord(nextTarget.value);
            else playPhonemeAudio(langSelect.value, nextTarget.value);
        }, 300);
    }
  }

  // Phoneme heatmap
  function renderPhonemeHeatmap(list) {
    phonemeHeatmapEl.innerHTML = '';
    list.forEach(ph => {
      if (!ph || ph === '-') return;
      const box = document.createElement('div');
      box.className = 'phoneme-box';
      box.textContent = ph;
      box.onclick = async () => {
        updateDrillTarget({ type: 'phoneme', value: ph });
        await playPhonemeAudio(langSelect.value, ph);
      };
      phonemeHeatmapEl.appendChild(box);
    });
  }

  const defaultPhonemeList = () => [
    "p", "b", "t", "d", "k", "g", "m", "n", "ŋ", "f", "v", "θ", "ð", "s", "z",
    "ʃ", "ʒ", "tʃ", "dʒ", "h", "l", "ɫ", "r", "w", "j", "i", "ɪ", "e", "æ",
    "ɑ", "ɔ", "ʊ", "u", "ʌ", "ə", "aɪ", "aʊ", "oɪ", "eɪ", "oʊ"
  ];
  
  // Helpers
  const getScoreClass = (score) => score >= 80 ? 'score-good' : score >= 50 ? 'score-medium' : 'score-bad';
  const getScoreColor = (score) => score >= 80 ? '#2ecc71' : score >= 50 ? '#f39c12' : '#e74c3c';
  
  // Initial setup
  renderProgressChart();
  renderPhonemeHeatmap(defaultPhonemeList());


    // Window control events
const { minimizeWindow, maximizeWindow, closeWindow } = window.api || {};
document.getElementById('min-btn').addEventListener('click', () => window.api.minimize());
document.getElementById('max-btn').addEventListener('click', () => window.api.maximize());
document.getElementById('close-btn').addEventListener('click', () => window.api.close());


// ------------------------------------------------------------------
// NEW: Centralized Tab Switching Logic for Both Panels
// ------------------------------------------------------------------
document.querySelectorAll('.tab-button').forEach(button => {
    button.addEventListener('click', () => {
        const parentTabContainer = button.closest('.tab-container');
        const targetTabId = button.getAttribute('data-tab');
        const targetTab = document.getElementById(targetTabId);

        // 1. Remove 'active' class from all buttons in the same container
        parentTabContainer.querySelectorAll('.tab-button').forEach(btn => btn.classList.remove('active'));
        
        // 2. Hide all tab content in the same container
        parentTabContainer.querySelectorAll('.tab-content').forEach(content => content.style.display = 'none');
        
        // 3. Add 'active' class to the clicked button
        button.classList.add('active');
        
        // 4. Show the corresponding tab content
        // Use 'flex' for layouts that benefit from vertical spacing (like Coach/Chat)
        if (targetTabId === 'coach-tab' || targetTabId === 'progress-tab') {
            targetTab.style.display = 'flex';
        } else {
            targetTab.style.display = 'block';
        }
    });
});

// Initial Display setup for new tabs
document.getElementById('coach-tab').style.display = 'flex';
document.getElementById('analysis-tab').style.display = 'block'; // Block display for the analysis content

});