"""Extract first-order AQWA 2023 R1 H00 hydrodynamic data with LIS provenance."""
import hashlib
import json
import math
import re

from aqwa_frequency import DIAGNOSTIC, DOF, validate_directions, match_frequency_row

AXES = ("X","Y","Z","RX","RY","RZ")
NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EDed][+-]?\d+)?"
NUMBERS = re.compile(NUMBER)
PERIOD = re.compile(r"WAVE PERIOD\s*=\s*("+NUMBER+r")\s+WAVE FREQUENCY\s*=\s*("+NUMBER+r")")
MATRIX = re.compile(r"^\s*(X|Y|Z|RX|RY|RZ)\s+((?:"+NUMBER+r"\s*){6})\s*$")
TOTAL = "FROUDE KRYLOV + DIFFRACTION FORCES-VARIATION WITH WAVE PERIOD/FREQUENCY"
RAO = "R.A.O.S-VARIATION WITH WAVE PERIOD/FREQUENCY"


def values(text):
    result = [float(s.replace("D","E").replace("d","e")) for s in NUMBERS.findall(text)]
    if not all(map(math.isfinite,result)):
        raise ValueError("Nonfinite AQWA numeric field.")
    return result


def frequency(period, omega, frequencies, digits):
    # AQWA 2023 R1's single-precision conversion can cross the decimal half-unit.
    pad = .55*10**(-digits)
    matches = [f for f in frequencies if abs(period-1/f)<=pad and abs(omega-2*math.pi*f)<=pad]
    if len(matches)!=1:
        raise ValueError(f"Unmatched LIS period and angular frequency: {period}, {omega}.")
    return matches[0]


def matrices(lines, frequencies, stop):
    data = {}
    for i in range(stop):
        if lines[i].strip()!="ADDED  MASS":
            continue
        match = next((m for row in lines[max(0,i-12):i] if (m:=PERIOD.search(row))),None)
        if not match or not any("WITH RESPECT TO STRUCTURE COG" in row for row in lines[max(0,i-12):i]):
            raise ValueError(f"Matrix lacks a frequency or center-of-gravity reference at line {i+1}.")
        f = frequency(*map(float,match.groups()),frequencies,digits=3)
        if f in data:
            raise ValueError(f"Duplicate matrix at {f} Hz.")
        sections = []
        for title in (i,next((j for j in range(i+1,min(i+33,stop)) if lines[j].strip()=="DAMPING"),-1)):
            if title<0:
                raise ValueError(f"Missing radiation damping at {f} Hz.")
            rows, sources = [], []
            for j in range(title+1,min(title+24,stop)):
                m = MATRIX.fullmatch(lines[j])
                if m:
                    if m[1]!=AXES[len(rows)]:
                        raise ValueError(f"Incorrect matrix row order at line {j+1}.")
                    rows.append(values(m[2]))
                    sources.append(j+1)
                if len(rows)==6:
                    break
            if len(rows)!=6 or any(len(row)!=6 for row in rows):
                raise ValueError(f"Incomplete 6x6 matrix at line {title+1}.")
            sections.append({"values":rows,"row_lines":sources,"heading_line":title+1})
        data[f] = {"frequency_hz":f,"added_mass":sections[0],"radiation_damping":sections[1]}
    if set(data)!=set(frequencies):
        raise ValueError("Full matrix coverage does not match the frequency input.")
    return [data[f] for f in frequencies]


def excitation(lines, frequencies, directions, start, stop):
    result = {}
    direction = None
    for i in range(start+1,stop):
        row = lines[i]
        if row.strip()==TOTAL and not any("WITH RESPECT TO STRUCTURE COG" in r for r in lines[max(0,i-12):i]):
            raise ValueError(f"Unknown excitation reference at line {i+1}.")
        if not re.match(r"^\s*\d+\.\d+\s+\d+\.\d+",row):
            continue
        items = values(row)
        if len(items)==15:
            direction = items.pop(2)
        if len(items)!=14 or direction not in directions:
            raise ValueError(f"Unexpected excitation row at line {i+1}.")
        period, omega, *response = items
        f = match_frequency_row(period,omega,frequencies)
        if (f,direction) in result:
            raise ValueError(f"Duplicate or inconsistent excitation row at line {i+1}.")
        result[f,direction] = {"frequency_hz":f,"direction_deg":direction,"line":i+1,"components":{
            axis:{"amplitude":a,"phase_deg":p}
            for axis,a,p in zip(AXES,response[::2],response[1::2])}}
    if set(result)!={(f,d) for f in frequencies for d in directions}:
        raise ValueError("Excitation does not cover the full frequency/direction grid.")
    return list(result.values())


def extract(raw, frequencies, directions, *, max_frequency_hz=.20):
    if ("FINISH DATE:" not in raw or DIAGNOSTIC.search(raw) or
        not re.search(r"Hydrodynamic Solver Unit System\s*:\s*Metric:\s*kg,\s*m\s*\[N\]",raw,re.I)):
        raise ValueError("Expected a clean completed metric H00 LIS.")
    directions = validate_directions(directions)
    if (not frequencies or len(set(frequencies))!=len(frequencies)
            or any(type(f) not in (int,float) or not .02<=f<=max_frequency_hz for f in frequencies)):
        raise ValueError("Unsupported H00 frequency/direction manifest.")
    lines=raw.splitlines()
    try:
        first=next(i for i,line in enumerate(lines) if line.strip()==TOTAL)
        last=next(i for i in range(first+1,len(lines)) if lines[i].strip()==RAO)
    except StopIteration as exc:
        raise ValueError("Missing first-order excitation or RAO heading.") from exc
    if not any("WITH RESPECT TO STRUCTURE COG" in r for r in lines[max(0,first-12):first]):
        raise ValueError("Unknown excitation moment reference.")
    return matrices(lines,frequencies,first),excitation(lines,frequencies,directions,first,last)
