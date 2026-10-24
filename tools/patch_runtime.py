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
    ('    <string name="app_name">Wind Waker HD</string>\n', '    <string name="app_name">Captain Toad</string>\n'),
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
    ('#include "../mods/mods.h"\n', '#include "../mods/mods.h"\n#include "../mods/ct_save.h"\n'),
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
         '    note("Each cheat changes the save and restarts the game: play since the game last saved is lost. "\n'
         '         "The save before the first cheat is kept as GameData.bin.before-cheats.");\n'
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
for source, relative in (('cheats.cpp', 'src/mods/cheats.cpp'), ('ct_save.h', 'src/mods/ct_save.h')):
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
