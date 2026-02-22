"""
AutoMiner script for TazUO using the LegionScripts API.

Purpose:
- Automate a recall-based mining route with optional smelting and tool crafting.
- Provide a clear control gump so the script can be started, paused, and configured.

When To Use:
- You want to mine from a runebook route and unload resources at home.
- You want optional ore smelting, ingot restocking, and shovel crafting.

Assumptions:
- `API.py` is available in this repository and loaded by the script engine.
- You configure a runebook and, optionally, a secure drop container.
- Your character has the required tools/reagents for selected travel mode.

Risks:
- The script moves items and can drop ore near the player during weight mitigation.
- The script performs continuous targeting/gump/spell actions while running.
- Incorrect runebook button setup can cause failed travel loops.
"""

import API
import json
import os
import time
import sys
import sqlite3
import traceback

# Early startup heartbeat for diagnosing silent launch failures.
# This runs at import-time before gump/UI code.
def _write_boot_heartbeat():
    """Write a minimal import-time heartbeat to the startup log.

    Args:
        None.

    Returns:
        None: Best-effort write used only for startup diagnostics.

    Side Effects:
        Appends one line to `Logs/AutoMiner.startup.log` when possible.
    """
    try:
        base = os.path.dirname(__file__) if "__file__" in globals() else os.getcwd()
    except Exception:
        base = os.getcwd()
    try:
        if os.path.basename(base).lower() in ("resources", "utilities", "skills", "scripts"):
            base = os.path.dirname(base)
        logs_dir = os.path.join(base, "Logs")
        os.makedirs(logs_dir, exist_ok=True)
        path = os.path.join(logs_dir, "AutoMiner.startup.log")
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        mod_name = str(globals().get("__name__", "unknown"))
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] BOOT module_import __name__={mod_name}\n")
    except Exception:
        pass


_write_boot_heartbeat()

# Use custom gump image background when True; fallback to colorbox when False.
CUSTOM_GUMP = False

# Debug log gump state (define early to avoid NameError in IronPython).
LOG_GUMP = None  # Current debug log gump instance.
LOG_TEXT = ""  # Rolling in-memory log text buffer.
LOG_LINES = []  # Pre-split log lines used by the scroll area UI.
LOG_EXPORT_BASE = None  # User-selected default export directory.
LOG_PATH_TEXTBOX = None  # Textbox control reference from the log gump.

# Journal texts that mark tiles as depleted.
NO_ORE_CACHE_TEXTS = [
    "There is no metal here to mine.",
    "You cannot see that location.",
]
# Journal texts that indicate a mining tool broke.
TOOL_WORN_TEXTS = [
    "You have worn out your tool!",
    "You destroyed the item : pickaxe",
    "You destroyed the item : shovel",
]
# Journal texts to capture in the debug log.
JOURNAL_LOG_TEXTS = [
    "Where do you wish to dig?",
    "You can't mine there.",
    "You cannot see that location.",
    "Target cannot be seen.",
    "You loosen some rocks but fail to find any useable ore.",
    "You must wait to perform another action",
]
# Journal texts that count as actionable mining results for wait-loop exit.
MINING_RESULT_TEXTS = NO_ORE_CACHE_TEXTS + TOOL_WORN_TEXTS + [
    "You dig some",
    "You loosen some rocks but fail to find any useable ore.",
    "You can't mine there.",
    "Target cannot be seen.",
]
# Journal text when ore is lost due to full backpack.
OVERWEIGHT_TEXTS = [
    "Your backpack is full, so the ore you mined is lost.",
]
# Journal text for hard encumbrance (can't move).
ENCUMBERED_TEXTS = [
    "Thou art too encumbered to move.",
]

# Tool and resource graphics.
SHOVEL_GRAPHICS = [0x0F3A, 0x0F39]  # Shovel item graphics (0x0F39 for UOAlive).
PICKAXE_GRAPHIC = 0x0E86  # Pickaxe item graphic.
ORE_GRAPHICS = [0x19B9, 0x19B8, 0x19BA]  # Ore piles.
ORE_GRAPHIC_MIN2 = 0x19B7  # Ore that requires 2+ to smelt.
INGOT_GRAPHICS = [0x1BF2]  # Base ingot graphic.
GEM_GRAPHICS = [0x3198, 0x3197, 0x3194, 0x3193, 0x3192, 0x3195]  # Gems to deposit.
BLACKSTONE_GRAPHICS = [0x0F2A, 0x0F2B, 0x0F28, 0x0F26]  # Blackrock to deposit.

# Mineable tile graphics (land/statics). Derived from provided decimal lists.
CAVE_MINEABLE = [
    0x053B, 0x053C, 0x053D, 0x053E, 0x053F, 0x0540, 0x0541, 0x0542, 0x0543, 0x0544,
    0x0545, 0x0546, 0x0547, 0x0548, 0x0549, 0x054A, 0x054B, 0x054C, 0x054D, 0x054E,
    0x054F, 0x0551, 0x0552, 0x0553, 0x056A,
]
MOUNTAIN_MINEABLE = [
    0x00DC, 0x00DD, 0x00DE, 0x00DF, 0x00E0, 0x00E1, 0x00E2, 0x00E3, 0x00E4, 0x00E5,
    0x00E6, 0x00E7, 0x00EC, 0x00ED, 0x00EE, 0x00EF, 0x00F0, 0x00F1, 0x00F2, 0x00F3,
    0x00F4, 0x00F5, 0x00F6, 0x00F7, 0x00FC, 0x00FD, 0x00FE, 0x00FF, 0x0100, 0x0101,
    0x0102, 0x0103, 0x0104, 0x0105, 0x0106, 0x0107, 0x010C, 0x010D, 0x010E, 0x010F,
    0x0110, 0x0111, 0x0112, 0x0113, 0x0114, 0x0115, 0x0116, 0x0117, 0x011E, 0x011F,
    0x0120, 0x0121, 0x0122, 0x0123, 0x0124, 0x0125, 0x0126, 0x0127, 0x0128, 0x0129,
    0x0141, 0x0142, 0x0143, 0x0144, 0x01D3, 0x01D4, 0x01D5, 0x01D6, 0x01D7, 0x01D8,
    0x01D9, 0x01DA, 0x01DB, 0x01DC, 0x01DD, 0x01DE, 0x01DF, 0x01E0, 0x01E1, 0x01E2, 0x01E3,
    0x01E4, 0x01E5, 0x01E6, 0x01E7, 0x01EC, 0x01ED, 0x01EE, 0x01EF, 0x021F, 0x0220,
    0x0221, 0x0222, 0x0223, 0x0224, 0x0225, 0x0226, 0x0227, 0x0228, 0x0229, 0x022A,
    0x022B, 0x022C, 0x022D, 0x022E, 0x022F, 0x0230, 0x0231, 0x0232, 0x0233, 0x0234,
    0x0235, 0x0236, 0x0237, 0x0238, 0x0239, 0x023A, 0x023B, 0x023C, 0x023D, 0x023E,
    0x023F, 0x0240, 0x0241, 0x0242, 0x0243, 0x0244, 0x0245, 0x0246, 0x0247, 0x0248,
    0x0249, 0x024A, 0x024B, 0x024C, 0x024D, 0x024E, 0x024F, 0x0250, 0x0251, 0x0252,
    0x0253, 0x0254, 0x0255, 0x0256, 0x0257, 0x0258, 0x0259, 0x025A, 0x025B, 0x025C,
    0x025D, 0x025E, 0x025F, 0x0260, 0x0261, 0x0262, 0x0263, 0x0264, 0x0265, 0x0266,
    0x0267, 0x0268, 0x0269, 0x026A, 0x026B, 0x026C, 0x026D, 0x026E, 0x026F, 0x0270,
    0x0271, 0x0272, 0x0273, 0x0274, 0x0275, 0x0276, 0x0277, 0x0278, 0x0279, 0x027A,
    0x027B, 0x027C, 0x027D, 0x027E, 0x027F, 0x0280, 0x0281, 0x0282, 0x0283, 0x0284,
    0x0285, 0x0286, 0x0287, 0x0288, 0x0289, 0x028A, 0x028B, 0x028C, 0x028D, 0x028E,
    0x028F, 0x0290, 0x0291, 0x0292, 0x0293, 0x0294, 0x0295, 0x0296, 0x0297, 0x0298,
    0x0299, 0x029A, 0x029B, 0x029C, 0x029D, 0x029E, 0x02E2, 0x02E3, 0x02E4, 0x02E5,
    0x02E6, 0x02E7, 0x02E8, 0x02E9, 0x02EA, 0x02EB, 0x02EC, 0x02ED, 0x02EE, 0x02EF,
    0x02F0, 0x02F1, 0x02F2, 0x02F3, 0x02F4, 0x02F5, 0x02F6, 0x02F7, 0x02F8, 0x02F9,
    0x02FA, 0x02FB, 0x02FC, 0x02FD, 0x02FE, 0x02FF, 0x0300, 0x0301, 0x0302, 0x0303,
    0x0304, 0x0305, 0x0306, 0x0307, 0x0308, 0x0309, 0x030A, 0x030B, 0x030C, 0x030D,
    0x030E, 0x030F, 0x0310, 0x0311, 0x0312, 0x0313, 0x0314, 0x0315, 0x0316, 0x0317,
    0x0318, 0x0319, 0x031A, 0x031B, 0x031C, 0x031D, 0x031E, 0x031F, 0x0320, 0x0321,
    0x0322, 0x0323, 0x0324, 0x0325, 0x0326, 0x0327, 0x0328, 0x0329, 0x032A, 0x032B,
    0x032C, 0x032D, 0x032E, 0x032F, 0x0330, 0x0331, 0x0332, 0x0333, 0x0334, 0x0335,
    0x0336, 0x0337, 0x0338, 0x0339, 0x033A, 0x033B, 0x033C, 0x033D, 0x033E, 0x033F,
    0x0340, 0x0341, 0x0342, 0x0343, 0x03F2, 0x06CD, 0x06CE, 0x06CF, 0x06D0, 0x06D1,
    0x06D2, 0x06D3, 0x06D4, 0x06D5, 0x06D6, 0x06D7, 0x06D8, 0x06D9, 0x06DA, 0x06DB,
    0x06DC, 0x06ED, 0x06EE, 0x06EF, 0x06F0, 0x06F1, 0x06F2, 0x06F3, 0x06F4, 0x06F5,
    0x06F6, 0x06F7, 0x06F8, 0x06F9, 0x06FA, 0x06FB, 0x06FC, 0x06FD, 0x06FE, 0x06FF,
    0x0700, 0x0709, 0x070A, 0x070B, 0x070C, 0x070D, 0x070E, 0x070F, 0x0710, 0x0711,
    0x0712, 0x0713, 0x0714, 0x0715, 0x0716, 0x0717, 0x0718, 0x0719, 0x071A, 0x071B,
    0x071C, 0x071D, 0x071E, 0x071F, 0x0720, 0x0721, 0x0722, 0x0723, 0x0724, 0x0725,
    0x0726, 0x0727, 0x0728, 0x0729, 0x072A, 0x072B, 0x072C, 0x072D, 0x072E, 0x072F,
    0x0730, 0x0731, 0x0732, 0x0733, 0x0734, 0x0735, 0x0736, 0x0737, 0x0738, 0x0739,
    0x073A, 0x073B, 0x073C, 0x073D, 0x073E, 0x073F, 0x0740, 0x0741, 0x0742, 0x0743,
    0x0744, 0x0745, 0x0746, 0x0747, 0x0748, 0x0749, 0x074A, 0x074B, 0x074C, 0x074D,
    0x074E, 0x074F, 0x0750, 0x0751, 0x0752, 0x0753, 0x0754, 0x0755, 0x0756, 0x0757,
    0x0758, 0x0759, 0x075A, 0x075B, 0x075C, 0x075D, 0x075E, 0x075F, 0x0760, 0x0761,
    0x0762, 0x0763, 0x0764, 0x0765, 0x0766, 0x0767, 0x0768, 0x0769, 0x076A, 0x076B,
    0x076C, 0x076D, 0x076E, 0x076F, 0x0770, 0x0771, 0x0772, 0x0773, 0x0774, 0x0775,
    0x0776, 0x0777, 0x0778, 0x0779, 0x077A, 0x077B, 0x077C, 0x077D, 0x077E, 0x077F,
    0x0780, 0x0781, 0x0782, 0x0783, 0x0784, 0x0785, 0x0786, 0x0787, 0x0788, 0x0789,
    0x078A, 0x078B, 0x078C, 0x078D, 0x078E, 0x078F, 0x0790, 0x0791, 0x0792, 0x0793,
    0x0794, 0x0795, 0x0796, 0x0797, 0x0798, 0x0799, 0x079A, 0x079B, 0x079C, 0x079D,
    0x079E, 0x079F, 0x07A0, 0x07A1, 0x07A2, 0x07A3, 0x07A4, 0x07A5, 0x083C, 0x083D,
    0x083E, 0x083F, 0x0840, 0x0841, 0x0842, 0x0843, 0x0844, 0x0845, 0x0846, 0x0847,
    0x0848, 0x0849, 0x084A, 0x084B, 0x084C, 0x084D, 0x084E, 0x084F, 0x0850, 0x0851,
    0x0852, 0x0853, 0x0854, 0x0855, 0x0856, 0x0857, 0x0858, 0x0859, 0x085A, 0x085B,
    0x085C, 0x085D, 0x085E, 0x085F, 0x0860, 0x0861, 0x0862, 0x0863, 0x0864, 0x0865,
    0x0866, 0x0867, 0x0868, 0x0869, 0x086A, 0x086B, 0x086C, 0x086D, 0x086E, 0x086F,
    0x0870, 0x0871, 0x0872, 0x0873, 0x0874, 0x0875, 0x0876, 0x0877, 0x0878, 0x0879,
    0x087A, 0x087B, 0x087C, 0x087D, 0x087E, 0x087F, 0x0880, 0x0881, 0x0882, 0x0883,
    0x0884, 0x0885, 0x0886, 0x0887, 0x0888, 0x0889, 0x088A, 0x088B, 0x088C, 0x088D,
    0x088E, 0x088F, 0x0890, 0x0891, 0x0892, 0x0893, 0x0894, 0x0895, 0x0896, 0x0897,
    0x0898, 0x0899, 0x089A, 0x089B, 0x089C, 0x089D, 0x089E, 0x089F, 0x08A0, 0x08A1,
    0x08A2, 0x08A3, 0x08A4, 0x08A5, 0x08A6, 0x08A7, 0x08A8, 0x08A9, 0x08AA, 0x08AB,
    0x08AC, 0x08AD, 0x08AE, 0x08AF, 0x08B0, 0x08B1, 0x08B2, 0x08B3, 0x08B4, 0x08B5,
    0x08B6, 0x08B7, 0x08B8, 0x08B9, 0x08BA, 0x08BB, 0x08BC, 0x08BD, 0x08BE, 0x08BF,
    0x08C0, 0x08C1, 0x08C2, 0x08C3, 0x08C4, 0x08C5, 0x08C6, 0x08C7, 0x08C8, 0x08C9,
    0x08CA, 0x08CB, 0x08CC, 0x08CD, 0x08CE, 0x08CF, 0x08D0, 0x08D1, 0x08D2, 0x08D3,
    0x08D4, 0x08D5, 0x08D6, 0x08D7, 0x08D8, 0x08D9, 0x08DA, 0x08DB, 0x08DC, 0x08DD,
    0x08DE, 0x08DF, 0x08E0, 0x08E1, 0x08E2, 0x08E3, 0x08E4, 0x08E5, 0x08E6, 0x08E7,
    0x08E8, 0x08E9, 0x08EA, 0x08EB, 0x08EC, 0x08ED, 0x08EE, 0x08EF, 0x08F0, 0x08F1,
    0x08F2, 0x08F3, 0x08F4, 0x08F5, 0x08F6, 0x08F7, 0x08F8, 0x08F9, 0x08FA, 0x08FB,
    0x08FC, 0x08FD, 0x08FE, 0x08FF, 0x0900, 0x0901, 0x0902, 0x0903, 0x0904, 0x0905,
    0x0906, 0x0907, 0x0908, 0x0909, 0x090A, 0x090B, 0x090C, 0x090D, 0x090E, 0x090F,
    0x0910, 0x0911, 0x0912, 0x0913, 0x0914, 0x0915, 0x0916, 0x0917, 0x0918, 0x0919,
    0x091A, 0x091B, 0x091C, 0x091D, 0x091E, 0x091F, 0x0920, 0x0921, 0x0922, 0x0923,
    0x0924, 0x0925, 0x0926, 0x0927, 0x0928, 0x0929, 0x092A, 0x092B, 0x092C, 0x092D,
    0x092E, 0x092F, 0x0930, 0x0931, 0x0932, 0x0933, 0x0934, 0x0935, 0x0936, 0x0937,
    0x0938, 0x0939, 0x093A, 0x093B, 0x093C, 0x093D, 0x093E, 0x093F, 0x0940, 0x0941,
    0x0942, 0x0943, 0x0944, 0x0945, 0x0946, 0x0947, 0x0948, 0x0949, 0x094A, 0x094B,
    0x094C, 0x094D, 0x094E, 0x094F, 0x0950, 0x0951, 0x0952, 0x0953, 0x0954, 0x0955,
    0x0956, 0x0957, 0x0958, 0x0959, 0x095A, 0x095B, 0x095C, 0x095D, 0x095E, 0x095F,
    0x0960, 0x0961, 0x0962, 0x0963, 0x0964, 0x0965, 0x0966, 0x0967, 0x0968, 0x0969,
    0x096A, 0x096B, 0x096C, 0x096D, 0x096E, 0x096F, 0x0970, 0x0971, 0x0972, 0x0973,
    0x0974, 0x0975, 0x0976, 0x0977, 0x0978, 0x0979, 0x097A, 0x097B, 0x097C, 0x097D,
    0x097E, 0x097F, 0x0980, 0x0981, 0x0982, 0x0983, 0x0984, 0x0985, 0x0986, 0x0987,
    0x0988, 0x0989, 0x098A, 0x098B, 0x098C, 0x098D, 0x098E, 0x098F, 0x0990, 0x0991,
    0x0992, 0x0993, 0x0994, 0x0995, 0x0996, 0x0997, 0x0998, 0x0999, 0x099A, 0x099B,
    0x099C, 0x099D, 0x099E, 0x099F, 0x09A0, 0x09A1, 0x09A2, 0x09A3, 0x09A4, 0x09A5,
    0x09A6, 0x09A7, 0x09A8, 0x09A9, 0x09AA, 0x09AB, 0x09AC, 0x09AD, 0x09AE, 0x09AF,
    0x09B0, 0x09B1, 0x09B2, 0x09B3, 0x09B4, 0x09B5, 0x09B6, 0x09B7, 0x09B8, 0x09B9,
    0x09BA, 0x09BB, 0x09BC, 0x09BD, 0x09BE, 0x09BF, 0x09C0, 0x09C1, 0x09C2, 0x09C3,
    0x09C4, 0x09C5, 0x09C6, 0x09C7, 0x09C8, 0x09C9, 0x09CA, 0x09CB, 0x09CC, 0x09CD,
    0x09CE, 0x09CF, 0x09D0, 0x09D1, 0x09D2, 0x09D3, 0x09D4, 0x09D5, 0x09D6, 0x09D7,
    0x09D8, 0x09D9, 0x09DA, 0x09DB, 0x09DC, 0x09DD, 0x09DE, 0x09DF, 0x09E0, 0x09E1,
    0x09E2, 0x09E3, 0x09E4, 0x09E5, 0x09E6, 0x09E7, 0x09E8, 0x09E9, 0x09EA, 0x09EB,
    0x09EC, 0x09ED, 0x09EE, 0x09EF, 0x09F0, 0x09F1, 0x09F2, 0x09F3, 0x09F4, 0x09F5,
    0x09F6, 0x09F7, 0x09F8, 0x09F9, 0x09FA, 0x09FB, 0x09FC, 0x09FD, 0x09FE, 0x09FF,
    0x0A00, 0x0A01, 0x0A02, 0x0A03, 0x0A04, 0x0A05, 0x0A06, 0x0A07, 0x0A08, 0x0A09,
    0x0A0A, 0x0A0B, 0x0A0C, 0x0A0D, 0x0A0E, 0x0A0F, 0x0A10, 0x0A11, 0x0A12, 0x0A13,
    0x0A14, 0x0A15, 0x0A16, 0x0A17, 0x0A18, 0x0A19, 0x0A1A, 0x0A1B, 0x0A1C, 0x0A1D,
    0x0A1E, 0x0A1F, 0x0A20, 0x0A21, 0x0A22, 0x0A23, 0x0A24, 0x0A25, 0x0A26, 0x0A27,
    0x0A28, 0x0A29, 0x0A2A, 0x0A2B, 0x0A2C, 0x0A2D, 0x0A2E, 0x0A2F, 0x0A30, 0x0A31,
    0x0A32, 0x0A33, 0x0A34, 0x0A35, 0x0A36, 0x0A37, 0x0A38, 0x0A39, 0x0A3A, 0x0A3B,
    0x0A3C, 0x0A3D, 0x0A3E, 0x0A3F, 0x0A40, 0x0A41, 0x0A42, 0x0A43, 0x0A44, 0x0A45,
    0x0A46, 0x0A47, 0x0A48, 0x0A49, 0x0A4A, 0x0A4B, 0x0A4C, 0x0A4D, 0x0A4E, 0x0A4F,
    0x0A50, 0x0A51, 0x0A52, 0x0A53, 0x0A54, 0x0A55, 0x0A56, 0x0A57, 0x0A58, 0x0A59,
    0x0A5A, 0x0A5B, 0x0A5C, 0x0A5D, 0x0A5E, 0x0A5F, 0x0A60, 0x0A61, 0x0A62, 0x0A63,
    0x0A64, 0x0A65, 0x0A66, 0x0A67, 0x0A68, 0x0A69, 0x0A6A, 0x0A6B, 0x0A6C, 0x0A6D,
    0x0A6E, 0x0A6F, 0x0A70, 0x0A71, 0x0A72, 0x0A73, 0x0A74, 0x0A75, 0x0A76, 0x0A77,
    0x0A78, 0x0A79, 0x0A7A, 0x0A7B, 0x0A7C, 0x0A7D, 0x0A7E, 0x0A7F, 0x0A80, 0x0A81,
    0x0A82, 0x0A83, 0x0A84, 0x0A85, 0x0A86, 0x0A87, 0x0A88, 0x0A89, 0x0A8A, 0x0A8B,
    0x0A8C, 0x0A8D, 0x0A8E, 0x0A8F, 0x0A90, 0x0A91, 0x0A92, 0x0A93, 0x0A94, 0x0A95,
    0x0A96, 0x0A97, 0x0A98, 0x0A99, 0x0A9A, 0x0A9B, 0x0A9C, 0x0A9D, 0x0A9E, 0x0A9F,
    0x0AA0, 0x0AA1, 0x0AA2, 0x0AA3, 0x0AA4, 0x0AA5, 0x0AA6, 0x0AA7, 0x0AA8, 0x0AA9,
]
ROCK_MINEABLE = [
    0x453B, 0x453C, 0x453D, 0x453E, 0x453F, 0x4540, 0x4541, 0x4542, 0x4543, 0x4544,
    0x4545, 0x4546, 0x4547, 0x4548, 0x4549, 0x454A, 0x454B, 0x454C, 0x454D, 0x454E,
    0x454F,
]
# Known limitation: mountainside targeting remains unreliable in this version.
SUPPORT_MOUNTAINSIDE_MINING = False  # Reserved toggle for future mountainside support.
MINEABLE_GRAPHICS = set(CAVE_MINEABLE + ROCK_MINEABLE)
if SUPPORT_MOUNTAINSIDE_MINING:
    MINEABLE_GRAPHICS.update(MOUNTAIN_MINEABLE)

