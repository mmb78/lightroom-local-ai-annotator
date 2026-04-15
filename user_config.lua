-- ==============================================================================
-- AI ANNOTATOR: LIGHTROOM CONFIGURATION
-- ==============================================================================
-- Modify these variables to match your system setup. 
-- Note: In Lua strings, backslashes (\) in Windows paths must be escaped as (\\).

return {
    -- The path to your conda activation script. 
    -- If you use standard Python, you can leave this blank ("") and the batch 
    -- script will just try to run "python" directly from your global PATH.
    condaActivatePath = "C:\\YOUR\\PATH\\miniconda3\\Scripts\\activate", 	-- REPLACE WITH YOUR OWN!
    
    -- The name of the conda environment where you installed your dependencies.
    condaEnvName = "base",
	
	-- Directory and Cache Names
    imageCacheDirName = "_Cache_Data/Images",
    geoCacheDirName = "_Cache_Data/GeoCode",
    batchFolderPrefix = "LLM_Batch_",

	-- true: Always export fresh JPEGs, overwriting the cache. false: Use cached JPEGs if available.
    defaultForceReexport = false,
	
    -- Default UI Settings (so you don't have to change them every time)
    -- exportSize options: 1024 (Small), 1600 (Medium), 1920 (Max for Gemma4 without resizing by the model for 3:2 images), 3000 (Large)
    defaultExportSize = 1920,
    
    -- true: Overwrite existing metadata. false: Skip photos that already have metadata.
    defaultOverwrite = true,
	
	-- true: Fetch address via geocoding. false: Skip geocoding (faster processing).
    defaultEnableGeocoding = true,
	
	-- true: Skip reverse geocoding if the photo already has full address data.
    defaultSkipGeoIfExists = true,
    
	-- true: Delete the batch folder when done. false: Keep it for debugging.
    defaultDeleteTempFolder = true,

	-- Number of parallel requests sent to the LLM
    defaultParallelWorkers = 256
	
}