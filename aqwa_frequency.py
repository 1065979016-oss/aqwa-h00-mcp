"""Shared AQWA frequency parse helpers."""
import math
import re

DOF = ("surge", "sway", "heave", "roll", "pitch", "yaw")

CARD = rb"(?m)^     1HRTZ[^\r\n]*\r?\n"

DIAGNOSTIC = re.compile(r"(?im)^\s*\*+[^\r\n]*\b(WARNING|ERRORS?|FATAL)\b[^\r\n]*")

def match_frequency_row(period, omega, frequencies):
    matches = [f for f in frequencies if abs(period-1/f)<=.006 and abs(omega-2*math.pi*f)<=.00051]
    if len(matches)!=1:
        raise ValueError(f"Unmatched or ambiguous LIS frequency row: {period} s / {omega} rad/s.")
    return matches[0]

def validate_directions(directions):
    if not isinstance(directions,(list,tuple)) or not 5<=len(directions)<=25 or any(
            type(d) not in (int,float) or not -180<=d<=180 or d!=round(d,2) for d in directions):
        raise ValueError("Provide 5–25 directions within -180 to +180 degrees, with at most two decimals.")
    if directions[0]!=-180 or directions[-1]!=180:
        raise ValueError("H00 requires both -180 and +180 degree endpoints.")
    if any(not 0 < b-a <= 90+1e-10 for a,b in zip(directions,directions[1:])):
        raise ValueError("Directions must ascend without duplicates or intervals over 90 degrees.")
    return tuple(directions)