# Drop and hue priorities (smaller graphic first, then hue order).
DROP_PRIORITY = [0x19B7, 0x19BA, 0x19B8, 0x19B9]
ORE_HUE_PRIORITY = [0, 2419, 2406, 2413, 2418, 2213, 2425, 2207, 2219]

# Tinkering and smelting helpers.
TINKER_TOOL_GRAPHICS = [0x1EB9, 0x1EB8]  # Tinker's tool graphics 
SMELTER_RANGE = 2  # Search radius for fire beetle smelting.
FIRE_BEETLE_GRAPHIC = 0x00A9  # Fire beetle graphic.

# Behavior flags and UI.
DEBUG_SMELT = False  # Enable smelt debug output.
DEBUG_TARGETING = True  # Enable mining target debug output.
DEBUG_CACHE_HUE = 33  # Hue for cache debug messages.
DIAG_HUE = 88  # Hue for container diagnostic messages.
DIAG_PHASE_HUES = {
    "RUN": 88,
    "CONFIG": 68,
    "TOOL": 78,
    "WEIGHT": 53,
    "SMELT": 115,
    "TRAVEL": 93,
    "UNLOAD": 83,
    "TARGET": 1285,
    "CACHE": 33,
    "CONTAINER": 88,
}
MINING_JOURNAL_WAIT_S = 2.2  # Max wait for mining journal result per tile.
TARGET_TIMEOUT_BACKOFF_S = 0.5  # Backoff when target cursor times out.
UOALIVE_TOOL_USE_DELAY_S = 0.2  # UOAlive mode: delay after using tool.
OSI_TOOL_USE_DELAY_S = 1.0  # OSI mode: delay after using tool.
OSI_JOURNAL_WAIT_S = 6.0  # OSI mode: journal wait timeout per tile.
CONTAINER_DIAG_USE_ATTEMPTS = 3  # Number of UseObject probes in diagnostics.
CONTAINER_DIAG_PAUSE_S = 1.0  # Delay between diagnostic probe steps.
DEBUG_LOG_MAX_CHARS = 5000  # In-memory rolling log cap.
DEBUG_LOG_FILE = "AutoMiner.debug.log"  # On-disk debug log filename.
DEBUG_LOG_ENABLED = True  # Toggle file logging.
LOG_DATA_KEY = "mining_bot_log_config"  # Persisted key for log UI settings.
JSON_RESET_DONE_KEY = "mining_bot_json_reset_done"  # Migration flag for one-time JSON reset.
HEADMSG_HUE = 1285  # Hue for overhead messages.
RUNNING = False  # Script run state.
CONTROL_GUMP = None  # Root gump reference.
CONTROL_BUTTON = None  # Enable/Disable button reference.
CONTROL_CONTROLS = []  # Strong refs to gump controls.
USE_FIRE_BEETLE_SMELT = False  # Toggle smelting on beetle.
USE_TOOL_CRAFTING = True  # Toggle auto tool crafting.
USE_SACRED_JOURNEY = False  # Toggle sacred journey button ranges.
USE_UOALIVE_SHARD = False  # Toggle shard timing profile (UOAlive vs OSI).
SHARD_OPTIONS = ["OSI", "UOAlive"]  # Dropdown options for shard timing profile.

# Runtime and persisted state.

# Persisted serials.
RUNBOOK_SERIAL = 0  # Runebook serial.
SECURE_CONTAINER_SERIAL = 0  # Drop container serial.

# Recall loop and cache state.
NO_ORE_TILE_CACHE = set()  # Cached depleted tiles at current spot.
NON_MINEABLE_TILE_CACHE = set()  # Cached non-mineable tiles at current spot.
OSI_TIMEOUT_TILE_COUNTS = {}  # Per-spot timeout tracking (used by OSI and UOAlive).
LAST_PLAYER_POS = None  # Last known player position.
MINE_CENTER = None  # Anchor position for the current mining spot.
LAST_MINE_PASS_POS = None  # Last position where a full 3x3 pass was attempted.
HOME_RECALL_BUTTON = 50  # Default home button (recall).
MINING_RUNES = list(range(51, 66))  # Default mining buttons (recall).
CURRENT_MINING_INDEX = 0  # Current mining rune index.
NEEDS_TOOL_CHECK = False  # Deferred tooling check flag.
NEEDS_INITIAL_RECALL = False  # Deferred first recall flag.

# Round-robin drop offsets around the player.
DROP_OFFSETS = [
    (-1, -1),
    (0, -1),
    (1, -1),
    (-1, 0),
    (1, 0),
    (-1, 1),
    (0, 1),
    (1, 1),
]
DROP_OFFSET_INDEX = 0

# Smelting feedback texts.
SMELT_SUCCESS_TEXTS = [
    "You smelt the ore into ingots",
]
# Persistent storage key.
DATA_KEY = "mining_bot_config"  # Persisted key for core AutoMiner settings.


# One-time migration reset for persisted config keys.
def _reset_persisted_config_for_json_migration_once():
    """Reset persisted config keys one time before JSON-only parsing.

    Args:
        None.

    Returns:
        None: Clears legacy persisted keys once and stores a migration flag.

    Side Effects:
        Writes to persistent storage and emits migration diagnostics.
    """
    reset_done = API.GetPersistentVar(JSON_RESET_DONE_KEY, "", API.PersistentVar.Char)
    if str(reset_done).strip() == "1":
        return

    # We clear both persisted blobs so first load starts from known JSON defaults.
    API.SavePersistentVar(DATA_KEY, "", API.PersistentVar.Char)
    API.SavePersistentVar(LOG_DATA_KEY, "", API.PersistentVar.Char)
    API.SavePersistentVar(JSON_RESET_DONE_KEY, "1", API.PersistentVar.Char)
    _diag_warn(
        "One-time config reset applied for JSON-only mode. "
        "Please set runebook and drop container again.",
        phase="CONFIG",
    )


# Lightweight data carrier for a single tile target attempt.
class TileAttempt:
    """Describe one mining-target attempt for a specific world tile.

    Attributes:
        tx: Absolute tile X coordinate in the world.
        ty: Absolute tile Y coordinate in the world.
        relx: Tile X offset from the player's current position.
        rely: Tile Y offset from the player's current position.
        tile: Tile object returned by `API.GetTile`, or `None`.
        tile_is_mineable: `True` when the tile graphic is in the mineable list.
    """
    def __init__(self, tx, ty, relx, rely, tile, tile_is_mineable):
        """Store tile-target context values for one mining attempt.

        Args:
            tx: Absolute target X coordinate.
            ty: Absolute target Y coordinate.
            relx: Relative target X offset from player.
            rely: Relative target Y offset from player.
            tile: Tile object returned by `API.GetTile`.
            tile_is_mineable: Whether this tile is mineable for AutoMiner.

        Returns:
            None: The constructor only stores values on the instance.

        Side Effects:
            Updates instance attributes used by later mining steps.
        """
        self.tx = tx
        self.ty = ty
        self.relx = relx
        self.rely = rely
        self.tile = tile
        self.tile_is_mineable = tile_is_mineable


# Lightweight result object for tile targeting status.
class TileTargetResult:
    """Capture the immediate result of a single target action.

    Attributes:
        target_timeout: `True` when no target cursor appeared in time.
        method_used: Targeting method label used for this attempt.
    """
    def __init__(self, target_timeout=False, method_used="unknown"):
        """Normalize result flags to booleans.

        Args:
            target_timeout: Raw timeout flag from targeting logic.
            method_used: Human-readable method label used for targeting.

        Returns:
            None: The constructor only stores normalized values.

        Side Effects:
            Updates instance attributes for pass-level decision logic.
        """
        self.target_timeout = bool(target_timeout)
        self.method_used = str(method_used or "unknown")


# Journal classification output for one mining attempt.
class TileJournalResult:
    """Store mined-tile journal classification flags for one attempt.

    Attributes:
        no_ore_hit: `True` when journal says the tile is depleted.
        cannot_see: `True` when target visibility failed.
        dig_some: `True` when mining succeeded and ore was found.
        fail_skill: `True` when mining attempt happened but skill failed.
        cant_mine: `True` when journal reports invalid mining location.
    """
    def __init__(self, no_ore_hit=False, cannot_see=False, dig_some=False, fail_skill=False, cant_mine=False):
        """Normalize journal flags and compute a combined status bit.

        Args:
            no_ore_hit: Raw no-ore flag.
            cannot_see: Raw cannot-see flag.
            dig_some: Raw successful-dig flag.
            fail_skill: Raw failed-skill flag.
            cant_mine: Raw cannot-mine flag.

        Returns:
            None: The constructor only stores normalized values.

        Side Effects:
            Updates `any_msg` so callers can quickly test for journal activity.
        """
        self.no_ore_hit = bool(no_ore_hit)
        self.cannot_see = bool(cannot_see)
        self.dig_some = bool(dig_some)
        self.fail_skill = bool(fail_skill)
        self.cant_mine = bool(cant_mine)
        self.any_msg = self.cannot_see or self.dig_some or self.no_ore_hit or self.fail_skill


# Pass-level counters used to decide whether to move to the next rune.
class PassCounters:
    """Track 3x3-pass counters used to decide whether to move runes.

    Attributes:
        no_ore_count: Number of tiles classified as no-ore/depleted.
        cannot_see_count: Number of tiles that remain blocked by visibility.
        timeout_count: Number of target-cursor timeouts this pass.
        dig_success: `True` after any successful or valid mining response.
    """
    def __init__(self):
        """Initialize pass counters to a clean state.

        Args:
            None.

        Returns:
            None: The constructor only stores initial values.

        Side Effects:
            Updates instance attributes read by mining-pass decision logic.
        """
        self.no_ore_count = 0
        self.cannot_see_count = 0
        self.timeout_count = 0
        self.dig_success = False


# Return default persisted settings payload.
def _default_config():
    # Default persisted settings.
    """Default config for the AutoMiner workflow.

    Args:
        None.

    Returns:
        object: Result value produced for the caller.

    Side Effects:
        No side effects beyond local calculations.
    """
    return {
        "runebook_serial": 0,
        "drop_container_serial": 0,
        "use_fire_beetle_smelt": False,
        "use_tool_crafting": True,
        "use_sacred_journey": False,
        "debug_targeting": True,
        "use_uoalive_shard": False,
    }


# Parse persisted settings text into a dictionary.
def _parse_persisted_dict(raw_value, settings_name):
    """Parse persisted settings text as JSON.

    Args:
        raw_value: Raw text loaded from persistent storage.
        settings_name: Friendly settings label used in diagnostic messages.

    Returns:
        dict: Structured parse result with `ok`, `data`, and `error`.

    Side Effects:
        Emits a diagnostic warning when parsing fails.
    """
    try:
        parsed = json.loads(raw_value)
    except (TypeError, ValueError):
        _diag_warn(
            f"{settings_name} config parse failed (invalid JSON). Using defaults.",
            phase="CONFIG",
        )
        return {
            "ok": False,
            "data": {},
            "error": "invalid_json",
        }

    if isinstance(parsed, dict):
        return {
            "ok": True,
            "data": parsed,
            "error": "",
        }

    _diag_warn(
        f"{settings_name} config was not a dictionary. Using defaults.",
        phase="CONFIG",
    )
    return {
        "ok": False,
        "data": {},
        "error": "not_dictionary",
    }


# Load persisted settings into runtime globals.
def _load_config():
    """Load persisted AutoMiner settings into runtime variables.

    Args:
        None.

    Returns:
        None: Runtime configuration globals are updated in place.

    Side Effects:
        Reads persisted config data and updates module-level state.
    """
    global RUNBOOK_SERIAL, SECURE_CONTAINER_SERIAL, USE_TOOL_CRAFTING
    global USE_FIRE_BEETLE_SMELT, USE_SACRED_JOURNEY, DEBUG_TARGETING
    global USE_UOALIVE_SHARD

    raw = API.GetPersistentVar(DATA_KEY, "", API.PersistentVar.Char)
    data = _default_config()

    if raw:
        parse_result = _parse_persisted_dict(raw, "AutoMiner")
        if parse_result.get("ok", False):
            data.update(parse_result.get("data", {}))
        else:
            _diag_warn(
                "AutoMiner config defaults applied reason={0}".format(
                    str(parse_result.get("error", "unknown"))
                ),
                phase="CONFIG",
            )

    RUNBOOK_SERIAL = int(data.get("runebook_serial", 0) or 0)
    SECURE_CONTAINER_SERIAL = int(data.get("drop_container_serial", 0) or 0)
    USE_FIRE_BEETLE_SMELT = bool(data.get("use_fire_beetle_smelt", False))
    USE_TOOL_CRAFTING = bool(data.get("use_tool_crafting", True))
    USE_SACRED_JOURNEY = bool(data.get("use_sacred_journey", False))
    DEBUG_TARGETING = bool(data.get("debug_targeting", True))
    USE_UOALIVE_SHARD = bool(data.get("use_uoalive_shard", False))
    _refresh_recall_buttons()
    if not RUNBOOK_SERIAL:
        _diag_warn("Runebook serial is not configured. Use Set before starting.", phase="CONFIG")
    if not SECURE_CONTAINER_SERIAL:
        _diag_warn(
            "Drop container serial is not configured. Use Set before starting.",
            phase="CONFIG",
        )


# Validate required serials before enabling the mining loop.
def _can_start_mining():
    """Check whether required configuration exists before start.

    Args:
        None.

    Returns:
        bool: `True` when both runebook and drop container are configured.

    Side Effects:
        Emits clear warnings when required values are missing.
    """
    if not RUNBOOK_SERIAL:
        _diag_warn("Start blocked: runebook is not configured.", phase="CONFIG")
        return False
    if not SECURE_CONTAINER_SERIAL:
        _diag_warn("Start blocked: drop container is not configured.", phase="CONFIG")
        return False
    return True

# Save current runtime settings back to persistent storage.
def _save_config():
    # Save persisted settings for runebook/drop.
    """Save config for the AutoMiner workflow.

    Args:
        None.

    Returns:
        None: Performs actions without returning a value.

    Side Effects:
        Interacts with the TazUO client through API calls.
    """
    data = {
        "runebook_serial": int(RUNBOOK_SERIAL or 0),
        "drop_container_serial": int(SECURE_CONTAINER_SERIAL or 0),
        "use_fire_beetle_smelt": bool(USE_FIRE_BEETLE_SMELT),
        "use_tool_crafting": bool(USE_TOOL_CRAFTING),
        "use_sacred_journey": bool(USE_SACRED_JOURNEY),
        "debug_targeting": bool(DEBUG_TARGETING),
        "use_uoalive_shard": bool(USE_UOALIVE_SHARD),
    }
    API.SavePersistentVar(DATA_KEY, json.dumps(data), API.PersistentVar.Char)

# RecipeStore database path helper (shared with Databases/craftables.db).
RECIPE_STORE = None
TINKER_CRAFT_PATHS_BY_SERVER = {}
_script_dir = os.path.dirname(__file__) if "__file__" in globals() else os.getcwd()
_project_root_dir = _script_dir
while _project_root_dir and os.path.basename(_project_root_dir).lower() in ("resources", "utilities", "skills", "scripts"):
    _project_root_dir = os.path.dirname(_project_root_dir)
_util_dir = ""
_util_candidates = []
if _script_dir:
    _util_candidates.append(_script_dir)
    _util_candidates.append(os.path.join(_script_dir, "Utilities"))
    _util_candidates.append(os.path.join(os.path.dirname(_script_dir), "Utilities"))
