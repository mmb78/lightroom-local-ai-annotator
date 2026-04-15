# ==============================================================================
# AI ANNOTATOR: PYTHON WORKER CONFIGURATION
# ==============================================================================

# --- NETWORK & API SETTINGS ---
LOCAL_LLM_MODEL = "google/gemma-4-26B-A4B-it" # "gemma-4-31B-it", "llama-3.2-vision"
BASE_URL = "http://127.0.0.1:11434/v1" # replace with address to you LLM server

# -- FILE NAMES
GEO_DB_FILENAME = "geocoding_cache.db"
GEO_LOCK_FILENAME = "nominatim_api.lock"
GEO_TRACKER_FILENAME = "last_api_call.txt"

# --- LLM PARAMETERS ---
MAX_TOKENS = 1000
LLM_TEMPERATURE = 1
LLM_TOP_P = 0.95
SEEDS = [1, 5, 10, 50, 100, 500, 1000, 5000, 10000, 50000]

# --- KEYWORD LIMITS ---
MIN_KEYWORDS = 5
MAX_KEYWORDS = 50

# --- SYSTEM & MAIN PROMPTS ---
SYSTEM_PROMPT = "You are an expert photography archivist and metadata tagger. Your job is to analyze images and generate highly accurate, searchable, and professional descriptions, titles, and keywords. You must strictly adhere to the provided JSON schema."

PROMPT_DESCRIPTION = """Provide a comprehensive, extensive and detailed description of what is in the image.
Identify and decode all texts in the image and report the texts in the image description. If you recognize no text in the image, do not mention this.
Return a descriptive title for the image.
Return a limited list of up to 30 of the most important keywords. 
Do not include any additional text or characters."""

# --- EXIF CONTEXT PROMPTS ---
# Note: {date_time} and {address} will be dynamically injected by the script. Do not remove the curly braces.
EXIF_PROMPT_FULL = "\nThe image was taken on {date_time} at {address}. Use this information to provide an accurate description of the image (for example to identify buildings, rivers, streets, sunrise/sunset), but the detailed address or the exact time and date does not need to be included in the title, description, or keywords."

EXIF_PROMPT_DATE_ONLY = "\nThe image was taken on {date_time}. This information can be used to provide an accurate description of the image (for example to identify sunset/sunrise), but the exact time and date does not need to be included in the title, description, or keywords."

# --- ERROR HANDLING / REPROMPTING TEXTS ---
REPROMPT_TEXT = "Your answer was returned in a wrong format. You have to strictly follow the format and order as defined by the supplied tools."

SUMMARIZE_SYSTEM_PROMPT = "Read the list of keywords describing an image that are separated by semicolon. Return a shorter list separated by semicolon (;). Respond concisely, without any introductory or concluding phrases. Output will be parsed by a script."

SUMMARIZE_USER_PROMPT = "Include only the most distinct keywords in the following list, remove duplications.\n"

# --- GEOCODING SETTINGS ---
GEO_USER_AGENT = "lr_local_ai_annotator_v1"
GEO_RATE_LIMIT_PAUSE = 1             # Seconds to wait between normal Geocoding calls (Nominatim requires > 1.0s)
GEOCODING_PAUSES = [10, 30, 120, 300]  # Seconds to wait between retries if Geocoding fails


# ==========================================
# ADVANCED: CLOUD FALLBACK (OPENAI)
# ==========================================
# If your computer cannot run local Vision models, you can optionally use the official OpenAI API.
# Warning: This costs money and requires an active internet connection.
LOCAL_LLM = 1                           # Change to 0 to use the official OpenAI API instead of your local server
OPENAI_API_KEY = ""                     # Paste your sk-... key here if LOCAL_LLM is set to 0
OPENAI_FALLBACK_MODEL = "gpt-5.4-nano"   # Model used if LOCAL_LLM = 0
