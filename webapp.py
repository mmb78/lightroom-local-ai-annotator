## C:\Users\<USERNAME>\miniconda3\Scripts\activate
## cd C:\LR\AI_Annotate.lrplugin
## streamlit run webapp.py
import streamlit as st
import base64
import json
import time
import asyncio
from io import BytesIO
from PIL import Image, ExifTags, ImageOps
from openai import AsyncOpenAI
from pydantic import BaseModel
from geopy.geocoders import Nominatim

# Import your exact config file
import config

# ==========================================
# DATA SCHEMAS
# ==========================================
class ImageDescription(BaseModel):
    title: str
    description: str
    keywords: list[str]

schema = ImageDescription.model_json_schema()
schema["additionalProperties"] = False

# ==========================================
# HELPER FUNCTIONS
# ==========================================
def resize_image(image: Image.Image, max_size: int) -> Image.Image:
    img_copy = image.copy()
    img_copy.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
    return img_copy

def image_to_base64(image: Image.Image) -> str:
    buffered = BytesIO()
    if image.mode != "RGB":
        image = image.convert("RGB")
    image.save(buffered, format="JPEG", quality=85)
    return base64.b64encode(buffered.getvalue()).decode('utf-8')

def get_decimal_from_dms(dms, ref):
    degrees = dms[0]
    minutes = dms[1]
    seconds = dms[2]
    decimal = float(degrees) + float(minutes)/60 + float(seconds)/3600
    if ref in ['S', 'W']:
        decimal = -decimal
    return decimal

def extract_exif_data(image: Image.Image):
    date_time = None
    lat, lon = None, None
    try:
        exif = image.getexif()
        if not exif:
            return date_time, lat, lon

        for tag_id, value in exif.items():
            tag = ExifTags.TAGS.get(tag_id, tag_id)
            if tag == 'DateTime':
                date_time = value

        gps_info = exif.get_ifd(ExifTags.IFD.GPSInfo)
        if gps_info:
            gps_lat = gps_info.get(2)
            gps_lat_ref = gps_info.get(1)
            gps_lon = gps_info.get(4)
            gps_lon_ref = gps_info.get(3)

            if gps_lat and gps_lat_ref and gps_lon and gps_lon_ref:
                lat = get_decimal_from_dms(gps_lat, gps_lat_ref)
                lon = get_decimal_from_dms(gps_lon, gps_lon_ref)
    except Exception:
        pass
    return date_time, lat, lon

def reverse_geocode(lat, lon):
    """Fetches the address and strictly enforces a rate limit using in-memory Session State."""
    pause_limit = getattr(config, 'GEO_RATE_LIMIT_PAUSE', 1.05)
    
    # Initialize the memory tracker if it doesn't exist yet
    if 'last_geocode_time' not in st.session_state:
        st.session_state.last_geocode_time = 0.0

    now = time.time()
    elapsed = now - st.session_state.last_geocode_time
    
    # If we hit the API too recently, pause for the remainder of the 1.05s
    if elapsed < pause_limit:
        time.sleep(pause_limit - elapsed)

    try:
        geolocator = Nominatim(user_agent=getattr(config, 'GEO_USER_AGENT', 'lr_local_ai_annotator_v1'))
        location = geolocator.reverse(f"{lat}, {lon}")
        
        # Log the exact time we made this call into Streamlit's memory
        st.session_state.last_geocode_time = time.time()
            
        return location.address if location else ""
    except Exception:
        return ""