_cwd = os.getcwd()
if _cwd:
    _util_candidates.append(_cwd)
    _util_candidates.append(os.path.join(_cwd, "Utilities"))
    _util_candidates.append(os.path.join(os.path.dirname(_cwd), "Utilities"))
for _cand in _util_candidates:
    try:
        c = os.path.normpath(str(_cand or ""))
    except Exception:
        c = ""
    if not c or not os.path.isdir(c):
        continue
    if os.path.basename(c).lower() == "utilities" and os.path.isfile(os.path.join(c, "RecipeStore.py")):
        _util_dir = c
        break
if not _util_dir:
    _util_dir = _script_dir
if _util_dir and _util_dir not in sys.path:
    sys.path.insert(0, _util_dir)
try:
    import RecipeStore as RECIPE_STORE
    try:
        # RecipeStore should resolve paths from the LegionScripts project root.
        RECIPE_STORE.set_base_dir(_project_root_dir or _util_dir)
    except Exception:
        pass
except Exception:
    RECIPE_STORE = None


def _active_recipe_server_name():
    """Active recipe server name for the AutoMiner workflow.

    Args:
        None.

    Returns:
        object: Result value produced for the caller.

    Side Effects:
        No side effects beyond local calculations.
    """
    return "UOAlive" if USE_UOALIVE_SHARD else "OSI"


def _normalize_recipe_name(text):
    """Normalize recipe name for the AutoMiner workflow.

    Args:
        text: Input value used by this helper.

    Returns:
        object: Result value produced for the caller.

    Side Effects:
        No side effects beyond local calculations.
    """
    return " ".join(str(text or "").strip().lower().split())


def _is_tinker_profession_name(text):
    """Is tinker profession name for the AutoMiner workflow.

    Args:
        text: Input value used by this helper.

    Returns:
        object: Result value produced for the caller.

    Side Effects:
        No side effects beyond local calculations.
    """
    n = _normalize_recipe_name(text)
    return n in ("tinker", "tinkering")


def _recipe_db_path():
    # Resolve craftables DB path from RecipeStore only (single source of truth).
    """Recipe db path for the AutoMiner workflow.

    Args:
        None.

    Returns:
        str: Absolute path to `craftables.db`, or empty string when unavailable.

    Side Effects:
        Emits diagnostics when the configured path is unavailable.
    """
    if not (RECIPE_STORE and hasattr(RECIPE_STORE, "_db_path")):
        _diag_error("Recipe DB path unavailable: RecipeStore._db_path is not available.", phase="TOOL")
        return ""
    try:
        p = str(RECIPE_STORE._db_path() or "").strip()
    except Exception as ex:
        _diag_error("Recipe DB path lookup failed: {0}".format(str(ex)), phase="TOOL")
        return ""
    if not p:
        _diag_error("Recipe DB path lookup returned an empty value.", phase="TOOL")
        return ""
    if not os.path.isfile(p):
        _diag_error("Recipe DB path does not exist: {0}".format(str(p)), phase="TOOL")
        return ""
    return p


def _connect_recipe_db_ro():
    # Runtime sqlite in this environment does not support sqlite URI open kwargs.
    # Use plain path + query_only so behavior is simple and consistent.
    """Open the craftables database in read-only mode for recipe lookup.

    Args:
        None.

    Returns:
        tuple: `(sqlite_connection, db_path)` when opening succeeds.

    Side Effects:
        Opens a SQLite connection and may raise if no read-only path works.
    """
    p = _recipe_db_path()
    if not p:
        raise Exception("db path not found")

    try:
        conn = sqlite3.connect(p, timeout=0.5)
        try:
            conn.execute("PRAGMA query_only=1;")
        except Exception:
            pass
        _diag_info("Recipe DB open success mode=path_query_only")
        return conn, p
    except Exception as ex:
        _diag_info("Recipe DB open failed mode=path_query_only err={0}".format(str(ex)))
        raise Exception("path=" + str(ex))


def _clear_recipe_caches():
    # Clear in-memory recipe caches so next lookup reloads from the database.
    """Clear recipe caches for the AutoMiner workflow.

    Args:
        None.

    Returns:
        None: Performs actions without returning a value.

    Side Effects:
        Updates module-level runtime state.
    """
    global TINKER_CRAFT_PATHS_BY_SERVER
    TINKER_CRAFT_PATHS_BY_SERVER = {}


def _prime_tinker_craft_path_cache(force=False):
    """Prime tinker craft path cache for the AutoMiner workflow.

    Args:
        force: When `True`, rebuild the cache from database queries.

    Returns:
        dict: Per-server tinker craft paths using canonical craftables tables.

    Side Effects:
        Updates module-level runtime state.
    """
    global TINKER_CRAFT_PATHS_BY_SERVER
    _ = bool(force)  # Parameter kept for call-site compatibility.
    has_existing_cache = isinstance(TINKER_CRAFT_PATHS_BY_SERVER, dict) and bool(TINKER_CRAFT_PATHS_BY_SERVER)

    try:
        db_path = _recipe_db_path()
        if not db_path:
            _diag_error(
                "Recipe DB path resolution failed; cache prime skipped using_existing_cache={0}".format(
                    str(has_existing_cache)
                ),
                phase="TOOL",
            )
            return TINKER_CRAFT_PATHS_BY_SERVER if isinstance(TINKER_CRAFT_PATHS_BY_SERVER, dict) else {}
        _diag_info("Recipe DB path: {0}".format(str(db_path)))

        out = {}
        material_option_by_server = {}

        conn = None
        try:
            conn, _ = _connect_recipe_db_ro()
            try:
                conn.execute("PRAGMA query_only=1;")
            except Exception:
                pass

            # Build item navigation paths for shovel and tinker's tools.
            cur = conn.execute(
                """
                SELECT gs.server_name,
                       ci.item_key_slug,
                       ci.item_display_name,
                       ci.default_material_option_id,
                       cins.gump_button_id
                FROM craftable_items ci
                JOIN crafting_contexts cc ON cc.context_id = ci.context_id
                JOIN game_servers gs ON gs.game_server_id = cc.game_server_id
                JOIN crafting_professions cp ON cp.profession_id = cc.profession_id
                JOIN craftable_item_navigation_steps cins ON cins.craftable_item_id = ci.craftable_item_id
                WHERE lower(trim(cp.profession_name)) IN (?, ?)
                  AND (
                      lower(trim(ci.item_key_slug)) IN (?, ?)
                      OR lower(trim(ci.item_display_name)) IN (?, ?)
                  )
                ORDER BY gs.server_name, ci.craftable_item_id, cins.step_number
                """,
                ("tinker", "tinkering", "shovel", "tinker's tools", "shovel", "tinker's tools"),
            )
            for server, item_key, item_name, material_option_id, button_id in (cur.fetchall() or []):
                s = str(server or "")
                n = _normalize_recipe_name(item_key or item_name)
                if n not in ("shovel", "tinker's tools"):
                    n = _normalize_recipe_name(item_name or item_key)
                if n not in ("shovel", "tinker's tools"):
                    continue

                if s not in out:
                    out[s] = {"material_buttons": [], "items": {}}
                if n not in out[s]["items"]:
                    out[s]["items"][n] = []
                try:
                    bid = int(button_id)
                    if bid > 0:
                        out[s]["items"][n].append(bid)
                except Exception:
                    pass

                try:
                    moid = int(material_option_id or 0)
                except Exception:
                    moid = 0
                if moid > 0:
                    # Prefer shovel's default material option when both targets exist.
                    if (s not in material_option_by_server) or (n == "shovel"):
                        material_option_by_server[s] = moid

            # Resolve material navigation using each server's default material option id.
            for s, moid in (material_option_by_server.items() if isinstance(material_option_by_server, dict) else []):
                try:
                    cur = conn.execute(
                        """
                        SELECT mons.gump_button_id
                        FROM material_option_navigation_steps mons
                        WHERE mons.material_option_id=?
                        ORDER BY mons.step_number
                        """,
                        (int(moid),),
                    )
                    out[s]["material_buttons"] = [
                        int(r[0]) for r in (cur.fetchall() or []) if int(r[0]) > 0
                    ]
                except Exception:
                    out[s]["material_buttons"] = []
        finally:
            try:
                conn.close()
            except Exception:
                pass

        try:
            _srv = _active_recipe_server_name()
            _node = out.get(_srv, {}) if isinstance(out, dict) else {}
            _items = _node.get("items", {}) if isinstance(_node, dict) else {}
            _diag_info(
                "Recipe prime server={0} shovel={1} tools={2} material={3}".format(
                    _srv,
                    list(_items.get("shovel", []) if isinstance(_items, dict) else []),
                    list(_items.get("tinker's tools", []) if isinstance(_items, dict) else []),
                    list(_node.get("material_buttons", []) if isinstance(_node, dict) else []),
                )
            )
        except Exception:
            pass

        TINKER_CRAFT_PATHS_BY_SERVER = out if isinstance(out, dict) else {}
        return TINKER_CRAFT_PATHS_BY_SERVER
    except Exception as ex:
        # Keep runtime stable, but emit explicit diagnostics instead of silent fallback behavior.
        _diag_error(
            "Recipe cache prime failed err={0} using_existing_cache={1}".format(
                str(ex), str(has_existing_cache)
            ),
            phase="TOOL",
        )
        if not isinstance(TINKER_CRAFT_PATHS_BY_SERVER, dict):
            TINKER_CRAFT_PATHS_BY_SERVER = {}
        return TINKER_CRAFT_PATHS_BY_SERVER


def _resolve_tinker_recipe_paths(item_name):
    """Resolve tinker recipe paths for the AutoMiner workflow.

    Args:
        item_name: Input value used by this helper.

    Returns:
        object: Result value produced for the caller.

    Side Effects:
        Updates module-level runtime state.
    """
    global TINKER_CRAFT_PATHS_BY_SERVER
    server = _active_recipe_server_name()
    target = _normalize_recipe_name(item_name)

    # Keep recipe resolution single-path: read from the primed cache only.
    # This avoids hidden fallback behavior that can make failures harder to debug.
    if not isinstance(TINKER_CRAFT_PATHS_BY_SERVER, dict) or not TINKER_CRAFT_PATHS_BY_SERVER:
        _diag_info("Recipe cache empty; priming from craftables DB.", phase="TOOL")
        _prime_tinker_craft_path_cache(True)

    paths = TINKER_CRAFT_PATHS_BY_SERVER if isinstance(TINKER_CRAFT_PATHS_BY_SERVER, dict) else {}
    node = paths.get(server, {})
    if not isinstance(node, dict):
        _diag_error(
            "Recipe cache missing server node server={0}. Expected keys: {1}".format(
                str(server), list(paths.keys()) if isinstance(paths, dict) else []
            ),
            phase="TOOL",
        )
        _diag_error(
            "Recipe path resolve failed item='{0}' reason=missing_server_node".format(str(target)),
            phase="TOOL",
        )
        return [], []

    items = node.get("items", {})
    if not isinstance(items, dict):
        _diag_error("Recipe cache malformed: items map is not a dictionary.", phase="TOOL")
        _diag_error(
            "Recipe path resolve failed item='{0}' reason=malformed_items_map".format(str(target)),
            phase="TOOL",
        )
        return [], []

    item_buttons = list(items.get(target, []))
    material_buttons = list(node.get("material_buttons", []))
    if not item_buttons:
        _diag_error(
            "Recipe path missing item buttons server={0} item='{1}'.".format(str(server), str(target)),
            phase="TOOL",
        )
    if not material_buttons:
        _diag_error(
            "Recipe path missing material buttons server={0} item='{1}'.".format(str(server), str(target)),
            phase="TOOL",
        )
    if not item_buttons or not material_buttons:
        _diag_error(
            "Recipe path resolve incomplete server={0} item='{1}' has_item_buttons={2} has_material_buttons={3}".format(
                str(server),
                str(target),
                str(bool(item_buttons)),
                str(bool(material_buttons)),
            ),
            phase="TOOL",
        )
    return item_buttons, material_buttons

# Tinker gump + button ids.
TINKER_GUMP_ID_OSI = 0x1CC  # Tinker gump id (OSI).
TINKER_GUMP_ID_UOALIVE = 0xD466EA9C  # Tinker gump id (UOAlive).
TINKER_GUMP_ANCHORS = [
    "TINKERING MENU",
    "TINKERING",
    "TINKER",
]
# Select the next smeltable ore stack from backpack contents.
def _find_ore_in_backpack():
    # Find the next smeltable ore in the backpack, honoring special min-stack rules.
    # Special case: only smelt 0x19B7 when stack is 2+ (check recursively).
    """Find ore in backpack for the AutoMiner workflow.

    Args:
        None.

    Returns:
        object: Result value produced for the caller.

    Side Effects:
        Interacts with the TazUO client through API calls.
    """
    items = API.ItemsInContainer(API.Backpack, True)
    if items:
        for item in items:
            if item.Graphic == ORE_GRAPHIC_MIN2 and int(item.Amount) >= 2:
                return item
    for graphic in ORE_GRAPHICS:
        ore = API.FindType(graphic, API.Backpack)
        if ore:
            return ore
    return None

def _count_ingots_in_backpack():
    # Count hue-0 ingots in the backpack.
    """Count ingots in backpack for the AutoMiner workflow.

    Args:
        None.

    Returns:
        object: Result value produced for the caller.

    Side Effects:
        Interacts with the TazUO client through API calls.
    """
    total = 0
    items = API.ItemsInContainer(API.Backpack, True) or []
    for item in items:
        if item.Graphic in INGOT_GRAPHICS and int(item.Hue) == 0:
            total += int(item.Amount)
    return total

def _count_shovels_in_backpack():
    # Count shovels in the backpack.
    """Count shovels in backpack for the AutoMiner workflow.

    Args:
        None.

    Returns:
        object: Result value produced for the caller.

    Side Effects:
        Interacts with the TazUO client through API calls.
    """
    items = API.ItemsInContainer(API.Backpack, True) or []
    return sum(1 for i in items if i.Graphic in SHOVEL_GRAPHICS)

def _count_tinker_tools_in_backpack():
    # Count tinker's tools in the backpack.
    """Count tinker tools in backpack for the AutoMiner workflow.

    Args:
        None.

    Returns:
        object: Result value produced for the caller.

    Side Effects:
        Interacts with the TazUO client through API calls.
    """
    items = API.ItemsInContainer(API.Backpack, True) or []
    return sum(1 for i in items if i.Graphic in TINKER_TOOL_GRAPHICS)

def _find_tinker_tool():
    # Find the first tinker's tool in the backpack.
    """Find tinker tool for the AutoMiner workflow.

    Args:
        None.

    Returns:
        object: Result value produced for the caller.

    Side Effects:
        Interacts with the TazUO client through API calls.
    """
    for graphic in TINKER_TOOL_GRAPHICS:
        tool = API.FindType(graphic, API.Backpack)
        if tool:
            return tool
    return None

def _gump_matches_anchors(gump_id, anchors):
    """Gump matches anchors for the AutoMiner workflow.

    Args:
        gump_id: Input value used by this helper.
        anchors: Input value used by this helper.

    Returns:
        object: Result value produced for the caller.

    Side Effects:
        Interacts with the TazUO client through API calls.
    """
    gid = int(gump_id or 0)
    if gid <= 0:
        return False
    try:
        txt = API.GetGumpContents(gid) or ""
    except Exception:
        txt = ""
    if not txt:
        return False
    lower = str(txt).lower()
    for a in (anchors or []):
        if str(a or "").lower() in lower:
            return True
    return False


def _find_tinker_gump_by_anchors():
    """Find tinker gump by anchors for the AutoMiner workflow.

    Args:
        None.

    Returns:
        object: Result value produced for the caller.

    Side Effects:
        No side effects beyond local calculations.
    """
    ids = _gump_ids_snapshot() or []
    seen = set()
    for gid in ids:
        try:
            g = int(gid)
        except Exception:
            continue
        if g <= 0 or g in seen:
            continue
        seen.add(g)
        if _gump_matches_anchors(g, TINKER_GUMP_ANCHORS):
            return g
    return 0


def _wait_for_tinker_gump(timeout_s=3.0, preferred_id=0):
    """Wait for tinker gump for the AutoMiner workflow.

    Args:
        timeout_s: Input value used by this helper.
        preferred_id: Input value used by this helper.

    Returns:
        object: Result value produced for the caller.

    Side Effects:
        Interacts with the TazUO client through API calls.
    """
    elapsed = 0.0
    step = 0.1
    pid = int(preferred_id or 0)
    while elapsed < float(timeout_s):
        if pid > 0:
            try:
                if API.WaitForGump(int(pid), 0.1) and _gump_matches_anchors(int(pid), TINKER_GUMP_ANCHORS):
                    return int(pid)
            except Exception:
                pass
        gid = _find_tinker_gump_by_anchors()
        if int(gid or 0) > 0:
            return int(gid)
        API.ProcessCallbacks()
        _sleep(step)
        elapsed += step
    return 0


def _open_tinker_menu(preferred_id):
    """Open tinker menu for the AutoMiner workflow.

    Args:
        preferred_id: Input value used by this helper.

    Returns:
        object: Result value produced for the caller.

    Side Effects:
        Interacts with the TazUO client through API calls.
    """
    tool = _find_tinker_tool()
    if not tool:
        return 0
    bp_ser = int(API.Backpack or 0)
    for _ in range(3):
        live_tool = None
        try:
            live_tool = API.FindItem(int(getattr(tool, "Serial", 0) or 0))
        except Exception:
            live_tool = None
        if not live_tool:
            live_tool = _find_tinker_tool()
        if not live_tool:
            return 0
        try:
            c1 = int(getattr(live_tool, "Container", 0) or 0)
            c2 = int(getattr(live_tool, "ContainerSerial", 0) or 0)
            if bp_ser > 0 and c1 != bp_ser and c2 != bp_ser:
                API.MoveItem(int(getattr(live_tool, "Serial", 0) or 0), API.Backpack, 1)
                _sleep(0.5)
                live_tool = API.FindItem(int(getattr(live_tool, "Serial", 0) or 0))
                if not live_tool:
                    live_tool = _find_tinker_tool()
        except Exception:
            pass
        try:
            API.UseObject(int(getattr(live_tool, "Serial", 0) or 0))
        except Exception:
            _sleep(0.25)
            continue
        gid = _wait_for_tinker_gump(3.0, int(preferred_id or 0))
        if int(gid or 0) > 0:
            return int(gid)
        _sleep(0.25)
    return 0


def _click_tinker_button_path(gump_id, buttons):
    """Click tinker button path for the AutoMiner workflow.

    Args:
        gump_id: Input value used by this helper.
        buttons: Input value used by this helper.

    Returns:
        object: Result value produced for the caller.

    Side Effects:
        Interacts with the TazUO client through API calls.
    """
    path = [int(x) for x in (buttons or []) if int(x) > 0]
    if not path:
        return 0
    gid = int(gump_id or 0)
    for idx, button_id in enumerate(path):
        if not _gump_matches_anchors(int(gid), TINKER_GUMP_ANCHORS):
            gid = _wait_for_tinker_gump(2.0, int(gid))
        if int(gid or 0) <= 0:
            return 0
        API.ReplyGump(int(button_id), int(gid))
        _sleep(0.28)
        if idx < (len(path) - 1):
            gid = _wait_for_tinker_gump(2.0, int(gid))
            if int(gid or 0) <= 0:
                return 0
    return int(gid)


