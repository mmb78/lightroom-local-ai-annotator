# ==============================================================================
# AI ANNOTATOR: PYTHON WORKER CONFIGURATION
# ==============================================================================

import os

# --- NETWORK & API SETTINGS ---
# Select which profile to use (0 = Local, 1 = Remote, 2 = OpenAI)
ACTIVE_LLM_PROFILE = 1

# --- LLM PARAMETERS ---
MAX_TOKENS = 5000 # this is just a fallback, the actual numbers defined for each model are used
SEEDS = [1, 5, 10, 50, 100] # each is tried max 5x
LOG_RAW_RESPONSES = 1 # "1" for an extra text file with raw outputs from the model

LLM_PROFILES = [
    # [0] Primary "Local" Server
    {
        "name": "Gemma4 26B",
        "base_url": "http://localhost:8000/v1",
        "api_key": "local-llm-key", # Required by OpenAI library, but ignored by local servers
        "model": "google/gemma-4-26B-A4B-it",
        "api_params": {
            "temperature": 1,
            "top_p": 0.95,
            "max_tokens": 1500,
            "seed": None  # <--- Placeholder: Tells the worker this model accepts seeds!
        }
    },
    # [1] Secondary "Local" Server
    {
        "name": "Qwen3.6 35B",
        "base_url": "http://localhost:11434/v1",
        "api_key": "local-llm-key", # Required by OpenAI library, but ignored by local servers
        "model": "Qwen/Qwen3.6-35B-A3B-FP8",
        "api_params": {
            "temperature": 0.7,
            "top_p": 0.8,
            "presence_penalty": 1.5,
            "max_tokens": 1500,
            "extra_body": {
                "top_k": 20,
                "min_p": 0.0,
                "repetition_penalty": 1.0,
                "chat_template_kwargs": {"enable_thinking": False}
                },
            "seed": None  # <--- Placeholder: Tells the worker this model accepts seeds!
        }
    },
    # [2] Secondary Remote Server - a thinking model!
    {
        "name": "Qwen 3.5 397B",
        "base_url": os.getenv("LITELLM_API_BASE", "localhost"), # Your alternative port/IP from OS env
        "api_key": os.getenv("LITELLM_API_KEY", ""),
        "model": "qwen35-397b-a17b-fp8",
        "api_params": {
            "temperature": 0.7,         # <--- BUMP TO 0.7: Breaks the overthinking loop!
            "top_p": 0.9,               # <--- BUMP TO 0.9: Allows broader thinking paths
            "frequency_penalty": 0.5,   # <--- ADD THIS: Punishes the AI for repeating the same words
            "reasoning_effort": "low", # Can be "low", "medium", or "high"
            "max_tokens": 10000,
            "presence_penalty": 0.5, # Encourages broader vocabulary
            "frequency_penalty": 0.3, # Stops repetitive keyword looping
            "timeout": 45.0, # If the server doesn't reply in 45 seconds, kill it and retry!
            "seed": None  # <--- Placeholder: Tells the worker this model accepts seeds!
        }
    },
    # [3] OpenAI Cloud
    {
        "name": "OpenAI GPT-5.4",
        "base_url": None, # Leaving this None tells the client to use the official OpenAI URL
        "api_key": os.getenv("OPENAI_API_KEY", ""),
        "model": "gpt-5.4-nano", # Or whatever OpenAI model you prefer
        "api_params": {
            "temperature": 1.0,
            "reasoning_effort": "low", # Can be "low", "medium", or "high"
            "max_completion_tokens": 1500,
            "seed": None  # <--- Placeholder: Tells the worker this model accepts seeds!
        }
    },
    # [4] Google Gemini API - no SEED parameter
    {
        "name": "Gemini 3.1 Flash Lite",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "api_key": os.getenv("GEMINI_API_KEY", ""),
        "model": "gemini-3.1-flash-lite-preview",
        "api_params": {
            "temperature": 1,
            "top_p": 0.95,
            "max_tokens": 1500
        }
    }
]


# -- FILE NAMES
GEO_DB_FILENAME = "geocoding_cache.db"
GEO_LOCK_FILENAME = "nominatim_api.lock"
GEO_TRACKER_FILENAME = "last_api_call.txt"

# --- KEYWORD LIMITS ---
MIN_KEYWORDS = 5
MAX_KEYWORDS = 50

# --- SYSTEM & MAIN PROMPTS ---
SYSTEM_PROMPT = "You are an expert photography archivist and metadata tagger. Your job is to carefully analyze images and generate highly accurate, searchable, and professional descriptions, titles, and keywords. You must strictly adhere to the provided JSON schema."

PROMPT_DESCRIPTION = """Provide a comprehensive, extensive and very detailed description of what is in the image.
Identify and decode all texts in the image and report the texts in the image description. If you recognize no text in the image, do not mention this.
Return a descriptive title for the image.
Return a limited list of the most important keywords.

CRITICAL RULES FOR KEYWORDS:
1. Every keyword MUST be a hierarchical path separated by the '|' character.
2. Limit the depth to 2 or 3 levels maximum (e.g., 'Level 1 | Level 2 | Level 3').
3. The first level MUST be exactly one of these root categories: [People, Nature, Animals, Location, Architecture, Objects, Activities].
Example: 'Nature | Flora | Rose' or 'Architecture | Infrastructure | Bridge'.
4. Generate a list that is at least 10 and up to 50 of such hierarchical keywords.

Do not include any additional text or characters."""

# --- EXIF CONTEXT PROMPTS ---
# Note: {date_time} and {address} will be dynamically injected by the script. Do not remove the curly braces.
EXIF_PROMPT_FULL = "\nThe image was taken on {date_time} at {address}. Use this information to provide an accurate description of the image (for example to identify buildings, rivers, streets, sunrise/sunset), but the detailed address or the exact time and date does not need to be included in the title, description, or keywords."

EXIF_PROMPT_DATE_ONLY = "\nThe image was taken on {date_time}. This information can be used to provide an accurate description of the image (for example to identify sunset/sunrise), but the exact time and date does not need to be included in the title, description, or keywords."

# --- ERROR HANDLING / REPROMPTING TEXTS ---
REPROMPT_TEXT = "Your answer was returned in a wrong format. You have to strictly follow the format and order as defined by the supplied tools."

SUMMARIZE_SYSTEM_PROMPT = "Read the list of hierarchical keywords (separated by semicolon). Return a shorter list of the most distinct hierarchical paths separated by semicolon (;). Preserve the '|' formatting. Respond concisely, without any introductory or concluding phrases. Output will be parsed by a script."

SUMMARIZE_USER_PROMPT = "Include only the most distinct keywords in the following list, remove duplications.\n"


# --- GEOCODING SETTINGS ---
GEO_USER_AGENT = "lr_local_ai_annotator_v1"
GEO_RATE_LIMIT_PAUSE = 1.05             # Seconds to wait between normal Geocoding calls (Nominatim requires > 1.0s)
GEOCODING_PAUSES = [10, 30, 120, 300]  # Seconds to wait between retries if Geocoding fails
