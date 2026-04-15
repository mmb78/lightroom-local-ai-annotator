import os
import base64
import random
import asyncio
from openai import AsyncOpenAI
import json
import csv
import argparse
import sqlite3
from geopy.geocoders import Nominatim
from filelock import FileLock
import time
from pydantic import BaseModel
from datetime import datetime
from tqdm import tqdm

# Import user configuration
import config

# ==========================================
# INITIALIZATION 
# ==========================================
if config.LOCAL_LLM == 1:
    # Use AsyncOpenAI instead of standard OpenAI
    client = AsyncOpenAI(
        base_url=config.BASE_URL,
        api_key='local-llm-key' # Required by the standard, but unused by local servers
    )
    llm_model = config.LOCAL_LLM_MODEL
else:
    client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
    llm_model = config.OPENAI_FALLBACK_MODEL

async def safe_print(msg, lock):
    """Safely prints above the tqdm progress bar without breaking it."""
    async with lock:
        tqdm.write(msg)

# ==========================================
# DATA SCHEMAS
# ==========================================
class ImageDescription(BaseModel):
    title: str
    description: str
    keywords: list[str]

schema = ImageDescription.model_json_schema()

def init_geo_db(db_path):
    conn = sqlite3.connect(db_path, timeout=15.0)
    conn.execute('PRAGMA journal_mode=WAL;')
    cursor = conn.cursor()
    # Store lat/lon as REAL (floats) for precision
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS geo_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lat REAL,
            lon REAL,
            full_address TEXT,
            city TEXT,
            state TEXT,
            country TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # CRITICAL: This index makes the range search fast
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_coords ON geo_cache (lat, lon)')
    conn.commit()
    conn.close()


def get_cached_location(db_path, lat, lon, tolerance=0.0001):
    conn = sqlite3.connect(db_path, timeout=15.0)
    cursor = conn.cursor()
    
    # Range query: Find any record within the tolerance box
    query = '''
        SELECT full_address, city, state, country 
        FROM geo_cache 
        WHERE lat BETWEEN ? AND ? 
          AND lon BETWEEN ? AND ?
        LIMIT 1
    '''
    cursor.execute(query, (lat - tolerance, lat + tolerance, lon - tolerance, lon + tolerance))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return {"full": row[0], "city": row[1], "state": row[2], "country": row[3]}
    return None

def save_location_to_db(db_path, lat, lon, geo_data):
    conn = sqlite3.connect(db_path, timeout=15.0)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO geo_cache (lat, lon, full_address, city, state, country)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (lat, lon, geo_data.get("full", ""), geo_data.get("city", ""), 
          geo_data.get("state", ""), geo_data.get("country", "")))
    conn.commit()
    conn.close()
    
# ==========================================
# CORE LLM FUNCTIONS
# ==========================================
async def read_and_encode_image(image_path):
    def _read_encode():
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')
    return await asyncio.to_thread(_read_encode)

