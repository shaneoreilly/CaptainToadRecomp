"""Prepare the reference game runtime (renderer, audio, input) for Captain Toad's generated code.

The reference runtime names the Wind Waker HD executable and calls Wind Waker HD guest functions
from its game-specific features. This script points the loader at Kinopio.rpx and writes weak stubs
for those guest symbols, following nsmbu-recomp tools/recomp/guest_stubs.py (MPL-2.0). A stub that
runs stops through ppc_unimplemented instead of executing unrelated Captain Toad code.
"""
from pathlib import Path
import argparse
import re

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('upstream', type=Path)
parser.add_argument('--gen', type=Path, default=Path('build/gen'), help='generated Captain Toad code')
args = parser.parse_args()
runtime = args.upstream / 'runtime'

REPLACEMENTS = {
    'src/main.cpp': [
        ('std::string rpx = config::game_dir + "/code/cking.rpx";',
         'std::string rpx = config::game_dir + "/code/Kinopio.rpx";'),
        ('mem::write_cstr(arg0, "cking.rpx", 16);', 'mem::write_cstr(arg0, "Kinopio.rpx", 16);'),
        # Windows crash reports also name the guest arguments and walk the guest stack back chain.
        ('    if(Cpu* c=threads::current()){n=snprintf(buf,sizeof buf,"guest lr=%08X ctr=%08X\\n",c->lr,c->ctr); win_crash_out(fd,buf,n);}\n',
         '    if(Cpu* c=threads::current()){n=snprintf(buf,sizeof buf,"guest lr=%08X ctr=%08X\\n",c->lr,c->ctr); win_crash_out(fd,buf,n);}\n'
         '    if(Cpu* c=threads::current()){\n'
         '        n=snprintf(buf,sizeof buf,"guest r1=%08X r3=%08X r4=%08X r5=%08X r31=%08X\\n",c->r[1],c->r[3],c->r[4],c->r[5],c->r[31]); win_crash_out(fd,buf,n);\n'
         '        uint32_t sp=c->r[1];\n'
         '        for(int i=0;i<24&&sp>=0x10000&&sp<0xF0000000u;i++){uint32_t next=ld32(sp);if(next<0x10000||next>=0xF0000000u)break;\n'
         '            n=snprintf(buf,sizeof buf,"  guest frame %08X lr %08X\\n",next,ld32(next+4)); win_crash_out(fd,buf,n); sp=next;}\n'
         '    }\n'),
    ],
    # Canonical addresses name Wind Waker HD code and data. With CT_FOREIGN_GUEST none of them is
    # valid, even when it falls inside Captain Toad's ranges: features that check validity switch
    # themselves off, and direct uses resolve into the protected guest null page and fault.
    'include/guest_addr.h': [
        ('static inline int guest_code_valid(uint32_t a) {\n',
         'static inline int guest_code_valid(uint32_t a) {\n#ifdef CT_FOREIGN_GUEST\n    (void)a;\n    return 0;\n#endif\n'),
        ('static inline int guest_data_valid(uint32_t a) {\n',
         'static inline int guest_data_valid(uint32_t a) {\n#ifdef CT_FOREIGN_GUEST\n    (void)a;\n    return 0;\n#endif\n'),
        ('static inline uint32_t guest_code(uint32_t canon) {\n',
         'static inline uint32_t guest_code(uint32_t canon) {\n#ifdef CT_FOREIGN_GUEST\n    (void)canon;\n    return 0x00001000u;\n#endif\n'),
        ('static inline uint32_t guest_data(uint32_t canon) {\n',
         'static inline uint32_t guest_data(uint32_t canon) {\n#ifdef CT_FOREIGN_GUEST\n    (void)canon;\n    return 0x00001000u;\n#endif\n'),
    ],
    # Wind Waker HD's sound manager supplies the TV/GamePad faders; other titles keep the TV default.
    'src/hle/ax.cpp': [
        ('    uint32_t mgr = ld32(GD(0x1018EC64));\n',
         '    if (!guest_data_valid(0x1018EC64)) return false;\n    uint32_t mgr = ld32(GD(0x1018EC64));\n'),
    ],
    # OSWaitRendezvous waits for the cores in its mask, as Cemu coreinit_Synchronization.cpp does.
    # Counting arrivals let Captain Toad's main thread (core 1, mask 1) pass before its audio launch
    # thread (core 0) had initialized the sound system. `arrived` now holds the arrived-core bits.
    'src/threads.cpp': [
        ('    uint32_t arrived = 0;\n', '    uint32_t arrived = 0;  // bit per core that has arrived\n'),
        ('''    // arg1 is a core mask; we treat each set bit as one participant
    HRendezvous* r = g_rdv.get(arg(c, 0));
    uint32_t need = __builtin_popcount(arg(c, 1) & 7);
    std::unique_lock<std::mutex> lk(r->m);
    r->arrived++;
    r->cv.notify_all();
    park_wait(lk, r->cv, [&] { return r->arrived >= need; }, W_RDV, arg(c, 0));''',
         '''    // arg1 is a core mask: mark this core, then wait until every core in the mask has arrived
    HRendezvous* r = g_rdv.get(arg(c, 0));
    uint32_t need = arg(c, 1) & 7;
    std::unique_lock<std::mutex> lk(r->m);
    r->arrived |= 1u << (c->core & 3);
    r->cv.notify_all();
    park_wait(lk, r->cv, [&] { return (r->arrived & need) == need; }, W_RDV, arg(c, 0));'''),
    ],
    # GX2's 0x800 format bit marks float formats (R16_FLOAT 0x806, R16G16_FLOAT 0x810), not depth.
    # A depth surface is one created for depth-buffer use, as Cemu's GX2CalculateSurfaceInfo decides.
    # Name the formats, so an unsupported copy identifies itself.
    'src/gfx/vulkan/surfaces.cpp': [
        ('    auto sf=format_info(uint32_t(s->format.value()),bool(uint32_t(s->format.value())&0x800));\n'
         '    auto df=format_info(uint32_t(d->format.value()),bool(uint32_t(d->format.value())&0x800));\n',
         '    auto sf=format_info(uint32_t(s->format.value()),(s->resFlag&(1u<<2))!=0);  // GX2_RESFLAG_USAGE_DEPTH_BUFFER\n'
         '    auto df=format_info(uint32_t(d->format.value()),(d->resFlag&(1u<<2))!=0);\n'),
        ('        exception_report::raise("Unsupported CPU GX2CopySurface format layout");\n',
         '        exception_report::raise("Unsupported CPU GX2CopySurface format layout: " +\n'
         '            std::to_string(uint32_t(s->format.value())) + " tile " + std::to_string(uint32_t(s->tileMode.value())) + " -> " +\n'
         '            std::to_string(uint32_t(d->format.value())) + " tile " + std::to_string(uint32_t(d->tileMode.value())));\n'),
    ],
    # Stream out (Cemu GX2_Streamout.cpp, LatteCommandProcessor.cpp, LatteStreamoutGPU.cpp): context
    # updates run on the render thread in command order; draws advance each buffer's write offset.
    'src/gx2/gx2_cmd.h': [
        ('    OP_CLOUDS_END,\n    OP_COUNT\n',
         '    OP_CLOUDS_END,\n'
         '    OP_STREAMOUT_UPDATE,  // buffer index, mode (0 reset, 2 load from context, 3 save to context), context\n'
         '    OP_COUNT\n'),
    ],
    'src/gx2/gx2_core.cpp': [
        ('static void execute_op(Op op, const uint32* p, uint32 n) {\n',
         '''// Stream-out draws advance each buffer's write offset by the bytes their vertices emit, bounded by
// the buffer (Cemu LatteStreamoutGPU.cpp). The renderer does not produce that output yet: the buffers
// keep their previous contents.
static void streamout_advance(uint32 count, uint32 instances) {
    if (!g_regs[mmVGT_STRMOUT_EN]) return;
    static bool logged = false;
    if (!logged) { logged = true; LOG("[gx2] stream-out draws advance their buffer offsets; their vertex output is not produced yet"); }
    for (uint32 i = 0; i < 4; i++) {
        const uint32 stride = g_regs[mmVGT_STRMOUT_VTX_STRIDE_0 + i * 4] << 2, size = g_regs[mmVGT_STRMOUT_BUFFER_SIZE_0 + i * 4] << 2;
        uint32& offset = g_regs[mmVGT_STRMOUT_BUFFER_OFFSET_0 + i * 4];
        if (!stride || !size) continue;
        offset += (uint32)std::min<uint64>(uint64(count) * instances * stride, offset < size ? size - offset : 0);
    }
}
static void execute_op(Op op, const uint32* p, uint32 n) {
'''),
        ('    case OP_DRAW: render::draw(g_regs, p[0], p[1], 0, 0, p[2], p[3]); break;\n'
         '    case OP_DRAW_INDEXED: render::draw(g_regs, p[0], p[1], p[2], p[3], p[4], p[5]); break;\n',
         '    case OP_DRAW: render::draw(g_regs, p[0], p[1], 0, 0, p[2], p[3]); streamout_advance(p[1], p[3]); break;\n'
         '    case OP_DRAW_INDEXED: render::draw(g_regs, p[0], p[1], p[2], p[3], p[4], p[5]); streamout_advance(p[1], p[5]); break;\n'
         '    case OP_STREAMOUT_UPDATE: {  // IT_STRMOUT_BUFFER_UPDATE\n'
         '        uint32& offset = g_regs[mmVGT_STRMOUT_BUFFER_OFFSET_0 + 4 * (p[0] & 3)];\n'
         '        if (p[1] == 0) offset = 0;\n'
         '        else if (p[1] == 2) offset = p[2] ? ld32(p[2]) : 0;\n'
         '        else if (p[1] == 3 && p[2]) st32(p[2], offset);\n'
         '        break;\n'
         '    }\n'),
    ],
    'src/gx2/gx2_resources.cpp': [
        ('        set_regs(mmSQ_VTX_SEMANTIC_0, tmp.at(mmSQ_VTX_SEMANTIC_0), nsem);\n    }\n}\n',
         '        set_regs(mmSQ_VTX_SEMANTIC_0, tmp.at(mmSQ_VTX_SEMANTIC_0), nsem);\n    }\n'
         '    if (ld32(vs + 0x110))  // usesStreamOut: per-buffer vertex strides in dwords (Cemu GX2_Shader.cpp)\n'
         '        for (uint32 i = 0; i < 4; i++) set_reg(mmVGT_STRMOUT_VTX_STRIDE_0 + i * 4, ld32(vs + 0x114 + 4 * i) >> 2);\n'
         '}\n'),
    ],
    'src/savestate.cpp': [
        ('fopen((config::game_dir + "/code/cking.rpx").c_str(), "rb")',
         'fopen((config::game_dir + "/code/Kinopio.rpx").c_str(), "rb")'),
        # The stage name is Wind Waker HD data: closing the window asked for it and read the null page.
        ('    const char* p = (const char*)mem::ptr(kStageName);\n',
         '    if (!guest_data_valid(0x1046F0B0)) return "";\n'
         '    const char* p = (const char*)mem::ptr(kStageName);\n'),
        # Portable states hold Wind Waker HD save data: Captain Toad's states are always full ones.
        ('bool full_states() {\n',
         'bool full_states() {\n#ifdef CT_FOREIGN_GUEST\n    return true;\n#endif\n'),
    ],
}
# The Android app gets its own package and name, so installing it never replaces a Wind Waker HD
# install. The Java namespace stays; only the installed identity changes.
REPLACEMENTS['../android/app/build.gradle'] = [
    ('        applicationId "org.wwhdrecomp.wwhd"\n', '        applicationId "org.ctrecomp.captaintoad"\n'),
]
REPLACEMENTS['../android/app/src/main/res/values/strings.xml'] = [
    ('    <string name="app_name">Wind Waker HD</string>\n',
     '    <string name="app_name">Captain Toad: Treasure Tracker</string>\n'),
]
# The PC route's game folder (copied over USB) holds Captain Toad's executable, not Wind Waker HD's.
REPLACEMENTS['../android/app/src/main/java/org/wwhdrecomp/wwhd/SetupActivity.java'] = [
    ('                return external != null && new File(external, "game/code/cking.rpx").isFile();\n',
     '                return external != null && new File(external, "game/code/Kinopio.rpx").isFile();\n'),
    ('                    (external != null && new File(external, "game/code/cking.rpx").isFile()));\n',
     '                    (external != null && new File(external, "game/code/Kinopio.rpx").isFile()));\n'),
]
REPLACEMENTS['../CMakeLists.txt'] = [
    ('target_include_directories(wwhd PRIVATE runtime/include runtime/src runtime/src/gx2)\n',
     'target_include_directories(wwhd PRIVATE runtime/include runtime/src runtime/src/gx2)\n'
     '# Captain Toad runtime services the reference runtime lacks (CaptainToadRecomp tools/patch_runtime.py)\n'
     'set(CT_EXTRA_SOURCES "" CACHE STRING "Captain Toad runtime sources added to the game executable")\n'
     'target_sources(wwhd PRIVATE ${CT_EXTRA_SOURCES})\n'),
]
# Captain Toad cheats (runtime/cheats.cpp, runtime/ct_save.h) replace the Wind Waker HD ones: save edits
# applied with a restart, listed in the Gameplay menu and the settings overlay.
REPLACEMENTS['src/gfx/menu.mm'] = [
    ('#include "../mods/mods.h"\n', '#include "../mods/mods.h"\n#include "../mods/ct_save.h"\n#include <tuple>\n'),
    (('    [gp addItemWithTitle:@"Cheats (save in game to keep them)" action:nil keyEquivalent:@""].enabled = NO;\n'
         '    toggle(gp, @"    Give all items", ^BOOL { return NO; }, ^(BOOL) { mods::request_cheat(mods::kCheatItems); },\n'
         '           @"Every inventory item, light arrows, deluxe picto box, power bracelets, 4 bottles, 99 arrows and bombs");\n'
         '    toggle(gp, @"    Equip Master Sword and Mirror Shield (until reload)", ^BOOL { return NO; }, ^(BOOL) { mods::request_cheat(mods::kCheatSword); });\n'
         '    toggle(gp, @"    20 hearts, double magic, 5000 rupees", ^BOOL { return NO; }, ^(BOOL) { mods::request_cheat(mods::kCheatStats); },\n'
         '           @"Also refills hearts and magic");\n'
         '    toggle(gp, @"    Fill the bags (spoils and bait)", ^BOOL { return NO; }, ^(BOOL) { mods::request_cheat(mods::kCheatBags); },\n'
         '           @"Spoils bag and bait bag (if missing), every kind of spoils x99, empty bait slots filled");\n'
         '    for (auto [title, which] : {std::pair{@"    Infinite health", mods::kInfHealth}, {@"    Infinite magic", mods::kInfMagic},\n'
         '                                {@"    Infinite arrows and bombs", mods::kInfAmmo}, {@"    Infinite rupees", mods::kInfRupees},\n'
         '                                {@"    Infinite bait and spoils", mods::kInfBags}, {@"    Infinite swimming", mods::kInfBreath}}) {\n'
         '        int bit = which;  // (blocks cannot capture structured bindings)\n'
         '        toggle(gp, title, ^BOOL { return mods::infinite(bit); }, ^(BOOL on) { mods::set_infinite(bit, on); });\n'
         '    }\n'
         '    [gp addItem:[NSMenuItem separatorItem]];\n'
         '    NSString* story = @"Can change or break story events: the game may skip or repeat scenes that teach or check this. "\n'
         '                      @"Save to a different file first.";\n'
         '    [gp addItemWithTitle:@"⚠️ Story cheats (can break story events; use a spare save file)" action:nil keyEquivalent:@""].enabled = NO;\n'
         '    toggle(gp, @"    All songs", ^BOOL { return NO; }, ^(BOOL) { mods::request_cheat(mods::kCheatSongs); }, story);\n'
         '    toggle(gp, @"    All Triforce shards", ^BOOL { return NO; }, ^(BOOL) { mods::request_cheat(mods::kCheatTriforce); }, story);\n'
         '    toggle(gp, @"    Map, compass and boss key (this dungeon)", ^BOOL { return NO; }, ^(BOOL) { mods::request_cheat(mods::kCheatDungeon); }, story);\n'
         '    toggle(gp, @"    Add a small key (this dungeon)", ^BOOL { return NO; }, ^(BOOL) { mods::request_cheat(mods::kCheatKey); }, story);\n'),
     ('    [gp addItemWithTitle:@"Cheats (the game restarts; play since its last save is lost)" action:nil keyEquivalent:@""].enabled = NO;\n'
         '    for (auto [title, which, tip] : {\n'
         '             std::tuple{@"    Unlock every episode and course", (int)ct_save::kUnlockEpisodes, @"Episodes 2 and 3, the bonus episode and every course page"},\n'
         '             {@"    Clear every course", (int)ct_save::kClearCourses, @"Every course counts as cleared, with the ending seen; the episodes open"},\n'
         '             {@"    Every Super Gem", (int)ct_save::kAllGems, @"All 192 Super Gems"},\n'
         '             {@"    Every bonus objective", (int)ct_save::kAllBonus, @"The second Toad Stamp\'s task in every course that has one"},\n'
         '             {@"    Every challenge time", (int)ct_save::kAllTimes, @"Each course\'s best time set to its challenge time unless it is already faster"},\n'
         '             {@"    Every Pixel Toad", (int)ct_save::kAllPixelToads, @"Pixel Toad found in every course that hides one: the golden Pixel Toad on each episode"},\n'
         '             {@"    100% completion", (int)ct_save::kComplete, @"All of the above, every course 100%, Coins Galore and Mummy-Me Maze Forever: every Toad Stamp with glittering stars"}}) {\n'
         '        int bit = which;  // (blocks cannot capture structured bindings)\n'
         '        toggle(gp, title, ^BOOL { return NO; }, ^(BOOL) { mods::request_cheat(bit); }, tip);\n'
         '    }\n')),
]
REPLACEMENTS['src/overlay/overlay.cpp'] = [
    ('#include "../mods/mods.h"\n', '#include "../mods/mods.h"\n#include "../mods/ct_save.h"\n#include "../ct_touch_menu.h"\n'),
    (('void cheats() {\n'
         '    bool v;\n'
         '    note("Save in the game to keep them.");\n'
         '    auto cheat = [first = true](const char* label, int which) mutable {\n'
         '        if (!first) modsui::same_line_if_fits(label);\n'
         '        first = false;\n'
         '        if (ImGui::Button(label)) mods::request_cheat(which);\n'
         '    };\n'
         '    cheat("Give all items", mods::kCheatItems);\n'
         '    cheat("Equip Master Sword + Mirror Shield (until reload)", mods::kCheatSword);\n'
         '    cheat("20 hearts, double magic, 5000 rupees", mods::kCheatStats);\n'
         '    cheat("Fill the bags (spoils and bait)", mods::kCheatBags);\n'
         '    static const std::pair<const char*, int> inf[] = {{"Infinite health", mods::kInfHealth}, {"Infinite magic", mods::kInfMagic},\n'
         '                                                      {"Infinite arrows and bombs", mods::kInfAmmo},\n'
         '                                                      {"Infinite rupees", mods::kInfRupees},\n'
         '                                                      {"Infinite bait and spoils", mods::kInfBags},\n'
         '                                                      {"Infinite swimming", mods::kInfBreath},\n'
         '                                                      {"Moon jump (hold L; left stick steers)", mods::kMoonJump},\n'
         '                                                      {"No fall damage after moon jump", mods::kMoonNoFall}};\n'
         '    for (const auto& [label, which] : inf) {\n'
         '        int bit = which;\n'
         '        if (check(label, mods::infinite(bit), &v)) hostui::post([bit, v] { mods::set_infinite(bit, v); });\n'
         '    }\n'
         '    heading("Story cheats (can break story events; use a spare save file)");\n'
         '    auto story = [first = true](const char* label, int which) mutable {\n'
         '        if (!first) modsui::same_line_if_fits(label);\n'
         '        first = false;\n'
         '        if (ImGui::Button(label)) mods::request_cheat(which);\n'
         '    };\n'
         '    story("All songs", mods::kCheatSongs);\n'
         '    story("All Triforce shards", mods::kCheatTriforce);\n'
         '    story("Map, compass, boss key", mods::kCheatDungeon);\n'
         '    story("Small key", mods::kCheatKey);\n'
         '}\n'),
     ('void cheats() {\n'
         '#ifdef __ANDROID__\n'
         '    note("Each cheat changes the save and closes the game: open it again to play with it. Play since the game "\n'
         '         "last saved is lost. The save before the first cheat is kept as GameData.bin.before-cheats.");\n'
         '#else\n'
         '    note("Each cheat changes the save and restarts the game: play since the game last saved is lost. "\n'
         '         "The save before the first cheat is kept as GameData.bin.before-cheats.");\n'
         '#endif\n'
         '    auto cheat = [first = true](const char* label, int which) mutable {\n'
         '        if (!first) modsui::same_line_if_fits(label);\n'
         '        first = false;\n'
         '        if (ImGui::Button(label)) mods::request_cheat(which);\n'
         '    };\n'
         '    cheat("Unlock every episode and course", ct_save::kUnlockEpisodes);\n'
         '    cheat("Clear every course", ct_save::kClearCourses);\n'
         '    cheat("Every Super Gem", ct_save::kAllGems);\n'
         '    cheat("Every bonus objective", ct_save::kAllBonus);\n'
         '    cheat("Every challenge time", ct_save::kAllTimes);\n'
         '    cheat("Every Pixel Toad", ct_save::kAllPixelToads);\n'
         '    heading("Everything");\n'
         '    cheat("100% completion (every Toad Stamp, glittering stars, golden Pixel Toads)", ct_save::kComplete);\n'
         '}\n')),
]
# Dynamic resolution starts on (down to 0.75 of the internal resolution), so a scene the GPU can't
# draw in time costs resolution instead of frame rate. The saved setting and WWHD_DYNRES_MIN still win.
REPLACEMENTS['src/dynres.cpp'] = [
    ('std::atomic<float> g_min{env_min() ? clamp_min((float)atof(env_min())) : 0.0f};\n',
     'std::atomic<float> g_min{env_min() ? clamp_min((float)atof(env_min())) : 0.75f};\n'),
]
# Settings that only act on Wind Waker HD (its frame pacing hooks, camera, projection, sky, clouds,
# bloom and occlusion shaders, gameplay mods) are left out of the Captain Toad runtime: the Graphics
# and Gameplay menus and the settings overlay keep what applies to any game.
_ct_only = '#ifndef CT_FOREIGN_GUEST  // Wind Waker HD only (CaptainToadRecomp tools/patch_runtime.py)\n'
_ct_end = '#endif  // Wind Waker HD only\n'
REPLACEMENTS['src/overlay/overlay.cpp'] += [
    ('    heading("Frame rate");\n', _ct_only + '    heading("Frame rate");\n'),
    ('    // debug only, not saved (gx2::uncapped)\n', _ct_end + '    // debug only, not saved (gx2::uncapped)\n'),
    ('    float fovPercent=aspect::fov_scale()*100.0f;\n', _ct_only + '    float fovPercent=aspect::fov_scale()*100.0f;\n'),
    ('            post_changed([i] { aspect::set_mode(i); hostui::set("aspectMode", std::to_string(i)); });\n    }\n',
     '            post_changed([i] { aspect::set_mode(i); hostui::set("aspectMode", std::to_string(i)); });\n    }\n' + _ct_end),
    ('    float bloom = render::bloom_strength() * 100.0f;\n', _ct_only + '    float bloom = render::bloom_strength() * 100.0f;\n'),
    ('        post_changed([v] { render::set_ao_hires(v); });\n', '        post_changed([v] { render::set_ao_hires(v); });\n' + _ct_end),
]
# Saved settings from a Wind Waker HD build (or an earlier Captain Toad one) still reach the setters of
# those features: the gameplay FOV rescaled Captain Toad's 2D layouts and broke its text. They keep the
# original game's values here whatever is saved.
_ct_keep = '#ifdef CT_FOREIGN_GUEST\n    {}\n#endif\n'
REPLACEMENTS['src/aspect.cpp'] = [
    ('void set_mode(int m) {\n    if (m < 0 || m >= kModes) return;\n',
     'void set_mode(int m) {\n' + _ct_keep.format('m = kOriginal;  // Wind Waker HD only') + '    if (m < 0 || m >= kModes) return;\n'),
    ('void set_fov_scale(float scale) {\n', 'void set_fov_scale(float scale) {\n' + _ct_keep.format('scale = 1.0f;  // Wind Waker HD only')),
]
REPLACEMENTS['src/interp.cpp'] = [
    ('void set_mode(int m) {\n    g_on = false;\n',
     'void set_mode(int m) {\n' + _ct_keep.format('m = 0;  // Wind Waker HD frame pacing (its hooks); Captain Toad runs at 60') + '    g_on = false;\n'),
]
# Captain Toad is played on the GamePad (touch, gyro camera): on Android the phone's screen starts as
# the GamePad, so a touch anywhere on the picture is a GamePad touch. The view button still cycles.
REPLACEMENTS['src/gfx/display_modes.cpp'] = [
    ('std::atomic<int> g_mode{kDrcOff};\n',
     '#ifdef CT_FOREIGN_GUEST\nstd::atomic<int> g_mode{kDrcGamePad};\n#else\n'
     'std::atomic<int> g_mode{kDrcOff};\n#endif  // Captain Toad GamePad view\n'),
    # The TV shows the GamePad's picture in Captain Toad: on Android a touch on the TV picture (TV only,
    # or outside the corner GamePad) touches the GamePad at the same place.
    ('    const Layout& L = g_tv_layout;\n    if (!L.pip_on || L.pip.w <= 0) return false;\n'
     '    float x = (nx * g_tv_dw - L.pip.x) / L.pip.w, y = (ny * g_tv_dh - L.pip.y) / L.pip.h;\n'
     '    if (!clamp_outside && (x < 0 || x > 1 || y < 0 || y > 1)) return false;\n',
     '    const Layout& L = g_tv_layout;\n'
     '#if defined(CT_FOREIGN_GUEST) && defined(__ANDROID__)\n'
     '    const bool on_pip = L.pip_on && L.pip.w > 0 && nx * g_tv_dw >= L.pip.x && ny * g_tv_dh >= L.pip.y &&\n'
     '        nx * g_tv_dw <= L.pip.x + L.pip.w && ny * g_tv_dh <= L.pip.y + L.pip.h;\n'
     '    const Box& P = on_pip || L.drc_only || L.tv.w <= 0 ? L.pip : L.tv;\n'
     '    if (P.w <= 0) return false;\n'
     '    float x = (nx * g_tv_dw - P.x) / P.w, y = (ny * g_tv_dh - P.y) / P.h;\n'
     '#else\n'
     '    if (!L.pip_on || L.pip.w <= 0) return false;\n'
     '    float x = (nx * g_tv_dw - L.pip.x) / L.pip.w, y = (ny * g_tv_dh - L.pip.y) / L.pip.h;\n'
     '#endif  // Captain Toad TV touch\n'
     '    if (!clamp_outside && (x < 0 || x > 1 || y < 0 || y > 1)) return false;\n'),
    # Android: one menu button (TouchControls.java, runtime/ct_touch_menu.cpp) replaces the view button,
    # the touch controls' show/hide button and the tilt button; WWHD_VIEW_BUTTON=1 still shows the view button.
    ('#ifdef __ANDROID__\n        return !e || atoi(e) != 0;\n#else\n',
     '#if defined(__ANDROID__) && !defined(CT_FOREIGN_GUEST)\n        return !e || atoi(e) != 0;\n#else\n'),
    ('bool overlay_hit(float nx, float ny, float* tx, float* ty, bool clamp_outside) {\n',
     '// ---- the picture-in-picture GamePad moved and resized with the pointer (display_modes.h)\n'
     'static int g_pip_drag = 0;  // 0 none, 1 move, 2 resize\n'
     'static float g_pip_grab_x = 0, g_pip_grab_y = 0;  // moving: the pointer minus the picture\'s centre\n'
     'static bool pip_under(const Layout& L, float x, float y) {\n'
     '    const Box& P = L.pip;\n'
     '    return L.pip_on && !L.drc_only && P.w > 0 && P.h > 0 && L.tv.w > 0 && L.tv.h > 0 && x >= P.x && y >= P.y &&\n'
     '        x <= P.x + P.w && y <= P.y + P.h;\n'
     '}\n'
     '// the picture with its centre at (cx, cy) in display units, `size` of the TV picture\'s width\n'
     'static void pip_put(const Layout& L, float cx, float cy, float size) {\n'
     '    g_pip_size = pip_clamp_size(size);\n'
     '    pip_set_position(pip_place(L.tv, L.pip.w / L.pip.h, g_pip_size, (cx - L.tv.x) / L.tv.w, (cy - L.tv.y) / L.tv.h));\n'
     '}\n'
     'bool pip_drag_begin(float nx, float ny) {\n'
     '    std::lock_guard<std::mutex> lk(g_layout_mu);\n'
     '    const Layout& L = g_tv_layout;\n'
     '    const float x = nx * g_tv_dw, y = ny * g_tv_dh;\n'
     '    if (!pip_under(L, x, y)) return false;\n'
     '    const Box& P = L.pip;\n'
     '    const float corner = std::max(12.0f, std::min(P.w, P.h) * 0.2f);\n'
     '    g_pip_drag = x > P.x + P.w - corner && y > P.y + P.h - corner ? 2 : 1;\n'
     '    g_pip_grab_x = x - (P.x + P.w / 2);\n'
     '    g_pip_grab_y = y - (P.y + P.h / 2);\n'
     '    return true;\n'
     '}\n'
     'bool pip_dragging() { return g_pip_drag != 0; }\n'
     'void pip_drag_move(float nx, float ny) {\n'
     '    std::lock_guard<std::mutex> lk(g_layout_mu);\n'
     '    const Layout& L = g_tv_layout;\n'
     '    if (!g_pip_drag || L.pip.w <= 0 || L.pip.h <= 0 || L.tv.w <= 0 || L.tv.h <= 0) return;\n'
     '    const float x = nx * g_tv_dw, y = ny * g_tv_dh;\n'
     '    if (g_pip_drag == 1) {\n'
     '        pip_put(L, x - g_pip_grab_x, y - g_pip_grab_y, g_pip_size);\n'
     '        return;\n'
     '    }\n'
     '    // resizing: the top-left corner stays, the bottom-right one follows the pointer\n'
     '    const float aspect = L.pip.w / L.pip.h;\n'
     '    const float w = pip_clamp_size(std::max({x - L.pip.x, (y - L.pip.y) * aspect, 1.0f}) / L.tv.w) * L.tv.w;\n'
     '    pip_put(L, L.pip.x + w / 2, L.pip.y + w / aspect / 2, w / L.tv.w);\n'
     '}\n'
     'bool pip_drag_end() {\n'
     '    const bool was = g_pip_drag != 0;\n'
     '    g_pip_drag = 0;\n'
     '    return was;\n'
     '}\n'
     'bool pip_wheel(float nx, float ny, float steps) {\n'
     '    std::lock_guard<std::mutex> lk(g_layout_mu);\n'
     '    const Layout& L = g_tv_layout;\n'
     '    if (!pip_under(L, nx * g_tv_dw, ny * g_tv_dh) || steps == 0) return false;\n'
     '    pip_put(L, L.pip.x + L.pip.w / 2, L.pip.y + L.pip.h / 2, g_pip_size * std::pow(1.1f, steps));\n'
     '    return true;\n'
     '}\n'
     'bool overlay_hit(float nx, float ny, float* tx, float* ty, bool clamp_outside) {\n'),
]
# The picture-in-picture GamePad moved and resized with the pointer (macOS TV window): a right-button
# or Option drag on the picture moves it (Custom placement), the same drag from its bottom-right corner
# resizes it, and the scroll wheel over it resizes it. A plain click stays a GamePad touch.
REPLACEMENTS['src/gfx/display.mm'] = [
    ('''- (void)mouseDown:(NSEvent*)e {
    float x, y;
    if ([self map:e x:&x y:&y clamp:false]) {
        self.touching = true;
''', '''// the picture-in-picture GamePad: a right-button or Option drag moves it (from its bottom-right corner:
// resizes it), the scroll wheel over it resizes it (display_modes.h)
- (void)point:(NSEvent*)e x:(float*)nx y:(float*)ny {
    NSPoint p = [self convertPoint:e.locationInWindow fromView:nil];
    NSSize sz = self.bounds.size;
    *nx = sz.width > 0 ? p.x / sz.width : 0;
    *ny = sz.height > 0 ? 1.0f - p.y / sz.height : 0;
}
- (bool)pipBegin:(NSEvent*)e {
    float nx, ny;
    [self point:e x:&nx y:&ny];
    if (!gfx::pip_drag_begin(nx, ny)) return false;
    [NSCursor.closedHandCursor push];
    return true;
}
- (bool)pipMove:(NSEvent*)e {
    if (!gfx::pip_dragging()) return false;
    float nx, ny;
    [self point:e x:&nx y:&ny];
    gfx::pip_drag_move(nx, ny);
    return true;
}
- (bool)pipEnd {
    if (!gfx::pip_drag_end()) return false;
    [NSCursor pop];
    gfx::save_options();
    return true;
}
- (void)rightMouseDown:(NSEvent*)e {
    if (![self pipBegin:e]) [super rightMouseDown:e];
}
- (void)rightMouseDragged:(NSEvent*)e {
    if (![self pipMove:e]) [super rightMouseDragged:e];
}
- (void)rightMouseUp:(NSEvent*)e {
    if (![self pipEnd]) [super rightMouseUp:e];
}
- (void)scrollWheel:(NSEvent*)e {
    float nx, ny;
    [self point:e x:&nx y:&ny];
    const float steps = e.hasPreciseScrollingDeltas ? e.scrollingDeltaY / 20.0f : e.scrollingDeltaY;
    if (gfx::pip_wheel(nx, ny, steps)) gfx::save_options();
    else [super scrollWheel:e];
}
- (void)mouseDown:(NSEvent*)e {
    float x, y;
    if ((e.modifierFlags & NSEventModifierFlagOption) && [self pipBegin:e]) return;
    if ([self map:e x:&x y:&y clamp:false]) {
        self.touching = true;
'''),
    ('''- (void)mouseDragged:(NSEvent*)e {
    float x, y;
    if (self.touching''', '''- (void)mouseDragged:(NSEvent*)e {
    float x, y;
    if ([self pipMove:e]) return;
    if (self.touching'''),
    ('''- (void)mouseUp:(NSEvent*)e {
    float x, y;
    if (!self.touching) return;''', '''- (void)mouseUp:(NSEvent*)e {
    float x, y;
    if ([self pipEnd]) return;
    if (!self.touching) return;'''),
]
REPLACEMENTS['src/gfx/display_modes.h'] = [
    ('void pip_set_position(PipPosition position);\n',
     'void pip_set_position(PipPosition position);\n'
     '// Pointer gestures on the picture-in-picture GamePad in the TV window (0..1 from the top left):\n'
     '// begin is true when the point is on the picture (a drag from its bottom-right corner resizes it,\n'
     '// any other drag moves it); end is true when a drag ended (the host saves the placement); wheel\n'
     '// resizes the picture under the point by 10% per step and is true when it did.\n'
     'bool pip_drag_begin(float nx, float ny);\n'
     'bool pip_dragging();\n'
     'void pip_drag_move(float nx, float ny);\n'
     'bool pip_drag_end();\n'
     'bool pip_wheel(float nx, float ny, float steps);\n'),
]
REPLACEMENTS['src/gfx/gamepad_ui_state.cpp'] = [
    ('void display_read_gamepad_ui() {\n    if (!display_gamepad_state_needed()) return;\n',
     'void display_read_gamepad_ui() {\n#ifdef CT_FOREIGN_GUEST\n    return;\n#endif\n    if (!display_gamepad_state_needed()) return;\n'),
]
REPLACEMENTS['src/gfx/renderer.cpp'] = [
    ('void set_cloud_style(int style) { g_cloud_style.store(std::clamp(style, 0, 2), std::memory_order_relaxed); }\n',
     '#ifdef CT_FOREIGN_GUEST\nvoid set_cloud_style(int) { g_cloud_style.store(0, std::memory_order_relaxed); }  // Wind Waker HD only\n#else\n'
     'void set_cloud_style(int style) { g_cloud_style.store(std::clamp(style, 0, 2), std::memory_order_relaxed); }\n#endif\n'),
    ('void set_cloud_shadows(bool on) { g_cloud_shadows.store(on, std::memory_order_relaxed); }\n',
     '#ifdef CT_FOREIGN_GUEST\nvoid set_cloud_shadows(bool) { g_cloud_shadows.store(false, std::memory_order_relaxed); }  // Wind Waker HD only\n#else\n'
     'void set_cloud_shadows(bool on) { g_cloud_shadows.store(on, std::memory_order_relaxed); }\n#endif\n'),
    ('void set_horizon_haze(float v) {\n', 'void set_horizon_haze(float v) {\n' + _ct_keep.format('v = 1.0f;  // Wind Waker HD only')),
    ('void set_bloom_strength(float v) {\n', 'void set_bloom_strength(float v) {\n' + _ct_keep.format('v = 1.0f;  // Wind Waker HD only')),
]
REPLACEMENTS['src/gfx/metal_draw.mm'] = [
    ('void set_ao_mode(int m) { g_ao_mode = m % 3;',
     'void set_ao_mode(int m) {\n' + _ct_keep.format('m = 0;  // Wind Waker HD only') + '    g_ao_mode = m % 3;'),
    ('void set_ao_hires(bool v) { g_ao_hires = v;',
     'void set_ao_hires(bool v) {\n' + _ct_keep.format('v = false;  // Wind Waker HD only') + '    g_ao_hires = v;'),
    # Stream-out on the GPU, as Cemu's Metal renderer does it: vertex shaders that write stream-out data
    # store it through a device pointer (sb) at each buffer's write offset, which gx2_core.cpp advances
    # after the draw, into a GPU shadow of the buffer that later draws read (never into guest memory). Draws with rasterization disabled run alone, in a pass
    # without attachments. Captain Toad's effects (particles and trails) are drawn from these buffers.
    ('    opt.strictMul = strictMul;\n',
     '    opt.strictMul = strictMul;\n'
     '    opt.useTFViaSSBO = vertex;  // stream-out writes go to a device buffer (sb)\n'),
    ('        cache_record_pipeline(regs, vs, ps, fsKey, tf);\n',
     '        if (ps) cache_record_pipeline(regs, vs, ps, fsKey, tf);  // no pixel shader: a stream-out-only draw\n'),
    ('    d.fragmentFunction = ps->fn;\n',
     '    d.fragmentFunction = ps ? ps->fn : nil;\n'
     '    if (!ps) d.rasterizationEnabled = NO;  // stream-out only: the vertex shader writes the buffers\n'),
    ('static void bind_stage(id<MTLRenderCommandEncoder> enc, const uint32_t* regs, Shader* sh, bool vertex, Surface* const* colors) {\n',
     '// ---- stream-out (Captain Toad)\n'
     '// The GPU runs a frame behind the game, and the game reuses small stream-out buffers from per-frame\n'
     '// memory, so the output never goes into guest memory: each buffer gets a shadow in one GPU arena\n'
     '// (seeded with the guest bytes; one arena, so the shader\'s one device pointer reaches every buffer),\n'
     '// and draws of this frame and the next that read the buffer read its shadow.\n'
     'static uint32_t g_so_vertices = 0;  // the current draw\'s vertices per instance (supportBuffer.verticesPerInstance)\n'
     'struct SoShadow { uint32_t base, size, at; uint64_t frame; };\n'
     'static std::vector<SoShadow> g_so_shadows;\n'
     'static id<MTLBuffer> g_so_arena = nil;\n'
     'static uint32_t g_so_used = 0;\n'
     'constexpr uint32_t kSoArena = 64u << 20;\n'
     'static uint32_t g_so_at[LATTE_NUM_STREAMOUT_BUFFER];  // the current draw\'s buffers: their shadows in the arena\n'
     '// the shadow holding `addr`, written this frame or the last, and the offset of addr in the arena\n'
     'static id<MTLBuffer> so_shadow(uint32_t addr, uint32_t* offset) {\n'
     '    for (auto& s : g_so_shadows)\n'
     '        if (addr - s.base < s.size && R.frame - s.frame <= 1) {\n'
     '            *offset = s.at + (addr - s.base);\n'
     '            return g_so_arena;\n'
     '        }\n'
     '    return nil;\n'
     '}\n'
     '// Shadows for the buffers the draw writes, made or reused. The shader drops writes past a buffer\'s\n'
     '// end, as the hardware does (supportBuffer.streamoutBufferEnd).\n'
     'static bool streamout_ready(const uint32_t* regs, const LatteDecompilerShader* dec, uint64_t vertices) {\n'
     '    if (!g_so_arena) g_so_arena = [R.device newBufferWithLength:kSoArena options:MTLResourceStorageModeShared];\n'
     '    if (!g_so_arena) return false;\n'
     '    for (int i = 0; i < LATTE_NUM_STREAMOUT_BUFFER; i++) {\n'
     '        if (dec->uniform.loc_streamoutBufferBase[i] < 0) continue;\n'
     '        const uint32_t base = regs[mmVGT_STRMOUT_BUFFER_BASE_0 + i * 4], size = regs[mmVGT_STRMOUT_BUFFER_SIZE_0 + i * 4] << 2;\n'
     '        const uint32_t offset = regs[mmVGT_STRMOUT_BUFFER_OFFSET_0 + i * 4];\n'
     '        if (!base || !size || size > kSoArena / 4 || offset > size || !mem::ptr(base)) {\n'
     '            static int logged = 0;\n'
     '            if (logged++ < 8)\n'
     '                LOG("[gfx] stream-out draw skipped: buffer %d at %08X size %X offset %X (%llu vertices)", i, base, size, offset,\n'
     '                    (unsigned long long)vertices);\n'
     '            return false;\n'
     '        }\n'
     '        SoShadow* shadow = nullptr;\n'
     '        for (auto it = g_so_shadows.begin(); it != g_so_shadows.end();) {\n'
     '            if (it->base == base && it->size == size) { shadow = &*it; break; }\n'
     '            // another buffer over the same bytes (the game reused the memory): forget the old one\n'
     '            if (base < it->base + it->size && it->base < base + size) it = g_so_shadows.erase(it);\n'
     '            else ++it;\n'
     '        }\n'
     '        if (!shadow) {\n'
     '            if (g_so_used + size > kSoArena) {  // full: start over (older shadows are long read)\n'
     '                g_so_shadows.clear();\n'
     '                g_so_used = 0;\n'
     '            }\n'
     '            memcpy((uint8_t*)g_so_arena.contents + g_so_used, mem::ptr(base), size);\n'
     '            g_so_shadows.push_back({base, size, g_so_used, R.frame});\n'
     '            g_so_used += (size + 255) & ~255u;\n'
     '            shadow = &g_so_shadows.back();\n'
     '        }\n'
     '        shadow->frame = R.frame;\n'
     '        g_so_at[i] = shadow->at;\n'
     '    }\n'
     '    return true;\n'
     '}\n'
     'static void bind_stage(id<MTLRenderCommandEncoder> enc, const uint32_t* regs, Shader* sh, bool vertex, Surface* const* colors) {\n'),
    ('            sz[1] = (regs[REGADDR::SQ_TEX_RESOURCE_WORD0_N_PS + t * 7 + 1] & 0x1FFF) + 1;\n        }\n'
     '        if (buf.size() <= 4096) {\n',
     '            sz[1] = (regs[REGADDR::SQ_TEX_RESOURCE_WORD0_N_PS + t * 7 + 1] & 0x1FFF) + 1;\n        }\n'
     '        if (vertex && dec->uniform.loc_verticesPerInstance >= 0) {  // stream-out (streamout_ready checked the buffers)\n'
     '            *(sint32*)at(dec->uniform.loc_verticesPerInstance) = (sint32)g_so_vertices;\n'
     '            for (int i = 0; i < LATTE_NUM_STREAMOUT_BUFFER; i++) {\n'
     '                if (dec->uniform.loc_streamoutBufferBase[i] < 0) continue;\n'
     '                *(sint32*)at(dec->uniform.loc_streamoutBufferBase[i]) = (sint32)(g_so_at[i] + regs[mmVGT_STRMOUT_BUFFER_OFFSET_0 + i * 4]);\n'
     '                *(sint32*)at(dec->uniform.loc_streamoutBufferBase[i] + 4) = (sint32)(g_so_at[i] + (regs[mmVGT_STRMOUT_BUFFER_SIZE_0 + i * 4] << 2));\n'
     '                if (rm.tfStorageBindingPoint >= 0) [enc setVertexBuffer:g_so_arena offset:0 atIndex:rm.tfStorageBindingPoint];\n'
     '            }\n'
     '        }\n'
     '        if (buf.size() <= 4096) {\n'),
    ('// ---------------------------------------------------------------- draw\n',
     '// A stream-out draw with rasterization disabled: only its vertex shader runs, writing the stream-out\n'
     '// buffers, in a pass without attachments (kept open for the next such draw).\n'
     'static bool streamout_only(const uint32_t* regs, Shader* vs, LatteFetchShader* fs, uint64_t fsKey, uint32_t prim, uint32_t count,\n'
     '                           uint32_t indexType, uint32_t indexAddr, uint32_t baseVertex, uint32_t instances) {\n'
     '    if (!vs || !vs->dec) return false;\n'
     '    retry_failed_compile(vs, false);\n'
     '    if (vs->state == CS_FAILED) return false;\n'
     '    compile_deferred(vs);\n'
     '    if (!wait_compiled(vs->state) || !vs->dec->hasStreamoutBufferWrite) return false;\n'
     '    static std::vector<uint32_t> indices;\n'
     '    MTLPrimitiveType ptype;\n'
     '    if (!build_indices(prim, count, indexType, indexAddr, indices, ptype)) return false;\n'
     '    uint64_t span = uint64_t(baseVertex) + count;\n'
     '    for (uint32_t i : indices) span = std::max<uint64_t>(span, uint64_t(baseVertex) + i + 1);\n'
     '    if (!streamout_ready(regs, vs->dec, span + uint64_t(count) * (instances - 1))) return false;\n'
     '    TargetFormats none;\n'
     '    id<MTLRenderPipelineState> pipe = get_pipeline(regs, vs, nullptr, fs, fsKey, none);\n'
     '    if (!pipe) return false;\n'
     '    bool open = R.enc && !R.passDepth;\n'
     '    for (auto* c : R.passColor) open = open && !c;\n'
     '    if (!open) {\n'
     '        end_encoder();\n'
     '        MTLRenderPassDescriptor* rp = [MTLRenderPassDescriptor renderPassDescriptor];\n'
     '        rp.renderTargetWidth = 1;\n'
     '        rp.renderTargetHeight = 1;\n'
     '        rp.defaultRasterSampleCount = 1;\n'
     '        R.enc = [command_buffer() renderCommandEncoderWithDescriptor:rp];\n'
     '        if (!R.enc) return false;\n'
     '        for (auto& c : R.passColor) c = nullptr;\n'
     '        R.passDepth = nullptr;\n'
     '    }\n'
     '    id<MTLRenderCommandEncoder> enc = R.enc;\n'
     '    [enc setRenderPipelineState:pipe];\n'
     '    for (auto& g : fs->bufferGroups) {\n'
     '        uint32_t off = 0;\n'
     '        const uint32_t addr = regs[mmSQ_VTX_ATTRIBUTE_BLOCK_START + g.attributeBufferIndex * 7];\n'
     '        id<MTLBuffer> b = so_shadow(addr, &off);\n'
     '        if (!b) b = guest_buffer(addr, &off);\n'
     '        if (b) [enc setVertexBuffer:b offset:off atIndex:GET_MTL_VERTEX_BUFFER_INDEX(g.attributeBufferIndex)];\n'
     '    }\n'
     '    Surface* noColors[8] = {};\n'
     '    g_so_vertices = count;\n'
     '    R.binding = true;\n'
     '    bind_stage(enc, regs, vs, true, noColors);\n'
     '    R.binding = false;\n'
     '    if (indices.empty()) {\n'
     '        [enc drawPrimitives:ptype vertexStart:baseVertex vertexCount:count instanceCount:instances];\n'
     '    } else {\n'
     '        Upload u = upload(indices.data(), (uint32_t)(indices.size() * 4));\n'
     '        [enc drawIndexedPrimitives:ptype indexCount:indices.size() indexType:MTLIndexTypeUInt32 indexBuffer:u.buf\n'
     '                 indexBufferOffset:u.offset instanceCount:instances baseVertex:baseVertex baseInstance:0];\n'
     '    }\n'
     '    [enc memoryBarrierWithScope:MTLBarrierScopeBuffers afterStages:MTLRenderStageVertex beforeStages:MTLRenderStageVertex];\n'
     '    static bool logged = false;\n'
     '    if (!logged) { logged = true; LOG("[gfx] stream-out: vertex shaders write their buffers on the GPU"); }\n'
     '    return true;\n'
     '}\n'
     '// ---------------------------------------------------------------- draw\n'),
    ('    if (regs[REGADDR::PA_CL_CLIP_CNTL] & (1 << 22)) { g_skip[SK_RASTER_KILL]++; return; }  // rasterization disabled\n',
     '    const bool rasterKill = (regs[REGADDR::PA_CL_CLIP_CNTL] & (1 << 22)) != 0;  // rasterization disabled\n'
     '    if (rasterKill && !regs[mmVGT_STRMOUT_EN]) { g_skip[SK_RASTER_KILL]++; return; }\n'),
    ('    Shader* ps = get_shader(regs, false, fs, fsKey);\n',
     '    if (rasterKill) {  // stream-out only\n'
     '        if (!streamout_only(regs, vs, fs, fsKey, prim, count, indexType, indexAddr, baseVertex, instances)) g_skip[SK_RASTER_KILL]++;\n'
     '        return;\n'
     '    }\n'
     '    Shader* ps = get_shader(regs, false, fs, fsKey);\n'),
    ('        if (g_snapshot && size <= kSnapshotLimit) {\n',
     '        uint32_t soOff = 0;  // stream-out output of this frame or the last: its shadow\n'
     '        if (id<MTLBuffer> shadow = so_shadow(addr, &soOff)) {\n'
     '            [enc setVertexBuffer:shadow offset:soOff atIndex:GET_MTL_VERTEX_BUFFER_INDEX(g.attributeBufferIndex)];\n'
     '            continue;\n'
     '        }\n'
     '        if (g_snapshot && size <= kSnapshotLimit) {\n'),
    ('        R.binding = true;\n        bind_stage(enc, regs, vs, true, colors);\n',
     '        g_so_vertices = count;\n'
     '        const bool streamout = vs->dec->uniform.loc_verticesPerInstance >= 0;\n'
     '        if (streamout) {\n'
     '            uint64_t span = uint64_t(baseVertex) + count;\n'
     '            for (uint32_t i : indices) span = std::max<uint64_t>(span, uint64_t(baseVertex) + i + 1);\n'
     '            if (!streamout_ready(regs, vs->dec, span + uint64_t(count) * (instances - 1))) { g_skip[SK_NO_SHADER]++; return; }\n'
     '        }\n'
     '        R.binding = true;\n        bind_stage(enc, regs, vs, true, colors);\n'),
    ('    for (int i = 0; i < 8; i++)\n        if (colors[i] && regs[mmCB_COLOR0_BASE + i]) g_target_drawn[regs[mmCB_COLOR0_BASE + i]].drawn(R.frame);\n',
     '    if (vs->dec->uniform.loc_verticesPerInstance >= 0)  // later draws read the stream-out output\n'
     '        [enc memoryBarrierWithScope:MTLBarrierScopeBuffers afterStages:MTLRenderStageVertex beforeStages:MTLRenderStageVertex];\n'
     '    for (int i = 0; i < 8; i++)\n        if (colors[i] && regs[mmCB_COLOR0_BASE + i]) g_target_drawn[regs[mmCB_COLOR0_BASE + i]].drawn(R.frame);\n'),
]
# Stream-out on Metal: each buffer's end (bytes, after its base in the support buffer) bounds the
# vertex shader's writes, which the hardware drops past a buffer's end (draws often emit more vertices
# than their buffer holds).
REPLACEMENTS['third_party/cemu/Cafe/HW/Latte/LegacyShaderDecompiler/LatteDecompilerEmitMSLHeader.hpp'] = [
    ('\t\t\t\t\tsrc->addFmt("int streamoutBufferBase{};" _CRLF, i);\n'
     '\t\t\t\t\tuniformOffsets.offset_streamoutBufferBase[i] = uniformCurrentOffset;\n'
     '\t\t\t\t\tuniformCurrentOffset += 4;\n',
     '\t\t\t\t\tsrc->addFmt("int streamoutBufferBase{};" _CRLF, i);\n'
     '\t\t\t\t\tuniformOffsets.offset_streamoutBufferBase[i] = uniformCurrentOffset;\n'
     '\t\t\t\t\tuniformCurrentOffset += 4;\n'
     '\t\t\t\t\tsrc->addFmt("int streamoutBufferEnd{};" _CRLF, i);  // Captain Toad: bounds the writes\n'
     '\t\t\t\t\tuniformCurrentOffset += 4;\n'),
]
REPLACEMENTS['third_party/cemu/Cafe/HW/Latte/LegacyShaderDecompiler/LatteDecompilerEmitMSL.cpp'] = [
    ('\t\t\tsrc->addFmt("sb[sbBase{} + {}]", streamoutBufferIndex, u32Offset);\n',
     '\t\t\tsrc->addFmt("if (sbBase{0} + {1} < supportBuffer.streamoutBufferEnd{0} / 4) sb[sbBase{0} + {1}]", streamoutBufferIndex, u32Offset);\n'),
]
REPLACEMENTS['src/gfx/vulkan/settings.cpp'] = [
    ('void set_ao_mode(int v) { settings().ao.store(normalize(v),std::memory_order_relaxed);',
     'void set_ao_mode(int v) {\n' + _ct_keep.format('v = 0;  // Wind Waker HD only') + '    settings().ao.store(normalize(v),std::memory_order_relaxed);'),
    ('void set_ao_hires(bool v) { settings().hires.store(v,std::memory_order_relaxed);',
     'void set_ao_hires(bool v) {\n' + _ct_keep.format('v = false;  // Wind Waker HD only') + '    settings().hires.store(v,std::memory_order_relaxed);'),
]
# PlayStation button prompts: the game reads a copy of FontData.szs with shapes for U+E000..E003
# (runtime/ct_prompts.cpp), the way the reference serves its item icon pack.
REPLACEMENTS['src/hle/fs.cpp'] = [
    ('    if(mode=="r"||mode=="rb")if(auto icons=item_icons::pack_for(guest,path);!icons.empty())return icons;\n',
     '    if(mode=="r"||mode=="rb")if(auto icons=item_icons::pack_for(guest,path);!icons.empty())return icons;\n'
     '#ifdef CT_FOREIGN_GUEST\n'
     '    if(mode=="r"||mode=="rb")if(auto font=ct_prompts::font_for(guest,path);!font.empty())return font;  // runtime/ct_prompts.cpp\n'
     '#endif\n'),
    ('#include "../rtl_text.h"\n',
     '#include "../rtl_text.h"\n'
     '#ifdef CT_FOREIGN_GUEST\nnamespace ct_prompts { std::string font_for(const std::string& guest, const std::string& host_path); }\n#endif\n'),
]
# Mods: Captain Toad packages (content trees, Cemu graphic packs, SDCafiine folders) installed from a file
# or folder, with their own game ID so Wind Waker HD mods are refused. The Wind Waker HD catalogue, its
# built-in mods, the GameCube game and code mods (Wind Waker HD's guest ABI) are left out; Cheats stay in
# More. The tab is Mods again.
_ct_package_id = ('#ifdef CT_FOREIGN_GUEST\n#define WWHD_PACKAGE_GAME_ID "captain-toad"  // CaptainToadRecomp\n'
                  '#else\n#define WWHD_PACKAGE_GAME_ID "wwhd"\n#endif\n')