def _craft_with_tinker_path(gump_id, item_buttons, material_buttons=None):
    # Craft an item using a full gump button path (optional material selection first).
    """Craft with tinker path for the AutoMiner workflow.

    Args:
        gump_id: Input value used by this helper.
        item_buttons: Input value used by this helper.
        material_buttons: Input value used by this helper.

    Returns:
        object: Result value produced for the caller.

    Side Effects:
        Interacts with the TazUO client through API calls.
    """
    active_gump_id = _open_tinker_menu(int(gump_id))
    if int(active_gump_id or 0) <= 0:
        _diag_info("Tinker gump not found.")
        return False
    _sleep(0.5)
    if material_buttons:
        active_gump_id = _click_tinker_button_path(int(active_gump_id), material_buttons)
        if int(active_gump_id or 0) <= 0:
            _diag_info("Tinker material selection failed.")
            return False
        active_gump_id = _wait_for_tinker_gump(2.0, int(active_gump_id))
        if int(active_gump_id or 0) <= 0:
            _diag_info("Tinker gump not found after material selection.")
            return False
        _sleep(0.25)
    active_gump_id = _click_tinker_button_path(int(active_gump_id), item_buttons)
    if int(active_gump_id or 0) <= 0:
        _diag_info("Tinker craft path failed.")
        return False
    _sleep(0.5)
    API.CloseGump(int(active_gump_id))
    API.CloseGump()
    return True

def _craft_tinker_tool():
    # Craft a spare tinker's tool using shard-specific gump buttons.
    """Craft tinker tool for the AutoMiner workflow.

    Args:
        None.

    Returns:
        object: Result value produced for the caller.

    Side Effects:
        No side effects beyond local calculations.
    """
    gump_id = TINKER_GUMP_ID_UOALIVE if USE_UOALIVE_SHARD else TINKER_GUMP_ID_OSI
    item_buttons, material_buttons = _resolve_tinker_recipe_paths("tinker's tools")
    _diag_info(
        "Tinker's tools path lookup server={0} item_buttons={1} material_buttons={2}".format(
            _active_recipe_server_name(), list(item_buttons or []), list(material_buttons or [])
        )
    )
    if not item_buttons:
        _diag_info("No DB craft path found for Tinker's tools.")
        return False
    if not material_buttons:
        _diag_info("No DB material path found for Tinker's tools.")
        return False
    return _craft_with_tinker_path(gump_id, item_buttons, material_buttons)

def _craft_shovel():
    # Craft a shovel using the shard-appropriate button flow.
    """Craft shovel for the AutoMiner workflow.

    Args:
        None.

    Returns:
        object: Result value produced for the caller.

    Side Effects:
        No side effects beyond local calculations.
    """
    gump_id = TINKER_GUMP_ID_UOALIVE if USE_UOALIVE_SHARD else TINKER_GUMP_ID_OSI
    item_buttons, material_buttons = _resolve_tinker_recipe_paths("shovel")
    _diag_info(
        "Shovel path lookup server={0} item_buttons={1} material_buttons={2}".format(
            _active_recipe_server_name(), list(item_buttons or []), list(material_buttons or [])
        )
    )
    if not item_buttons:
        _diag_info("No DB craft path found for shovel.")
        return False
    if not material_buttons:
        _diag_info("No DB material path found for shovel.")
        return False
    return _craft_with_tinker_path(gump_id, item_buttons, material_buttons)

def _ensure_tooling_in_backpack():
    # Ensure required tools exist before mining.
    """Ensure tooling in backpack for the AutoMiner workflow.

    Args:
        None.

    Returns:
        None: Performs actions without returning a value.

    Side Effects:
        No side effects beyond local calculations.
    """
    if USE_TOOL_CRAFTING:
        tinker_count = _count_tinker_tools_in_backpack()
        if tinker_count == 0:
            _diag_error("No tinker's tool in backpack.", phase="TOOL")
            _diag_error("You forgot to bring your tinker's tool", phase="TOOL")
            _stop_running_with_message()
            return
        if tinker_count == 1:
            _craft_tinker_tool()
        if _count_shovels_in_backpack() == 0:
            _craft_shovel()
        return
    if _count_shovels_in_backpack() == 0:
        _ensure_shovels_from_drop_container()


def _ensure_shovels_from_drop_container():
    # Pull shovels from the drop container when auto tooling is disabled.
    """Ensure shovels from drop container for the AutoMiner workflow.

    Args:
        None.

    Returns:
        None: Performs actions without returning a value.

    Side Effects:
        Interacts with the TazUO client through API calls.
    """
    count = _count_shovels_in_backpack()
    if count == 0:
        _diag_info("No shovels in backpack. Recalling home and pausing.")
        _recall_home()
        _stop_running_with_message()
        return
    if count >= 2:
        return
    if not SECURE_CONTAINER_SERIAL:
        _diag_info("Drop container not set. Pausing.")
        _stop_running_with_message()
        return
    items = API.ItemsInContainer(SECURE_CONTAINER_SERIAL, True) or []
    for item in items:
        if item.Graphic in SHOVEL_GRAPHICS and _count_shovels_in_backpack() < 2:
            API.MoveItem(item.Serial, API.Backpack, 1)
            _sleep(0.6)
    if _count_shovels_in_backpack() == 0:
        _diag_info("No shovels available in drop container. Recalling home and pausing.")
        _recall_home()
        _stop_running_with_message()

def _find_drop_item():
    # Drop by smallest graphic, then by hue priority (iron -> hued), then by lowest hue value.
    """Find drop item for the AutoMiner workflow.

    Args:
        None.

    Returns:
        object: Result value produced for the caller.

    Side Effects:
        Interacts with the TazUO client through API calls.
    """
    items = API.ItemsInContainer(API.Backpack, True) or []
    if not items:
        return None
    for graphic in sorted(set(DROP_PRIORITY)):
        candidates = [i for i in items if i.Graphic == graphic]
        if not candidates:
            continue
        for hue in ORE_HUE_PRIORITY:
            for item in candidates:
                try:
                    if int(item.Hue) == int(hue):
                        return item
                except Exception:
                    continue
        try:
            return sorted(candidates, key=lambda i: int(i.Hue))[0]
        except Exception:
            return candidates[0]
    return None

def _toggle_running():
    # Toggle the main run state and refresh the gump button text.
    """Toggle running for the AutoMiner workflow.

    Args:
        None.

    Returns:
        None: Performs actions without returning a value.

    Side Effects:
        Updates module-level runtime state.
        Interacts with the TazUO client through API calls.
    """
    global RUNNING, NEEDS_TOOL_CHECK, NEEDS_INITIAL_RECALL

    # We split start/stop handling so start can be blocked with clear feedback.
    if RUNNING:
        RUNNING = False
        NEEDS_TOOL_CHECK = False
        NEEDS_INITIAL_RECALL = False
        _diag_info("Mining: OFF")
        _update_control_gump()
        return

    # Run one-time config migration only when user clicks Start.
    # This keeps initial script load focused on showing the control gump.
    _reset_persisted_config_for_json_migration_once()

    if not _can_start_mining():
        RUNNING = False
        NEEDS_TOOL_CHECK = False
        NEEDS_INITIAL_RECALL = False
        _update_control_gump()
        return

    RUNNING = True
    state = "ON"
    if RUNNING:
        _clear_recipe_caches()
        _reset_mine_cache()
        _diag_info("Tile caches cleared for fresh run start")
        _diag_info("Craftables.db caches cleared; forcing fresh craft-path prime")
        _prime_tinker_craft_path_cache(True)
        API.Dismount()
        API.ToggleFly()
        NEEDS_TOOL_CHECK = True
        if RUNBOOK_SERIAL:
            NEEDS_INITIAL_RECALL = True
    _diag_info(f"Mining: {state}")
    _update_control_gump()

def _toggle_fire_beetle():
    # Toggle fire beetle smelting.
    """Toggle fire beetle for the AutoMiner workflow.

    Args:
        None.

    Returns:
        None: Performs actions without returning a value.

    Side Effects:
        Updates module-level runtime state.
    """
    global USE_FIRE_BEETLE_SMELT
    USE_FIRE_BEETLE_SMELT = not USE_FIRE_BEETLE_SMELT
    _save_config()

def _toggle_tool_crafting():
    # Toggle auto tool crafting.
    """Toggle tool crafting for the AutoMiner workflow.

    Args:
        None.

    Returns:
        None: Performs actions without returning a value.

    Side Effects:
        Updates module-level runtime state.
    """
    global USE_TOOL_CRAFTING
    USE_TOOL_CRAFTING = not USE_TOOL_CRAFTING
    _save_config()


# Refresh home/mining runebook button ranges for current travel mode.
def _refresh_recall_buttons():
    """Refresh recall buttons for the AutoMiner workflow.

    Args:
        None.

    Returns:
        None: Performs actions without returning a value.

    Side Effects:
        Updates module-level runtime state.
    """
    global HOME_RECALL_BUTTON, MINING_RUNES
    if USE_SACRED_JOURNEY:
        HOME_RECALL_BUTTON = 75
        MINING_RUNES = list(range(76, 91))
    else:
        HOME_RECALL_BUTTON = 50
        MINING_RUNES = list(range(51, 66))


# Switch travel mode to Sacred Journey button mapping.
def _set_travel_chiv():
    """Set travel chiv for the AutoMiner workflow.

    Args:
        None.

    Returns:
        None: Performs actions without returning a value.

    Side Effects:
        Updates module-level runtime state.
    """
    global USE_SACRED_JOURNEY
    USE_SACRED_JOURNEY = True
    _refresh_recall_buttons()
    _save_config()
    _rebuild_control_gump()


# Switch travel mode to Mage Recall button mapping.
def _set_travel_mage():
    """Set travel mage for the AutoMiner workflow.

    Args:
        None.

    Returns:
        None: Performs actions without returning a value.

    Side Effects:
        Updates module-level runtime state.
    """
    global USE_SACRED_JOURNEY
    USE_SACRED_JOURNEY = False
    _refresh_recall_buttons()
    _save_config()
    _rebuild_control_gump()

def _unset_runebook():
    # Clear the runebook serial.
    """Unset runebook for the AutoMiner workflow.

    Args:
        None.

    Returns:
        None: Performs actions without returning a value.

    Side Effects:
        Updates module-level runtime state.
    """
    global RUNBOOK_SERIAL
    RUNBOOK_SERIAL = 0
    _diag_info("Runebook unset.")
    _save_config()
    _rebuild_control_gump()

def _unset_secure_container():
    # Clear the drop container serial.
    """Unset secure container for the AutoMiner workflow.

    Args:
        None.

    Returns:
        None: Performs actions without returning a value.

    Side Effects:
        Updates module-level runtime state.
    """
    global SECURE_CONTAINER_SERIAL
    SECURE_CONTAINER_SERIAL = 0
    _diag_info("Drop container unset.")
    _save_config()
    _rebuild_control_gump()

def _set_runebook():
    # Target and set the runebook.
    """Set runebook for the AutoMiner workflow.

    Args:
        None.

    Returns:
        None: Performs actions without returning a value.

    Side Effects:
        Updates module-level runtime state.
        Interacts with the TazUO client through API calls.
    """
    global RUNBOOK_SERIAL
    _diag_info("Target your runebook.")
    serial = API.RequestTarget()
    if serial:
        RUNBOOK_SERIAL = int(serial)
        _diag_info("Runebook set.")
        _save_config()
        _rebuild_control_gump()

def _set_secure_container():
    # Target and set the drop container.
    """Set secure container for the AutoMiner workflow.

    Args:
        None.

    Returns:
        None: Performs actions without returning a value.

    Side Effects:
        Updates module-level runtime state.
        Interacts with the TazUO client through API calls.
    """
    global SECURE_CONTAINER_SERIAL
    _diag_info("Target your secure container.")
    serial = API.RequestTarget()
    if serial:
        SECURE_CONTAINER_SERIAL = int(serial)
        _diag_info("Drop container set.")
        _save_config()
        _rebuild_control_gump()


# Human-readable shard mode for gump/status output.
def _active_shard_mode_name():
    """Active shard mode name for the AutoMiner workflow.

    Args:
        None.

    Returns:
        object: Result value produced for the caller.

    Side Effects:
        No side effects beyond local calculations.
    """
    if USE_UOALIVE_SHARD:
        return "UOAlive"
    return "OSI"


def _get_active_mining_timings():
    # Return (tool_use_delay_s, journal_wait_s) for current shard.
    """Get active mining timings for the AutoMiner workflow.

    Args:
        None.

    Returns:
        object: Result value produced for the caller.

    Side Effects:
        No side effects beyond local calculations.
    """
    if USE_UOALIVE_SHARD:
        return (UOALIVE_TOOL_USE_DELAY_S, MINING_JOURNAL_WAIT_S)
    return (OSI_TOOL_USE_DELAY_S, OSI_JOURNAL_WAIT_S)


def _set_shard_osi():
    # Use OSI mining timings.
    """Set shard osi for the AutoMiner workflow.

    Args:
        None.

    Returns:
        None: Performs actions without returning a value.

    Side Effects:
        Updates module-level runtime state.
    """
    global USE_UOALIVE_SHARD
    USE_UOALIVE_SHARD = False
    _diag_info("Shard set to OSI.")
    _save_config()
    _rebuild_control_gump()

def _set_shard_uoalive():
    # Use UOAlive mining timings.
    """Set shard uoalive for the AutoMiner workflow.

    Args:
        None.

    Returns:
        None: Performs actions without returning a value.

    Side Effects:
        Updates module-level runtime state.
    """
    global USE_UOALIVE_SHARD
    USE_UOALIVE_SHARD = True
    _diag_info("Shard set to UOAlive.")
    _save_config()
    _rebuild_control_gump()


def _set_shard_from_dropdown(selected_index):
    """Set shard from dropdown for the AutoMiner workflow.

    Args:
        selected_index: Input value used by this helper.

    Returns:
        None: Performs actions without returning a value.

    Side Effects:
        Updates module-level runtime state.
    """
    global USE_UOALIVE_SHARD
    idx = int(selected_index)
    if idx < 0 or idx >= len(SHARD_OPTIONS):
        idx = 0
    use_uoalive = (SHARD_OPTIONS[idx] == "UOAlive")
    if USE_UOALIVE_SHARD == use_uoalive:
        return
    USE_UOALIVE_SHARD = use_uoalive
    _diag_info(f"Shard set to {SHARD_OPTIONS[idx]}.")
    _save_config()
    _rebuild_control_gump()

def _set_debug_on():
    # Enable debug system messages.
    """Set debug on for the AutoMiner workflow.

    Args:
        None.

    Returns:
        None: Performs actions without returning a value.

    Side Effects:
        Updates module-level runtime state.
    """
    global DEBUG_TARGETING
    DEBUG_TARGETING = True
    _diag_info("Debug messages enabled.")
    _save_config()
    _rebuild_control_gump()

def _set_debug_off():
    # Disable debug system messages.
    """Set debug off for the AutoMiner workflow.

    Args:
        None.

    Returns:
        None: Performs actions without returning a value.

    Side Effects:
        Updates module-level runtime state.
    """
    global DEBUG_TARGETING
    DEBUG_TARGETING = False
    _diag_info("Debug messages disabled.")
    _save_config()
    _rebuild_control_gump()

def _update_control_gump():
    # Refresh the gump button label to reflect current run state.
    """Update control gump for the AutoMiner workflow.

    Args:
        None.

    Returns:
        None: Performs actions without returning a value.

    Side Effects:
        No side effects beyond local calculations.
    """
    if not CONTROL_BUTTON:
        return
    CONTROL_BUTTON.Text = "Pause" if RUNNING else "Start"

def _stop_running_with_message():
    # Stop the run loop without closing the gump.
    """Stop running with message for the AutoMiner workflow.

    Args:
        None.

    Returns:
        None: Performs actions without returning a value.

    Side Effects:
        Updates module-level runtime state.
    """
    global RUNNING, NEEDS_TOOL_CHECK, NEEDS_INITIAL_RECALL
    RUNNING = False
    NEEDS_TOOL_CHECK = False
    NEEDS_INITIAL_RECALL = False
    _update_control_gump()

def _rebuild_control_gump():
    # Rebuild the gump to reflect updated settings.
    """Rebuild control gump for the AutoMiner workflow.

    Args:
        None.

    Returns:
        None: Performs actions without returning a value.

    Side Effects:
        Updates module-level runtime state.
    """
    global CONTROL_GUMP, CONTROL_BUTTON, CONTROL_CONTROLS
    if CONTROL_GUMP:
        CONTROL_GUMP.Dispose()
        CONTROL_GUMP = None
    CONTROL_BUTTON = None
    CONTROL_CONTROLS = []
    _create_control_gump()

def _pause_if_needed():
    # Block execution while paused, still processing gump callbacks.
    """Pause if needed for the AutoMiner workflow.

    Args:
        None.

    Returns:
        None: Performs actions without returning a value.

    Side Effects:
        Interacts with the TazUO client through API calls.
    """
    while not RUNNING:
        API.ProcessCallbacks()
        API.Pause(0.1)

def _sleep(seconds):
    # Pause in small steps so the pause button is responsive.
    """Sleep for the AutoMiner workflow.

    Args:
        seconds: Input value used by this helper.

    Returns:
        None: Performs actions without returning a value.

    Side Effects:
        Interacts with the TazUO client through API calls.
    """
    elapsed = 0.0
    step = 0.1
    while elapsed < seconds:
        _pause_if_needed()
        API.ProcessCallbacks()
        API.Pause(step)
        elapsed += step

def _wait_for_target(seconds):
    # Wait for a target cursor while respecting pause state.
    """Wait for target for the AutoMiner workflow.

    Args:
        seconds: Input value used by this helper.

    Returns:
        object: Result value produced for the caller.

    Side Effects:
        Interacts with the TazUO client through API calls.
    """
    elapsed = 0.0
    step = 0.1
    while elapsed < seconds:
        _pause_if_needed()
        if API.HasTarget():
            return True
        API.Pause(step)
        elapsed += step
    return False


# Append a message to the rolling in-memory log buffer and refresh log UI.
def _append_log(msg):
    """Append log for the AutoMiner workflow.

    Args:
        msg: Input value used by this helper.

    Returns:
        None: Performs actions without returning a value.

    Side Effects:
        Updates module-level runtime state.
    """
    global LOG_TEXT, LOG_LINES
    LOG_TEXT = (LOG_TEXT + msg + "\n")[-DEBUG_LOG_MAX_CHARS:]
    LOG_LINES = LOG_TEXT.splitlines() or ["(log empty)"]
    if LOG_GUMP:
        _update_log_gump()


# Resolve the default on-disk debug log location.
def _debug_log_path():
    """Debug log path for the AutoMiner workflow.

    Args:
        None.

    Returns:
        object: Result value produced for the caller.

    Side Effects:
        No side effects beyond local calculations.
    """
    try:
        base = os.path.dirname(__file__)
    except Exception:
        base = os.getcwd()
    if os.path.basename(base).lower() in ("resources", "utilities", "skills", "scripts"):
        base = os.path.dirname(base)
    logs_dir = os.path.join(base, "Logs")
    return os.path.join(logs_dir, DEBUG_LOG_FILE)


# Write one timestamped debug line to disk (best-effort).
def _write_debug_log(line):
    """Write debug log for the AutoMiner workflow.

    Args:
        line: Input value used by this helper.

    Returns:
        None: Performs actions without returning a value.

    Side Effects:
        No side effects beyond local calculations.
    """
    if not DEBUG_LOG_ENABLED or not DEBUG_TARGETING:
        return
    try:
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        ts = "unknown-time"
    try:
        path = _debug_log_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {line}\n")
    except Exception:
        pass


# Reset the debug log at startup so each script run has a clean file.
def _reset_debug_log_for_new_session():
    """Reset debug log for the AutoMiner workflow.

    Args:
        None.

    Returns:
        None: Performs actions without returning a value.

    Side Effects:
        Truncates `Logs/AutoMiner.debug.log` and writes a session header line.
    """
    if not DEBUG_LOG_ENABLED or not DEBUG_TARGETING:
        return
    try:
        path = _debug_log_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        # Open in write mode to clear old loop history from previous runs.
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"[{ts}] [RUN] Debug log reset for new AutoMiner session.\n")
    except Exception:
        # Logging is best-effort and should never stop script startup.
        pass