async def analyze_image(image_path, seed, date_time, address):
    try:
        encoded_image = await read_and_encode_image(image_path)
        messages = [
            {"role": "system", "content": config.SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": config.PROMPT_DESCRIPTION},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{encoded_image}"
                        },
                    },
                ],
            }
        ]

        if date_time and address:
            exif_info = config.EXIF_PROMPT_FULL.format(date_time=date_time, address=address)
            messages[1]["content"].append({"type": "text", "text": exif_info})
        elif date_time and not address:
            exif_info = config.EXIF_PROMPT_DATE_ONLY.format(date_time=date_time)
            messages[1]["content"].append({"type": "text", "text": exif_info})
        
        # Await the API call using strict Structured Outputs (JSON Schema)
        response = await client.chat.completions.create(
            model=llm_model,
            messages=messages,
            temperature=config.LLM_TEMPERATURE, 
            top_p=config.LLM_TOP_P, 
            seed=seed, 
            max_tokens=config.MAX_TOKENS,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "image_description_schema",
                    "strict": True,
                    "schema": schema
                }
            }
        )

        # With Structured Outputs, the answer is always guaranteed to be in the message content
        assistant_response = response.choices[0].message.content

        try:
            llm_answer = json.loads(assistant_response)
            image_description = ImageDescription(**llm_answer)
            
            return {
                "LLM answer": str(response),
                "Prompt tokens": response.usage.prompt_tokens,
                "Completion tokens": response.usage.completion_tokens,
                "Title": image_description.title,
                "Description": image_description.description,
                "Keywords": image_description.keywords,
                "Notes": "Structured Output successful.",
                "messages": messages,
                "assistant_response": assistant_response
            }
        except Exception as e:
            # Failsafe for extreme server-side crashes or parsing issues
            return {
                "LLM answer": f"JSON Load Error: {e}", 
                "Prompt tokens": response.usage.prompt_tokens if hasattr(response, 'usage') else 0, 
                "Completion tokens": response.usage.completion_tokens if hasattr(response, 'usage') else 0, 
                "Title": "", 
                "Description": "", 
                "Keywords": [], 
                "Notes": f"Error parsing guaranteed JSON: {e}. Raw: {assistant_response}", 
                "messages": messages, 
                "assistant_response": assistant_response
            }

    except Exception as e:
        return {"LLM answer": f"Error analyzing {image_path}: {e}", "Prompt tokens": 0, "Completion tokens": 0, "Title": "", "Description": "", "Keywords": [], "Notes": f"Error: {e}", "messages": [], "assistant_response": ""}


