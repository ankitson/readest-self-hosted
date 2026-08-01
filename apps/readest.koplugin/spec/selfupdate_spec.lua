require("spec_helper")
require("spec.koreader_stubs")

local SelfUpdate = require("readest_selfupdate")
local ReadestSync = require("main")

describe("selfhost KOReader updater policy", function()
    it("exposes an explicit disabled self-update policy", function()
        assert.are.equal("function", type(SelfUpdate.isEnabled))
        assert.is_false(SelfUpdate:isEnabled())
    end)

    it("disables the update menu entry", function()
        local plugin = setmetatable({
            installed_version = "0.11.20",
            settings = {},
            ui = { document = {} },
        }, { __index = ReadestSync })
        local menu_items = {}

        plugin:addToMainMenu(menu_items)

        local items = menu_items.readest_sync.sub_item_table
        local update_item = items[#items]
        assert.are.equal("function", type(update_item.enabled_func))
        assert.is_false(update_item.enabled_func())
    end)
end)