# Emit a diagnostic message to sysmsg + in-memory log + optional file log.
def _diag_msg(msg, hue=DIAG_HUE):
    """Diag msg for the AutoMiner workflow.

    Args:
        msg: Input value used by this helper.
        hue: Input value used by this helper.

    Returns:
        None: Performs actions without returning a value.

    Side Effects:
        Interacts with the TazUO client through API calls.
    """
    # Startup can occur before all UI/message channels are ready, so each
    # diagnostic sink is wrapped independently to avoid hard startup failure.
    try:
        API.SysMsg(msg, hue)
    except Exception:
        pass
    try:
        _append_log(msg)
    except Exception:
        pass
    try:
        _write_debug_log(msg)
    except Exception:
        pass


# Standardized phase-tagged diagnostic wrapper.
def _diag_emit(msg, phase="RUN", hue=None, debug_only=False):
    """Diag emit for the AutoMiner workflow.

    Args:
        msg: Input value used by this helper.
        phase: Input value used by this helper.
        hue: Input value used by this helper.
        debug_only: Input value used by this helper.

    Returns:
        None: Performs actions without returning a value.

    Side Effects:
        No side effects beyond local calculations.
    """
    if debug_only and not DEBUG_TARGETING:
        return
    p = str(phase or "RUN").upper()
    base = DIAG_PHASE_HUES.get(p, DIAG_HUE)
    effective_hue = int(hue if hue is not None else base)
    _diag_msg(f"[{p}] {msg}", effective_hue)


def _diag_info(msg, phase="RUN"):
    """Diag info for the AutoMiner workflow.

    Args:
        msg: Input value used by this helper.
        phase: Input value used by this helper.

    Returns:
        None: Performs actions without returning a value.

    Side Effects:
        No side effects beyond local calculations.
    """
    _diag_emit(msg, phase=phase)


def _diag_warn(msg, phase="RUN"):
    """Diag warn for the AutoMiner workflow.

    Args:
        msg: Input value used by this helper.
        phase: Input value used by this helper.

    Returns:
        None: Performs actions without returning a value.

    Side Effects:
        No side effects beyond local calculations.
    """
    _diag_emit(msg, phase=phase, hue=53)


def _diag_error(msg, phase="RUN"):
    """Diag error for the AutoMiner workflow.

    Args:
        msg: Input value used by this helper.
        phase: Input value used by this helper.

    Returns:
        None: Performs actions without returning a value.

    Side Effects:
        No side effects beyond local calculations.
    """
    _diag_emit(msg, phase=phase, hue=33)


def _diag_debug(msg, phase="TARGET", hue=None):
    """Diag debug for the AutoMiner workflow.

    Args:
        msg: Input value used by this helper.
        phase: Input value used by this helper.
        hue: Input value used by this helper.

    Returns:
        None: Performs actions without returning a value.

    Side Effects:
        No side effects beyond local calculations.
    """
    _diag_emit(msg, phase=phase, hue=hue, debug_only=True)


def _startup_error_log_path():
    """Resolve the startup error log path for early-launch failures.

    Args:
        None.

    Returns:
        str: Full path to the startup error log file.

    Side Effects:
        No side effects beyond local calculations.
    """
    try:
        base = os.path.dirname(__file__)
    except Exception:
        base = os.getcwd()
    if os.path.basename(base).lower() in ("resources", "utilities", "skills", "scripts"):
        base = os.path.dirname(base)
    logs_dir = os.path.join(base, "Logs")
    return os.path.join(logs_dir, "AutoMiner.startup.log")


def _report_startup_exception(startup_step, ex):
    """Report startup exceptions so script-manager failures are not silent.

    Args:
        startup_step: Human-readable startup step that failed.
        ex: Exception instance raised by the failed startup step.

    Returns:
        None: Emits visible messages and writes a startup log entry.

    Side Effects:
        Sends system messages and appends a traceback to disk.
    """
    step_text = str(startup_step or "unknown startup step")
    err_text = str(ex) if ex is not None else "unknown error"
    try:
        API.SysMsg(f"[AutoMiner][STARTUP] Failed at: {step_text}", 33)
        API.SysMsg(f"[AutoMiner][STARTUP] {err_text}", 33)
    except Exception:
        pass

    try:
        tb_text = traceback.format_exc()
    except Exception:
        tb_text = "traceback unavailable"

    try:
        path = _startup_error_log_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] Startup step: {step_text}\n")
            f.write(f"[{ts}] Error: {err_text}\n")
            f.write(tb_text + "\n")
            f.write("-" * 80 + "\n")
    except Exception:
        # Startup diagnostics should never create a second crash path.
        pass


def _write_startup_trace(step_text):
    """Write startup progress breadcrumbs to disk for silent-launch debugging.

    Args:
        step_text: Human-readable startup stage name.

    Returns:
        None: Appends one timestamped line to the startup log.

    Side Effects:
        Writes to `Logs/AutoMiner.startup.log`.
    """
    try:
        path = _startup_error_log_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] STEP {str(step_text or 'unknown')}\n")
    except Exception:
        pass


def _reset_startup_log_for_new_session():
    """Reset startup log for the AutoMiner workflow.

    Args:
        None.

    Returns:
        None: Performs actions without returning a value.

    Side Effects:
        Truncates `Logs/AutoMiner.startup.log` and writes a session header line.
    """
    try:
        path = _startup_error_log_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        # Clear old startup traces so the file does not grow forever.
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"[{ts}] STEP Startup log reset for new AutoMiner session.\n")
    except Exception:
        # Startup diagnostics should never create a second crash path.
        pass


def _diag_target_event(msg):
    """Diag target event for the AutoMiner workflow.

    Args:
        msg: Input value used by this helper.

    Returns:
        None: Performs actions without returning a value.

    Side Effects:
        No side effects beyond local calculations.
    """
    _diag_debug(msg, phase="TARGET")


def _diag_target_journal_hits(journal_texts):
    """Diag target journal hits for the AutoMiner workflow.

    Args:
        journal_texts: Input value used by this helper.

    Returns:
        None: Performs actions without returning a value.

    Side Effects:
        No side effects beyond local calculations.
    """
    if not DEBUG_TARGETING:
        return
    for text in JOURNAL_LOG_TEXTS:
        if _journal_contains(journal_texts, text):
            _diag_target_event(f"Journal: {text}")


def _debug(msg):
    """Debug for the AutoMiner workflow.

    Args:
        msg: Input value used by this helper.

    Returns:
        None: Performs actions without returning a value.

    Side Effects:
        No side effects beyond local calculations.
    """
    _diag_debug(msg, phase="TARGET", hue=HEADMSG_HUE)


def _debug_cache(msg):
    """Debug cache for the AutoMiner workflow.

    Args:
        msg: Input value used by this helper.

    Returns:
        None: Performs actions without returning a value.

    Side Effects:
        No side effects beyond local calculations.
    """
    _diag_debug(msg, phase="CACHE", hue=DEBUG_CACHE_HUE)


# Callback-friendly wait that does not pause on RUNNING state.
def _diag_wait(seconds):
    """Diag wait for the AutoMiner workflow.

    Args:
        seconds: Input value used by this helper.

    Returns:
        None: Performs actions without returning a value.

    Side Effects:
        Interacts with the TazUO client through API calls.
    """
    elapsed = 0.0
    step = 0.1
    while elapsed < seconds:
        API.ProcessCallbacks()
        API.Pause(step)
        elapsed += step


# Chebyshev-style tile distance helper for container diagnostics.
def _tile_distance_to_xy(x, y):
    """Tile distance to xy for the AutoMiner workflow.

    Args:
        x: Input value used by this helper.
        y: Input value used by this helper.

    Returns:
        int | None: Tile distance, or `None` when coordinates cannot be resolved.

    Side Effects:
        No side effects beyond local calculations.
    """
    if x is None or y is None:
        _diag_warn("Container probe: target coordinates are missing.", phase="CONTAINER")
        return None
    try:
        px = int(getattr(API.Player, "X", 0) or 0)
        py = int(getattr(API.Player, "Y", 0) or 0)
        return max(abs(px - int(x)), abs(py - int(y)))
    except Exception as ex:
        _diag_error(f"Container probe: failed to read player position: {ex}", phase="CONTAINER")
        return None


# Snapshot active gump ids across varying object/int representations.
def _gump_ids_snapshot():
    """Gump ids snapshot for the AutoMiner workflow.

    Args:
        None.

    Returns:
        object: Result value produced for the caller.

    Side Effects:
        Interacts with the TazUO client through API calls.
    """
    out = set()
    try:
        all_gumps = API.GetAllGumps() or []
    except Exception:
        all_gumps = []
    for gump in all_gumps:
        try:
            if isinstance(gump, int):
                out.add(int(gump))
                continue
            for attr in ("ServerSerial", "ID", "Id", "GumpID", "GumpId", "Serial"):
                value = getattr(gump, attr, None)
                if value is None:
                    continue
                out.add(int(value))
                break
        except Exception:
            continue
    return sorted(list(out))


# Return structured details for a container/item serial used by diagnostics.
def _container_debug_info(serial):
    """Container debug info for the AutoMiner workflow.

    Args:
        serial: Input value used by this helper.

    Returns:
        object: Result value produced for the caller.

    Side Effects:
        Interacts with the TazUO client through API calls.
    """
    sid = int(serial or 0)
    if sid <= 0:
        return {"ok": False, "reason": "serial_zero"}
    try:
        item = API.FindItem(sid)
    except Exception:
        item = None
    if not item:
        return {"ok": False, "reason": "not_found", "serial": sid}
    name = str(getattr(item, "Name", "") or "")
    x = int(getattr(item, "X", 0) or 0)
    y = int(getattr(item, "Y", 0) or 0)
    z = int(getattr(item, "Z", 0) or 0)
    dist = _tile_distance_to_xy(x, y)
    if dist is None:
        return {"ok": False, "reason": "distance_probe_failed", "serial": sid}
    is_container = bool(getattr(item, "IsContainer", True))
    holder = int(getattr(item, "Container", 0) or 0)
    return {
        "ok": True,
        "serial": sid,
        "name": name,
        "x": x,
        "y": y,
        "z": z,
        "dist": dist,
        "is_container": is_container,
        "holder": holder,
    }


# Return item counts (shallow, recursive) for a container serial.
def _container_item_counts(container_serial):
    """Container item counts for the AutoMiner workflow.

    Args:
        container_serial: Input value used by this helper.

    Returns:
        dict: Probe payload with `ok`, `shallow`, `recursive`, and optional `error`.

    Side Effects:
        Interacts with the TazUO client through API calls.
    """
    sid = int(container_serial or 0)
    if sid <= 0:
        return {
            "ok": False,
            "shallow": None,
            "recursive": None,
            "error": "serial_zero",
        }
    try:
        shallow = len(API.ItemsInContainer(sid, False) or [])
        recursive = len(API.ItemsInContainer(sid, True) or [])
        return {
            "ok": True,
            "shallow": int(shallow),
            "recursive": int(recursive),
            "error": "",
        }
    except Exception as ex:
        return {
            "ok": False,
            "shallow": None,
            "recursive": None,
            "error": str(ex),
        }


# Probe a container via UseObject/context menu and log what the client reports.
def _run_container_diag_for(container_serial, label):
    """Run container diag for for the AutoMiner workflow.

    Args:
        container_serial: Input value used by this helper.
        label: Input value used by this helper.

    Returns:
        None: Performs actions without returning a value.

    Side Effects:
        Interacts with the TazUO client through API calls.
    """
    sid = int(container_serial or 0)
    diag_name = str(label or "ContainerDiag")
    _diag_msg(f"{diag_name}: starting.")
    if sid <= 0:
        _diag_msg(f"{diag_name}: target container is not set.", DEBUG_CACHE_HUE)
        return
    info = _container_debug_info(sid)
    if not info.get("ok", False):
        _diag_msg(f"{diag_name}: target 0x{sid:08X} invalid ({str(info.get('reason', 'unknown'))}).", DEBUG_CACHE_HUE)
        return
    _diag_msg(
        f"{diag_name}: target 0x{sid:08X} name='{str(info.get('name', ''))}' "
        f"dist={int(info.get('dist', 0))} is_container={bool(info.get('is_container', False))} "
        f"holder=0x{int(info.get('holder', 0)):08X}"
    )
    pre_gumps = _gump_ids_snapshot()
    pre_counts = _container_item_counts(sid)
    _diag_msg(f"{diag_name}: pre gumps={pre_gumps}")
    if not pre_counts.get("ok", False):
        _diag_msg(
            f"{diag_name}: pre-count probe failed err={str(pre_counts.get('error', 'unknown'))}",
            DEBUG_CACHE_HUE,
        )
    _diag_msg(
        f"{diag_name}: pre counts shallow={str(pre_counts.get('shallow', 'n/a'))} "
        f"recursive={str(pre_counts.get('recursive', 'n/a'))}"
    )

    for i in range(1, int(CONTAINER_DIAG_USE_ATTEMPTS) + 1):
        try:
            API.UseObject(sid)
            _diag_msg(f"{diag_name}: UseObject attempt {i} sent.")
        except Exception as ex:
            _diag_msg(f"{diag_name}: UseObject attempt {i} exception: {ex}", DEBUG_CACHE_HUE)
        _diag_wait(CONTAINER_DIAG_PAUSE_S)
        gumps = _gump_ids_snapshot()
        post_counts = _container_item_counts(sid)
        _diag_msg(f"{diag_name}: post UseObject {i} gumps={gumps}")
        if not post_counts.get("ok", False):
            _diag_msg(
                f"{diag_name}: post-count probe failed err={str(post_counts.get('error', 'unknown'))}",
                DEBUG_CACHE_HUE,
            )
        _diag_msg(
            f"{diag_name}: post UseObject {i} counts shallow={str(post_counts.get('shallow', 'n/a'))} "
            f"recursive={str(post_counts.get('recursive', 'n/a'))}"
        )

    try:
        API.ContextMenu(sid, 0)
        _diag_msg(f"{diag_name}: ContextMenu open attempt sent.")
    except Exception as ex:
        _diag_msg(f"{diag_name}: ContextMenu exception: {ex}", DEBUG_CACHE_HUE)
    _diag_wait(CONTAINER_DIAG_PAUSE_S)
    cg = _gump_ids_snapshot()
    end_counts = _container_item_counts(sid)
    _diag_msg(f"{diag_name}: post context gumps={cg}")
    if not end_counts.get("ok", False):
        _diag_msg(
            f"{diag_name}: context-count probe failed err={str(end_counts.get('error', 'unknown'))}",
            DEBUG_CACHE_HUE,
        )
    _diag_msg(
        f"{diag_name}: post context counts shallow={str(end_counts.get('shallow', 'n/a'))} "
        f"recursive={str(end_counts.get('recursive', 'n/a'))}"
    )
    _diag_msg(f"{diag_name}: done.")


# Execute a broad diagnostics sweep across config, tools, travel, target cache, and container state.
def _run_all_diagnostics():
    """Run all diagnostics for the AutoMiner workflow.

    Args:
        None.

    Returns:
        None: Performs actions without returning a value.

    Side Effects:
        Interacts with the TazUO client through API calls.
    """
    _diag_info("Starting all-phase diagnostics.", phase="RUN")
    try:
        px = int(getattr(API.Player, "X", 0) or 0)
        py = int(getattr(API.Player, "Y", 0) or 0)
        pz = int(getattr(API.Player, "Z", 0) or 0)
        w = int(getattr(API.Player, "Weight", 0) or 0)
        wmax = int(getattr(API.Player, "WeightMax", 0) or 0)
        _diag_info(f"Player state: pos=({px},{py},{pz}) weight={w}/{wmax}", phase="RUN")
    except Exception as ex:
        _diag_warn(f"Player state probe failed: {ex}", phase="RUN")

    # Config phase
    _diag_info(
        f"Config: runebook=0x{int(RUNBOOK_SERIAL or 0):08X} drop=0x{int(SECURE_CONTAINER_SERIAL or 0):08X}",
        phase="CONFIG",
    )
    _diag_info(
        f"Config: shard={_active_shard_mode_name()} "
        f"travel={'Chiv' if USE_SACRED_JOURNEY else 'Mage'} auto_tooling={bool(USE_TOOL_CRAFTING)}",
        phase="CONFIG",
    )

    # Tooling phase
    pick = API.FindType(PICKAXE_GRAPHIC, API.Backpack)
    sh0 = API.FindType(SHOVEL_GRAPHICS[0], API.Backpack)
    sh1 = API.FindType(SHOVEL_GRAPHICS[1], API.Backpack)
    _diag_info(
        f"Tools: pickaxe={'yes' if pick else 'no'} shovelA={'yes' if sh0 else 'no'} shovelB={'yes' if sh1 else 'no'} "
        f"tinker_count={_count_tinker_tools_in_backpack()} shovel_count={_count_shovels_in_backpack()} ingots={_count_ingots_in_backpack()}",
        phase="TOOL",
    )

    # Travel phase (non-invasive)
    if int(RUNBOOK_SERIAL or 0) <= 0:
        _diag_warn("Travel: runebook not set.", phase="TRAVEL")
    else:
        try:
            rb = API.FindItem(int(RUNBOOK_SERIAL))
            if not rb:
                _diag_warn(f"Travel: runebook 0x{int(RUNBOOK_SERIAL):08X} not found.", phase="TRAVEL")
            else:
                _diag_info(f"Travel: runebook found name='{str(getattr(rb, 'Name', '') or '')}'.", phase="TRAVEL")
        except Exception as ex:
            _diag_warn(f"Travel: runebook probe failed: {ex}", phase="TRAVEL")

    # Target/cache phase
    _diag_info(
        f"Target: center={MINE_CENTER} last_pass={LAST_MINE_PASS_POS} "
        f"cache(no_ore={len(NO_ORE_TILE_CACHE)}, non_mineable={len(NON_MINEABLE_TILE_CACHE)}, "
        f"timeout={len(OSI_TIMEOUT_TILE_COUNTS)})",
        phase="TARGET",
    )

    # Unload/container phase
    _run_container_diag_for(SECURE_CONTAINER_SERIAL, "DropContainerDiag")
    if int(SECURE_CONTAINER_SERIAL or 0) > 0:
        counts = _container_item_counts(SECURE_CONTAINER_SERIAL)
        if not counts.get("ok", False):
            _diag_warn(
                f"Unload: drop container count probe failed err={str(counts.get('error', 'unknown'))}",
                phase="UNLOAD",
            )
        _diag_info(
            f"Unload: drop container counts shallow={str(counts.get('shallow', 'n/a'))} "
            f"recursive={str(counts.get('recursive', 'n/a'))}",
            phase="UNLOAD",
        )

    _diag_info("All-phase diagnostics complete.", phase="RUN")


# Pull recent journal text entries into a simple list of strings.
def _get_recent_journal_texts(seconds):
    """Get recent journal texts for the AutoMiner workflow.

    Args:
        seconds: Input value used by this helper.

    Returns:
        dict: Probe payload with `ok`, `texts`, and optional `error`.

    Side Effects:
        Interacts with the TazUO client through API calls.
    """
    try:
        entries = API.GetJournalEntries(seconds) or []
    except Exception as ex:
        return {
            "ok": False,
            "texts": [],
            "error": str(ex),
        }
    texts = []
    for entry in entries:
        text = getattr(entry, "Text", "")
        if text:
            texts.append(text)
    return {
        "ok": True,
        "texts": texts,
        "error": "",
    }


