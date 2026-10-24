// Captain Toad's frame start. The profile's hook list (profiles/*.json "hooks", tools/recompile.py)
// routes the game's per-frame function through hook_<address>: USA v16 0x02420F10, which runs the game
// logic, draws and swaps the TV/GamePad buffers, and which the main loop calls once a frame. Its entry
// is the point where save states are made and loaded (savestate.cpp ss::ct_service): the main thread
// is there on every frame with the same call chain, and the other game threads can be parked.
// Built only into the full reference runtime (CT_EXTRA_SOURCES).
#include "runtime.h"

namespace ss { void ct_service(Cpu* c); }  // savestate.cpp, Captain Toad additions (tools/patch_runtime.py)

// weak: a build of another region has no such hook and no such function
extern "C" __attribute__((weak)) void f_02420F10_orig(Cpu* c);
extern "C" void hook_02420F10(Cpu* c) {
    ss::ct_service(c);
    f_02420F10_orig(c);
}

// Return addresses that continue the same way, for the save-state check that a parked thread is where
// the state saved it (threads.cpp same_chain). sead::Thread::run (USA v16 0x022DA820) waits on its
// message queue first before its loop (returning to 0x022DA840) and then in the loop (0x022DA870); both
// test the message for quit, call calc and wait again. A thread that has not yet had a message, as in a
// game started afresh, can so load a state saved after it had one (sead::MicConnectThread).
// The polling loop at USA v16 0x0241EBC4 has four branches that end in OSSleepTicks (returning to
// 0x0241EC68, 0x0241ECB4, 0x0241ED18 and 0x0241ED74); each reloads the same registers and then tests r11
// to loop or leave. Every pair was checked in the generated code to reload the same register set.
extern "C" uint32_t ct_equivalent_return(uint32_t lr) {
    switch (lr) {
    case 0x022DA840u: return 0x022DA870u;
    case 0x0241EC68u: case 0x0241ECB4u: case 0x0241ED18u: return 0x0241ED74u;
    default: return lr;
    }
}