async def summarize_keywords(keywords_str, seed):
    prompt = config.SUMMARIZE_USER_PROMPT + keywords_str
    try:
        messages = [
            {"role": "system", "content": config.SUMMARIZE_SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ]
        # Await the API call
        response = await client.chat.completions.create(
            model=llm_model,
            messages=messages,
            temperature=0.5, 
            top_p=0.5,
            seed=seed,
            max_tokens=100
        )
        return {"Keywords": response.choices[0].message.content}
    except Exception as e:
        return {"Keywords": f"Error {e} while shortening keywords."}


in_flight = {} # Tracks coordinates currently being processed

async def reverse_geocode_async(lat, lon, geo_lock, console_lock, db_path):
    if not lat or not lon:
        return {}, "No GPS"

    try:
        # Convert to floats for the database search
        lat_val = float(lat)
        lon_val = float(lon)
    except ValueError:
        # Safely catch corrupted strings like "N/A" or "   "
        return {}, "Invalid GPS Data"

    # 1. Check SQLite Database using HIGH-PRECISION RANGE
    cached_geo = await asyncio.to_thread(get_cached_location, db_path, lat_val, lon_val)
    if cached_geo:
        return cached_geo, "GPS Cache (DB)"

    # Round to the nearest 0.0002 (approx 22-meter accuracy)
    lat_bucket = round(lat_val * 5000) / 5000
    lon_bucket = round(lon_val * 5000) / 5000
    lock_bucket = f"{lat_bucket:.4f}, {lon_bucket:.4f}"
 
    # 2. Is another parallel task CURRENTLY fetching this exact coordinate?
    if lock_bucket in in_flight:
        await in_flight[lock_bucket].wait()
        # Check DB again; the other task just filled it
        cached_geo = await asyncio.to_thread(get_cached_location, db_path, lat_val, lon_val)
        return cached_geo, "GPS Cache (Waited)"

    # 3. If not cached and not in-flight, fetch it.
    event = asyncio.Event()
    in_flight[lock_bucket] = event

    async with geo_lock:
        try:
            # Define a blocking function to run in a separate thread
            def locked_api_call():
                lock_path = os.path.join(os.path.dirname(db_path), config.GEO_LOCK_FILENAME)
                last_call_file = os.path.join(os.path.dirname(db_path), config.GEO_TRACKER_FILENAME)

                try:                
                    # Claim the physical lock across ALL running Python scripts
                    # Wait up to 60 seconds. If there are 4 parallel scripts, the line should only ever take 4 seconds to clear.
                    with FileLock(lock_path, timeout=60):
                        # We just acquired the lock. Before we hit the API, let's 
                        # make absolutely sure another script didn't just save this 
                        # exact coordinate to the database while we were waiting.
                        late_cache = get_cached_location(db_path, lat_val, lon_val)
                        if late_cache:
                            return late_cache, "GPS Cache (Late)"

                        # THE SMART SLEEP
                        now = time.time()
                        try:
                            # Read when the very last API call happened globally
                            with open(last_call_file, 'r') as f:
                                last_call = float(f.read())
                        except (FileNotFoundError, ValueError):
                            last_call = 0.0 # If file doesn't exist, it's safe to proceed immediately

                        # How much time has passed since the last call?
                        elapsed = now - last_call
                        
                        # Only sleep if we haven't reached the 1-second mark yet
                        # We only sleep for the REMAINDER of the window.
                        if elapsed < config.GEO_RATE_LIMIT_PAUSE:
                            time.sleep(config.GEO_RATE_LIMIT_PAUSE - elapsed)

                        geolocator = Nominatim(user_agent=config.GEO_USER_AGENT)
                        result = geolocator.reverse(f"{lat}, {lon}")
                        
                        # --- UPDATE THE TRACKER ---
                        # Record the exact time we just made this call
                        with open(last_call_file, 'w') as f:
                            f.write(str(time.time()))
                        
                        return result
                        
                except Timeout:
                    # The lock is dead/crashed. Force delete the ghost file.
                    try:
                        os.remove(lock_path)
                    except OSError:
                        pass # Another script might have already deleted it

                    # Return empty so your outer loop's `config.GEOCODING_PAUSES` 
                    # naturally pauses and retries safely.
                    return {}, "Lock Timeout"

            # Send the blocking lock/API call to a thread so your asyncio loop doesn't freeze
            api_result = await asyncio.to_thread(locked_api_call)
            
            # Extract the raw dictionary from Nominatim
            if isinstance(api_result, tuple):
                data, note = api_result
                return data, note  # Safely exit early without trying to parse it
            
            # If it's not a tuple, it's a successful Nominatim Location object!
            location = api_result
            
            # Extract the raw dictionary from Nominatim
            raw_address = location.raw.get('address', {}) if location else {}
            
            # Build a structured dictionary of the components we care about
            geo_data = {
                "full": location.address if location else "Address not found.",
                "city": raw_address.get('city', raw_address.get('town', raw_address.get('village', ''))),
                "state": raw_address.get('state', ''),
                "country": raw_address.get('country', '')
            }
            
            # Save to SQLite Database
            await asyncio.to_thread(save_location_to_db, db_path, lat_val, lon_val, geo_data)
            return geo_data, "GPS API"
                        
        except Exception as e:
            await safe_print(f"Geocoding error: {e}", console_lock)
            return {}, "GPS Error"
            
        finally:
            event.set()
            if lock_bucket in in_flight:
                del in_flight[lock_bucket]
                
# ==========================================
# ASYNC BATCH EXECUTION
# ==========================================
async def process_single_image(n, img_data, args, semaphore, locks, progress_stats, pbar, results_path, analytics_path, progress_path, geo_db_path):
    # The semaphore safely throttles how many tasks run this block simultaneously based on --workers
    async with semaphore:
        # Safely increment started count and update progress bar
        async with locks['stats']:
            progress_stats["started"] += 1
            try:
                pbar.set_postfix(Started=progress_stats["started"], Done=progress_stats["done"])
            except NameError:
                pass # Failsafe in case the thread executes before pbar is fully bound

        image_path = img_data['ImagePath']
        date_time = img_data['DateTime']
        lat = img_data['Latitude']
        lon = img_data['Longitude']
        photo_id = img_data['PhotoID']
        existing_loc = img_data.get('Location', '').strip()
        existing_city = img_data.get('City', '').strip()
        existing_state = img_data.get('State', '').strip()
        existing_country = img_data.get('Country', '').strip()
        
        start_time = time.time()

        address = ""
        city, state, country = "", "", ""
        geo_note = "GPS Skipped"
        
        # STRICT CHECK: Only skip if the FULL address (Sublocation) is already filled out
        has_full_address = bool(existing_loc)
        
        # 1. If user enabled skipping AND we have the full address, use it!
        if args.skip_existing_geo == 1 and has_full_address:
            address = existing_loc
            # We still carry over the existing city/state/country so they aren't lost
            city = existing_city
            state = existing_state
            country = existing_country
            geo_note = "GPS Skipped (Address exists)"
            
        # 2. Otherwise, check if we should query the Geocoding API
        elif args.geocode == 1:
            for pause in config.GEOCODING_PAUSES:
                geo_data, geo_note = await reverse_geocode_async(lat, lon, locks['geocode'], locks['console'], geo_db_path)
                if geo_data:
                    address = geo_data.get("full", "")
                    city = geo_data.get("city", "")
                    state = geo_data.get("state", "")
                    country = geo_data.get("country", "")
                    break
                elif lat and lon and not geo_data:
                    geo_note = "GPS API Retrying"
                    # Add a random amount of time (e.g., between 0.5 and 2.5 seconds)
                    jitter = random.uniform(0.5, 2.5)
                    actual_pause = pause + jitter
                    
                    await safe_print(f"[{image_path}] Geocoding failed, waiting {actual_pause:.2f} seconds...", locks['console'])
                    await asyncio.sleep(actual_pause)                    
                    
                else:
                    break

        # 3. FALLBACK: If Nominatim crashed/failed, but you had partial data in Lightroom
            if not address and (existing_city or existing_country):
                city = existing_city
                state = existing_state
                country = existing_country
                address = ", ".join(filter(None, [city, state, country]))
                geo_note = "GPS Fallback (Used partial data)"
                
        # 4. GEO DISABLED SCENARIO: Geocoding is off, but we have partial data
        elif existing_city or existing_country:
            city = existing_city
            state = existing_state
            country = existing_country
            address = ", ".join(filter(None, [city, state, country]))
            geo_note = "GPS Skipped (Used partial data)"

        attempt = 0
        answer = {}
        llm_retry_reasons = []
        keyword_note = "Keywords OK"
        successful_seed = config.SEEDS[0]
        
        for seed in config.SEEDS:
            attempt += 1
            
            # Only print if we are retrying with a new seed (attempt 2+)
            if attempt > 1:
                await safe_print(f"[{image_path}] Attempt #{attempt} triggered with new seed: {seed}", locks['console'])
            # else:
            #     await safe_print(f"[{img_data['Filename']}] Attempt #{attempt} with seed {seed}", locks['console']) # Commented out standard attempt 1

            answer = await analyze_image(image_path, seed, date_time, address)
            keywords = answer.get('Keywords', [])

            # Track if the LLM function caught a JSON format error
            if "Error" in answer.get('Notes', ''):
                llm_retry_reasons.append("JSON Error")
                await safe_print(f"[{image_path}] JSON parsing failed. Retrying with new seed...", locks['console'])
                continue # Add this to skip keyword checks on a JSON failure
                
            # Since JSON formatting is strictly guaranteed now, we only need to check keyword count rules
            if len(keywords) < config.MIN_KEYWORDS:
                llm_retry_reasons.append(f"Low Keywords ({len(keywords)})")
                await safe_print(f"[{image_path}] Not enough keywords generated ({len(keywords)}). Retrying with new seed...", locks['console'])
                continue # Skip the rest of the loop and try the next seed

            if len(keywords) > config.MAX_KEYWORDS:
                await safe_print(f"[{image_path}] Asking LLM to shorten keywords...", locks['console']) 
                shorter_keywords = await summarize_keywords('; '.join(keywords), seed)
                keywords_str = shorter_keywords['Keywords'].strip()
                keywords = [k.strip() for k in keywords_str.split(';')]
                keyword_note = "Keywords Shortened"
                attempt *= 10 

            # If we made it here and have a valid token count, we have a successful generation!
            if answer.get('Completion tokens', 0) < config.MAX_TOKENS:
                successful_seed = seed
                break
            else:
                llm_retry_reasons.append("Max Tokens Hit")

        # Compile the final notes string
        final_notes_list = [geo_note]
        
        if not llm_retry_reasons:
            final_notes_list.append("LLM OK (1st Try)")
        else:
            final_notes_list.append("LLM Retries: [" + ", ".join(llm_retry_reasons) + "]")
            
        final_notes_list.append(keyword_note)
        final_notes_list.append(f"Seed: {successful_seed}")
        
        final_notes_str = "; ".join(final_notes_list)
                
        clean_title = str(answer.get('Title', '')).replace('\t', ' ').replace('\n', ' ')
        clean_desc = str(answer.get('Description', '')).replace('\t', ' ').replace('\n', ' ')
        clean_keywords = ";".join(keywords).replace('\t', ' ').replace('\n', ' ')
        clean_address = str(address).replace('\t', ' ').replace('\n', ' ')
        clean_city = str(city).replace('\t', ' ').replace('\n', ' ')
        clean_state = str(state).replace('\t', ' ').replace('\n', ' ')
        clean_country = str(country).replace('\t', ' ').replace('\n', ' ')
        
        current_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Shorten the model name by removing 'google/' and keeping it concise
        short_model = llm_model.split('/')[-1][:21] # Keeps up to 21 chars of the model name
        # Use a short date/time format
        short_time_str = datetime.now().strftime("%Y%m%d")
        # Keep the resulting string under 32 characters
        model_with_date = f"{short_model} ({short_time_str})"
        
        end_time = time.time()
        elapsed_time = end_time - start_time
        formatted_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(end_time))

        # Write results using the async lock
        async with locks['file']:
            with open(results_path, 'a', encoding='utf-8') as f:
                f.write(f"{photo_id}\t{clean_title}\t{clean_desc}\t{clean_keywords}\t{model_with_date}\t{clean_address}\t{clean_city}\t{clean_state}\t{clean_country}\n")

            with open(analytics_path, 'a', encoding='utf-8') as tsv_file:
                tsv_file.write(f"{image_path}\t{formatted_time}\t{date_time}\t{lat}\t{lon}\t{address}\t")
                tsv_file.write(f"{llm_model}\t{attempt}\t{answer.get('Prompt tokens', 0)}\t{answer.get('Completion tokens', 0)}\t{len(keywords)}\t{elapsed_time:.2f}\t")
                tsv_file.write(f"{clean_title}\t{clean_desc}\t{clean_keywords}\t{final_notes_str}\n")        

        # Update final UI stats using the async lock
        async with locks['stats']:
            progress_stats["done"] += 1
            pbar.update(1)
            pbar.set_postfix(Started=progress_stats["started"], Done=progress_stats["done"])
            
            # Sync to Lightroom
            with open(progress_path, 'w') as pf:
                pf.write(str(progress_stats["done"]))