REPLACEMENTS['src/mods/packages.h'] = [
    ('inline constexpr const char* kGameId="wwhd";\ninline constexpr const char* kLegacyGameId="wwhd-usa";\n',
     '#ifdef CT_FOREIGN_GUEST  // Captain Toad packages (CaptainToadRecomp); Wind Waker HD ones are refused\n'
     'inline constexpr const char* kGameId="captain-toad";\ninline constexpr const char* kLegacyGameId="captain-toad";\n#else\n'
     'inline constexpr const char* kGameId="wwhd";\ninline constexpr const char* kLegacyGameId="wwhd-usa";\n#endif\n'),
]
for _file in ('src/mods/content.cpp', 'src/mods/cemu_pack.cpp'):
    REPLACEMENTS[_file] = [
        ('#include "../exception_report.h"\n', '#include "../exception_report.h"\n' + _ct_package_id),
        ('m["game_id"]="wwhd"', 'm["game_id"]=WWHD_PACKAGE_GAME_ID'),
    ]
REPLACEMENTS['src/overlay/mods_tab.h'] = [
    ('    int area = kBuiltin;     // remembered for the session (State lives as long as the game runs)\n',
     '#ifdef CT_FOREIGN_GUEST\n    int area = kCommunity;   // Captain Toad: no built-in mods\n#else\n'
     '    int area = kBuiltin;     // remembered for the session (State lives as long as the game runs)\n#endif\n'),
    ('            if (ImGui::BeginTabItem(kAreaNames[i], nullptr, f)) {\n',
     '#ifdef CT_FOREIGN_GUEST\n            if (i == kBuiltin) continue;  // Wind Waker HD\'s built-in mods\n#endif\n'
     '            if (ImGui::BeginTabItem(kAreaNames[i], nullptr, f)) {\n'),
    ('    if (h.file_picker && section("GameCube game for mods")) {',
     '    if (h.file_picker && !kCaptainToad && section("GameCube game for mods")) {'),
    ('    if (section("Save backups")) {\n', '    if (!kCaptainToad && section("Save backups")) {\n'),
    ('enum Area { kBuiltin, kCommunity, kMore, kAreas };\n',
     'enum Area { kBuiltin, kCommunity, kMore, kAreas };\n'
     '#ifdef CT_FOREIGN_GUEST\ninline constexpr bool kCaptainToad = true;  // CaptainToadRecomp: Wind Waker HD sections left out\n#else\n'
     'inline constexpr bool kCaptainToad = false;\n#endif\n'),
    ('inline const char* const kAreaNames[kAreas] = {"Built-in", "Community", "More"};\n',
     '#ifdef CT_FOREIGN_GUEST\ninline const char* const kAreaNames[kAreas] = {"Built-in", "Installed", "More"};\n#else\n'
     'inline const char* const kAreaNames[kAreas] = {"Built-in", "Community", "More"};\n#endif\n'),
]
REPLACEMENTS['src/overlay/overlay.cpp'] += [
    ('        h.code_mods = ext::features().code_mods;\n        h.mod_downloads = ext::features().mod_downloads;\n',
     '#ifdef CT_FOREIGN_GUEST  // no Wind Waker HD catalogue or code mods\n        h.code_mods = false;\n        h.mod_downloads = false;\n#else\n'
     '        h.code_mods = ext::features().code_mods;\n        h.mod_downloads = ext::features().mod_downloads;\n#endif\n'),
]
# A parked thread may resume from either of two return addresses that continue the same way
# (runtime/ct_frame.cpp ct_equivalent_return: sead's thread loop), so a state saved in one session loads
# in a new one.
REPLACEMENTS['src/threads.cpp'] += [
    ('bool same_chain(const Cpu& cur, const Cpu& saved) {\n',
     '#ifdef CT_FOREIGN_GUEST\nextern "C" uint32_t ct_equivalent_return(uint32_t lr);  // runtime/ct_frame.cpp\n#else\n'
     'static uint32_t ct_equivalent_return(uint32_t lr) { return lr; }\n#endif\n'
     'bool same_chain(const Cpu& cur, const Cpu& saved) {\n'),
    ('        if (ld32(na + 4) != ss::snap_ld32(na + 4)) return false;\n',
     '        if (ct_equivalent_return(ld32(na + 4)) != ct_equivalent_return(ss::snap_ld32(na + 4))) return false;\n'),
    # A thread the game starts later (in a course, for one) cannot be made up: say what to do.
    ('            snprintf(buf, sizeof buf, "thread %08X (running in the save) does not exist yet", s.guest);\n',
     '#ifdef CT_FOREIGN_GUEST\n'
     '            snprintf(buf, sizeof buf, "the game has not started everything the state needs yet (thread %08X): "\n'
     '                     "go where it was saved (into a course for one saved in a course), then load", s.guest);\n'
     '#else\n'
     '            snprintf(buf, sizeof buf, "thread %08X (running in the save) does not exist yet", s.guest);\n'
     '#endif\n'),
]
REPLACEMENTS['src/gfx/menu.mm'] += [
    ('    [g addItemWithTitle:@"Aspect ratio" action:nil keyEquivalent:@""].enabled = NO;\n',
     _ct_only + '    [g addItemWithTitle:@"Aspect ratio" action:nil keyEquivalent:@""].enabled = NO;\n'),
    ('    add(g, @"16x anisotropic filtering (N)", @selector(toggleAniso:), @"N");\n',
     _ct_end + '    add(g, @"16x anisotropic filtering (N)", @selector(toggleAniso:), @"N");\n'),
    ('    add(g, @"40 fps: frame interpolation (for 40, 80 and 120 Hz screens)", @selector(toggleInterpFps:), @"", 40);\n',
     _ct_only + '    add(g, @"40 fps: frame interpolation (for 40, 80 and 120 Hz screens)", @selector(toggleInterpFps:), @"", 40);\n'),
    ('    add(g, @"60 fps: true 60, game logic at 60 steps/s (7, experimental)", @selector(toggleInterp:), @"7", 2);\n',
     '    add(g, @"60 fps: true 60, game logic at 60 steps/s (7, experimental)", @selector(toggleInterp:), @"7", 2);\n' + _ct_end),
    ('    toggle(gp, @"Enable code mods (PowerPC mods)"', _ct_only + '    toggle(gp, @"Enable code mods (PowerPC mods)"'),
    ('    [gp addItem:[NSMenuItem separatorItem]];\n    [gp addItemWithTitle:@"Cheats (',
     '    [gp addItem:[NSMenuItem separatorItem]];\n' + _ct_end + '    [gp addItemWithTitle:@"Cheats ('),
]
# Internal resolution "Screen" (Vulkan): 0 asks for the factor that draws the picture on screen (the
# 1280x720 TV picture, or the 854x480 GamePad picture in GamePad-only mode) with as many pixels as it
# covers in the TV window (in steps of 1/16), so a phone draws at its panel's resolution. Captain Toad on
# Android starts with it; a saved choice and WWHD_RES_SCALE still win.
REPLACEMENTS['src/gfx/display_modes.h'] += [
    ('bool main_picture(float* x, float* y, float* w, float* h);\n',
     'bool main_picture(float* x, float* y, float* w, float* h);\n'
     'bool main_picture_is_gamepad();  // that picture is the GamePad\'s (Captain Toad screen resolution)\n'),
]
REPLACEMENTS['src/gfx/display_modes.cpp'] += [
    ('// ---------------------------------------------------------------- view button (touch screens)\n',
     'bool main_picture_is_gamepad() {\n'
     '    std::lock_guard<std::mutex> lk(g_layout_mu);\n'
     '    return g_tv_layout.drc_only;\n'
     '}\n'
     '\n'
     '// ---------------------------------------------------------------- view button (touch screens)\n'),
]
REPLACEMENTS['src/gfx/vulkan/surfaces.cpp'] += [
    ('#include "dynres.h"\n', '#include "dynres.h"\n#include "../display_modes.h"\n'),
    # before the first frame's latch: 1x, never 0
    ('static float g_res_frame = g_res_requested.load();  // render thread: the factor for this frame\n',
     'static float g_res_frame = std::max(g_res_requested.load(), 1.0f);  // render thread: the factor for this frame\n'),
    ('static float parse_scale(const char* e) {\n    float f = e ? (float)atof(e) : 1.0f;\n',
     'static float parse_scale(const char* e) {\n'
     '#ifdef CT_FOREIGN_GUEST\n'
     '#ifdef __ANDROID__\n'
     '    if (!e) return 0.0f;  // the screen\'s own resolution\n'
     '#endif\n'
     '    if (e && atof(e) == 0) return 0.0f;\n'
     '#endif  // Captain Toad screen resolution\n'
     '    float f = e ? (float)atof(e) : 1.0f;\n'),
    ('void set_res_scale(float f) {\n    g_res_requested = std::clamp(std::isfinite(f) ? f : 1.0f, 1.0f, 4.0f);\n',
     'void set_res_scale(float f) {\n'
     '#ifdef CT_FOREIGN_GUEST\n'
     '    if (f == 0) {\n'
     '        g_res_requested = 0;\n'
     '        LOG("[gfx] internal resolution: the screen\'s");\n'
     '        return;\n'
     '    }\n'
     '#endif  // Captain Toad screen resolution\n'
     '    g_res_requested = std::clamp(std::isfinite(f) ? f : 1.0f, 1.0f, 4.0f);\n'),
    ('void latch_res_scale() {\n',
     '#ifdef CT_FOREIGN_GUEST\n'
     '// the factor that draws the picture on screen (TV 720 lines, GamePad 480) with the TV window\'s pixels\n'
     '// it covers, in steps of 1/16 so that resizing a window does not make new render targets every pixel\n'
     'static float screen_res_scale() {\n'
     '    float x, y, w, h;\n'
     '    const float pixels = float(R.tv.swapExtent.height);\n'
     '    if (pixels <= 0 || !gfx::main_picture(&x, &y, &w, &h)) return 1.0f;\n'
     '    const float lines = gfx::main_picture_is_gamepad() ? 480.0f : 720.0f;\n'
     '    return std::clamp(std::round(h * pixels / lines * 16.0f) / 16.0f, 1.0f, 4.0f);\n'
     '}\n'
     '#endif  // Captain Toad screen resolution\n'
     'void latch_res_scale() {\n'),
    ('    g_res_frame = g_res_requested.load(std::memory_order_relaxed);\n    latch_aspect();\n',
     '    g_res_frame = g_res_requested.load(std::memory_order_relaxed);\n'
     '#ifdef CT_FOREIGN_GUEST\n'
     '    if (g_res_frame == 0) g_res_frame = screen_res_scale();\n'
     '#endif  // Captain Toad screen resolution\n'
     '    latch_aspect();\n'),
]
REPLACEMENTS['src/gfx/vulkan/backend.cpp'] = [
    # the window title names the factor in use
    ('          double(requested_res_scale()), fxaa_enabled() ? " · FXAA" : "");\n',
     '          double(requested_res_scale() > 0 ? requested_res_scale() : res_scale()), fxaa_enabled() ? " · FXAA" : "");\n'),
]
REPLACEMENTS['src/overlay/overlay.cpp'] += [
    ('        if (radio(names[i], std::fabs(cur - s) < 0.01f)) post_changed([s] { hostui::set_res_scale(s); });\n    }\n',
     '        if (radio(names[i], std::fabs(cur - s) < 0.01f)) post_changed([s] { hostui::set_res_scale(s); });\n    }\n'
     '#ifdef CT_FOREIGN_GUEST\n'
     '    if (!strcmp(hostui::name(), "SDL")) {  // Vulkan: 0 follows the window (gfx/vulkan/surfaces.cpp)\n'
     '        flow::next(flow::check("Screen"));\n'
     '        if (radio("Screen", cur == 0)) post_changed([] { hostui::set_res_scale(0); });\n'
     '        help("Screen draws the game at the resolution of your screen, or of the game\'s window: as many pixels\\n"\n'
     '             "as the picture covers, up to 4x.");\n'
     '    }\n'
     '#endif  // Captain Toad screen resolution\n'),
    ('        ImGui::TextDisabled("%s  %gx  %s", render::api_name(render::active()), hostui::res_scale(), interp::mode_name());\n',
     '        if (hostui::res_scale() == 0)  // Captain Toad: the screen\'s resolution\n'
     '            ImGui::TextDisabled("%s  screen  %s", render::api_name(render::active()), interp::mode_name());\n'
     '        else\n'
     '        ImGui::TextDisabled("%s  %gx  %s", render::api_name(render::active()), hostui::res_scale(), interp::mode_name());\n'),
    # Window sizes (desktop): the TV window with this many pixels inside, those that fit its screen
    ('                                           : "The TV window (F11 or Alt+Enter); remembered for the next start");\n#endif\n',
     '                                           : "The TV window (F11 or Alt+Enter); remembered for the next start");\n#endif\n'
     '#ifndef __ANDROID__\n'
     '    {  // Captain Toad: window sizes (CaptainToadRecomp tools/patch_runtime.py)\n'
     '        static const int sizes[][2] = {{1280, 720}, {1600, 900}, {1920, 1080}, {2560, 1440}, {3840, 2160}};\n'
     '        int ww = 0, wh = 0;\n'
     '        hostui::window_size(ww, wh);\n'
     '        const bool windowed = !hostui::fullscreen();\n'
     '        ImGui::TextUnformatted("Window size");\n'
     '        bool first = true;\n'
     '        for (const auto& size : sizes) {\n'
     '            const int w = size[0], h = size[1];\n'
     '            if (!hostui::window_size_fits(w, h)) continue;\n'
     '            char label[32];\n'
     '            snprintf(label, sizeof label, "%dx%d##windowSize", w, h);\n'
     '            if (!first) flow::next(flow::check(label));\n'
     '            first = false;\n'
     '            if (radio(label, ww == w && wh == h, windowed)) hostui::post([w, h] { hostui::set_window_size(w, h); });\n'
     '        }\n'
     '        help(windowed ? "The game\'s window, in pixels inside it: the sizes that fit this screen. Drag the window\'s\\n"\n'
     '                        "edge for any other size."\n'
     '                      : "Leave full screen to choose a window size.");\n'
     '    }\n'
     '#endif  // Captain Toad window sizes\n'
     '#if defined(__ANDROID__) && defined(CT_FOREIGN_GUEST)\n'
     '    {  // Captain Toad: a punch-hole or notch camera (runtime/ct_touch_menu.cpp, WwhdActivity.java)\n'
     '        int cutout = ct_touch::cutout_clear() ? 1 : 0;\n'
     '        if (combo("Camera cutout", &cutout, "Use the area\\0Keep clear (black bar)\\0"))\n'
     '            hostui::post([cutout] { ct_touch::set_cutout_clear(cutout != 0); });\n'
     '        help("For phones with a punch-hole or notch camera at the edge of the screen. Use the area draws up to\\n"\n'
     '             "the edge, around the camera; Keep clear leaves a black bar along the camera\'s edge. Full screen only.");\n'
     '    }\n'
     '#endif  // Captain Toad camera cutout\n'),
    # Android: how opaque the on-screen controls are (runtime/ct_touch_menu.cpp)
    ('            hostui::set("touchControls", v ? "1" : "0");\n        });\n#endif\n',
     '            hostui::set("touchControls", v ? "1" : "0");\n        });\n'
     '#ifdef CT_FOREIGN_GUEST\n'
     '    pip_percent("Controls opacity (%)", ct_touch::opacity(), ct_touch::kOpacityMin, 1.0f, ct_touch::set_opacity);\n'
     '    help("How opaque the on-screen controls are drawn. The menu button (top left) sets it too.");\n'
     '#endif  // Captain Toad touch controls opacity\n'
     '#endif\n'),
]
REPLACEMENTS['src/overlay/hostui.h'] = [
    ('void set_fullscreen(bool on);\n',
     'void set_fullscreen(bool on);\n'
     '// Captain Toad (CaptainToadRecomp tools/patch_runtime.py): the TV window\'s size in pixels inside it, for\n'
     '// Settings > Display > Window size on desktop hosts\n'
     'void window_size(int& w, int& h);      // 0x0 when unknown\n'
     'bool window_size_fits(int w, int h);   // a window with this many pixels inside fits the TV window\'s screen\n'
     'void set_window_size(int w, int h);    // main thread; in a window only (full screen: nothing changes)\n'),
]
REPLACEMENTS['src/gfx/vulkan/overlay_sdl.cpp'] = [
    ('bool fullscreen() { return gfxvk::R.tv.window && (SDL_GetWindowFlags(gfxvk::R.tv.window) & SDL_WINDOW_FULLSCREEN); }\n',
     'bool fullscreen() { return gfxvk::R.tv.window && (SDL_GetWindowFlags(gfxvk::R.tv.window) & SDL_WINDOW_FULLSCREEN); }\n'
     '// Captain Toad window sizes: SDL sizes windows in its own units, the menu in pixels\n'
     'void window_size(int& w, int& h) {\n'
     '    w = h = 0;\n'
     '    if (SDL_Window* win = gfxvk::R.tv.window) SDL_GetWindowSizeInPixels(win, &w, &h);\n'
     '}\n'
     'bool window_size_fits(int w, int h) {\n'
     '    SDL_Window* win = gfxvk::R.tv.window;\n'
     '    SDL_Rect r{};\n'
     '    if (!win || !SDL_GetDisplayUsableBounds(SDL_GetDisplayForWindow(win), &r)) return false;\n'
     '    const float density = std::max(SDL_GetWindowPixelDensity(win), 0.1f);\n'
     '    return w / density <= r.w && h / density <= r.h;\n'
     '}\n'
     'void set_window_size(int w, int h) {\n'
     '    SDL_Window* win = gfxvk::R.tv.window;\n'
     '    if (!win || fullscreen()) return;\n'
     '    const float density = std::max(SDL_GetWindowPixelDensity(win), 0.1f);\n'
     '    if (!SDL_SetWindowSize(win, int(w / density + 0.5f), int(h / density + 0.5f)))\n'
     '        LOG("[display] TV window: size %dx%d failed: %s", w, h, SDL_GetError());\n'
     '    else\n'
     '        LOG("[display] TV window: %dx%d pixels inside", w, h);\n'
     '}\n'),
]
REPLACEMENTS['src/gfx/overlay_appkit.mm'] = [
    ('void set_fullscreen(bool on) { gfx::display_set_tv_fullscreen(on); }\n',
     'void set_fullscreen(bool on) { gfx::display_set_tv_fullscreen(on); }\n'
     '// Captain Toad window sizes: AppKit sizes windows in points, the menu in pixels\n'
     'void window_size(int& w, int& h) {\n'
     '    w = h = 0;\n'
     '    NSWindow* win = (__bridge NSWindow*)gfx::display_tv_window();\n'
     '    if (!win) return;\n'
     '    const NSRect r = [win convertRectToBacking:[win contentRectForFrameRect:win.frame]];\n'
     '    w = int(r.size.width + 0.5);\n'
     '    h = int(r.size.height + 0.5);\n'
     '}\n'
     'bool window_size_fits(int w, int h) {\n'
     '    NSWindow* win = (__bridge NSWindow*)gfx::display_tv_window();\n'
     '    NSScreen* screen = win.screen ?: NSScreen.mainScreen;\n'
     '    if (!win || !screen) return false;\n'
     '    const CGFloat scale = screen.backingScaleFactor;\n'
     '    const NSSize frame = [win frameRectForContentRect:NSMakeRect(0, 0, w / scale, h / scale)].size;\n'
     '    return frame.width <= screen.visibleFrame.size.width && frame.height <= screen.visibleFrame.size.height;\n'
     '}\n'
     'void set_window_size(int w, int h) {\n'
     '    NSWindow* win = (__bridge NSWindow*)gfx::display_tv_window();\n'
     '    if (!win || gfx::tv_fullscreen()) return;\n'
     '    const CGFloat scale = win.backingScaleFactor;\n'
     '    // the top left corner stays where it is, unless the window would leave the screen\n'
     '    NSRect frame = [win frameRectForContentRect:NSMakeRect(0, 0, w / scale, h / scale)];\n'
     '    frame.origin = NSMakePoint(NSMinX(win.frame), NSMaxY(win.frame) - frame.size.height);\n'
     '    [win setFrame:[win constrainFrameRect:frame toScreen:win.screen] display:YES];\n'
     '    LOG("[display] TV window: %dx%d pixels inside", w, h);\n'
     '}\n'),
]
# Android: one menu button in the top left corner (where the reference has its view button) in place of
# the view button, the touch controls' show/hide button and the tilt button. Its menu (an Android dialog)
# switches the view, shows or hides the touch controls, edits their layout, sets their opacity, turns
# the phone's gyro on or off, applies the save cheats and opens the settings window
# (runtime/ct_touch_menu.cpp). A long press still edits the layout. The controls are drawn with the
# opacity of Settings > Display > Touch controls; the menu button keeps the reference's look.
_touch = '../android/app/src/main/java/org/wwhdrecomp/wwhd/TouchControls.java'
REPLACEMENTS[_touch] = [
    ('// On-screen controls over the game: two sticks, A B X Y, L R ZL ZR, + -, a D-pad, and a small button\n'
     '// under the view button (top left) that shows or hides them (remembered).',
     '// On-screen controls over the game: two sticks, A B X Y, L R ZL ZR, + -, a D-pad, and Captain Toad\'s\n'
     '// menu button (top left; CaptainToadRecomp tools/patch_runtime.py) that shows or hides them (remembered).'),
    ('    private static native void nativeShowControls(boolean shown);\n',
     '    private static native void nativeShowControls(boolean shown);\n'
     '    // Captain Toad\'s menu button (runtime/ct_touch_menu.cpp)\n'
     '    private static native int nativeMenuState();\n'
     '    private static native int nativeNextView();\n'
     '    private static native void nativeSwitchView();\n'
     '    private static native void nativeToggleTilt();\n'
     '    private static native void nativeOpenSettings();\n'
     '    private static native void nativeCheat(int which);\n'
     '    private static native float nativeOpacity();\n'
     '    private static native void nativeSetOpacity(float opacity);\n'
     '    private static native boolean nativeCutoutClear();\n'
     '    private static volatile boolean cutoutClear;  // Settings > Display > Camera cutout: Keep clear\n'
     '    // for WwhdActivity\'s window layout: false (use the area) until libmain.so is loaded\n'
     '    static boolean cutoutClear() {\n'
     '        try { cutoutClear = nativeCutoutClear(); } catch (UnsatisfiedLinkError ignored) {}\n'
     '        return cutoutClear;\n'
     '    }\n'),
    ('    private float lastLx, lastLy, lastRx, lastRy, lastLt, lastRt;\n',
     '    private float lastLx, lastLy, lastRx, lastRy, lastLt, lastRt;\n'
     '    private float opacity = 1f;  // the controls\' (Settings > Display > Touch controls), not the menu button\'s\n'
     '    private android.app.AlertDialog menu;\n'),
    ('        toggle = new Control(KIND_TOGGLE, 0, "🎮", 0f, 0f, 0.04f);  // placed in onSizeChanged\n',
     '        toggle = new Control(KIND_TOGGLE, 0, "☰", 0f, 0f, 0.045f);  // the menu button, placed in onSizeChanged\n'),
    ('        // under the game\'s view button (screen_layout.cpp: a square of 9% of the short side, 1.5% from\n'
     '        // the top left corner)\n'
     '        toggle.r = toggle.fr * s;\n'
     '        toggle.cx = s * (0.015f + 0.045f);\n'
     '        toggle.cy = s * (0.015f + 0.09f + 0.02f) + toggle.r;\n',
     '        // where the reference has its view button (display_modes.cpp: a square of 9% of the short side,\n'
     '        // 1.5% from the top left corner)\n'
     '        toggle.r = toggle.fr * s;\n'
     '        toggle.cx = toggle.cy = s * (0.015f + 0.045f);\n'),
    ('        fill.setColor(on ? 0x90FFFFFF : 0x38FFFFFF);\n        edge.setColor(0x80FFFFFF);\n',
     '        fill.setColor(faded(on ? 0x90FFFFFF : 0x38FFFFFF, c));\n        edge.setColor(faded(0x80FFFFFF, c));\n'),
    ('            fill.setColor(c.pressed ? 0xB0FFFFFF : 0x70FFFFFF);\n',
     '            fill.setColor(faded(c.pressed ? 0xB0FFFFFF : 0x70FFFFFF, c));\n'),
    ('        text.setColor(0xE0FFFFFF);\n', '        text.setColor(faded(0xE0FFFFFF, c));\n'),
    ('    private Control hit(float x, float y) {\n',
     '    // a colour with the controls\' opacity (the menu button keeps its own)\n'
     '    private int faded(int argb, Control c) {\n'
     '        if (c == toggle || opacity >= 1f) return argb;\n'
     '        return Math.round((argb >>> 24) * opacity) << 24 | (argb & 0xFFFFFF);\n'
     '    }\n'
     '\n'
     '    private Control hit(float x, float y) {\n'),
    ('                        if (!all && !longPressConsumed) setShown(toggleTo);\n',
     '                        if (!all && !longPressConsumed) post(this::showMenu);\n'),
    ('            nativeControllerConnected(controller);\n',
     '            nativeControllerConnected(controller);\n'
     '            final float o = nativeOpacity();\n'
     '            if (o != opacity) { opacity = o; invalidate(); }\n'
     '            if (nativeCutoutClear() != cutoutClear && getContext() instanceof WwhdActivity)\n'
     '                ((WwhdActivity) getContext()).cutoutChanged();  // reads it again\n'),
    ('    @Override public void onWindowFocusChanged(boolean hasFocus) {\n',
     """    // ---- Captain Toad's menu (CaptainToadRecomp tools/patch_runtime.py, runtime/ct_touch_menu.cpp)
    private static final int[] CHEATS = {1, 2, 4, 8, 16, 32, 64};  // runtime/ct_save.h, as R.array.ct_cheats lists them
    private static final float[] OPACITIES = {1f, 0.75f, 0.5f, 0.25f};

    private void showMenu() {
        if (menu != null && menu.isShowing()) return;
        final int state, next;
        try { state = nativeMenuState(); next = nativeNextView(); }
        catch (UnsatisfiedLinkError e) { return; }  // libmain.so not loaded yet
        final Context c = getContext();
        final String[] views = c.getResources().getStringArray(R.array.ct_views);
        final int view = state & 15;
        final boolean tilt = (state & 16) != 0;
        final String[] items = {
            c.getString(R.string.ct_menu_settings),
            c.getString(R.string.ct_menu_view, view < views.length ? views[view] : "", next < views.length ? views[next] : ""),
            c.getString(shown ? R.string.ct_menu_hide_controls : R.string.ct_menu_show_controls),
            c.getString(R.string.ct_menu_edit_layout),
            c.getString(R.string.ct_menu_opacity, Math.round(opacity * 100)),
            c.getString(tilt ? R.string.ct_menu_tilt_off : R.string.ct_menu_tilt_on),
            c.getString(R.string.ct_menu_cheats)};
        show(new android.app.AlertDialog.Builder(c).setTitle(R.string.app_name).setItems(items, (d, which) -> {
            switch (which) {
                case 0: nativeOpenSettings(); break;
                case 1: nativeSwitchView(); break;
                case 2: setShown(!shown); invalidate(); break;
                case 3: post(this::beginEditing); break;
                case 4: post(this::showOpacity); break;
                case 5: nativeToggleTilt(); break;
                case 6: post(this::showCheats); break;
            }
        }).setNegativeButton(android.R.string.cancel, null));
    }

    private void showOpacity() {
        int checked = 0;
        for (int i = 1; i < OPACITIES.length; i++)
            if (Math.abs(OPACITIES[i] - opacity) < Math.abs(OPACITIES[checked] - opacity)) checked = i;
        final String[] names = new String[OPACITIES.length];
        for (int i = 0; i < names.length; i++) names[i] = Math.round(OPACITIES[i] * 100) + "%";
        show(new android.app.AlertDialog.Builder(getContext()).setTitle(R.string.ct_menu_opacity_title)
            .setSingleChoiceItems(names, checked, (d, which) -> {
                opacity = OPACITIES[which];
                nativeSetOpacity(opacity);
                invalidate();
                d.dismiss();
            }).setNegativeButton(android.R.string.cancel, null));
    }

    // each cheat asks first: it changes the save and closes the game (runtime/cheats.cpp)
    private void showCheats() {
        final String[] names = getContext().getResources().getStringArray(R.array.ct_cheats);
        show(new android.app.AlertDialog.Builder(getContext()).setTitle(R.string.ct_menu_cheats_title)
            .setItems(names, (d, which) -> post(() -> show(new android.app.AlertDialog.Builder(getContext())
                .setTitle(names[which]).setMessage(R.string.ct_cheat_confirm)
                .setPositiveButton(R.string.ct_cheat_apply, (d2, w2) -> nativeCheat(CHEATS[which]))
                .setNegativeButton(android.R.string.cancel, null))))
            .setNegativeButton(android.R.string.cancel, null));
    }

    private void show(android.app.AlertDialog.Builder builder) {
        menu = builder.create();
        menu.show();
        WwhdActivity.syncSystemBars(menu.getWindow());  // full screen: the system bars stay hidden
    }

    @Override public void onWindowFocusChanged(boolean hasFocus) {
"""),
]
REPLACEMENTS['../android/app/src/main/res/values/strings.xml'] += [
    ('</resources>\n', """    <!-- Captain Toad's menu button (CaptainToadRecomp tools/patch_runtime.py) -->
    <string name="ct_menu_settings">Settings</string>
    <string name="ct_menu_view">View: %1$s (tap for %2$s)</string>
    <string name="ct_menu_show_controls">Show touch controls</string>
    <string name="ct_menu_hide_controls">Hide touch controls</string>
    <string name="ct_menu_edit_layout">Move and resize touch controls</string>
    <string name="ct_menu_opacity">Touch controls opacity: %1$d%%</string>
    <string name="ct_menu_opacity_title">Touch controls opacity</string>
    <string name="ct_menu_tilt_on">Tilt camera (phone gyro): off, tap to turn on</string>
    <string name="ct_menu_tilt_off">Tilt camera (phone gyro): on, tap to turn off</string>
    <string name="ct_menu_cheats">Cheats</string>
    <string name="ct_menu_cheats_title">Cheats (change your save)</string>
    <string name="ct_cheat_confirm">Your save is changed and Captain Toad closes: open it again to play with the cheat. Play since the game last saved is lost. The save from before the first cheat is kept as GameData.bin.before-cheats.</string>
    <string name="ct_cheat_apply">Apply and close</string>
    <!-- gfx::DrcMode order -->
    <string-array name="ct_views">
        <item>separate window</item>
        <item>picture-in-picture</item>
        <item>automatic</item>
        <item>TV only</item>
        <item>GamePad only</item>
    </string-array>
    <!-- runtime/ct_save.h bit order (TouchControls.CHEATS) -->
    <string-array name="ct_cheats">
        <item>Unlock every episode and course</item>
        <item>Clear every course</item>
        <item>Every Super Gem</item>
        <item>Every bonus objective</item>
        <item>Every challenge time</item>
        <item>Every Pixel Toad</item>
        <item>100% completion</item>
    </string-array>
</resources>
"""),
]
# Android: Settings > Display > Camera cutout. Keep clear lays the window out beside a punch-hole or notch
# camera (a black bar along that edge); Use the area keeps the reference's layout into it.
REPLACEMENTS['../android/app/src/main/java/org/wwhdrecomp/wwhd/WwhdActivity.java'] = [
    ('            if (lp.layoutInDisplayCutoutMode != WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES &&\n',
     '            if (TouchControls.cutoutClear()) {\n'
     '                // Captain Toad: Settings > Display > Camera cutout > Keep clear (CaptainToadRecomp)\n'
     '                if (lp.layoutInDisplayCutoutMode != WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_NEVER) {\n'
     '                    lp.layoutInDisplayCutoutMode = WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_NEVER;\n'
     '                    w.setAttributes(lp);\n'
     '                }\n'
     '            } else\n'
     '            if (lp.layoutInDisplayCutoutMode != WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES &&\n'),
    ('    private final Runnable reapplyFullScreen = this::applyFullScreen;\n',
     '    private final Runnable reapplyFullScreen = this::applyFullScreen;\n'
     '    // Captain Toad: the camera cutout setting changed (TouchControls polls it)\n'
     '    void cutoutChanged() { applyFullScreen(); }\n'),
]
# Gyro controllers (macOS, Windows, Linux): the reference's Controller gyro source (SDL3 sensors; the
# AppKit host's GameController.framework) and Cemuhook (DSU) move the virtual GamePad as on Android.
# Desktop builds start with Controller gyro, which does nothing until a controller with motion sensors
# is connected; a saved choice and WWHD_GYRO still win. The mouse source waits for Wind Waker HD's
# aiming hooks, so Captain Toad leaves it out, and the dialog describes Captain Toad.
REPLACEMENTS['src/motion/motion.h'] = [
    ('    int source = kOff;\n',
     '#if defined(CT_FOREIGN_GUEST) && !defined(__ANDROID__)\n'
     '    int source = kController;  // Captain Toad on desktops: a controller\'s gyro moves the GamePad\n'
     '#else\n'
     '    int source = kOff;\n'
     '#endif\n'),
]
REPLACEMENTS['src/overlay/gyro_popup.h'] = [
    ('    note("On the Wii U you aim in first person (bow, hookshot, boomerang, telescope, Picto Box, grappling hook) by "\n'
     '         "moving the GamePad. This works with the GamePad and the Pro Controller choice alike. The game\'s own "\n'
     '         "Options > Gyro switch still decides whether it uses the motion, and it ignores the motion while the right "\n'
     '         "stick is pushed.");\n',
     '#ifdef CT_FOREIGN_GUEST\n'
     '    note("Captain Toad reads the Wii U GamePad\'s motion: moving the GamePad turns the camera where the game "\n'
     '         "allows it, such as the first-person views. Controller gyro takes that motion from a controller\'s own "\n'
     '         "sensors (DualSense, DualShock 4, Switch Pro Controller, Joy-Con, Steam Deck and others), Cemuhook "\n'
     '         "from a DSU server app.");\n'
     '#else\n'
     '    note("On the Wii U you aim in first person (bow, hookshot, boomerang, telescope, Picto Box, grappling hook) by "\n'
     '         "moving the GamePad. This works with the GamePad and the Pro Controller choice alike. The game\'s own "\n'
     '         "Options > Gyro switch still decides whether it uses the motion, and it ignores the motion while the right "\n'
     '         "stick is pushed.");\n'
     '#endif\n'),
    ('    for (int i = 0; i < motion::kSourceCount; i++)\n',
     '    for (int i = 0; i < motion::kSourceCount; i++)\n'
     '#ifdef CT_FOREIGN_GUEST\n'
     '        if (i != motion::kMouse || g.source == motion::kMouse)  // it waits for Wind Waker HD\'s aiming\n'
     '#endif\n'),
]
# Exports that read state private to a reference source file are appended to that file.
APPENDS = {
    'src/hle/ax.cpp': '''
// ---- Captain Toad additions (CaptainToadRecomp tools/patch_runtime.py), following Cemu ax_aux.cpp
HLE(snd_core, AXGetAuxCallback) {
    // (device, deviceIndex, auxBus, funcOut, userOut): TV index 0 and GamePad indices 0-1 are valid
    uint32_t dev = arg(c, 0), idx = arg(c, 1), bus = arg(c, 2), func = 0, user = 0;
    if ((dev == 0 && idx != 0) || (dev == 1 && idx > 1) || dev > 1) { ret(c, (uint32_t)-1); return; }
    if (bus >= kAuxBuses) { ret(c, (uint32_t)-5); return; }
    if (dev == 0) { func = g_aux_cb[bus]; user = g_aux_user[bus]; }
    else if (idx == 0) { std::lock_guard<std::mutex> lk(g_ax_mutex); func = g_drc.aux_cb[bus]; user = g_drc.aux_user[bus]; }
    if (arg(c, 3)) st32(arg(c, 3), func);
    if (arg(c, 4)) st32(arg(c, 4), user);
    ret(c, 0);
}
''',
    'src/gx2/gx2_core.cpp': '''
// ---- Captain Toad additions (CaptainToadRecomp tools/patch_runtime.py)
HLE(gx2, GX2GetDisplayListWriteStatus) { ret(c, recording() != nullptr); }  // this thread records a display list
HLE(gx2, GX2SetDefaultState) { set_default_state(); }                 // the state GX2Init establishes
''',
    'src/gx2/gx2_state.cpp': '''
// ---- Captain Toad additions (CaptainToadRecomp tools/patch_runtime.py), following Cemu GX2_State.cpp
HLE(gx2, GX2SetPolygonOffset) {
    // (frontOffset, frontScale, backOffset, backScale, clampOffset): the scales count 1/16 units
    set_reg(REGADDR::PA_SU_POLY_OFFSET_FRONT_SCALE, gx2::fbits(fa(c, 1) * 16.0f));
    set_reg(REGADDR::PA_SU_POLY_OFFSET_FRONT_SCALE + 1, gx2::fbits(fa(c, 0)));
    set_reg(REGADDR::PA_SU_POLY_OFFSET_FRONT_SCALE + 2, gx2::fbits(fa(c, 3) * 16.0f));
    set_reg(REGADDR::PA_SU_POLY_OFFSET_FRONT_SCALE + 3, gx2::fbits(fa(c, 2)));
    set_reg(REGADDR::PA_SU_POLY_OFFSET_CLAMP, gx2::fbits(fa(c, 4)));
}
HLE(gx2, GX2SetCullOnlyControl) {
    // (frontFace, cullFront, cullBack): polygon modes and offsets off
    LATTE_PA_SU_SC_MODE_CNTL v;
    v.set_FRONT_FACE((LATTE_PA_SU_SC_MODE_CNTL::E_FRONTFACE)arg(c, 0));
    v.set_CULL_FRONT((arg(c, 1) & 1) != 0);
    v.set_CULL_BACK((arg(c, 2) & 1) != 0);
    set_reg(REGADDR::PA_SU_SC_MODE_CNTL, v.getRawValue());
}
HLE(gx2, GX2SetDepthOnlyControl) {
    // (depthTest, depthWrite, depthFunc): also disables the stencil test
    LATTE_DB_DEPTH_CONTROL r;
    r.set_Z_ENABLE(arg(c, 0) != 0).set_Z_WRITE_ENABLE(arg(c, 1) != 0).set_Z_FUNC((LATTE_DB_DEPTH_CONTROL::E_ZFUNC)arg(c, 2));
    set_reg(REGADDR::DB_DEPTH_CONTROL, r.getRawValue());
}
HLE(gx2, GX2SetPointLimits) {
    uint32 lo = std::min<uint32>((uint32)(std::max(fa(c, 0), 0.0f) * 8.0f), 0xFFFF);
    uint32 hi = std::min<uint32>((uint32)(std::max(fa(c, 1), 0.0f) * 8.0f), 0xFFFF);
    set_reg(REGADDR::PA_SU_POINT_MINMAX, LATTE_PA_SU_POINT_MINMAX().set_MIN_SIZE(lo).set_MAX_SIZE(hi).getRawValue());
}
HLE(gx2, GX2SetPrimitiveRestartIndex) { set_reg(REGADDR::VGT_MULTI_PRIM_IB_RESET_INDX, arg(c, 0)); }
HLE(gx2, GX2SetStreamOutEnable) { set_reg(mmVGT_STRMOUT_EN, arg(c, 0) & 1); }
HLE(gx2, GX2SetStreamOutBuffer) {
    // (index, GX2StreamOutBuffer*): +0 size, +4 data, +0xC GX2RBuffer (elementSize +0x10, elementCount
    // +0x14, data +0x18) used when data is null. BASE holds the full address (this renderer's convention).
    uint32 i = arg(c, 0) & 3, b = arg(c, 1);
    uint32 data = ld32(b + 4), size = ld32(b);
    if (!data) { data = ld32(b + 0x18); size = ld32(b + 0x10) * ld32(b + 0x14); }
    set_reg(mmVGT_STRMOUT_BUFFER_SIZE_0 + i * 4, size >> 2);
    set_reg(mmVGT_STRMOUT_BUFFER_BASE_0 + i * 4, data);
}
// (index, GX2StreamOutBuffer*, reset): reset starts at offset 0, otherwise the offset its context saved
HLE(gx2, GX2SetStreamOutContext) {
    gx2::emit(gx2::OP_STREAMOUT_UPDATE, {arg(c, 0) & 3, arg(c, 2) ? 0u : 2u, ld32(arg(c, 1) + 0x1C)});
}
HLE(gx2, GX2SaveStreamOutContext) { gx2::emit(gx2::OP_STREAMOUT_UPDATE, {arg(c, 0) & 3, 3u, ld32(arg(c, 1) + 0x1C)}); }
// Cemu exports no tessellation calls; draws never select tessellated primitives here, so the mode
// changes nothing and the level registers only record the values.
HLE(gx2, GX2SetTessellation) {}
HLE(gx2, GX2SetMaxTessellationLevel) { set_reg(mmVGT_HOS_MAX_TESS_LEVEL, gx2::fbits(fa(c, 0))); }
HLE(gx2, GX2SetMinTessellationLevel) { set_reg(mmVGT_HOS_MIN_TESS_LEVEL, gx2::fbits(fa(c, 0))); }
''',
    'src/savestate.cpp': '''
// ---- Captain Toad additions (CaptainToadRecomp tools/patch_runtime.py)
namespace ss {
// Captain Toad's frame start (runtime/ct_frame.cpp): the full save and load requests of service(); the
// rest of it follows Wind Waker HD's scenes, events, portable states and automatic states.
void ct_service(Cpu* c) {
    (void)c;
    // test aids (TV frames), as in service(): WWHD_STATE_SAVE_AT=frame:slot,... / WWHD_STATE_LOAD_AT
    static const std::vector<Timed> save_at = parse_timed("WWHD_STATE_SAVE_AT"), load_at = parse_timed("WWHD_STATE_LOAD_AT");
    if (!save_at.empty() || !load_at.empty()) {
        static uint64_t last = 0;
        const uint64_t f = render::frame_count();
        for (auto& t : save_at)
            if (t.frame > last && t.frame <= f) request_save_full(t.slot);
        for (auto& t : load_at)
            if (t.frame > last && t.frame <= f) request_load(t.slot);
        last = f;
    }
    if (int slot = g_save_req.load()) {
        if (do_save(slot)) {
            g_save_req = 0;
            g_attempts = 0;
        }
        return;
    }
    std::shared_ptr<Snapshot> s;
    {
        std::lock_guard<std::mutex> lk(g_mu);
        s = g_load_ready;
    }
    if (s && do_load(s)) {
        if (s->load_applied) {
            g_last_load_frame = render::frame_count();
            g_last_load_step = interp::logic_steps();
        }
        {
            std::lock_guard<std::mutex> lk(g_mu);
            g_load_ready.reset();
        }
        g_loading = false;
        g_attempts = 0;
    }
}
}  // namespace ss
''',
}
# Captain Toad files that replace or join reference files
for source, relative in (('cheats.cpp', 'src/mods/cheats.cpp'), ('ct_save.h', 'src/mods/ct_save.h'),
                         ('ct_touch_menu.cpp', 'src/ct_touch_menu.cpp'), ('ct_touch_menu.h', 'src/ct_touch_menu.h')):
    text = (Path(__file__).resolve().parent.parent / 'runtime' / source).read_text(encoding='utf-8')
    (runtime / relative).write_text(text, encoding='utf-8', newline='\n')

