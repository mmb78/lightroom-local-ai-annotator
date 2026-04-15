# Local AI Annotator for Lightroom Classic

A robust, privacy-first Lightroom Classic plugin that bridges the gap between your local photo catalog and modern Large Language Models (LLMs). 

This tool uses a local Python worker to automatically analyze your photos and generate high-quality titles, captions (descriptions), and keywords. Because it runs entirely on your local machine using an OpenAI-compatible API (via tools like Ollama, LM Studio, or vLLM), there are **zero API costs**, **no internet connection required for the AI**, and your photos remain **100% private**.

---

## ✨ Key Features

* **Complete Privacy & Zero Cost:** All AI processing happens on your local hardware. Your images are never uploaded to Adobe or third-party cloud servers.
* **Persistent Image Cache:** To save massive amounts of time on subsequent runs, the tool maintains a persistent local cache of exported JPEGs. If you re-process a photo (e.g., trying a different AI prompt), it skips the Lightroom export phase entirely, saving significant time!
* **High-Concurrency Geocoding Cache (SQLite WAL):** The tool automatically converts GPS coordinates into human-readable addresses. To ensure lightning-fast processing, it saves all results to a permanent, local SQLite database. It utilizes **Write-Ahead Logging (WAL)**, allowing hundreds of parallel workers to read the database simultaneously without locking or crashing. 
* **Bulletproof Anti-Stampede & Jitter Logic:** Strictly enforces Nominatim's 1-request-per-second API limit. If dozens of parallel workers hit a timeout simultaneously, intelligent randomized "Jitter" staggers their retries, gracefully re-queuing them and completely eliminating the risk of API IP bans.
* **Concurrent `In-Flight` Memory Cache:** If multiple parallel workers are simultaneously processing photos taken at the exact same location (like a burst shot), the tool uses an intelligent `in_flight` RAM cache. It pauses the workers, sends a single API request, and shares the result across all threads instantly.
* **Blazing Fast Asynchronous Processing:** Run up to 256 concurrent AI requests using modern Python `asyncio`. Maximize your GPU utilization (especially with high-throughput servers like vLLM) by processing dozens of photos simultaneously with incredibly low system overhead.
* **Guaranteed Output Formatting:** Utilizes state-of-the-art "Structured Outputs" (JSON Schema constraint) to mathematically guarantee the LLM returns the exact metadata format required, completely eliminating formatting errors and wasted "reprompt" tokens.
* **Intelligent Keyword Summarization:** If the AI gets overly enthusiastic and generates too many keywords (exceeding your set max limit), the script automatically spins up a secondary background task to summarize and condense the keywords into a tighter, punchier list.
* **High-Efficiency Pipeline:** The tool bypasses heavy Python image re-encoding by reading Lightroom's freshly exported JPEGs directly into memory. This drastically lowers CPU usage and speeds up inference time.
* **Non-Blocking Background Processing:** The heavy AI analysis runs in a background terminal. You can continue culling, editing, and organizing your catalog in Lightroom without experiencing UI lag.
* **Real-Time Dual Progress Tracking:** Watch a detailed, animated `tqdm` progress bar in the terminal while Lightroom's native UI progress bar smoothly updates in the background via live file-syncing.
* **Smart Skipping & Granular Metadata Protection:** Automatically detects existing metadata. Instead of an all-or-nothing approach, it evaluates Titles, Descriptions, and Keywords individually, preserving your meticulously written custom fields while seamlessly filling in only the missing blanks. You can also choose to force a complete overwrite.
* **Graceful Interruptions (Safe Stop):** If you accidentally start a massive batch, you can safely hit `CTRL+C` in the background terminal. The script will cleanly catch the interrupt, instantly free Lightroom from its waiting loop, wait for active tasks to finish, save your progress, and signal Lightroom to import whatever annotations were successfully completed.
* **Anti-Hang Rescue Protocol:** Robust fail-safes ensure Lightroom never hangs indefinitely. If the background Python environment fails to initialize or crashes unexpectedly, Lightroom's script monitor will automatically detect the failure, trigger a rescue protocol, and gracefully abort.
* **Detailed Analytics & Import Optimizations:** Automatically tracks generation times, true prompt tokens, and attempts, appending a final batch summary to your TSV file. During import, the Lua script utilizes a RAM cache for created keywords to bypass heavy database write-calls, drastically speeding up the application of metadata to your catalog.

---

## 🧠 How It Works (The Architecture)