# ==========================================
# CORE LLM FUNCTION
# ==========================================
async def analyze_image_test(base64_image, profile, sys_prompt, user_prompt, exif_context):
    if profile.get("base_url"):
        client = AsyncOpenAI(base_url=profile["base_url"], api_key=profile["api_key"], timeout=120.0)
    else:
        client = AsyncOpenAI(api_key=profile["api_key"], timeout=120.0)

    messages = [
        {"role": "system", "content": sys_prompt},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": user_prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}},
            ],
        }
    ]

    if exif_context.strip():
        messages[1]["content"].append({"type": "text", "text": exif_context})

    api_args = profile["api_params"].copy()
    api_args["model"] = profile["model"]
    api_args["messages"] = messages
    api_args["response_format"] = {
        "type": "json_schema",
        "json_schema": {"name": "image_description_schema", "strict": True, "schema": schema}
    }
    
    if "seed" in api_args and hasattr(config, 'SEEDS') and config.SEEDS:
        api_args["seed"] = config.SEEDS[0]

    start_time = time.time()
    try:
        response = await client.chat.completions.create(**api_args)
        elapsed_time = time.time() - start_time
        
        raw_dump = response.model_dump_json(indent=4)
        assistant_response = response.choices[0].message.content

        llm_answer = json.loads(assistant_response)
        
        return {
            "success": True,
            "data": llm_answer,
            "stats": {
                "Prompt Tokens": response.usage.prompt_tokens if hasattr(response, 'usage') else 0,
                "Completion Tokens": response.usage.completion_tokens if hasattr(response, 'usage') else 0,
                "Time (s)": round(elapsed_time, 2),
                "Model": profile["model"]
            },
            "raw": raw_dump,
            "messages_sent": messages
        }
    except Exception as e:
        return {"success": False, "error": str(e), "stats": {}, "raw": "", "messages_sent": messages}

# ==========================================
# STREAMLIT UI
# ==========================================
st.set_page_config(page_title="LLM Annotator Sandbox", layout="wide")

if "uploader_key" not in st.session_state:
    st.session_state.uploader_key = 0

def reset_uploader():
    st.session_state.uploader_key += 1

# --- SIDEBAR SETTINGS ---
st.sidebar.markdown("### 📸 AI Image Annotator Sandbox")
st.sidebar.caption("Test prompts, resolutions, and `config.py` profiles interactively.")
st.sidebar.divider()

st.sidebar.header("📁 Step 1: Upload Images")
uploaded_files = st.sidebar.file_uploader(
    "Upload images...", 
    type=["jpg", "jpeg", "png"], 
    accept_multiple_files=True, 
    key=f"uploader_{st.session_state.uploader_key}"
)

process_btn = False
if uploaded_files:
    process_btn = st.sidebar.button("🚀 Process Images", type="primary", use_container_width=True)

if st.sidebar.button("🗑️ Clear Images", on_click=reset_uploader, use_container_width=True):
    pass 

st.sidebar.divider()

st.sidebar.header("Step 2: Model Configuration")
profile_names = [f"{p['name']} ({p['model']})" for p in config.LLM_PROFILES]
selected_idx = st.sidebar.selectbox("Select LLM Profile", range(len(profile_names)), format_func=lambda x: profile_names[x], index=config.ACTIVE_LLM_PROFILE)
active_profile = config.LLM_PROFILES[selected_idx]

st.sidebar.header("Step 3: Image Settings")
resize_images = st.sidebar.checkbox("Resize Images?", value=True)
max_resolution = st.sidebar.number_input("Max Long Side (px)", min_value=100, max_value=8000, value=1500, disabled=not resize_images)

st.sidebar.header("Step 4: Context & Geocoding")
do_geocode = st.sidebar.checkbox("Enable Reverse Geocoding", value=True, help="If GPS data is found in Exif, ping Nominatim.")

st.sidebar.header("📝 Step 5: Edit Prompts")
sys_prompt_override = st.sidebar.text_area("System Prompt", value=config.SYSTEM_PROMPT, height=150)
user_prompt_override = st.sidebar.text_area("User Prompt", value=config.PROMPT_DESCRIPTION, height=200)

