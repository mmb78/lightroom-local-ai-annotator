# Local AI Annotator for Lightroom Classic

A robust, highly flexible Lightroom Classic plugin that bridges the gap between your photo catalog and modern Large Language Models (LLMs). 

While originally designed to run entirely on your local machine for **zero API costs** and **100% privacy**, this tool now features a dynamic multi-profile architecture. You can seamlessly switch between free local models (via Ollama, LM Studio, vLLM), remote university/enterprise clusters, or state-of-the-art commercial cloud APIs (like OpenAI and Google Gemini) with a single configuration tweak. It also includes a **standalone interactive sandbox** to test and tune your models without opening Lightroom.

---

## ✨ Key Features

* **The Streamlit Sandbox (NEW):** A standalone web application (`webapp.py`) that lets you interactively test prompts, resolution sizes, LLM profiles, and EXIF injections on individual images before running massive batches in Lightroom. View exactly what the AI sees and returns in real-time.
* **Complete Privacy & Zero Cost (Local Mode):** When using local hardware, your images are never uploaded to Adobe or third-party cloud servers.
* **Multi-Model Profile Switching:** Easily toggle between Local LLMs, remote clusters (like SciCORE), and commercial cloud APIs (OpenAI, Gemini). The script dynamically shape-shifts its API payloads, structured JSON schemas, and parameter handling to perfectly match the strict rules of whatever model you select.
* **Advanced API Tuning per Model:** Define specific API parameters (temperature, frequency penalties, reasoning effort, top_p, dynamic token limits, and even custom `extra_body` parameters like disabling Qwen's `enable_thinking`) directly inside individual model profiles. The worker executes these rules automatically, meaning you never have to touch the core Python logic when new models are released.
* **Deep Diagnostics & Error Logging:** Generates a comprehensive analytics `.tsv` tracking prompt tokens, completion tokens, execution time, geocoding sources, and specific retry reasons per image. Includes an optional toggle to dump the raw, unedited JSON API responses into a text file to easily debug complex AI "reasoning" loops or server-side formatting errors.
* **Safe to Run Multiple Times:** You can safely run this plugin on the exact same batch of photos as many times as you want! Thanks to the persistent caches and smart-skipping logic, it will never duplicate metadata or waste time re-exporting images. It only fills in what is missing (unless you force it to overwrite).
* **Persistent Image Cache:** To save massive amounts of time on subsequent runs, the tool maintains a persistent local cache of exported JPEGs. If you re-process a photo (e.g., trying a different AI prompt), it skips the Lightroom export phase entirely, saving significant time.
* **High-Concurrency Geocoding Cache (SQLite WAL):** The tool automatically converts GPS coordinates into human-readable addresses. To ensure lightning-fast processing, it saves all results to a permanent, local SQLite database. It utilizes **Write-Ahead Logging (WAL)**, allowing hundreds of parallel workers to read the database simultaneously without locking or crashing. 
* **Bulletproof Anti-Stampede & Jitter Logic:** Strictly enforces Nominatim's 1-request-per-second API limit. If dozens of parallel workers hit a timeout simultaneously, intelligent randomized "Jitter" staggers their retries, gracefully re-queuing them and completely eliminating the risk of API IP bans.
* **Concurrent `In-Flight` Memory Cache:** If multiple parallel workers are simultaneously processing photos taken at the exact same location (like a burst shot), the tool uses an intelligent `in_flight` RAM cache. It pauses the workers, sends a single API request, and shares the result across all threads instantly.
* **Blazing Fast Asynchronous Processing:** Run up to 256 concurrent AI requests using modern Python `asyncio`. Maximize your GPU utilization (especially with high-throughput servers like vLLM) by processing dozens of photos simultaneously with incredibly low system overhead.
* **Guaranteed Output Formatting:** Utilizes state-of-the-art "Structured Outputs" (JSON Schema constraint) to mathematically guarantee the LLM returns the exact metadata format required, completely eliminating formatting errors and wasted "reprompt" tokens. Gracefully handles model-specific tool-calling quirks and nested JSON responses.
* **Intelligent Keyword Summarization:** If the AI gets overly enthusiastic and generates too many keywords (exceeding your set max limit), the script automatically spins up a secondary background task to summarize and condense the keywords into a tighter, punchier list.
* **High-Efficiency Pipeline:** The tool bypasses heavy Python image re-encoding by reading Lightroom's freshly exported JPEGs directly into memory. This drastically lowers CPU usage and speeds up inference time.
* **Non-Blocking Background Processing:** The heavy AI analysis runs in a background terminal. You can continue culling, editing, and organizing your catalog in Lightroom without experiencing UI lag.
* **Real-Time Dual Progress Tracking:** Watch a detailed, animated `tqdm` progress bar in the terminal while Lightroom's native UI progress bar smoothly updates in the background via live file-syncing.
* **Smart Skipping & Granular Metadata Protection:** Automatically detects existing metadata. Instead of an all-or-nothing approach, it evaluates Titles, Descriptions, and Keywords individually, preserving your meticulously written custom fields while seamlessly filling in only the missing blanks. You can also choose to force a complete overwrite (which now securely wipes old keywords before applying new ones).
* **Graceful Interruptions (Safe Stop):** If you accidentally start a massive batch, you can safely hit `CTRL+C` in the background terminal. The script will cleanly catch the interrupt, instantly free Lightroom from its waiting loop, wait for active tasks to finish, save your progress, and signal Lightroom to import whatever annotations were successfully completed.
* **Anti-Hang Rescue Protocol:** Robust fail-safes ensure Lightroom never hangs indefinitely. If the background Python environment fails to initialize or crashes unexpectedly, Lightroom's script monitor will automatically detect the failure, trigger a rescue protocol, and gracefully abort.
* **Import Optimizations:** During import, the Lua script utilizes a RAM cache for created keywords to bypass heavy database write-calls, drastically speeding up the application of metadata to your catalog.

---

## 🧠 How It Works (The Architecture)

To bypass Lightroom's restricted Lua environment, this tool uses a parallel "file-system handshake" architecture:
1. **Lightroom (Lua)** checks the Persistent Image Cache. It only exports missing or updated JPEGs to the cache folder, bypassing previously processed images. It then generates a `.tsv` manifest file containing EXIF data and GPS coordinates.
2. **Lightroom** writes a `.bat` file passing your configuration (including the number of parallel workers) and launches the **Python Worker** in the background. Lightroom then goes to "sleep," checking the folder every second with builtin timeout fail-safes.
3. **Python** reads the manifest and spins up an Asynchronous Event Loop. It first checks the local SQLite Database for cached GPS addresses. If missing, it uses strict Double-Checked Locking and Smart Sleeping to get addresses from the Nominatim API one by one safely.
4. **Python** extracts your chosen LLM Profile from `config.py`. It concurrently sends the raw image bytes, context, and dynamic profile parameters to your designated API endpoint without blocking the system.
5. **Python** validates the AI's output using strict JSON schemas, requests keyword summarization if necessary, updates a `progress.txt` file for Lightroom to read, and safely locks to write the finalized metadata to a `results.tsv` file.
6. **Python** writes a `done.txt` flag and exits upon completion.
7. **Lightroom** sees the flag, wakes up, ingests the TSV data directly into your catalog, and deletes the temporary batch files (while safely leaving your persistent Image Cache and SQLite Database intact for future runs).

---

## 🛠️ Prerequisites

Before installing the plugin, ensure you have the following set up on your Windows machine:

1. **Adobe Lightroom Classic** (Version 8.0 or later).
2. **Windows OS** (Currently uses `.bat` files for execution).
3. **Python 3.8+** (Anaconda or Miniconda is highly recommended for managing environments).
4. **A Vision LLM Server OR Cloud API Key:** * *Local/Remote:* A server running a Vision-capable model (like LLaVA, Qwen-VL, or Gemma) that exposes an OpenAI-compatible API endpoint (e.g., vLLM, Ollama, LM Studio).
   * *Cloud:* An active API key for OpenAI (GPT-4o) or Google Gemini.
5. **Python Dependencies:** Install the required packages in your Python environment by running this command: 
   `pip install openai geopy pydantic tqdm filelock streamlit pillow`

---

## 📦 Installation & Setup

This tool consists of two distinct parts: the **Lightroom Plugin** and the **Python Worker Script**.

### Part 1: Installing the Lightroom Plugin
1. Create a folder on your computer and name it exactly `AIAnnotate.lrplugin`. (The `.lrplugin` extension tells Lightroom this is a plugin).
2. Place the following three files inside this folder:
   * `Info.lua`
   * `AIAnnotate.lua`
   * `user_config.lua`
3. Open `user_config.lua` in a text editor. 
   * Adjust the `condaActivatePath` to point to your specific Python or Anaconda installation script.
   * You can customize the default parallel worker count and the names/locations of your persistent cache folders (e.g., nesting them inside a `_Cache_Data/` directory).
4. Open Lightroom Classic. Go to **File > Plug-in Manager...**
5. Click **Add** in the bottom left corner, navigate to, and select your `AIAnnotate.lrplugin` folder. Ensure the status reads "Installed and Running."

### Part 2: Setting up the Python Worker
1. Create a permanent, safe folder for your scripts on your hard drive (e.g., `C:\Scripts\AI_Annotator\`).
2. Place the following three files inside this folder:
   * `AI_Annotate_Worker.py`
   * `config.py`
   * `webapp.py`
3. Open `config.py` in a text editor. 
   * Set your `ACTIVE_LLM_PROFILE` (e.g., `0` for Local, `1` for Remote Cluster, `2` for OpenAI, `3` for Gemini).
   * Inside the `LLM_PROFILES` array, configure your models. Update the `model` name, `base_url`, `api_key`, and customize the `api_params` dictionary to perfectly tune the model's behavior.
   * *Optional:* Fine-tune your geocoding database filenames, jitter settings, and pauses in the Geocoding Settings block.

---

## 🧪 The Streamlit Sandbox (Interactive Testing)

Before running massive batches in Lightroom, use the Webapp Sandbox to test how your specific models respond to your prompts, resolution limits, and EXIF injections without waiting for Lightroom exports.

1. Open your Anaconda Prompt or command line.
2. Activate your environment and navigate to your Python script folder.
3. Run the following command:
   `streamlit run webapp.py`
4. A browser window will automatically open. From here, you can:
   * Upload test images and dynamically resize them on the fly.
   * Switch between the LLM profiles defined in your `config.py`.
   * Edit system/user prompts and EXIF context injection live.
   * View the exact JSON payload sent to the server and the raw token statistics.

---

## 🚀 Daily Usage Guide (All Settings Explained)

1. **Select Photos:** In Lightroom's Library module (Grid View), select one or more photos you want to annotate.
2. **Launch the Tool:** Navigate to the top menu bar and click **Library > Plug-in Extras > Generate AI Metadata**.
3. **Configure the Run:** A dialog box will appear with the following settings:
   * **Temp Root Folder:** Choose a processing location (like your Desktop). The plugin creates your persistent caches and temporary batch folders here.
   * **Python Script Path:** Browse and select your `AI_Annotate_Worker.py` file.
   * **Force re-export:** Check this to ignore the persistent image cache and force Lightroom to generate fresh JPEGs (useful if you have heavily edited the image since the last run).
   * **Export Quality:** *Small (1024px)* is recommended for most vision models for max speed. Higher resolutions (like *Gemma4 (1920px)*, or the expanded *Qwen3.6 series up to 5040px*) take longer to process but provide much better detail for models that support massive native aspect ratios.
   * **Overwrite Existing Data:** Check this to force the AI to completely overwrite any existing Title, Description, and Keywords (safely stripping old tags before applying the new hierarchy). Leave unchecked to smartly preserve your manual edits and only let the AI fill in empty fields.
   * **Enable Reverse Geocoding:** Check this to query the Nominatim API and convert raw GPS coordinates into human-readable City, State, and Country tags.
   * **Skip geocoding if photo already has Location data:** If enabled, the script skips the API/Database check if you have already manually entered a full address into Lightroom.
   * **Parallel Prompts (1-256):** Set the number of concurrent asynchronous requests to send to your LLM (e.g., 4-8 for standard GPUs, or 25+ if using vLLM or Cloud APIs).
   * **Cleanup - Delete temporary folder after processing:** Automatically deletes the specific batch folder when finished to keep your drive clean. *(Note: This safely leaves the image and geocoding caches entirely intact).*
4. **Process:** Click **OK**.
   * Lightroom will display a brief progress bar as it exports JPEGs (or instantly skip if cached).
   * A Command Prompt window will open in the background, logging the AI's progress with an animated `tqdm` bar.
   * **You can continue working in Lightroom!** Check the live-updating progress bar in the top-left corner of the Lightroom UI.
5. **Completion:** Once finished, the Command Prompt will close itself. Lightroom will ingest the generated metadata, clean up the temporary batch files, and display a success popup detailing how many photos were updated.

---

## 🛑 Safe Interruption (Stopping a Job Early)

If you start a massive batch of 1,000 photos and realize you need to shut down your computer, you can stop the process without losing the work the AI has already completed.

1. Bring the black Python Command Prompt window to the front of your screen.
2. Press `CTRL+C` on your keyboard. 
3. If Windows asks "Terminate batch job (Y/N)?", type `Y` and press Enter.
4. The Python script will catch the interruption, instantly free Lightroom from its background waiting loop, wait for any currently active API requests to finish, save all completed annotations to the results file, and signal Lightroom to import the partial batch.
5. Wait a few seconds for Lightroom to process the partial import and clean up the temporary folder.

*⚠️ **Do NOT click the "X"** to close the command prompt. Windows will instantly kill the process without saving. If you do accidentally close it (or if it crashes entirely), the new Lightroom fail-safes allow you to simply click the "X" on the Lightroom background progress bar in the top-left corner. This will trigger a "rescue" protocol and force Lightroom to import whatever partial data was saved before the crash.*

---

## 🔧 Advanced Configuration & Diagnostics

You can deeply customize how the AI behaves and debug issues without ever touching the core logic files. 

* **Model Profiling & Parameter Tuning:** In `config.py`, the `LLM_PROFILES` array lets you define endless API endpoints. Inside the `api_params` dictionary for each profile, you can inject settings like `temperature`, `frequency_penalty`, `reasoning_effort`, or even custom dictionary entries like `extra_body` to adjust model-specific behaviors (like disabling `enable_thinking`). The worker script will automatically map these rules to the current active profile.
* **Debugging AI Reasoning & Errors:** In `config.py`, set `LOG_RAW_RESPONSES = 1`. This will generate a `raw_responses.txt` file directly inside your temporary batch folder. It captures the unedited, raw JSON response from the server for every analyzed image. This is invaluable for debugging "Reasoning Paralysis" in models like Qwen or o1, tracking exact token usage, or viewing hidden `tool_call` behaviors in open-source servers.
* **To change UI Defaults & Folder Structures:** Open `user_config.lua`. You can change the default export size, worker count, overwrite behavior, and even define nested, cross-platform folder structures for your caches (e.g., `_Cache_Data/Images`).