MARKER = '\n// ---- Captain Toad additions'
for relative, text in APPENDS.items():
    path = runtime / relative
    source = path.read_text(encoding='utf-8')
    if text not in source:
        # The additions block always ends the file: replace an older version of it.
        if source.count(MARKER) > 1:
            raise SystemExit(f'{relative} has several Captain Toad addition blocks; review it')
        source = source.split(MARKER)[0]
        path.write_text(source.rstrip('\n') + '\n' + text, encoding='utf-8', newline='\n')

for relative, pairs in REPLACEMENTS.items():
    path = runtime / relative
    source = path.read_text(encoding='utf-8')
    for old, new in pairs:
        if new in source:
            continue
        if source.count(old) != 1:
            raise SystemExit(f'reference changed: {relative} needs review')
        source = source.replace(old, new)
    path.write_text(source, encoding='utf-8', newline='\n')

# Names the player sees (window titles, menus, dialogs, overlay, logs, crash reports) and the per-user
# folders outside portable mode name Captain Toad. Only string literals change: comments keep naming
# the reference code they describe, and the vendored third-party code is left alone.
BRANDING = [
    ('The Legend of Zelda: The Wind Waker HD', 'Captain Toad: Treasure Tracker'),
    ('Wind Waker HD', 'Captain Toad'),
    ('captures/wwhd', 'captures/captain-toad'),
    ('./build/cmake/wwhd', 'captain-toad'),
    ('Application Support/wwhd', 'Application Support/Captain Toad'),
    ('Application Support/WWHD', 'Application Support/Captain Toad'),
    ('Library/Caches/wwhd', 'Library/Caches/org.ctrecomp.captaintoad'),
    ('/.config/wwhd', '/.config/captain-toad'),
]
literal = re.compile(r'"(?:[^"\\\n]|\\.)*"')
def rebrand(match):
    text = match.group(0)
    if text == '"/wwhd"':  # $XDG_CONFIG_HOME/wwhd (platform/host.h)
        return '"/captain-toad"'
    if text == '"/WWHD"':  # %APPDATA%/WWHD (platform/host.h)
        return '"/Captain Toad"'
    for old, new in BRANDING:
        text = text.replace(old, new)
    return text