async def main_async(args, images_to_process, results_path, analytics_path, progress_path, geo_db_path):
    # Setup the Semaphore using the user's --workers argument
    semaphore = asyncio.Semaphore(args.workers)
    
    # Initialize all our asyncio Locks
    locks = {
        'file': asyncio.Lock(),
        'geocode': asyncio.Lock(),
        'stats': asyncio.Lock(),
        'console': asyncio.Lock()
    }
    
    progress_stats = {"started": 0, "done": 0}
    total_images = len(images_to_process)

    print(f"Starting parallel processing with {args.workers} concurrent async tasks...\n")
    custom_format = "{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_noinv_fmt}{postfix}]"
    
    with tqdm(total=total_images, desc="AI Annotator", unit="img", bar_format=custom_format) as pbar:
        # Create a list of all the tasks we want to run
        tasks = [
            process_single_image(
                n, img_data, args, semaphore, locks, progress_stats, 
                pbar, results_path, analytics_path, progress_path, geo_db_path
            ) 
            for n, img_data in enumerate(images_to_process, 1)
        ]
        
        # Run them all concurrently
        await asyncio.gather(*tasks)
        
    print("\nBatch processing complete!")


def main():
    # Get the exact datetime object for right now
    start_datetime = datetime.now()
    # Format it for the text file
    start_time_str = start_datetime.strftime("%Y-%m-%d %H:%M:%S")
    
    parser = argparse.ArgumentParser(description="Process LR image batch.")
    parser.add_argument("--batch_dir", required=True, help="Path to the temp folder with JPEGs and manifest.tsv")
    parser.add_argument("--root_temp", required=True, help="Path to the root temp folder for analytics TSV")
    parser.add_argument("--geo_cache_dir", required=True, help="Path to the persistent geocoding cache directory")
    parser.add_argument("--workers", type=int, default=1, help="Number of concurrent LLM requests")
    parser.add_argument("--geocode", type=int, default=1, help="1 to enable geocoding, 0 to skip")
    parser.add_argument("--skip_existing_geo", type=int, default=1, help="1 to skip geocoding if address exists")
    args = parser.parse_args()

    # Initialize Database
    geo_db_path = os.path.join(args.geo_cache_dir, config.GEO_DB_FILENAME)
    init_geo_db(geo_db_path)
    
    manifest_path = os.path.join(args.batch_dir, "manifest.tsv")
    results_path = os.path.join(args.batch_dir, "results.tsv")
    done_path = os.path.join(args.batch_dir, "done.txt")
    progress_path = os.path.join(args.batch_dir, "progress.txt")
    
    timestamp_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    analytics_path = os.path.join(args.root_temp, f"analytics_{timestamp_str}.tsv")
    
    images_to_process = []
    if os.path.exists(manifest_path):
        with open(manifest_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f, delimiter='\t')
            for row in reader:
                images_to_process.append(row)
    else:
        print(f"Manifest not found at {manifest_path}")
        return

    # Setup files
    with open(analytics_path, 'w', encoding='utf-8') as tsv_file:
        tsv_file.write("Image Path\tProcessed on\tDate\tLatitude\tLongitude\tAddress\tLLM model\tAttempt\tPrompt tokens\tCompletion tokens\tNumber of keywords\tProcessing time\tTitle\tDescription\tKeywords\tNotes\n")

    with open(results_path, 'w', encoding='utf-8') as f:
        f.write("PhotoID\tTitle\tDescription\tKeywords\tModel\tAddress\tCity\tState\tCountry\n")

    with open(progress_path, 'w') as f:
        f.write("0")

    try:
        # Kick off the asyncio event loop
        asyncio.run(main_async(args, images_to_process, results_path, analytics_path, progress_path, geo_db_path))

    except KeyboardInterrupt:
        print("\n[!] Process interrupted manually by user! Stopping early.")
        
        # Calculate the duration exactly when the interrupt happened
        end_datetime = datetime.now()
        end_time_str = end_datetime.strftime("%Y-%m-%d %H:%M:%S")
        duration_str = str(end_datetime - start_datetime).split('.')[0]
        
        # 1. INSTANTLY write the done file to free Lightroom from its waiting loop
        with open(done_path, 'w') as f:
            f.write("done")

        formatted_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        with open(analytics_path, 'a', encoding='utf-8') as tsv_file:
            tsv_file.write(f"INTERRUPTED\t{formatted_time}\t\t\t\t\t{llm_model}\t\t\t\t\t\t\t\t\tProcess manually stopped by user.\n")
            tsv_file.write(f"\nBATCH SUMMARY (PARTIAL)\tStart:\t{start_time_str}\tEnd:\t{end_time_str}\tTotal Time:\t{duration_str}\t\t\t\t\t\t\t\t\t\n")

        # 2. Perform a hard-exit to bypass asyncio hanging and Windows timeouts
        os._exit(0)

    finally:
        # For normal, uninterrupted completions
        if not os.path.exists(done_path):
            print("Sending 'done' signal to Lightroom...")
            with open(done_path, 'w') as f:
                f.write("done")
            
        end_datetime = datetime.now()
        end_time_str = end_datetime.strftime("%Y-%m-%d %H:%M:%S")
        duration_str = str(end_datetime - start_datetime).split('.')[0]
        
        # Write the tab-delimited summary line
        with open(analytics_path, 'a', encoding='utf-8') as tsv_file:
            tsv_file.write(f"\nBATCH SUMMARY\tStart:\t{start_time_str}\tEnd:\t{end_time_str}\tTotal Time:\t{duration_str}\t\t\t\t\t\t\t\t\t\n")

if __name__ == "__main__":
    main()