# Substring match helper for journal text arrays.
def _journal_contains(texts, needle):
    """Journal contains for the AutoMiner workflow.

    Args:
        texts: Input value used by this helper.
        needle: Input value used by this helper.

    Returns:
        object: Result value produced for the caller.

    Side Effects:
        No side effects beyond local calculations.
    """
    for text in texts:
        if needle in text:
            return True
    return False


# Any-match helper across multiple needles and journal entries.
def _journal_contains_any(texts, needles):
    """Journal contains any for the AutoMiner workflow.

    Args:
        texts: Input value used by this helper.
        needles: Input value used by this helper.

    Returns:
        object: Result value produced for the caller.

    Side Effects:
        No side effects beyond local calculations.
    """
    for text in texts:
        for needle in needles:
            if needle in text:
                return True
    return False


# Wait for mining-result journal output up to timeout.
def _wait_for_mining_journal(timeout_s):
    """Wait for mining journal for the AutoMiner workflow.

    Args:
        timeout_s: Input value used by this helper.

    Returns:
        dict: Probe payload with `ok`, `texts`, and terminal status metadata.

    Side Effects:
        Interacts with the TazUO client through API calls.
    """
    elapsed = 0.0
    step = 0.2
    while elapsed < timeout_s:
        _pause_if_needed()
        API.ProcessCallbacks()
        API.Pause(step)
        elapsed += step
        journal_probe = _get_recent_journal_texts(timeout_s)
        if not journal_probe.get("ok", False):
            journal_probe["result_text_seen"] = False
            journal_probe["timed_out"] = False
            return journal_probe
        texts = journal_probe.get("texts", [])
        if texts and _journal_contains_any(texts, MINING_RESULT_TEXTS):
            journal_probe["result_text_seen"] = True
            journal_probe["timed_out"] = False
            return journal_probe
    final_probe = _get_recent_journal_texts(timeout_s)
    if not final_probe.get("ok", False):
        final_probe["result_text_seen"] = False
        final_probe["timed_out"] = True
        return final_probe
    final_texts = final_probe.get("texts", [])
    final_probe["result_text_seen"] = bool(final_texts and _journal_contains_any(final_texts, MINING_RESULT_TEXTS))
    final_probe["timed_out"] = True
    return final_probe


# Resolve or create the default directory used for log exports.
def _get_log_export_dir():
    """Get log export dir for the AutoMiner workflow.

    Args:
        None.

    Returns:
        object: Result value produced for the caller.

    Side Effects:
        Updates module-level runtime state.
    """
    global LOG_EXPORT_BASE
    if LOG_EXPORT_BASE:
        return LOG_EXPORT_BASE
    try:
        base = os.path.dirname(__file__)
    except Exception:
        base = os.getcwd()
    if os.path.basename(base).lower() in ("resources", "utilities", "skills", "scripts"):
        base = os.path.dirname(base)
    LOG_EXPORT_BASE = os.path.join(base, "Logs")
    return LOG_EXPORT_BASE


# Load persisted log export settings.
def _load_log_config():
    """Load persisted debug-log export settings.

    Args:
        None.

    Returns:
        None: Updates the module-level export directory when available.

    Side Effects:
        Reads persisted settings and updates `LOG_EXPORT_BASE`.
    """
    global LOG_EXPORT_BASE

    raw = API.GetPersistentVar(LOG_DATA_KEY, "", API.PersistentVar.Char)
    if not raw:
        return

    parse_result = _parse_persisted_dict(raw, "AutoMiner log")
    if not parse_result.get("ok", False):
        _diag_warn(
            "AutoMiner log config defaults applied reason={0}".format(
                str(parse_result.get("error", "unknown"))
            ),
            phase="CONFIG",
        )
        return
    data = parse_result.get("data", {})
    path = str(data.get("export_path", "")).strip()
    if path:
        LOG_EXPORT_BASE = path

# Persist log export settings.
def _save_log_config():
    """Save log config for the AutoMiner workflow.

    Args:
        None.

    Returns:
        None: Performs actions without returning a value.

    Side Effects:
        Interacts with the TazUO client through API calls.
    """
    data = {"export_path": LOG_EXPORT_BASE or ""}
    API.SavePersistentVar(LOG_DATA_KEY, json.dumps(data), API.PersistentVar.Char)


# Export the in-memory debug log buffer to a text file.
def _export_log_to_file():
    """Export log to file for the AutoMiner workflow.

    Args:
        None.

    Returns:
        None: Performs actions without returning a value.

    Side Effects:
        Updates module-level runtime state.
    """
    export_dir = _get_log_export_dir()
    if LOG_PATH_TEXTBOX and LOG_PATH_TEXTBOX.Text.strip():
        export_dir = LOG_PATH_TEXTBOX.Text.strip()
        global LOG_EXPORT_BASE
        LOG_EXPORT_BASE = export_dir
        _save_log_config()
    path = ""
    try:
        os.makedirs(export_dir, exist_ok=True)
        filename = "AutoMinerDebug.txt"
        path = os.path.join(export_dir, filename)
        with open(path, "w", encoding="utf-8") as f:
            f.write(LOG_TEXT)
        _diag_info(f"Saved: {filename}")
    except Exception as ex:
        _diag_error(
            f"Failed to export debug log path='{path or export_dir}': {ex}",
            phase="RUN",
        )


# Open or refresh the debug log gump.
def _open_log_gump():
    """Open log gump for the AutoMiner workflow.

    Args:
        None.

    Returns:
        None: Performs actions without returning a value.

    Side Effects:
        No side effects beyond local calculations.
    """
    _update_log_gump()


# Build and show the floating debug log gump.
def _update_log_gump():
    """Update log gump for the AutoMiner workflow.

    Args:
        None.

    Returns:
        None: Performs actions without returning a value.

    Side Effects:
        Updates module-level runtime state.
        Interacts with the TazUO client through API calls.
    """
    global LOG_GUMP, LOG_PATH_TEXTBOX
    if LOG_GUMP:
        LOG_GUMP.Dispose()
        LOG_GUMP = None

    g = API.CreateGump(True, True, False)
    g.SetRect(350, 140, 360, 420)
    bg = API.CreateGumpColorBox(0.7, "#1B1B1B")
    bg.SetRect(0, 0, 360, 420)
    g.Add(bg)

    title = API.CreateGumpTTFLabel("AutoMiner Debug Log", 14, "#FFFFFF", "alagard", "center", 360)
    title.SetPos(0, 6)
    g.Add(title)

    path_label = API.CreateGumpTTFLabel("Save Path:", 12, "#FFFFFF", "alagard", "left", 120)
    path_label.SetPos(10, 32)
    g.Add(path_label)
    path_box = API.CreateGumpTextBox(LOG_EXPORT_BASE or "", 230, 18, False)
    path_box.SetPos(90, 30)
    g.Add(path_box)
    LOG_PATH_TEXTBOX = path_box

    exp = API.CreateSimpleButton("Export", 70, 20)
    exp.SetPos(275, 52)
    g.Add(exp)
    API.AddControlOnClick(exp, _export_log_to_file)

    scroll = API.CreateGumpScrollArea(10, 76, 340, 330)
    g.Add(scroll)
    y = 0
    lines = LOG_LINES or ["(log empty)"]
    for line in lines:
        label = API.CreateGumpTTFLabel(line, 12, "#FFFFFF", "alagard", "left", 330)
        label.SetRect(0, y, 330, 16)
        scroll.Add(label)
        y += 18

    API.AddGump(g)
    LOG_GUMP = g

def _reset_mine_cache_if_moved():
    # Clear per-spot caches when the player moves.
    """Reset mine cache if moved for the AutoMiner workflow.

    Args:
        None.

    Returns:
        None: Performs actions without returning a value.

    Side Effects:
        Updates module-level runtime state.
    """
    global LAST_PLAYER_POS, NO_ORE_TILE_CACHE, NON_MINEABLE_TILE_CACHE, OSI_TIMEOUT_TILE_COUNTS
    pos = (int(API.Player.X), int(API.Player.Y), int(API.Player.Z))
    if LAST_PLAYER_POS is None:
        LAST_PLAYER_POS = pos
        return
    if pos != LAST_PLAYER_POS:
        NO_ORE_TILE_CACHE.clear()
        NON_MINEABLE_TILE_CACHE.clear()
        OSI_TIMEOUT_TILE_COUNTS.clear()
        LAST_PLAYER_POS = pos

def _reset_mine_cache():
    # Force-clear per-spot caches.
    """Reset mine cache for the AutoMiner workflow.

    Args:
        None.

    Returns:
        None: Performs actions without returning a value.

    Side Effects:
        Updates module-level runtime state.
    """
    global LAST_PLAYER_POS, NO_ORE_TILE_CACHE, NON_MINEABLE_TILE_CACHE, LAST_MINE_PASS_POS, MINE_CENTER, OSI_TIMEOUT_TILE_COUNTS
    NO_ORE_TILE_CACHE.clear()
    NON_MINEABLE_TILE_CACHE.clear()
    OSI_TIMEOUT_TILE_COUNTS.clear()
    LAST_PLAYER_POS = (int(API.Player.X), int(API.Player.Y), int(API.Player.Z))
    LAST_MINE_PASS_POS = None
    MINE_CENTER = None


# Track control references so callbacks stay alive.
def _add_gump_control(control, on_click=None):
    """Add gump control for the AutoMiner workflow.

    Args:
        control: Input value used by this helper.
        on_click: Input value used by this helper.

    Returns:
        None: Performs actions without returning a value.

    Side Effects:
        Interacts with the TazUO client through API calls.
    """
    CONTROL_CONTROLS.append(control)
    if on_click:
        API.AddControlOnClick(control, on_click)


# Add a standard label to the control gump.
def _add_control_label(g, text, x, y, width=160):
    """Add control label for the AutoMiner workflow.

    Args:
        g: Input value used by this helper.
        text: Input value used by this helper.
        x: Input value used by this helper.
        y: Input value used by this helper.
        width: Input value used by this helper.

    Returns:
        object: Result value produced for the caller.

    Side Effects:
        Interacts with the TazUO client through API calls.
    """
    label = API.CreateGumpTTFLabel(text, 12, "#FFFFFF", "alagard", "left", width)
    label.SetPos(x, y)
    g.Add(label)
    return label


# Add a clickable button to the control gump.
def _add_control_button(g, text, x, y, w, h, on_click):
    """Add control button for the AutoMiner workflow.

    Args:
        g: Input value used by this helper.
        text: Input value used by this helper.
        x: Input value used by this helper.
        y: Input value used by this helper.
        w: Input value used by this helper.
        h: Input value used by this helper.
        on_click: Input value used by this helper.

    Returns:
        object: Result value produced for the caller.

    Side Effects:
        Interacts with the TazUO client through API calls.
    """
    btn = API.CreateSimpleButton(text, w, h)
    btn.SetPos(x, y)
    g.Add(btn)
    _add_gump_control(btn, on_click)
    return btn


# Add a checkbox row entry to the control gump.
def _add_control_checkbox(g, text, x, y, value, on_click):
    """Add control checkbox for the AutoMiner workflow.

    Args:
        g: Input value used by this helper.
        text: Input value used by this helper.
        x: Input value used by this helper.
        y: Input value used by this helper.
        value: Input value used by this helper.
        on_click: Input value used by this helper.

    Returns:
        object: Result value produced for the caller.

    Side Effects:
        Interacts with the TazUO client through API calls.
    """
    cb = API.CreateGumpCheckbox(text, 996, value)
    cb.SetPos(x, y)
    g.Add(cb)
    _add_gump_control(cb, on_click)
    return cb


# Render shard mode row.
def _add_shard_row(g):
    """Add shard row for the AutoMiner workflow.

    Args:
        g: Input value used by this helper.

    Returns:
        None: Performs actions without returning a value.

    Side Effects:
        Interacts with the TazUO client through API calls.
    """
    _add_control_label(g, "Shard Selection:", 21, 50)
    shard_idx = 1 if USE_UOALIVE_SHARD else 0
    shard_dd = API.CreateDropDown(145, list(SHARD_OPTIONS), shard_idx)
    shard_dd.SetPos(150, 48)
    g.Add(shard_dd)
    _add_gump_control(shard_dd)
    shard_dd.OnDropDownOptionSelected(_set_shard_from_dropdown)


# Render toggles row.
def _add_option_rows(g):
    """Add option rows for the AutoMiner workflow.

    Args:
        g: Input value used by this helper.

    Returns:
        None: Performs actions without returning a value.

    Side Effects:
        No side effects beyond local calculations.
    """
    _add_control_checkbox(g, "Use Fire Beetle", 20, 77, USE_FIRE_BEETLE_SMELT, _toggle_fire_beetle)
    _add_control_checkbox(g, "Auto Tooling", 20, 101, USE_TOOL_CRAFTING, _toggle_tool_crafting)


# Render travel mode row.
def _add_travel_row(g):
    """Add travel row for the AutoMiner workflow.

    Args:
        g: Input value used by this helper.

    Returns:
        None: Performs actions without returning a value.

    Side Effects:
        No side effects beyond local calculations.
    """
    travel_mode = "Chiv" if USE_SACRED_JOURNEY else "Mage"
    _add_control_label(g, f"Travel: {travel_mode}", 20, 130)
    _add_control_button(g, "Chiv", 190, 128, 50, 18, _set_travel_chiv)
    _add_control_button(g, "Mage", 245, 128, 50, 18, _set_travel_mage)


# Render runebook set/unset row.
def _add_runebook_row(g):
    """Add runebook row for the AutoMiner workflow.

    Args:
        g: Input value used by this helper.

    Returns:
        None: Performs actions without returning a value.

    Side Effects:
        No side effects beyond local calculations.
    """
    runebook_status = "Set" if RUNBOOK_SERIAL else "Unset"
    _add_control_label(g, f"Runebook: {runebook_status}", 20, 154)
    _add_control_button(g, "Set", 190, 152, 50, 18, _set_runebook)
    _add_control_button(g, "Unset", 245, 152, 50, 18, _unset_runebook)


# Render drop container set/unset row.
def _add_drop_container_row(g):
    """Add drop container row for the AutoMiner workflow.

    Args:
        g: Input value used by this helper.

    Returns:
        None: Performs actions without returning a value.

    Side Effects:
        No side effects beyond local calculations.
    """
    secure_status = "Set" if SECURE_CONTAINER_SERIAL else "Unset"
    _add_control_label(g, f"Drop Container: {secure_status}", 20, 180)
    _add_control_button(g, "Set", 190, 178, 50, 18, _set_secure_container)
    _add_control_button(g, "Unset", 245, 178, 50, 18, _unset_secure_container)


# Render debug toggle row.
def _add_debug_row(g):
    """Add debug row for the AutoMiner workflow.

    Args:
        g: Input value used by this helper.

    Returns:
        None: Performs actions without returning a value.

    Side Effects:
        No side effects beyond local calculations.
    """
    debug_status = "On" if DEBUG_TARGETING else "Off"
    _add_control_label(g, f"Debug: {debug_status}", 20, 204)
    _add_control_button(g, "On", 190, 202, 50, 18, _set_debug_on)
    _add_control_button(g, "Off", 245, 202, 50, 18, _set_debug_off)


# Render centered start/pause action row.
def _add_action_row(g):
    """Add action row for the AutoMiner workflow.

    Args:
        g: Input value used by this helper.

    Returns:
        object: Result value produced for the caller.

    Side Effects:
        No side effects beyond local calculations.
    """
    return _add_control_button(g, "Start", 110, 226, 100, 20, _toggle_running)


def _create_control_gump():
    # Build the in-game gump for enabling/disabling the script.
    """Create control gump for the AutoMiner workflow.

    Args:
        None.

    Returns:
        None: Performs actions without returning a value.

    Side Effects:
        Updates module-level runtime state.
        Interacts with the TazUO client through API calls.
    """
    global CONTROL_GUMP, CONTROL_BUTTON, CONTROL_CONTROLS
    if CONTROL_GUMP:
        return
    panel_w = 320
    panel_h = 270
    g = API.CreateGump(True, True, False)
    g.SetRect(100, 100, panel_w, panel_h)
    if CUSTOM_GUMP:
        bg = API.CreateGumpPic(62189, 0, 0)
    else:
        bg = API.CreateGumpColorBox(0.7, "#1B1B1B")
        bg.SetRect(0, 0, panel_w, panel_h)
    g.Add(bg)

    label = API.CreateGumpTTFLabel("Recall Miner Control Panel", 16, "#FFFFFF", "alagard", "center", panel_w)
    label.SetPos(0, 18)
    g.Add(label)

    _add_shard_row(g)
    _add_option_rows(g)
    _add_travel_row(g)
    _add_runebook_row(g)
    _add_drop_container_row(g)
    _add_debug_row(g)
    CONTROL_BUTTON = _add_action_row(g)

    API.AddGump(g)
    CONTROL_GUMP = g
    _update_control_gump()

def _next_drop_offset():
    # Get next offset for round-robin drops.
    """Next drop offset for the AutoMiner workflow.

    Args:
        None.

    Returns:
        object: Result value produced for the caller.

    Side Effects:
        Updates module-level runtime state.
    """
    global DROP_OFFSET_INDEX
    if not DROP_OFFSETS:
        return (0, 1)
    dx, dy = DROP_OFFSETS[DROP_OFFSET_INDEX % len(DROP_OFFSETS)]
    DROP_OFFSET_INDEX = (DROP_OFFSET_INDEX + 1) % len(DROP_OFFSETS)
    return (dx, dy)

def _drop_ore_until_weight(target_weight):
    # Drop ore by priority until under the target weight.
    """Drop ore until weight for the AutoMiner workflow.

    Args:
        target_weight: Input value used by this helper.

    Returns:
        None: Performs actions without returning a value.

    Side Effects:
        Interacts with the TazUO client through API calls.
    """
    _diag_info("Dropping ore to reduce weight.")
    while API.Player.Weight > target_weight:
        _pause_if_needed()
        item = _find_drop_item()
        if not item:
            _diag_warn("Weight mitigation: no ore stack available to drop.", phase="WEIGHT")
            break

        dropped = False
        item_serial = int(getattr(item, "Serial", 0) or 0)
        item_graphic = int(getattr(item, "Graphic", 0) or 0)
        for attempt in range(1, 4):
            API.ClearJournal()
            before_amt = int(getattr(item, "Amount", 0) or 0)
            if before_amt <= 0:
                _diag_warn("Weight mitigation: ore stack amount is zero before drop.", phase="WEIGHT")
                break
            dx, dy = _next_drop_offset()
            API.QueueMoveItemOffset(item_serial, 1, dx, dy, 0)
            _sleep(1.0)

            if API.InJournal("You must wait to perform another action", True):
                _diag_warn(
                    "Weight mitigation: drop blocked by action throttle (attempt {0}).".format(attempt),
                    phase="WEIGHT",
                )
                _sleep(1.2)
                continue

            refreshed = API.FindItem(item_serial)
            after_amt = int(getattr(refreshed, "Amount", 0) or 0) if refreshed else 0
            if after_amt < before_amt:
                dropped = True
                break

            _diag_warn(
                "Weight mitigation: queued drop did not move ore serial=0x{0:08X} graphic=0x{1:04X} attempt={2}.".format(
                    item_serial, item_graphic, attempt
                ),
                phase="WEIGHT",
            )

        if not dropped:
            _diag_error(
                "Weight mitigation failed for ore serial=0x{0:08X}. Local drop fallback disabled; will escalate recall path.".format(
                    item_serial
                ),
                phase="WEIGHT",
            )
            break


