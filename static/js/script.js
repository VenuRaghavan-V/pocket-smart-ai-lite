/* ==========================================================================
   Pocket Smart AI - frontend logic
   - Text chat
   - Voice input via the browser's native Web Speech API
   - Automatic language badge shown per AI reply
   - Loads chat history on page load
   - PDF upload + RAG question answering
   - Speaker button to read AI replies aloud (cute voice)
   ========================================================================== */

const chatWindow = document.getElementById("chatWindow");
const textInput = document.getElementById("textInput");
const sendBtn = document.getElementById("sendBtn");
const micBtn = document.getElementById("micBtn");
const newChatBtn = document.getElementById("newChatBtn");
const typingIndicator = document.getElementById("typingIndicator");
const statusLine = document.getElementById("statusLine");
const langToggle = document.getElementById("langToggle");

const pdfBtn = document.getElementById("pdfBtn");
const pdfFileInput = document.getElementById("pdfFileInput");
const pdfStatusBar = document.getElementById("pdfStatusBar");
const pdfStatusText = document.getElementById("pdfStatusText");

let voiceLang = "en-IN"; // used only for the speech recognizer's target language

/* ---------------- Rendering helpers ---------------- */

function scrollToBottom() {
  chatWindow.scrollTop = chatWindow.scrollHeight;
}

function addBubble(role, text, languageLabel, langCode) {
  const bubble = document.createElement("div");
  bubble.className = `bubble ${role === "user" ? "user-bubble" : "bot-bubble"}`;

  if (role !== "user") {
    const avatar = document.createElement("img");
    avatar.src = "/static/img/mascot.svg";
    avatar.className = "bubble-avatar";
    bubble.appendChild(avatar);
  }

  const content = document.createElement("div");
  content.className = "bubble-content";
  content.textContent = text;

  if (languageLabel) {
    const tag = document.createElement("div");
    tag.className = "lang-tag";
    tag.textContent = languageLabel;
    content.appendChild(tag);
  }

  // Speaker button - only for AI replies, reads the reply out loud
  if (role !== "user") {
    const speakBtn = document.createElement("button");
    speakBtn.className = "speak-btn";
    speakBtn.type = "button";
    speakBtn.title = "Listen to this reply";
    speakBtn.textContent = "🔊";
    speakBtn.addEventListener("click", () => speakText(text, langCode));
    content.appendChild(speakBtn);
  }

  bubble.appendChild(content);
  chatWindow.appendChild(bubble);
  scrollToBottom();
}

function setTyping(isTyping) {
  typingIndicator.classList.toggle("hidden", !isTyping);
  if (isTyping) scrollToBottom();
}

/* ---------------- Text-to-Speech (speaker button, cute voice) ---------------- */

let cachedVoices = [];
if ("speechSynthesis" in window) {
  window.speechSynthesis.addEventListener("voiceschanged", () => {
    cachedVoices = window.speechSynthesis.getVoices();
  });
}

function pickCuteVoice(langCode) {
  const voices = cachedVoices.length ? cachedVoices : window.speechSynthesis.getVoices();
  const wantTamil = langCode === "ta";

  const langMatches = voices.filter(v =>
    wantTamil ? v.lang.toLowerCase().includes("ta") : v.lang.toLowerCase().startsWith("en")
  );

  const preferredNames = ["female", "woman", "girl", "child", "zira", "samantha", "google uk english female"];
  const cuteMatch = langMatches.find(v =>
    preferredNames.some(name => v.name.toLowerCase().includes(name))
  );

  return cuteMatch || langMatches[0] || voices[0] || null;
}

function speakText(text, langCode) {
  if (!("speechSynthesis" in window)) {
    alert("Voice playback isn't supported in this browser.");
    return;
  }
  window.speechSynthesis.cancel();

  const voices = cachedVoices.length ? cachedVoices : window.speechSynthesis.getVoices();
  const wantTamil = langCode === "ta";

  if (wantTamil) {
    const hasTamilVoice = voices.some(v => v.lang.toLowerCase().includes("ta"));
    if (!hasTamilVoice) {
      alert(
        "இந்த device-la Tamil voice install pannala. " +
        "Windows Settings → Time & Language → Speech → Add voices → Tamil (India) install pannunga."
      );
      return;
    }
  }

  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = wantTamil ? "ta-IN" : "en-IN";

  const voice = pickCuteVoice(langCode);
  if (voice) utterance.voice = voice;

  utterance.pitch = 1.6;
  utterance.rate = 1.05;
  utterance.volume = 1;

  utterance.onerror = (e) => {
    console.error("Speech synthesis error:", e.error);
  };

  window.speechSynthesis.speak(utterance);
}
/* ---------------- History ---------------- */