for path in sorted((runtime / 'src').rglob('*')):
    if path.suffix not in {'.c', '.cpp', '.h', '.mm'} or 'third_party' in path.parts:
        continue
    source = path.read_text(encoding='utf-8')
    branded = literal.sub(rebrand, source)
    if branded != source:
        path.write_text(branded, encoding='utf-8', newline='\n')

# The Android app's own text and save checks: its texts in every language, the save export/import
# (Captain Toad's save is user/GameData.bin) and the setup notification. Java comments are left alone.
ANDROID_BRANDING = [
    ('The Wind Waker HD', 'Captain Toad: Treasure Tracker'),
    ('Wind Waker HD', 'Captain Toad'),
    ('code/cking.rpx', 'code/Kinopio.rpx'),
    ('user/cking.sav', 'user/GameData.bin'),
]
android_main = runtime.parent / 'android/app/src/main'
android_files = sorted(android_main.glob('res/values*/strings.xml')) + [
    android_main / 'java/org/wwhdrecomp/wwhd' / name for name in ('SaveFiles.java', 'SetupService.java')]
for path in android_files:
    source = path.read_text(encoding='utf-8')
    if path.suffix == '.java':
        def android_rebrand(match):
            text = match.group(0)
            for old, new in ANDROID_BRANDING:
                text = text.replace(old, new)
            return text
        branded = literal.sub(android_rebrand, source)
    else:
        branded = source
        for old, new in ANDROID_BRANDING:
            branded = branded.replace(old, new)
    if branded != source:
        path.write_text(branded, encoding='utf-8', newline='\n')

