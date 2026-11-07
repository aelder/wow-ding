-- Forever 1.60.1. Each row is one byte, most significant bit on the left.
local marker = CreateFrame("Frame", nil, UIParent)
marker:SetFrameStrata("TOOLTIP")
marker:Hide()
local tiles = {}
for i = 1, 88 do
    tiles[i] = marker:CreateTexture(nil, "OVERLAY")
end

local function packet(level, kind)
    local stamp = GetServerTime()
    local nonce = math.random(0, 65535)
    local bytes = { 0xD6, 0x39, kind, level }
    for shift = 3, 0, -1 do
        table.insert(bytes, math.floor(stamp / 256 ^ shift) % 256)
    end
    table.insert(bytes, math.floor(nonce / 256))
    table.insert(bytes, nonce % 256)
    local crc = 0
    for _, byte in ipairs(bytes) do
        crc = bit.bxor(crc, byte)
        for i = 1, 8 do
            local high = crc >= 128
            crc = (crc * 2) % 256
            if high then crc = bit.bxor(crc, 7) end
        end
    end
    table.insert(bytes, crc)
    return bytes
end

local function draw(bytes)
    local cell = UIParent:GetHeight() / 96
    marker:SetSize(8 * cell, #bytes * cell)
    marker:SetPoint("TOPLEFT", UIParent, "TOPLEFT", cell, -cell)
    for row, byte in ipairs(bytes) do
        for col = 0, 7 do
            local tile = tiles[(row - 1) * 8 + col + 1]
            local value = math.floor(byte / 2 ^ (7 - col)) % 2
            tile:SetPoint("TOPLEFT", marker, "TOPLEFT", col * cell, -(row - 1) * cell)
            tile:SetSize(cell, cell)
            tile:SetColorTexture(value, value, value, 1)
        end
    end
    marker:Show()
end

local events = CreateFrame("Frame")
local queue = {}
local active, requested
local startNext

local function finish(message)
    if message then print("Ding: " .. message) end
    marker:Hide()
    requested = false
    -- Separate captures across filename timestamps, even on a burst of events.
    C_Timer.After(1.2, function()
        active = nil
        startNext()
    end)
end

startNext = function()
    if active or #queue == 0 then return end
    local bytes = table.remove(queue, 1)
    active = bytes
    if not UIParent:IsVisible() then
        finish("capture skipped because the UI is hidden.")
        return
    end
    draw(bytes)
    -- OnUpdate also runs before rendering. Wait for two complete frames.
    local frames = 0
    events:SetScript("OnUpdate", function(self)
        frames = frames + 1
        if frames < 3 then return end
        self:SetScript("OnUpdate", nil)
        if not marker:IsVisible() then
            finish("capture skipped because the marker is hidden.")
            return
        end
        requested = true
        C_Timer.After(10, function()
            if active == bytes and requested then finish("screenshot timed out.") end
        end)
        Screenshot()
    end)
end

local function enqueue(level, kind)
    if issecretvalue and issecretvalue(level) then return end
    if type(level) ~= "number" or level < 1 or level > 255 or level ~= math.floor(level) then return end
    table.insert(queue, packet(level, kind))
    startNext()
end

events:RegisterEvent("PLAYER_LEVEL_UP")
events:RegisterEvent("SCREENSHOT_SUCCEEDED")
events:RegisterEvent("SCREENSHOT_FAILED")
events:SetScript("OnEvent", function(_, event, level)
    if event == "PLAYER_LEVEL_UP" then
        enqueue(level, 0x10)
    elseif requested then
        if event == "SCREENSHOT_FAILED" then
            finish("WoW could not save the screenshot.")
        else
            finish()
        end
    end
end)

SLASH_WOWDING1 = "/ding"
SlashCmdList.WOWDING = function(input)
    if input:lower():match("^%s*test%s*$") then
        enqueue(42, 0x11)
        print("Ding: requested a local test capture for level 42.")
    else
        print("Ding: /ding test takes a diagnostic screenshot. Tests never post.")
    end
end