To bypass Lightroom's restricted Lua environment, this tool uses a parallel "file-system handshake" architecture:
1. **Lightroom (Lua)** checks the Persistent Image Cache. It only exports missing or updated JPEGs to the cache folder, bypassing previously processed images. It then generates a `.tsv` manifest file containing EXIF data and GPS coordinates.
2. **Lightroom** writes a `.bat` file passing your configuration (including the number of parallel workers) and launches the **Python Worker** in the background. Lightroom then goes to "sleep," checking the folder every second with built-in timeout fail-safes.
3. **Python** reads the manifest and spins up an Asynchronous Event Loop. It first checks the local SQLite Database for cached GPS addresses. If missing, it uses strict Double-Checked Locking and Smart Sleeping to get addresses from the Nominatim API one by one safely.
4. **Python** concurrently sends the raw image bytes and context to your local LLM vision model without blocking the system.
5. **Python** validates the AI's output using JSON schemas, requests keyword summarization if necessary, updates a `progress.txt` file for Lightroom to read, and safely locks to write the finalized metadata to a `results.tsv` file.
6. **Python** writes a `done.txt` flag and exits upon completion.
7. **Lightroom** sees the flag, wakes up, ingests the TSV data directly into your catalog, and deletes the temporary batch files (while safely leaving your persistent Image Cache and SQLite Database intact for future runs).

---

## 🛠️ Prerequisites

Before installing the plugin, ensure you have the following set up on your Windows machine:

1. **Adobe Lightroom Classic** (Version 8.0 or later).
2. **Windows OS** (Currently uses `.bat` files for execution).
3. **Python 3.8+** (Anaconda or Miniconda is highly recommended for managing environments).
4. **A Local Vision LLM Server:** You need a local server running a Vision-capable model (like LLaVA, Llama-3.2-Vision, or Gemma 3) that exposes an OpenAI-compatible API endpoint. *vLLM*, *Ollama*, or *LM Studio* are recommended.
5. **Python Dependencies:** Install the required packages in your Python environment by running this command: 
   `pip install openai geopy pydantic tqdm filelock`

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
2. Place the following two files inside this folder:
   * `AI_Annotate_Worker.py`
   * `config.py`
3. Open `config.py` in a text editor. 
   * Update the `LOCAL_LLM_MODEL` to the exact name of the model you have downloaded.
   * Ensure the `BASE_URL` matches your local server's endpoint (e.g., `http://127.0.0.1:11434/v1` for standard Ollama). 
   * *Optional:* Fine-tune your geocoding database filenames, jitter settings, and pauses in the Geocoding Settings block.

---

## 🚀 Daily Usage Guide (All Settings Explained)

1. **Select Photos:** In Lightroom's Library module (Grid View), select one or more photos you want to annotate.
2. **Launch the Tool:** Navigate to the top menu bar and click **Library > Plug-in Extras > Generate AI Metadata**.
3. **Configure the Run:** A dialog box will appear with the following settings:
   * **Temp Root Folder:** Choose a processing location (like your Desktop). The plugin creates your persistent caches and temporary batch folders here.
   * **Python Script Path:** Browse and select your `AI_Annotate_Worker.py` file.
   * **Force re-export:** Check this to ignore the persistent image cache and force Lightroom to generate fresh JPEGs (useful if you have heavily edited the image since the last run).
   * **Export Quality:** *Small (1024px)* is recommended for most vision models for max speed. Higher resolutions (like *Gemma4 (1920px)* or *High (3000px)*) take longer to process but provide better detail for models that support native aspect ratios.
   * **Overwrite Existing Data:** Check this to force the AI to completely overwrite any existing Title, Description, and Keywords. Leave unchecked to smartly preserve your manual edits and only let the AI fill in empty fields.
   * **Enable Reverse Geocoding:** Check this to query the Nominatim API and convert raw GPS coordinates into human-readable City, State, and Country tags.
   * **Skip geocoding if photo already has Location data:** If enabled, the script skips the API/Database check if you have already manually entered a full address into Lightroom.
   * **Parallel Prompts (1-256):** Set the number of concurrent asynchronous requests to send to your LLM (e.g., 4-8 for standard GPUs, or 25+ if using vLLM).
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

## 🔧 Advanced Configuration & Tuning

You can deeply customize how the AI behaves without ever touching the core logic files. 

* **To change UI Defaults & Folder Structures:** Open `user_config.lua`. You can change the default export size, worker count, overwrite behavior, and even define nested, cross-platform folder structures for your caches (e.g., `_Cache_Data/Images`).
* **To change Prompts & AI Constraints:** Open `config.py`. Here you can alter the system prompts, adjust the strictness of the LLM (`LLM_TEMPERATURE`), change the maximum allowed keywords, or fine-tune how the script handles edge cases if the AI fails to generate enough keywords.