STUBS = runtime / 'src/ct_guest_stubs.c'
symbol = re.compile(r'\bf_([0-9A-F]{8})(_orig)?\b')
fence = re.compile(r'\bT60_FENCE_(?:LINK|ANY)\(([0-9A-F]{8})')  # pastes f_<address>_orig
names = set()
for path in sorted((runtime / 'src').rglob('*')):  # sources built into the game executable
    if path.suffix in {'.c', '.cpp', '.h', '.mm'} and path != STUBS:
        text = path.read_text(encoding='utf-8', errors='replace')
        names.update(f'f_{address}{suffix}' for address, suffix in symbol.findall(text))
        names.update(f'f_{address}_orig' for address in fence.findall(text))

table = args.gen / 'table.c'
if not table.is_file():
    raise SystemExit(f'{table} is missing; run tools/recomp.py first')
generated = set(re.findall(r'\bf_[0-9A-F]{8}\b', table.read_text(encoding='utf-8')))
collisions = sorted(name for name in names if name in generated)
if collisions:
    # The strong game function would silently replace the stub and run with Wind Waker HD semantics.
    # Generation without hooks emits no *_orig symbols, so only plain names can collide.
    raise SystemExit('Wind Waker HD guest symbols match Captain Toad functions: ' + ', '.join(collisions))

lines = ['// Generated by tools/patch_runtime.py: Wind Waker HD guest symbols named by the reference runtime.',
         '#include "ppc.h"', '']
for name in sorted(names):
    lines.append(f'__attribute__((weak)) void {name}(Cpu* __restrict c) {{ ppc_unimplemented(c, 0x{name[2:10]}u, 0); }}')
STUBS.write_text('\n'.join(lines) + '\n', encoding='utf-8', newline='\n')
print(f'runtime targets Kinopio.rpx; {len(names)} weak Wind Waker HD guest stubs, no collisions')
