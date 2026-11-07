-- Minimal rendering/event harness for running the shipped addon in LuaJIT.
UIParent = { GetHeight = function() return 768 end, IsVisible = function() return uiVisible end }
uiVisible = true
SlashCmdList = {}
frames, timers = {}, {}
shots = 0
function GetServerTime() return 1700000000 end
function Screenshot() shots = shots + 1 end
C_Timer = { After = function(delay, run) table.insert(timers, { delay = delay, run = run }) end }
local region = {}
function region:SetSize(w, h) self.w, self.h = w, h end
function region:SetPoint(anchor, parent, relative, x, y)
    assert(anchor == "TOPLEFT" and relative == "TOPLEFT")
    self.x, self.y = x, -y
end
function region:SetColorTexture(r, g, b, a)
    assert(r == g and r == b and a == 1)
    self.color = r
end
function region:Show() self.shown = true end
function region:Hide() self.shown = false end
function region:IsVisible() return uiVisible and self.shown end
function region:SetFrameStrata() end
function region:SetScript(name, fn) self[name] = fn end
function region:RegisterEvent(name) self.registered[name] = true end
function region:CreateTexture()
    local tile = setmetatable({}, {__index = region})
    table.insert(self.tiles, tile)
    return tile
end
function CreateFrame()
    local frame = setmetatable({tiles = {}, registered = {}}, {__index = region})
    table.insert(frames, frame)
    return frame
end
function fire(name, arg)
    for _, frame in ipairs(frames) do
        if frame.registered[name] then frame:OnEvent(name, arg) end
    end
end
function tick()
    for _, frame in ipairs(frames) do
        if frame.OnUpdate then frame:OnUpdate(1/60) end
    end
end
function timer(delay)
    for i, task in ipairs(timers) do
        if task.delay == delay then
            table.remove(timers, i)
            task.run()
            return
        end
    end
end
