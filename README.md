# RIO (Responsive Intelligent Operator) — v1.0

A minimal, stable, and hardened AI computer assistant designed for reliability and simplicity.

---

## 🎯 Features (Version 1.0)
- **Minimal Core**: stripped down to essential functions for zero-crash stability.
- **Hardened Brain**: Multi-strategy JSON parsing ensures LLM outputs never break the system.
- **Guardrails**: Input validation prevents malicious shell injections and dangerous file operations.
- **Text-Only I/O**: Efficient terminal-based interaction.
- **PC Control**: Seamlessly opens apps, searches the web, and handles basic file operations.

---

## 🛠️ Quick Start

### 1. Prerequisites
- **Python 3.10+**
- **Ollama**: Download and install from [ollama.com](https://ollama.com).
- **LLM Model**: Pull the default model:
  ```bash
  ollama pull llama3
  ```

### 2. Installation
Clone this repository and install the dependencies:
```bash
py -3 -m pip install -r requirements.txt
```

### 3. Run RIO
Ensure Ollama is running (`ollama serve`), then start the assistant:
```bash
py -3 main.py
```

---

## 🏗️ Architecture
RIO is divided into 4 minimal modules:
- **`core/`**: Simple colored logging system.
- **`brain/`**: LLM integration, prompt engineering, and hardened JSON parsing.
- **`agent/`**: The execution engine that dispatches intents to local actions.
- **`actions/`**: The "hands" of the assistant (App control, Web search, File operations).

---

## 🛡️ Stability & Safety
- **Anti-Crash**: Every module uses defensive programming to handle malformed LLM responses.
- **Path Traversal Protection**: Files cannot be read or created outside the designated `~/Desktop` directory via RIO.
- **Injection Protection**: Shell metacharacters are blocked to prevent command injection.
- **Fallbacks**: If a command is misunderstood, RIO returns a graceful "Did not understand" message rather than crashing.

---

## 📦 Version History
- **v1.0**: Initial stable release. Minimal, text-only, hardened.
- **Next Up (v2.0)**: Plans for Voice STT/TTS integration, Mobile API bridge, and Memory context.

---

## 📜 License
MIT License. Feel free to use and modify!
