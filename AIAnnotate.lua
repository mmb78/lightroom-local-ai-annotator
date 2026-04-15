local LrApplication = import 'LrApplication'
local LrTasks = import 'LrTasks'
local LrDialogs = import 'LrDialogs'
local LrView = import 'LrView'
local LrPrefs = import 'LrPrefs'
local LrFileUtils = import 'LrFileUtils'
local LrPathUtils = import 'LrPathUtils'
local LrExportSession = import 'LrExportSession'
local LrDate = import 'LrDate'
local LrFunctionContext = import 'LrFunctionContext'
local LrProgressScope = import 'LrProgressScope'

-- LOAD USER CONFIG
local userConfig = require('user_config')
local prefs = LrPrefs.prefsForPlugin()

-- Highly robust TSV splitter that handles empty fields correctly
local function splitTsv(str)
    local t = {}
    local start = 1
    local delim_pos
    while true do
        delim_pos = string.find(str, "\t", start)
        if not delim_pos then
            table.insert(t, string.sub(str, start))
            break
        end
        table.insert(t, string.sub(str, start, delim_pos - 1))
        start = delim_pos + 1
    end
    return t
end

LrTasks.startAsyncTask(function()
    LrFunctionContext.callWithContext("AI_Annotator_Context", function(context)
        
        local catalog = LrApplication.activeCatalog()
        local targetPhotos = catalog:getTargetPhotos()

        if #targetPhotos == 0 then
            LrDialogs.message("Please select at least one photo.")
            return
        end

        local f = LrView.osFactory()

        -- Load defaults from prefs or fallback to user_config
        prefs.tempRootFolder = prefs.tempRootFolder or LrPathUtils.getStandardFilePath('desktop')
        prefs.pythonScriptPath = prefs.pythonScriptPath or ""
        prefs.exportSize = prefs.exportSize or userConfig.defaultExportSize
        if prefs.forceReexport == nil then prefs.forceReexport = userConfig.defaultForceReexport end
        if prefs.overwriteExisting == nil then prefs.overwriteExisting = userConfig.defaultOverwrite end
        if prefs.enableGeocoding == nil then prefs.enableGeocoding = userConfig.defaultEnableGeocoding end
        if prefs.skipGeoIfExists == nil then prefs.skipGeoIfExists = userConfig.defaultSkipGeoIfExists end
        if prefs.deleteTempFolder == nil then prefs.deleteTempFolder = userConfig.defaultDeleteTempFolder end
        
        prefs.parallelWorkers = prefs.parallelWorkers or userConfig.defaultParallelWorkers

        local c = f:column {
            spacing = f:control_spacing(),
            bind_to_object = prefs,
            
            f:row {
                f:static_text { title = "Temp Root Folder:", width = LrView.share "label_width" },
                f:edit_field { value = LrView.bind 'tempRootFolder', width_in_chars = 40 },
                f:push_button {
                    title = "Browse...",
                    action = function()
                        local result = LrDialogs.runOpenPanel({
                            title = "Choose Temp Folder",
                            canChooseFiles = false,
                            canChooseDirectories = true,
                            canCreateDirectories = true,
                        })
                        if result and #result > 0 then prefs.tempRootFolder = result[1] end
                    end
                }
            },
            f:row {
                f:static_text { title = "Python Script Path:", width = LrView.share "label_width" },
                f:edit_field { value = LrView.bind 'pythonScriptPath', width_in_chars = 40 },
                f:push_button {
                    title = "Browse...",
                    action = function()
                        local result = LrDialogs.runOpenPanel({
                            title = "Select Python Script",
                            canChooseFiles = true,
                            canChooseDirectories = false,
                        })
                        if result and #result > 0 then prefs.pythonScriptPath = result[1] end
                    end
                }
            },
            f:row {
                f:static_text { title = "", width = LrView.share "label_width" },
                f:checkbox {
                    title = "Force re-export (ignore cached images)",
                    value = LrView.bind 'forceReexport'
                }
            },
            f:row {
                f:static_text { title = "Export Quality:", width = LrView.share "label_width" },
                f:popup_menu {
                    value = LrView.bind 'exportSize',
                    items = {
                        { title = "Small (1024px, 60% Quality)", value = 1024 },
                        { title = "Medium (1600px, 60% Quality)", value = 1600 },
                        { title = "Gemma4 (1920px, 70% Quality)", value = 1920 },
                        { title = "High (3000px, 80% Quality)", value = 3000 },
                    }
                }
            },
            f:row {
                f:static_text { title = "Existing Data:", width = LrView.share "label_width" },
                f:checkbox {
                    title = "Overwrite existing Title, Description, and Keywords",
                    value = LrView.bind 'overwriteExisting'
                }
            },
            f:row {
                f:static_text { title = "Geocoding:", width = LrView.share "label_width" },
                f:checkbox {
                    title = "Enable Reverse Geocoding",
                    value = LrView.bind 'enableGeocoding'
                }
            },
            f:row {
                f:static_text { title = "", width = LrView.share "label_width" },
                f:checkbox {
                    title = "Skip geocoding if photo already has Location data",
                    value = LrView.bind 'skipGeoIfExists'
                }
            },
            f:row {
                f:static_text { title = "Parallel Prompts (1-256):", width = LrView.share "label_width" },
                f:edit_field { 
                    value = LrView.bind 'parallelWorkers', 
                    width_in_chars = 5, 
                    min = 1, 
                    max = 256, 
                    precision = 0 
                },
                f:static_text { title = "(Concurrent LLM requests)" }
            },
            f:row {
                f:static_text { title = "Cleanup:", width = LrView.share "label_width" },
                f:checkbox {
                    title = "Delete temporary folder after processing",
                    value = LrView.bind 'deleteTempFolder'
                }
            }
        }

        local dialogResult = LrDialogs.presentModalDialog {
            title = "AI Auto-Annotate",
            contents = c,
        }

        if dialogResult == "cancel" then return end

        -- Start the background progress bar immediately (No modal dialog!)
        local bgProgress = LrProgressScope({
            title = "AI Annotator",
        })
        
        -- ========================================================
        -- OPTIMIZATION: BATCH FETCH METADATA
        -- ========================================================
        bgProgress:setCaption("Reading catalog metadata...")
        
        -- Fetch all required metadata for all selected photos in two fast bulk queries
        local rawMeta = catalog:batchGetRawMetadata(targetPhotos, {"keywords", "path", "gps"})
        local fmtMeta = catalog:batchGetFormattedMetadata(targetPhotos, {"title", "caption", "dateTimeOriginal", "location", "city", "stateProvince", "country"})

        -- FILTER PHOTOS BASED ON OVERWRITE PREFERENCE
        local photosToProcess = {}
        for _, photo in ipairs(targetPhotos) do
            local skip = false
            if not prefs.overwriteExisting then
                -- Pull from our pre-fetched tables instead of querying the database
                local title = fmtMeta[photo].title
                local caption = fmtMeta[photo].caption
                local keywords = rawMeta[photo].keywords 
                
                local hasKeywords = keywords and #keywords > 0
                local hasTitle = title and title ~= ""
                local hasCaption = caption and caption ~= ""

                if hasTitle and hasCaption and hasKeywords then
                    skip = true
                end
            end
            
            if not skip then
                table.insert(photosToProcess, photo)
            end
        end

        local totalPhotos = #photosToProcess

        if totalPhotos == 0 then
            LrDialogs.message("All Skipped", "All selected photos already have metadata and 'Overwrite' is unchecked. Nothing to process.")
            bgProgress:done()
            return
        end

		-- Create standard ephemeral batch folder
        local timestamp = LrDate.currentTime()
        local uniqueFolderName = (userConfig.batchFolderPrefix or "AI_Batch_") .. tostring(math.floor(timestamp))
        local batchFolderPath = LrPathUtils.child(prefs.tempRootFolder, uniqueFolderName)
        LrFileUtils.createAllDirectories(batchFolderPath)
        
        -- Create the root for the Persistent Image Cache
        local cacheRootDir = LrPathUtils.child(prefs.tempRootFolder, userConfig.imageCacheDirName or "AI_Image_Cache")
        LrFileUtils.createAllDirectories(cacheRootDir)
        
        -- Create the root for the Persistent Geocode Cache
        local geoCacheDir = LrPathUtils.child(prefs.tempRootFolder, userConfig.geoCacheDirName or "Image_GeoCode_Cache")
        LrFileUtils.createAllDirectories(geoCacheDir)

        local photoIdMap = {}

        -- ========================================================
        -- PHASE 1 & 2: UNIFIED BACKGROUND PROCESSING
        -- ========================================================

        local currentRes = prefs.exportSize or 1920
        local quality = 0.6
        if currentRes == 1920 then quality = 0.7 end
        if currentRes == 3000 then quality = 0.8 end

        local photosNeedingExport = {}
        local manifestData = {}

        -- SORT PHOTOS INTO "CACHE HIT" vs "NEEDS EXPORT"
        for _, photo in ipairs(photosToProcess) do
            local origPath = rawMeta[photo].path
            local origFileName = LrPathUtils.leafName(origPath)
            local origFolder = LrPathUtils.parent(origPath)

            local safeFolder = origFolder:gsub("^%a:[/\\]", ""):gsub("^/", "")
            local targetDir = LrPathUtils.child(cacheRootDir, safeFolder)
            LrFileUtils.createAllDirectories(targetDir)

            local baseName = LrPathUtils.removeExtension(origFileName)
            local smartFileName = string.format("%s_%dpx.jpg", baseName, currentRes)
            local targetFile = LrPathUtils.child(targetDir, smartFileName)

            if LrFileUtils.exists(targetFile) and not prefs.forceReexport then
                table.insert(manifestData, { targetPath = targetFile, photo = photo })
            else
                table.insert(photosNeedingExport, { photo = photo, targetFile = targetFile })
            end
        end

        -- EXPORT ONLY THE MISSING PHOTOS
        if #photosNeedingExport > 0 then
            bgProgress:setCaption(string.format("Exporting %d new image(s) to cache...", #photosNeedingExport))
            
            local exportArray = {}
            for _, item in ipairs(photosNeedingExport) do table.insert(exportArray, item.photo) end

            local exportSettings = {
                LR_format = "JPEG",
                LR_jpeg_quality = quality,
                LR_export_colorSpace = "sRGB",
                LR_size_doConstrain = true,
                LR_size_maxWidth = currentRes,
                LR_size_maxHeight = currentRes,
                LR_export_destinationType = "specificFolder",
                LR_export_destinationPathPrefix = batchFolderPath, 
                LR_export_useSubfolder = false,
                LR_collisionHandling = "rename",
                LR_renamingTokensOn = false,
            }

            local exportSession = LrExportSession { photosToExport = exportArray, exportSettings = exportSettings }

            local exportIndex = 1
            for _, rendition in exportSession:renditions() do
                -- Allow the user to cancel the background export by clicking the 'X' in the top left
                if bgProgress:isCanceled() then
                    bgProgress:done()
                    return
                end

                local success, pathOrMessage = rendition:waitForRender()
                local item = photosNeedingExport[exportIndex]

                if not success then
                    LrDialogs.message("Export failed", pathOrMessage)
                    bgProgress:done()
                    return
                end
                
                if LrFileUtils.exists(item.targetFile) then LrFileUtils.delete(item.targetFile) end
                LrFileUtils.move(pathOrMessage, item.targetFile)

                table.insert(manifestData, { targetPath = item.targetFile, photo = item.photo })
                
                -- Update the visual progress bar as images export
                bgProgress:setPortionComplete(exportIndex, #photosNeedingExport)
                exportIndex = exportIndex + 1
            end
        end

        -- GENERATE MANIFEST
        bgProgress:setCaption("Generating Manifest...")
        
        local manifestPath = LrPathUtils.child(batchFolderPath, "manifest.tsv")
        local manifestFile = io.open(manifestPath, "w")
        manifestFile:write("ImagePath\tPhotoID\tDateTime\tLatitude\tLongitude\tLocation\tCity\tState\tCountry\n")
        
        for _, data in ipairs(manifestData) do
            local photo = data.photo
            local targetFile = data.targetPath 
            
            local photoId = tostring(photo.localIdentifier)
            photoIdMap[photoId] = photo
            
            -- Pull from our pre-fetched tables
            local dateTime = fmtMeta[photo].dateTimeOriginal or ""
            local gps = rawMeta[photo].gps
            local lat, lon = "", ""
            if gps then
                lat = gps.latitude
                lon = gps.longitude
            end
            
            local loc = string.gsub(fmtMeta[photo].location or "", "[\r\n\t]", " ")
            local city = string.gsub(fmtMeta[photo].city or "", "[\r\n\t]", " ")
            local state = string.gsub(fmtMeta[photo].stateProvince or "", "[\r\n\t]", " ")
            local country = string.gsub(fmtMeta[photo].country or "", "[\r\n\t]", " ")
            
            manifestFile:write(string.format("%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n", targetFile, photoId, dateTime, lat, lon, loc, city, state, country))
        end
        manifestFile:close()

        -- Reset progress bar to empty for the Python phase
        bgProgress:setPortionComplete(0, 1)
        bgProgress:setCaption("Initializing LLM Analysis...")

        local safeBatchPath = string.gsub(batchFolderPath, "\\$", "")
        local safeRootTemp = string.gsub(prefs.tempRootFolder, "\\$", "")
        local geoFlag = prefs.enableGeocoding and 1 or 0
        local skipGeoFlag = prefs.skipGeoIfExists and 1 or 0

        local batPath = LrPathUtils.child(batchFolderPath, "run_ai.bat")
        local batFile = io.open(batPath, "w")
        batFile:write("@echo off\n")
        batFile:write("echo ===========================================\n")
        batFile:write(string.format("echo  AI Annotator processing %d image(s)... Do not close!\n", totalPhotos))
        batFile:write("echo ===========================================\n")
        
        -- DYNAMIC CONDA EXECUTION FROM CONFIG
        if userConfig.condaActivatePath and userConfig.condaActivatePath ~= "" then
            batFile:write(string.format('call "%s"\n', userConfig.condaActivatePath))
            batFile:write(string.format('call conda activate %s\n', userConfig.condaEnvName))
        end
        
        -- Chain the exit command on the same line using &
		batFile:write(string.format('python "%s" --batch_dir "%s" --root_temp "%s" --geo_cache_dir "%s" --workers %d --geocode %d --skip_existing_geo %d & exit\n', prefs.pythonScriptPath, safeBatchPath, safeRootTemp, geoCacheDir, prefs.parallelWorkers, geoFlag, skipGeoFlag))

        batFile:close()

        -- Launch Python without /WAIT
        local command = string.format('start "Local AI Annotator" "%s"', batPath)
        LrTasks.execute(command)

        -- ========================================================
        -- REAL-TIME PROGRESS TRACKING
        -- ========================================================
        local donePath = LrPathUtils.child(batchFolderPath, "done.txt")
        local progressPath = LrPathUtils.child(batchFolderPath, "progress.txt")
        
        while not LrFileUtils.exists(donePath) do
            if bgProgress:isCanceled() then 
                -- RESCUE PROTOCOL
                break 
            end
            
            -- Read progress.txt created by the Python worker
            if LrFileUtils.exists(progressPath) then
                local pf = io.open(progressPath, "r")
                if pf then
                    local content = pf:read("*a")
                    pf:close()
                    local completed = tonumber(content)
                    if completed then
                        bgProgress:setPortionComplete(completed, totalPhotos)
                        bgProgress:setCaption(string.format("Analyzing images with LLM: %d of %d completed...", completed, totalPhotos))
                    end
                end
            end

            LrTasks.sleep(1) -- Check progress every 1 second
        end

        bgProgress:setCaption("Importing Metadata...")

        local resultsPath = LrPathUtils.child(batchFolderPath, "results.tsv")
        if not LrFileUtils.exists(resultsPath) then
            bgProgress:done()
            LrDialogs.message("Notice", "Processing stopped before any results were saved.")
            return
        end

        local resultFile = io.open(resultsPath, "r")
        local lines = {}
        for line in resultFile:lines() do
            line = string.gsub(line, "\r", "")
            table.insert(lines, line)
        end
        resultFile:close()

        local appliedCount = 0

        catalog:withWriteAccessDo("AI Annotations", function(writeContext)
            -- OPTIMIZATION: Keyword Cache
            local cachedKeywords = {}
            
            for i = 2, #lines do
                local parts = splitTsv(lines[i])
                
                if #parts >= 9 then
                    local photoId = tostring(parts[1])
                    local title = parts[2]
                    local desc = parts[3]
                    local keywordsStr = parts[4]
                    local modelName = parts[5]
                    local addressStr = parts[6]
                    local cityStr = parts[7]
                    local stateStr = parts[8]
                    local countryStr = parts[9]

                    local photo = photoIdMap[photoId]
                    if photo then
                        if title and title ~= "" then photo:setRawMetadata("title", title) end
                        if desc and desc ~= "" then photo:setRawMetadata("caption", desc) end
                        
                        if addressStr and addressStr ~= "" and addressStr ~= "Address not found." then
                            photo:setRawMetadata("location", addressStr)
                        end
                        if cityStr and cityStr ~= "" then photo:setRawMetadata("city", cityStr) end
                        if stateStr and stateStr ~= "" then photo:setRawMetadata("stateProvince", stateStr) end
                        if countryStr and countryStr ~= "" then photo:setRawMetadata("country", countryStr) end
                        
                        if modelName and modelName ~= "" then 
                            photo:setRawMetadata("descriptionWriter", modelName) 
                        end
                        
                        if keywordsStr and keywordsStr ~= "" then
                            for kw in string.gmatch(keywordsStr, "([^;]+)") do
                                kw = kw:match("^%s*(.-)%s*$")
                                if kw ~= "" then
                                    -- Check local RAM cache first
                                    local keywordObj = cachedKeywords[kw]
                                    
                                    -- If not in cache, ask Lightroom for it, then cache it
                                    if not keywordObj then
                                        keywordObj = catalog:createKeyword(kw, {}, true, nil, true)
                                        cachedKeywords[kw] = keywordObj
                                    end
                                    
                                    -- Apply to photo
                                    if keywordObj then
                                        photo:addKeyword(keywordObj)
                                    end
                                end
                            end
                        end
                        
                        appliedCount = appliedCount + 1
                    end
                end
            end
            
            -- Give the terminal 1.5 seconds to read 'exit' and close before deleting the folder
            LrTasks.sleep(1.5)
            -- Only delete the temporary batch folder. The AI_Image_Cache remains untouched!
            if prefs.deleteTempFolder then
                LrFileUtils.delete(batchFolderPath)
            end
            bgProgress:done()
            
            -- Report the exact outcome comparing total exported to total applied
            LrTasks.startAsyncTask(function()
                if appliedCount == totalPhotos then
                    LrDialogs.message("Success!", string.format("All %d photo(s) were successfully annotated!", appliedCount))
                elseif appliedCount > 0 then
                    LrDialogs.message("Partial Success / Interrupted", string.format("%d out of %d photo(s) were exported, but only %d were annotated. (Process may have been stopped early)", totalPhotos, totalPhotos, appliedCount))
                else
                    LrDialogs.message("Notice", string.format("0 out of %d exported photo(s) were annotated. Process was likely stopped before completing any.", totalPhotos))
                end
            end)
        end)
    end)
end)