st.sidebar.markdown("**Context Injection Templates**")
exif_full_override = st.sidebar.text_area("EXIF Prompt (Full)", value=config.EXIF_PROMPT_FULL, height=100)
exif_date_override = st.sidebar.text_area("EXIF Prompt (Date Only)", value=config.EXIF_PROMPT_DATE_ONLY, height=100)

st.sidebar.markdown("**Fallback & Retry Templates**")
reprompt_text_override = st.sidebar.text_area("Reprompt Text", value=getattr(config, 'REPROMPT_TEXT', ''), height=100)
summarize_sys_override = st.sidebar.text_area("Summarize System Prompt", value=getattr(config, 'SUMMARIZE_SYSTEM_PROMPT', ''), height=100)
summarize_usr_override = st.sidebar.text_area("Summarize User Prompt", value=getattr(config, 'SUMMARIZE_USER_PROMPT', ''), height=100)

# --- MAIN AREA ---
if uploaded_files and process_btn:
    for file in uploaded_files:
        try:
            original_img = Image.open(file)
            date_time, lat, lon = extract_exif_data(original_img)
            original_img = ImageOps.exif_transpose(original_img)
            
            address = ""
            if do_geocode and lat and lon:
                with st.spinner(f"Resolving coordinates for {file.name}..."):
                    address = reverse_geocode(lat, lon)

            exif_context = ""
            if date_time and address:
                exif_context = exif_full_override.format(date_time=date_time, address=address)
            elif date_time and not address:
                exif_context = exif_date_override.format(date_time=date_time)

            original_size = original_img.size
            if resize_images:
                processed_img = resize_image(original_img, max_resolution)
            else:
                processed_img = original_img
                
            processed_size = processed_img.size
            base64_str = image_to_base64(processed_img)

            col1, col2 = st.columns([1, 2])
            
            with col1:
                st.image(processed_img, caption=f"{file.name}", width="stretch")
                st.caption(f"Original: {original_size[0]}x{original_size[1]} | Sent: {processed_size[0]}x{processed_size[1]}")
                
                if date_time or address:
                    st.info(f"**Extracted Metadata:**\n\nDate: {date_time or 'N/A'}\n\nAddress: {address or 'N/A'}")

            with col2:
                with st.spinner(f"Analyzing {file.name}..."):
                    result = asyncio.run(analyze_image_test(
                        base64_str, 
                        active_profile, 
                        sys_prompt_override, 
                        user_prompt_override, 
                        exif_context
                    ))

                if result["success"]:
                    st.subheader(result["data"].get("title", "No Title"))
                    st.write(result["data"].get("description", "No Description"))
                    
                    keywords = result["data"].get("keywords", [])
                    st.write(f"**Keywords ({len(keywords)}):**")
                    st.code(";\n".join(keywords), language="text")
                    
                    with st.expander("✉️ View Assembled Prompt Payload"):
                        st.markdown("This is the exact message structure sent to the LLM.")
                        safe_messages = json.loads(json.dumps(result["messages_sent"]))
                        if len(safe_messages) > 1 and "content" in safe_messages[1]:
                            for item in safe_messages[1]["content"]:
                                if item.get("type") == "image_url":
                                    item["image_url"]["url"] = "[BASE64_IMAGE_DATA_REMOVED_FOR_DISPLAY]"
                        st.json(safe_messages)
                    
                    with st.expander("📊 LLM Token Statistics"):
                        st.json(result["stats"])
                        
                    if getattr(config, 'LOG_RAW_RESPONSES', 0) == 1:
                        with st.expander("🛠️ Raw API Response (JSON)"):
                            st.code(result["raw"], language="json")
                else:
                    st.error(f"Error processing image: {result['error']}")
        except Exception as e:
            st.error(f"Failed to load or process {file.name}: {e}")
            
        st.write("---")

elif not uploaded_files:
    st.info("👈 Upload images in the sidebar to get started.")
elif uploaded_files and not process_btn:
    st.info("👈 Click **🚀 Process Images** in the sidebar when you are ready.")