async function loadHistory() {
  try {
    const res = await fetch("/api/history");
    const data = await res.json();
    (data.history || []).forEach(item => {
      addBubble(item.role, item.message, null, item.language);
    });
  } catch (err) {
    console.error("Failed to load history:", err);
  }
}

/* ---------------- PDF status / upload ---------------- */

function showPdfStatus(text, isError) {
  pdfStatusBar.classList.remove("hidden");
  pdfStatusText.textContent = text;
  pdfStatusBar.classList.toggle("pdf-status-error", !!isError);
}

async function refreshPdfStatus() {
  try {
    const res = await fetch("/api/pdf-status");
    const data = await res.json();
    if (data.pdf_uploaded) {
      showPdfStatus("📄 A PDF is loaded - ask me anything about it!", false);
    }
  } catch (err) {
    console.error("Failed to check PDF status:", err);
  }
}

pdfBtn.addEventListener("click", () => pdfFileInput.click());

pdfFileInput.addEventListener("change", async () => {
  const file = pdfFileInput.files[0];
  if (!file) return;

  if (file.type !== "application/pdf") {
    showPdfStatus("Only PDF files are supported.", true);
    pdfFileInput.value = "";
    return;
  }

  showPdfStatus(`Uploading "${file.name}"...`, false);
  statusLine.textContent = "Reading your PDF... 📄";

  const formData = new FormData();
  formData.append("pdf_file", file);

  try {
    const res = await fetch("/upload_pdf", { method: "POST", body: formData });
    const data = await res.json();

    if (data.success) {
      showPdfStatus(`📄 "${file.name}" is ready - ask me anything about it!`, false);
      addBubble("assistant", `I've read "${file.name}". Ask me anything about it! 📄✨`);
    } else {
      showPdfStatus(data.message || "Could not process that PDF.", true);
    }
  } catch (err) {
    console.error(err);
    showPdfStatus("Upload failed - please try again.", true);
  } finally {
    statusLine.textContent = `${document.title} is ready to chat ✨`;
    pdfFileInput.value = "";
  }
});

/* ---------------- Sending messages ---------------- */

async function sendMessage(message) {
  if (!message || !message.trim()) return;

  addBubble("user", message);
  textInput.value = "";
  setTyping(true);
  statusLine.textContent = "Sparko is thinking...";

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message })
    });
    const data = await res.json();

    setTyping(false);

    if (data.error) {
      addBubble("assistant", `Oops! ${data.error}`);
      statusLine.textContent = "Something went wrong 😔";
      return;
    }

    addBubble("assistant", data.reply, data.language_label, data.language);
    statusLine.textContent = "Sparko is ready to chat ✨";
  } catch (err) {
    setTyping(false);
    addBubble("assistant", "I couldn't reach the server. Please try again!");
    statusLine.textContent = "Connection error 😔";
    console.error(err);
  }
}

sendBtn.addEventListener("click", () => sendMessage(textInput.value));
textInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") sendMessage(textInput.value);
});

/* ---------------- New chat ---------------- */

newChatBtn.addEventListener("click", async () => {
  await fetch("/api/clear", { method: "POST" });
  chatWindow.innerHTML = "";
  addBubble("assistant", "Fresh start! What would you like to talk about?");
});

/* ---------------- Voice language toggle ---------------- */

langToggle.querySelectorAll(".lang-option").forEach(btn => {
  btn.addEventListener("click", () => {
    langToggle.querySelectorAll(".lang-option").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    voiceLang = btn.dataset.lang;
  });
});

/* ---------------- Voice input (Web Speech API) ---------------- */

const SpeechRecognitionAPI = window.SpeechRecognition || window.webkitSpeechRecognition;
let recognizer = null;
let isRecording = false;

if (SpeechRecognitionAPI) {
  recognizer = new SpeechRecognitionAPI();
  recognizer.continuous = false;
  recognizer.interimResults = false;

  recognizer.onstart = () => {
    isRecording = true;
    micBtn.classList.add("recording");
    statusLine.textContent = "Listening... 🎤";
  };

  recognizer.onresult = (event) => {
    const transcript = event.results[0][0].transcript;
    sendMessage(transcript);
  };

  recognizer.onerror = (event) => {
    console.error("Speech recognition error:", event.error);
    statusLine.textContent = "Didn't catch that - try again!";
  };

  recognizer.onend = () => {
    isRecording = false;
    micBtn.classList.remove("recording");
  };

  micBtn.addEventListener("click", () => {
    if (isRecording) {
      recognizer.stop();
      return;
    }
    recognizer.lang = voiceLang;
    recognizer.start();
  });
} else {
  micBtn.addEventListener("click", () => {
    alert(
      "Voice input isn't supported in this browser. Try Chrome/Edge, " +
      "or on Android - or ask your instructor about enabling the " +
      "optional server-side voice fallback (see core/voice_fallback.py)."
    );
  });
}

/* ---------------- Init ---------------- */
loadHistory();
refreshPdfStatus();