# Determine whether weight/journal state indicates immediate overload handling.
def _get_overweight_triggers():
    """Get overweight triggers for the AutoMiner workflow.

    Args:
        None.

    Returns:
        object: Result value produced for the caller.

    Side Effects:
        Interacts with the TazUO client through API calls.
    """
    overweight_trigger = API.Player.Weight >= (API.Player.WeightMax - 50) or API.InJournalAny(OVERWEIGHT_TEXTS, True)
    encumbered_trigger = API.InJournalAny(ENCUMBERED_TEXTS, True)
    return overweight_trigger, encumbered_trigger


# Attempt local mitigation before recalling (drop excess ore first).
def _apply_local_weight_mitigation(overweight_trigger, encumbered_trigger):
    """Apply local weight mitigation for the AutoMiner workflow.

    Args:
        overweight_trigger: Input value used by this helper.
        encumbered_trigger: Input value used by this helper.

    Returns:
        None: Performs actions without returning a value.

    Side Effects:
        No side effects beyond local calculations.
    """
    if overweight_trigger:
        _diag_info("Overweight detected.")
        if API.Player.Weight > API.Player.WeightMax:
            _diag_info("Overweight: dropping ore before recall.")
            _drop_ore_until_weight(API.Player.WeightMax - 50)
    if encumbered_trigger:
        _diag_info("Encumbered: dropping ore.")
        _drop_ore_until_weight(API.Player.WeightMax - 50)


# Escalate to smelt and/or home recall if local mitigation was insufficient.
def _escalate_weight_via_home_recall():
    """Escalate weight via home recall for the AutoMiner workflow.

    Args:
        None.

    Returns:
        None: Performs actions without returning a value.

    Side Effects:
        No side effects beyond local calculations.
    """
    if API.Player.Weight < (API.Player.WeightMax - 50):
        return
    if USE_FIRE_BEETLE_SMELT:
        _diag_info("Overweight: smelting ore.")
        _smelt_ore()
    if API.Player.Weight >= (API.Player.WeightMax - 50):
        _diag_info("Overweight: recall to unload.")
        if _recall_home_and_unload():
            _advance_mining_spot()
            _sleep(1.0)
            _recall_mining_spot()


# Full overweight handler entry point.
def _handle_overweight():
    """Handle overweight for the AutoMiner workflow.

    Args:
        None.

    Returns:
        object: Result value produced for the caller.

    Side Effects:
        No side effects beyond local calculations.
    """
    overweight_trigger, encumbered_trigger = _get_overweight_triggers()
    if not overweight_trigger and not encumbered_trigger:
        return False

    _apply_local_weight_mitigation(overweight_trigger, encumbered_trigger)
    _escalate_weight_via_home_recall()
    return True

def _find_fire_beetle():
    # Find a nearby fire beetle to use as a portable smelter.
    """Find fire beetle for the AutoMiner workflow.

    Args:
        None.

    Returns:
        object: Result value produced for the caller.

    Side Effects:
        Interacts with the TazUO client through API calls.
    """
    mobs = API.GetAllMobiles(graphic=FIRE_BEETLE_GRAPHIC, distance=SMELTER_RANGE) or []
    if not mobs:
        return None
    return mobs[0]


# Resolve nearby smelting context (fire beetle only).
def _discover_smelt_context():
    """Discover smelt context for the AutoMiner workflow.

    Args:
        None.

    Returns:
        object: Result value produced for the caller.

    Side Effects:
        No side effects beyond local calculations.
    """
    if not USE_FIRE_BEETLE_SMELT:
        return None
    beetle = _find_fire_beetle()
    while not beetle:
        _pause_if_needed()
        _diag_info("No fire beetle nearby. Move closer...")
        _sleep(2.0)
        beetle = _find_fire_beetle()
    return {
        "beetle": beetle,
    }


# Request a target cursor for ore use using the primary serial flow only.
def _request_ore_target_cursor(ore):
    """Request a target cursor after using an ore stack by serial.

    Args:
        ore: Ore item instance being smelted.

    Returns:
        bool: `True` when a target cursor is available, else `False`.

    Side Effects:
        Uses an item, waits for targeting state, and emits diagnostics on failures.
    """
    ore_serial = int(getattr(ore, "Serial", 0) or 0)
    ore_graphic = int(getattr(ore, "Graphic", 0) or 0)
    if ore_serial <= 0:
        _diag_error("Smelt: ore serial is invalid; cannot request target cursor.", phase="SMELT")
        return False

    API.ClearJournal()
    try:
        API.UseObject(ore_serial)
    except Exception as ex:
        _diag_error(
            "Smelt: failed to use ore serial=0x{0:08X} graphic=0x{1:04X}; err={2}".format(
                ore_serial, ore_graphic, str(ex)
            ),
            phase="SMELT",
        )
        return False
    _sleep(0.2)
    if _wait_for_target(2):
        return True
    _diag_warn(
        "Smelt: no target cursor after ore use serial=0x{0:08X} graphic=0x{1:04X}.".format(
            ore_serial, ore_graphic
        ),
        phase="SMELT",
    )
    return False


# Target the active fire beetle smelter.
def _target_smelter(context):
    """Target smelter for the AutoMiner workflow.

    Args:
        context: Input value used by this helper.

    Returns:
        object: Result value produced for the caller.

    Side Effects:
        Interacts with the TazUO client through API calls.
    """
    beetle = context.get("beetle") if context else None
    if not beetle:
        return False
    serial = int(getattr(beetle, "Serial", 0) or 0)
    if serial <= 0:
        return False
    API.Target(serial)
    return True


# Handle the ore-first targeting flow (ore -> smelter target).
def _attempt_smelt_ore_to_smelter(context):
    """Attempt smelt ore to smelter for the AutoMiner workflow.

    Args:
        context: Input value used by this helper.

    Returns:
        bool: `True` when the target flow completes, else `False`.

    Side Effects:
        Interacts with the TazUO client through API calls and emits diagnostics.
    """
    for _ in range(3):
        if not _target_smelter(context):
            _diag_error("Smelt: fire beetle target unavailable.", phase="SMELT")
            return False
        _sleep(0.2)
        if not API.HasTarget():
            break
    if API.HasTarget():
        API.CancelTarget()
        _diag_warn("Smelt: target cursor remained active after smelter targeting.", phase="SMELT")
        return False
    _sleep(0.8)
    if DEBUG_SMELT and API.InJournalAny(SMELT_SUCCESS_TEXTS, True):
        _diag_info("Smelt: success message detected.")
    return True


# Smelt one ore stack using the primary ore-first target flow.
def _smelt_single_ore(ore, context):
    """Smelt single ore for the AutoMiner workflow.

    Args:
        ore: Input value used by this helper.
        context: Input value used by this helper.

    Returns:
        bool: `True` when smelting actions were sent, else `False`.

    Side Effects:
        Sends smelting actions and emits diagnostics on failures.
    """
    ore_serial = int(getattr(ore, "Serial", 0) or 0)
    ore_graphic = int(getattr(ore, "Graphic", 0) or 0)
    if not _request_ore_target_cursor(ore):
        _diag_error(
            "Smelt: stopping ore stack serial=0x{0:08X} graphic=0x{1:04X}; alternate fallback flow is disabled.".format(
                ore_serial, ore_graphic
            ),
            phase="SMELT",
        )
        return False
    return _attempt_smelt_ore_to_smelter(context)


def _smelt_ore():
    # Smelt all eligible ore in the backpack using a nearby fire beetle.
    """Smelt ore for the AutoMiner workflow.

    Args:
        None.

    Returns:
        None: Performs actions without returning a value.

    Side Effects:
        No side effects beyond local calculations.
    """
    if not USE_FIRE_BEETLE_SMELT:
        return
    if DEBUG_SMELT:
        _diag_info("Smelt: starting...")
    context = _discover_smelt_context()
    if not context:
        return
    while True:
        _pause_if_needed()
        ore = _find_ore_in_backpack()
        if not ore:
            if DEBUG_SMELT:
                _diag_info("Smelt: no ore found in backpack.")
            break
        if DEBUG_SMELT:
            _diag_info(f"Smelt ore: 0x{int(ore.Graphic):04X} serial {int(ore.Serial)}")
        if not _smelt_single_ore(ore, context):
            _diag_error("Smelt: stopping smelt pass due to target-flow failure.", phase="SMELT")
            break
        # Smelt cooldown to reduce spam.
        _sleep(1.2)

def _recall_home():
    # Recall to the home rune (button depends on travel mode).
    """Recall home for the AutoMiner workflow.

    Args:
        None.

    Returns:
        object: Result value produced for the caller.

    Side Effects:
        Interacts with the TazUO client through API calls.
    """
    if not RUNBOOK_SERIAL:
        _diag_info("No runebook set.")
        return False
    for _ in range(3):
        API.ClearJournal()
        API.Pause(0.3)
        API.UseObject(RUNBOOK_SERIAL)
        if API.WaitForGump(0x59, 3):
            _sleep(1.5)
            API.ReplyGump(int(HOME_RECALL_BUTTON), 0x59)
            return True
        _sleep(0.6)
    _diag_info("Runebook gump not found.")
    return False

def _recall_to_button(button_id):
    # Recall using a specific runebook button id.
    """Recall to button for the AutoMiner workflow.

    Args:
        button_id: Input value used by this helper.

    Returns:
        object: Result value produced for the caller.

    Side Effects:
        Updates module-level runtime state.
        Interacts with the TazUO client through API calls.
    """
    if not RUNBOOK_SERIAL:
        _diag_info("No runebook set.")
        return False
    for _ in range(3):
        API.ClearJournal()
        API.Pause(0.3)
        API.UseObject(RUNBOOK_SERIAL)
        if API.WaitForGump(0x59, 3):
            _sleep(1.5)
            API.ReplyGump(int(button_id), 0x59)
            _reset_mine_cache()
            _sleep(2.0)
            global LAST_PLAYER_POS, MINE_CENTER
            LAST_PLAYER_POS = (int(API.Player.X), int(API.Player.Y), int(API.Player.Z))
            MINE_CENTER = None
            return True
        _sleep(0.6)
    _diag_info("Runebook gump not found.")
    return False

def _recall_mining_spot():
    # Recall to the current mining rune.
    """Recall mining spot for the AutoMiner workflow.

    Args:
        None.

    Returns:
        object: Result value produced for the caller.

    Side Effects:
        No side effects beyond local calculations.
    """
    if not MINING_RUNES:
        return False
    button_id = MINING_RUNES[CURRENT_MINING_INDEX]
    _diag_info(f"Recalling to mining rune {button_id}.")
    return _recall_to_button(button_id)

def _advance_mining_spot():
    # Advance to the next mining rune in the loop.
    """Advance mining spot for the AutoMiner workflow.

    Args:
        None.

    Returns:
        None: Performs actions without returning a value.

    Side Effects:
        Updates module-level runtime state.
    """
    global CURRENT_MINING_INDEX
    if not MINING_RUNES:
        return
    CURRENT_MINING_INDEX = (CURRENT_MINING_INDEX + 1) % len(MINING_RUNES)

def _recall_home_and_unload():
    # Recall home, unload, and restock.
    """Recall home and unload for the AutoMiner workflow.

    Args:
        None.

    Returns:
        object: Result value produced for the caller.

    Side Effects:
        No side effects beyond local calculations.
    """
    _diag_info("Recalling home to unload.")
    if _recall_home():
        _sleep(5.0)
        _unload_ore_and_ingots()
        return True
    return False

def _move_item_to_container(item, container_serial):
    # Move an item to a container with retry/backoff.
    """Move item to container for the AutoMiner workflow.

    Args:
        item: Input value used by this helper.
        container_serial: Input value used by this helper.

    Returns:
        bool: `True` when the move is confirmed, else `False`.

    Side Effects:
        Interacts with the TazUO client through API calls.
    """
    item_serial = int(getattr(item, "Serial", 0) or 0)
    item_graphic = int(getattr(item, "Graphic", 0) or 0)
    move_amount = int(getattr(item, "Amount", 0) or 0)
    target_serial = int(container_serial or 0)
    if item_serial <= 0 or target_serial <= 0 or move_amount <= 0:
        _diag_error(
            "MoveToContainer: invalid move request serial=0x{0:08X} graphic=0x{1:04X} amount={2} target=0x{3:08X}".format(
                item_serial, item_graphic, move_amount, target_serial
            ),
            phase="UNLOAD",
        )
        return False

    # We verify by re-reading the item state after each move attempt.
    # If the item moved containers or amount dropped, we treat it as success.
    for attempt in range(1, 4):
        API.ClearJournal()
        API.MoveItem(item_serial, target_serial, move_amount)
        _sleep(1.0)
        moved_item = API.FindItem(item_serial)
        moved_item_container = int(getattr(moved_item, "Container", 0) or 0) if moved_item else 0
        moved_item_amount = int(getattr(moved_item, "Amount", 0) or 0) if moved_item else 0
        if moved_item is None or moved_item_container == target_serial or moved_item_amount < move_amount:
            return True
        if API.InJournal("You must wait to perform another action", True):
            _diag_warn(
                "MoveToContainer: throttle on attempt {0} serial=0x{1:08X} target=0x{2:08X}".format(
                    attempt, item_serial, target_serial
                ),
                phase="UNLOAD",
            )
            _sleep(1.2)
            continue
        _diag_warn(
            "MoveToContainer: move unconfirmed on attempt {0} serial=0x{1:08X} graphic=0x{2:04X} amount={3} target=0x{4:08X}".format(
                attempt, item_serial, item_graphic, move_amount, target_serial
            ),
            phase="UNLOAD",
        )
    _diag_error(
        "MoveToContainer failed after retries serial=0x{0:08X} graphic=0x{1:04X} amount={2} target=0x{3:08X}".format(
            item_serial, item_graphic, move_amount, target_serial
        ),
        phase="UNLOAD",
    )
    return False

def _drop_blackstone(item):
    # Move blackstone into the drop container.
    """Drop blackstone for the AutoMiner workflow.

    Args:
        item: Input value used by this helper.

    Returns:
        bool: `True` when the blackstone move was confirmed, else `False`.

    Side Effects:
        Interacts with the TazUO client through API calls and emits diagnostics.
    """
    if not SECURE_CONTAINER_SERIAL:
        _diag_error(
            "Unload: blackstone move blocked because drop container is not configured. Ground-drop fallback is disabled.",
            phase="UNLOAD",
        )
        return False
    if not _move_item_to_container(item, SECURE_CONTAINER_SERIAL):
        _diag_error(
            "Unload: blackstone move failed serial=0x{0:08X}.".format(int(getattr(item, "Serial", 0) or 0)),
            phase="UNLOAD",
        )
        return False
    return True

def _target_mine_tile(dx, dy, tile):
    # Target mineable tile relative to player using the tile graphic.
    """Target mine tile for the AutoMiner workflow.

    Args:
        dx: Input value used by this helper.
        dy: Input value used by this helper.
        tile: Input value used by this helper.

    Returns:
        object: Result value produced for the caller.

    Side Effects:
        Interacts with the TazUO client through API calls.
    """
    use_land = int(tile.Graphic) < 0x4000
    for _ in range(5):
        if not API.HasTarget():
            _wait_for_target(0.5)
        if DEBUG_TARGETING:
            _debug(
                f"MineTarget: rel=({dx},{dy}) graphic=0x{int(tile.Graphic):04X} land={use_land} has_target={API.HasTarget()}"
            )
        API.TargetTileRel(dx, dy, int(tile.Graphic))
        _sleep(0.2)
        if DEBUG_TARGETING:
            _debug(f"MineTarget: method=TargetTileRel has_target={API.HasTarget()}")
        if not API.HasTarget():
            return True
    if API.HasTarget():
        API.CancelTarget()
        return False
    return True


def _prepare_tile_attempt(px, py, dx, dy, mine_tools, tool_use_delay_s=0.2):
    # Prepare one tile attempt: tool use, relative offsets, and tile metadata.
    """Prepare tile attempt for the AutoMiner workflow.

    Args:
        px: Input value used by this helper.
        py: Input value used by this helper.
        dx: Input value used by this helper.
        dy: Input value used by this helper.
        mine_tools: Input value used by this helper.
        tool_use_delay_s: Input value used by this helper.

    Returns:
        object: Result value produced for the caller.

    Side Effects:
        Interacts with the TazUO client through API calls.
    """
    tx = px + dx
    ty = py + dy
    _pause_if_needed()
    API.ClearJournal()
    API.UseObject(mine_tools)
    _sleep(tool_use_delay_s)
    curx = int(API.Player.X)
    cury = int(API.Player.Y)
    relx = tx - curx
    rely = ty - cury
    tile = API.GetTile(int(tx), int(ty))
    graphic = None
    if tile:
        graphic = getattr(tile, "Graphic", None)
    tile_is_mineable = tile and graphic in MINEABLE_GRAPHICS
    return TileAttempt(tx, ty, relx, rely, tile, tile_is_mineable)


def _classify_mining_journal(journal_texts):
    # Parse journal output for mining outcomes.
    """Classify mining journal for the AutoMiner workflow.

    Args:
        journal_texts: Input value used by this helper.

    Returns:
        object: Result value produced for the caller.

    Side Effects:
        No side effects beyond local calculations.
    """
    no_ore_hit = _journal_contains_any(journal_texts, NO_ORE_CACHE_TEXTS)
    cannot_see = _journal_contains(journal_texts, "Target cannot be seen.")
    dig_some = _journal_contains(journal_texts, "You dig some")
    fail_skill = _journal_contains(journal_texts, "You loosen some rocks but fail to find any useable ore.")
    cant_mine = _journal_contains(journal_texts, "You can't mine there.")
    return TileJournalResult(no_ore_hit, cannot_see, dig_some, fail_skill, cant_mine)


def _execute_target_for_tile(tile_ctx, counters):
    # Execute primary targeting for one tile and apply timeout/cache effects.
    """Target one tile with the primary targeting method.

    Args:
        tile_ctx: `TileAttempt` metadata for the tile being mined.
        counters: `PassCounters` instance tracking this 3x3 mining pass.

    Returns:
        TileTargetResult: Timeout and method status for this tile attempt.

    Side Effects:
        Sends target calls, updates tile caches, and increments pass counters.
    """
    tx = tile_ctx.tx
    ty = tile_ctx.ty
    relx = tile_ctx.relx
    rely = tile_ctx.rely
    tile = tile_ctx.tile
    tile_is_mineable = tile_ctx.tile_is_mineable

    target_timeout = False
    method_used = "none"

    if not tile_is_mineable:
        method_used = "skip_non_mineable"
        NON_MINEABLE_TILE_CACHE.add((tx, ty))
        if API.HasTarget():
            if DEBUG_TARGETING:
                _debug("MineTarget: non-mineable tile; canceling target.")
            API.CancelTarget()
        return TileTargetResult(target_timeout, method_used)

    if _wait_for_target(5):
        method_used = "TargetTileRel_primary"
        if not _target_mine_tile(relx, rely, tile):
            _diag_info("Mining target failed; canceling cursor.")
            API.CancelTarget()
            method_used = "TargetTileRel_primary_failed"
        return TileTargetResult(target_timeout, method_used)

    target_timeout = True
    method_used = "target_cursor_timeout"
    counters.timeout_count += 1
    if DEBUG_TARGETING:
        _debug("MineTarget: wait_for_target timed out.")
    key = (int(tx), int(ty))
    OSI_TIMEOUT_TILE_COUNTS[key] = OSI_TIMEOUT_TILE_COUNTS.get(key, 0) + 1
    if OSI_TIMEOUT_TILE_COUNTS[key] >= 2:
        NO_ORE_TILE_CACHE.add(key)
        counters.no_ore_count += 1
        if DEBUG_TARGETING:
            _debug_cache(f"MineTarget: cached timeout tile ({tx},{ty}).")
    _sleep(TARGET_TIMEOUT_BACKOFF_S)
    return TileTargetResult(target_timeout, method_used)


