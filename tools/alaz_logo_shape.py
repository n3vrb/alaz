"""Alaz tamga emblem as an exact vector polygon (traced from the chosen logo, symmetric about x=627)."""
RIGHT = [(627, 155), (716, 247), (669, 296), (669, 757), (844, 598), (742, 494), (742, 405),
         (843, 307), (843, 467), (974, 598), (627, 896)]
def outline():
    left = [(1254 - x, y) for x, y in reversed(RIGHT[1:-1])]
    return RIGHT + left
COLOR = "#1AD2C4"
# per perf-mode emblem colour; "quiet" is the base logo (COLOR)
MODE_COLORS = {"quiet": COLOR, "balanced": "#2F7BFF", "turbo": "#E8323A", "custom": "#F2A93B"}