def _unload_ore_and_ingots():
    # Unload ores/ingots/gems/blackrock to the drop container.
    """Unload ore and ingots for the AutoMiner workflow.

    Args:
        None.

    Returns:
        None: Performs actions without returning a value.

    Side Effects:
        Interacts with the TazUO client through API calls.
    """
    if not SECURE_CONTAINER_SERIAL:
        _diag_info("No drop container set.")
        return
    _diag_info("Unloading resources to containers.")
    items = API.ItemsInContainer(API.Backpack, True) or []
    _diag_info(f"Unload: {len(items)} items in backpack.")
    for item in items:
        if item.Graphic in BLACKSTONE_GRAPHICS:
            _diag_info(f"Unload: moving blackstone 0x{int(item.Graphic):04X}.")
            if not _drop_blackstone(item):
                _diag_error("Unload: blackstone transfer failed.", phase="UNLOAD")
            continue
        if SECURE_CONTAINER_SERIAL and (item.Graphic in ORE_GRAPHICS or item.Graphic == ORE_GRAPHIC_MIN2 or item.Graphic in INGOT_GRAPHICS or item.Graphic in GEM_GRAPHICS):
            if not _move_item_to_container(item, SECURE_CONTAINER_SERIAL):
                _diag_error(
                    "Unload: item transfer failed serial=0x{0:08X} graphic=0x{1:04X}".format(
                        int(getattr(item, "Serial", 0) or 0),
                        int(getattr(item, "Graphic", 0) or 0),
                    ),
                    phase="UNLOAD",
                )
    _restock_ingots_from_container(22)
    _ensure_min_shovels_on_dropoff()

def _restock_ingots_from_container(target_amount):
    # Restock hue-0 ingots from the drop container.
    """Restock ingots from container for the AutoMiner workflow.

    Args:
        target_amount: Input value used by this helper.

    Returns:
        None: Performs actions without returning a value.

    Side Effects:
        Interacts with the TazUO client through API calls.
    """
    if not SECURE_CONTAINER_SERIAL:
        return
    API.UseObject(SECURE_CONTAINER_SERIAL)
    _sleep(0.5)
    current = _count_ingots_in_backpack()
    if current >= target_amount:
        return
    _diag_info("Restocking ingots from drop container.")
    need = target_amount - current
    items = API.ItemsInContainer(SECURE_CONTAINER_SERIAL, True) or []
    for item in items:
        if item.Graphic not in INGOT_GRAPHICS:
            continue
        if int(item.Hue) != 0:
            continue
        take = min(need, int(item.Amount))
        if take <= 0:
            continue
        for attempt in range(1, 4):
            API.ClearJournal()
            API.MoveItem(item.Serial, API.Backpack, int(take))
            _sleep(1.0)
            if API.InJournal("You must wait to perform another action", True):
                _sleep(1.2)
                continue
            break
        need -= take
        if need <= 0:
            break

def _ensure_min_shovels_on_dropoff():
    # Ensure at least two shovels after dropoff.
    """Ensure min shovels on dropoff for the AutoMiner workflow.

    Args:
        None.

    Returns:
        None: Performs actions without returning a value.

    Side Effects:
        No side effects beyond local calculations.
    """
    if not SECURE_CONTAINER_SERIAL:
        return
    if not USE_TOOL_CRAFTING:
        return
    _diag_info("Ensuring at least two shovels.")
    if _count_tinker_tools_in_backpack() == 0:
        _diag_info("No tinker's tool available to craft shovels.")
        return
    if _count_tinker_tools_in_backpack() == 1:
        if not _craft_tinker_tool():
            _diag_info("Unable to craft a new tinker's tool.")
            return
    count = _count_shovels_in_backpack()
    if count >= 2:
        return
    _restock_ingots_from_container(22)
    attempts = 0
    while _count_shovels_in_backpack() < 2:
        if _count_ingots_in_backpack() < 8:
            _diag_info("Not enough ingots to craft shovels.")
            break
        if _count_tinker_tools_in_backpack() == 0:
            _diag_info("No tinker's tool available to craft shovels.")
            break
        if _count_tinker_tools_in_backpack() == 1:
            if not _craft_tinker_tool():
                _diag_info("Unable to craft a new tinker's tool.")
                break
        if not _craft_shovel():
            attempts += 1
        else:
            attempts = 0
        _sleep(0.5)
        if attempts >= 3:
            _diag_info("Crafting shovels failed repeatedly. Stopping attempt.")
            break


# Run one 3x3 mining pass around the current center tile.
def _mine_adjacent_tiles(mine_tools):
    """Mine adjacent tiles for the AutoMiner workflow.

    Args:
        mine_tools: Input value used by this helper.

    Returns:
        object: Result value produced for the caller.

    Side Effects:
        No side effects beyond local calculations.
    """
    status, px, py = _init_mine_center_or_skip(mine_tools)
    if status != "ok":
        return status
    offsets = [
        (0, 0),
        (0, -1),
        (0, 1),
        (-1, 0),
        (1, 0),
        (-1, -1),
        (-1, 1),
        (1, -1),
        (1, 1),
    ]
    tool_use_delay_s, journal_wait_s = _get_active_mining_timings()
    return _mine_pass_dynamic_timed(
        mine_tools,
        px,
        py,
        offsets,
        tool_use_delay_s,
        journal_wait_s,
    )


# Initialize/validate mine center and early-exit states for this pass.
def _init_mine_center_or_skip(mine_tools):
    """Init mine center or skip for the AutoMiner workflow.

    Args:
        mine_tools: Input value used by this helper.

    Returns:
        object: Result value produced for the caller.

    Side Effects:
        Updates module-level runtime state.
    """
    global MINE_CENTER
    if not mine_tools:
        return "tool_worn", None, None
    if _handle_overweight():
        return "overweight", None, None
    if MINE_CENTER is None:
        MINE_CENTER = (int(API.Player.X), int(API.Player.Y), int(API.Player.Z))
        if DEBUG_TARGETING:
            _debug(f"MineTarget: set center=({MINE_CENTER[0]},{MINE_CENTER[1]},{MINE_CENTER[2]})")
    px, py, pz = MINE_CENTER
    if LAST_MINE_PASS_POS == MINE_CENTER:
        if DEBUG_TARGETING:
            _debug(f"MineTarget: already attempted 3x3 at ({px},{py},{pz}).")
        return "no_ore", None, None
    return "ok", px, py


# Convert pass counters into final action state ("ok" or "no_ore").
def _finalize_pass_result(counters, total_offsets):
    """Finalize pass result for the AutoMiner workflow.

    Args:
        counters: Input value used by this helper.
        total_offsets: Input value used by this helper.

    Returns:
        object: Result value produced for the caller.

    Side Effects:
        Updates module-level runtime state.
    """
    global LAST_MINE_PASS_POS
    if counters.no_ore_count >= total_offsets:
        LAST_MINE_PASS_POS = MINE_CENTER
        _diag_info("No ore here... move.")
        _sleep(3)
        return "no_ore"
    if counters.cannot_see_count >= total_offsets:
        _diag_info("Cannot see mining tiles... moving.")
        _sleep(3)
        return "no_ore"
    if (counters.timeout_count + counters.no_ore_count) >= total_offsets and counters.timeout_count > 0 and not counters.dig_success:
        _diag_info("Mining target timed out... moving.")
        _sleep(3)
        return "no_ore"
    return "ok"


# Skip tiles already known as depleted/non-mineable at this spot.
def _should_skip_tile(tx, ty):
    """Should skip tile for the AutoMiner workflow.

    Args:
        tx: Input value used by this helper.
        ty: Input value used by this helper.

    Returns:
        object: Result value produced for the caller.

    Side Effects:
        No side effects beyond local calculations.
    """
    return (tx, ty) in NO_ORE_TILE_CACHE or (tx, ty) in NON_MINEABLE_TILE_CACHE


# Execute one tile attempt: prepare tool use, target tile, collect journal outcome.
def _attempt_tile(px, py, dx, dy, mine_tools, counters, tool_use_delay_s=0.2, journal_wait_s=MINING_JOURNAL_WAIT_S):
    """Attempt tile for the AutoMiner workflow.

    Args:
        px: Input value used by this helper.
        py: Input value used by this helper.
        dx: Input value used by this helper.
        dy: Input value used by this helper.
        mine_tools: Input value used by this helper.
        counters: Input value used by this helper.
        tool_use_delay_s: Input value used by this helper.
        journal_wait_s: Input value used by this helper.

    Returns:
        object: Result value produced for the caller.

    Side Effects:
        No side effects beyond local calculations.
    """
    attempt = _prepare_tile_attempt(px, py, dx, dy, mine_tools, tool_use_delay_s)
    tx = attempt.tx
    ty = attempt.ty
    relx = attempt.relx
    rely = attempt.rely
    tile = attempt.tile
    tile_is_mineable = attempt.tile_is_mineable
    if DEBUG_TARGETING:
        _debug(f"MineTarget: attempt target=({int(tx)},{int(ty)},{int(API.Player.Z)}) rel=({relx},{rely})")
    if tile and getattr(tile, "Graphic", None) is not None and DEBUG_TARGETING:
        _debug(f"System: MineTarget: tile graphic=0x{int(tile.Graphic):04X} in_list={tile_is_mineable}")
    target_result = _execute_target_for_tile(attempt, counters)
    journal_probe = _wait_for_mining_journal(journal_wait_s)
    journal_ok = bool(journal_probe.get("ok", False))
    journal_texts = list(journal_probe.get("texts", []))
    journal_timed_out = bool(journal_probe.get("timed_out", False))
    journal_result_text_seen = bool(journal_probe.get("result_text_seen", False))
    if not journal_ok:
        _diag_error(
            "Mining journal probe failed for tile ({0},{1}) err={2}".format(
                int(tx), int(ty), str(journal_probe.get("error", "unknown"))
            ),
            phase="TARGET",
        )
    elif journal_timed_out and not journal_result_text_seen:
        _diag_warn(
            "Mining journal timeout without result text for tile ({0},{1}) after {2:.1f}s.".format(
                int(tx), int(ty), float(journal_wait_s)
            ),
            phase="TARGET",
        )
    elif DEBUG_TARGETING:
        journal_result = _classify_mining_journal(journal_texts)
        if journal_result.dig_some:
            outcome = "dig_some"
        elif journal_result.fail_skill:
            outcome = "fail_skill"
        elif journal_result.no_ore_hit:
            outcome = "no_ore"
        elif journal_result.cant_mine:
            outcome = "cant_mine"
        elif journal_result.cannot_see:
            outcome = "cannot_see"
        else:
            outcome = "no_actionable_journal"
        _diag_target_event(
            "MineTargetOutcome: tile=({0},{1}) method={2} timeout={3} outcome={4}".format(
                int(tx),
                int(ty),
                str(getattr(target_result, "method_used", "unknown")),
                str(bool(getattr(target_result, "target_timeout", False))),
                outcome,
            )
        )
    _diag_target_journal_hits(journal_texts)
    return attempt, journal_texts, target_result, journal_ok


# Handle target-timeout bookkeeping without fallback queueing.
def _handle_tile_timeout(attempt, target_result):
    """Handle tile timeout for the AutoMiner workflow.

    Args:
        attempt: Input value used by this helper.
        target_result: Input value used by this helper.

    Returns:
        object: Result value produced for the caller.

    Side Effects:
        No side effects beyond local calculations.
    """
    if not target_result.target_timeout:
        return False
    tx = attempt.tx
    ty = attempt.ty
    if DEBUG_TARGETING:
        _diag_target_event(
            "MineTargetTimeout: tile=({0},{1}) method={2} action=no_failover_queue".format(
                int(tx),
                int(ty),
                str(getattr(target_result, "method_used", "unknown")),
            )
        )
    return True


# Apply primary journal classification results to caches and pass counters.
def _apply_primary_journal_outcome(attempt, primary, counters):
    """Apply primary journal outcome for the AutoMiner workflow.

    Args:
        attempt: Input value used by this helper.
        primary: Input value used by this helper.
        counters: Input value used by this helper.

    Returns:
        None: Performs actions without returning a value.

    Side Effects:
        Interacts with the TazUO client through API calls.
    """
    tx = attempt.tx
    ty = attempt.ty
    if primary.no_ore_hit or primary.cant_mine:
        counters.no_ore_count += 1
        NO_ORE_TILE_CACHE.add((tx, ty))
        if DEBUG_TARGETING:
            _debug_cache(f"MineTarget: cached no-ore tile ({tx},{ty}).")
        API.ClearJournal()
    elif primary.dig_some:
        # Successful dig: do not cache.
        counters.dig_success = True
        API.ClearJournal()
    elif primary.fail_skill:
        # Failed skill check still counts as a successful response (ore may remain).
        counters.dig_success = True
    else:
        if primary.cannot_see and not primary.dig_some and not primary.no_ore_hit and not primary.fail_skill:
            NO_ORE_TILE_CACHE.add((tx, ty))
            counters.cannot_see_count += 1
            if DEBUG_TARGETING:
                _debug_cache(f"MineTarget: cached cannot-see tile ({tx},{ty}).")


# Core mining pass loop with shard-tuned timings.
def _mine_pass_dynamic_timed(mine_tools, px, py, offsets, tool_use_delay_s, journal_wait_s):
    """Mine pass dynamic timed for the AutoMiner workflow.

    Args:
        mine_tools: Input value used by this helper.
        px: Input value used by this helper.
        py: Input value used by this helper.
        offsets: Input value used by this helper.
        tool_use_delay_s: Input value used by this helper.
        journal_wait_s: Input value used by this helper.

    Returns:
        object: Result value produced for the caller.

    Side Effects:
        No side effects beyond local calculations.
    """
    counters = PassCounters()
    for dx, dy in offsets:
        if _handle_overweight():
            return "overweight"
        tx = px + dx
        ty = py + dy
        if _should_skip_tile(tx, ty):
            counters.no_ore_count += 1
            continue
        attempt, journal_texts, target_result, journal_ok = _attempt_tile(
            px, py, dx, dy, mine_tools, counters, tool_use_delay_s, journal_wait_s
        )
        if not journal_ok:
            return "journal_probe_failed"
        if _handle_tile_timeout(attempt, target_result):
            continue
        if _journal_contains_any(journal_texts, TOOL_WORN_TEXTS):
            return "tool_worn"
        primary = _classify_mining_journal(journal_texts)
        _apply_primary_journal_outcome(attempt, primary, counters)
    return _finalize_pass_result(counters, len(offsets))


# Find the active mining tool (pickaxe preferred, then shovel variants).
def _get_mine_tool():
    """Get mine tool for the AutoMiner workflow.

    Args:
        None.

    Returns:
        object: Result value produced for the caller.

    Side Effects:
        Interacts with the TazUO client through API calls.
    """
    return (
        API.FindType(PICKAXE_GRAPHIC, API.Backpack)
        or API.FindType(SHOVEL_GRAPHICS[0], API.Backpack)
        or API.FindType(SHOVEL_GRAPHICS[1], API.Backpack)
    )


# Recovery path when journal indicates tool breakage.
def _handle_tool_worn_path():
    """Handle tool worn path for the AutoMiner workflow.

    Args:
        None.

    Returns:
        object: Result value produced for the caller.

    Side Effects:
        No side effects beyond local calculations.
    """
    mine_tools = _get_mine_tool()
    if not mine_tools:
        if _recall_home_and_unload():
            _ensure_tooling_in_backpack()
            mine_tools = _get_mine_tool()
            _advance_mining_spot()
            _sleep(1.0)
            _recall_mining_spot()
    if not mine_tools:
        _diag_info("Out of tools.")
        _stop_running_with_message()
    return mine_tools


# Recovery path when the current spot is considered depleted.
def _handle_no_ore_path():
    """Handle no ore path for the AutoMiner workflow.

    Args:
        None.

    Returns:
        None: Performs actions without returning a value.

    Side Effects:
        No side effects beyond local calculations.
    """
    if _recall_home_and_unload():
        _advance_mining_spot()
        _sleep(1.0)
        _recall_mining_spot()


# Single-loop mining tick: callbacks, checks, mining pass, and recovery handling.
def _tick_mining_cycle(mine_tools):
    """Tick mining cycle for the AutoMiner workflow.

    Args:
        mine_tools: Input value used by this helper.

    Returns:
        object: Result value produced for the caller.

    Side Effects:
        Updates module-level runtime state.
        Interacts with the TazUO client through API calls.
    """
    global NEEDS_TOOL_CHECK, NEEDS_INITIAL_RECALL
    API.ProcessCallbacks()
    _pause_if_needed()
    _reset_mine_cache_if_moved()

    if NEEDS_TOOL_CHECK:
        _ensure_tooling_in_backpack()
        _diag_info("Tooling check complete.")
        NEEDS_TOOL_CHECK = False
        mine_tools = _get_mine_tool()
        if NEEDS_INITIAL_RECALL and RUNBOOK_SERIAL:
            _diag_info("Recalling to first mining spot.")
            _recall_mining_spot()
            NEEDS_INITIAL_RECALL = False

    if _handle_overweight():
        return mine_tools

    result = _mine_adjacent_tiles(mine_tools)
    if result == "tool_worn":
        mine_tools = _handle_tool_worn_path()
    elif result == "no_ore":
        _handle_no_ore_path()
    elif result == "journal_probe_failed":
        _diag_error("Mining stopped: journal probe failed.", phase="TARGET")
        _stop_running_with_message()
    return mine_tools


def main():
    """Start the AutoMiner control gump and run the mining loop.

    Args:
        None.

    Returns:
        None: Runs until the script is stopped by the user or client.

    Side Effects:
        Creates UI gumps, loads persisted settings, and sends game actions.
    """
    startup_step = "initializing startup state"
    try:
        startup_step = "create control gump"
        _write_startup_trace(startup_step)
        _create_control_gump()
        startup_step = "load persisted config"
        _write_startup_trace(startup_step)
        _load_config()
        startup_step = "load log config"
        _write_startup_trace(startup_step)
        _load_log_config()
        startup_step = "rebuild control gump"
        _write_startup_trace(startup_step)
        _rebuild_control_gump()
        startup_step = "reset debug log for new session"
        _write_startup_trace(startup_step)
        _reset_debug_log_for_new_session()
        startup_step = "reset startup log for new session"
        _reset_startup_log_for_new_session()
        _write_startup_trace("startup sequence complete")
    except Exception as ex:
        # We intentionally catch broad startup failures so users get a clear
        # message instead of a silent script-manager launch failure.
        _report_startup_exception(startup_step, ex)
        raise

    mine_tools = _get_mine_tool()
    if not mine_tools:
        _diag_info("You are out of mining equipment.")
        _stop_running_with_message()

    _diag_info("AutoMiner loaded. Press Start on the gump to begin.")
    _pause_if_needed()
    _diag_info("Mining started...")

    while True:
        mine_tools = _tick_mining_cycle(mine_tools)


def _should_autostart_main():
    """Decide whether script runtime should auto-start `main()`.

    Args:
        None.

    Returns:
        bool: True when launched as script-manager entrypoint.

    Side Effects:
        No side effects beyond local calculations.
    """
    module_name = str(globals().get("__name__", ""))
    if module_name == "__main__":
        return True
    if module_name == "<module>":
        return True
    # Some launchers import scripts with module names like "Resources.AutoMiner".
    return module_name.endswith(".AutoMiner") or module_name.endswith("AutoMiner")


_AUTO_START_MAIN = _should_autostart_main()
_write_startup_trace(
    "entrypoint_check __name__={0} autostart={1}".format(
        str(globals().get("__name__", "")),
        str(_AUTO_START_MAIN),
    )
)
if _AUTO_START_MAIN:
    main()
