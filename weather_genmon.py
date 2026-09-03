#!/usr/bin/env python3
"""
Weather Widget -- a genmon script for the Xfce panel's Generic Monitor plugin.

Displays current weather for a given Lokit coordinate using Open-Meteo
(free, no API key required) in Janus balanced-dozenal notation, matching
the design language of civil_clock_genmon.py: format-string templates,
janus_notation for continuous values, janus_integer for whole counts,
same genmon XML output conventions.

Data is fetched from https://api.open-meteo.com using only the Python
standard library (urllib.request) — no pip dependencies needed.

USAGE:
    python3 weather_genmon.py --lokit "Lo w26②⑤4n14③3②"
    python3 weather_genmon.py --lokit "Lo w26②⑤4n14③3②" --format "{temp_short}"
    python3 weather_genmon.py --lokit "Lo w26②⑤4n14③3②" --cache-minutes 30

ARGUMENTS:
    --lokit           Lokit coordinate of the location (required).
                      Accepts the full "Lo w..." form or the bare 12-char form.
    --format          Panel text format string (default shows all five units).
    --tooltip-format  Hover tooltip format string. Use literal \\n for line
                      breaks; they are encoded as &#10; in the XML output.
    --sig-digits      Significant digits for continuous Janus values (default 3).
    --cache-minutes   Cache the Open-Meteo API response for this many minutes
                      before re-fetching (default 15). Cache lives in /tmp.

FORMAT TOKENS:

    {temp}              Temperature in Thermit, Janus notation
    {temp_short}        "Th <value>" (official unit abbreviation)
    {temp_full}         "<value> Thermit"

    {pressure}          Atmospheric pressure in Barit, Janus notation
    {pressure_short}    "Ba <value>"
    {pressure_full}     "<value> Barit"

    {wind_speed}        Wind speed in Tachit, Janus notation
    {wind_speed_short}  "Ta <value>"
    {wind_speed_full}   "<value> Tachit"

    {wind_dir}          Wind direction in Azimit, Janus notation
                        (0 = north, increases clockwise)
    {wind_dir_short}    "Az <value>"
    {wind_dir_full}     "<value> Azimit"

    {wind_short}        "Az<dir> Ta<speed>" (compact combined form)

    {precip}            Precipitation probability in Valit (0–100 integer scale
                        per musa.bet; stored as a whole-number janus_integer)
    {precip_short}      "Va <value>"
    {precip_full}       "<value> Valit"

    {lokit}             The Lokit string as supplied to --lokit

Example:
    python3 weather_genmon.py --lokit "Lo w26②⑤4n14③3②" \\
        --format "{temp_short}  {wind_short}" \\
        --tooltip-format "{temp_full}\\n{pressure_full}\\n{precip_full}\\n{lokit}"
"""

import argparse
import hashlib
import json
import math
import os
import time
import urllib.request

from janus_notation import janus_notation, janus_integer

# ---------------------------------------------------------------------------
# Janus unit constants from musa.bet/metrics.htm (same source as janus_convert.py)
# ---------------------------------------------------------------------------
_MACRIT_M   = 2.16332257927855e1
_DYNIT_N    = 3.78450497576255e-15
TACHIT_MS   = 3.36237192e-5          # m/s per Tachit
THERMIT_K   = 6.65077402e-4          # kelvin per Thermit
BARIT_PA    = _DYNIT_N / (_MACRIT_M ** 2)  # pascal per Barit
AZIMIT_RAD  = 2 * math.pi / 12       # radians per Azimit (1/12 turn)

# ---------------------------------------------------------------------------
# Lokit decode inlined from janus_convert.py for self-containment
# ---------------------------------------------------------------------------
_NEG_CIRCLED = {1: "\u2460", 2: "\u2461", 3: "\u2462", 4: "\u2463", 5: "\u2464", 6: "\u2465"}
_CIRCLED_NEG = {v: -k for k, v in _NEG_CIRCLED.items()}


def _lokit_parse_frac(s):
    total = 0.0
    for i, ch in enumerate(s, 1):
        if ch in _CIRCLED_NEG:
            d = _CIRCLED_NEG[ch]
        elif ch.isdigit():
            d = int(ch)
            if d > 6:
                raise ValueError(f"digit {d} not a valid Janus digit")
        else:
            raise ValueError(f"unexpected char {ch!r} in Lokit")
        total += d / (12 ** i)
    return total


def lokit_decode(lokit_str):
    """Decode a Janus balanced-dozenal Lokit string to (lon_deg_west, lat_deg_north)."""
    s = lokit_str.strip()
    if s.startswith("Lo "):
        s = s[3:]
    if len(s) != 12:
        raise ValueError(f"Lokit must be 12 chars after 'Lo ': {lokit_str!r}")
    lon_dir, lat_dir = s[0], s[6]
    if lon_dir not in ('w', 'e'):
        raise ValueError(f"bad lon direction: {lon_dir!r}")
    if lat_dir not in ('n', 's'):
        raise ValueError(f"bad lat direction: {lat_dir!r}")
    lon_deg = _lokit_parse_frac(s[1:6]) * 360.0
    lat_deg = _lokit_parse_frac(s[7:12]) * 360.0
    if lon_dir == 'e':
        lon_deg = -lon_deg
    if lat_dir == 's':
        lat_deg = -lat_deg
    return lon_deg, lat_deg

# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------
CACHE_DIR = "/tmp"


def _cache_path(lokit):
    h = hashlib.sha256(lokit.encode()).hexdigest()[:8]
    return os.path.join(CACHE_DIR, f"xfce_musa_janus_weather_{h}.json")


def _load_cache(lokit, max_age_seconds):
    path = _cache_path(lokit)
    try:
        with open(path) as f:
            data = json.load(f)
        if time.time() - data.get("fetched_at", 0) < max_age_seconds:
            return data["weather"]
    except (OSError, KeyError, json.JSONDecodeError):
        pass
    return None


def _save_cache(lokit, weather):
    path = _cache_path(lokit)
    with open(path, "w") as f:
        json.dump({"fetched_at": time.time(), "weather": weather}, f)

# ---------------------------------------------------------------------------
# API fetch
# ---------------------------------------------------------------------------


def fetch_weather(lat, lon, cache_minutes, lokit):
    """Fetch current weather from Open-Meteo; cache results."""
    cached = _load_cache(lokit, cache_minutes * 60)
    if cached is not None:
        return cached
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        "&current=temperature_2m,surface_pressure,wind_speed_10m,"
        "wind_direction_10m,precipitation_probability"
        "&wind_speed_unit=ms"
    )
    with urllib.request.urlopen(url, timeout=10) as resp:
        raw = json.loads(resp.read())
    current = raw["current"]
    weather = {
        "temp_c":       current["temperature_2m"],
        "pressure_hpa": current["surface_pressure"],
        "wind_ms":      current["wind_speed_10m"],
        "wind_deg":     current["wind_direction_10m"],
        "precip_pct":   current.get("precipitation_probability", 0),
    }
    _save_cache(lokit, weather)
    return weather

# ---------------------------------------------------------------------------
# Build tokens
# ---------------------------------------------------------------------------


def build_tokens(weather, sig_digits):
    temp_th   = (weather["temp_c"] + 273.15) / THERMIT_K
    pres_ba   = (weather["pressure_hpa"] * 100.0) / BARIT_PA
    wind_ta   = weather["wind_ms"] / TACHIT_MS
    wdir_az   = (weather["wind_deg"] * math.pi / 180.0) / AZIMIT_RAD
    precip_va = round(weather["precip_pct"])

    temp_str  = janus_notation(temp_th,  sig_digits=sig_digits)
    pres_str  = janus_notation(pres_ba,  sig_digits=sig_digits)
    wspd_str  = janus_notation(wind_ta,  sig_digits=sig_digits)
    wdir_str  = janus_notation(wdir_az,  sig_digits=sig_digits)
    prec_str  = janus_integer(precip_va)

    return {
        "temp":             temp_str,
        "temp_short":       f"Th {temp_str}",
        "temp_full":        f"{temp_str} Thermit",
        "pressure":         pres_str,
        "pressure_short":   f"Ba {pres_str}",
        "pressure_full":    f"{pres_str} Barit",
        "wind_speed":       wspd_str,
        "wind_speed_short": f"Ta {wspd_str}",
        "wind_speed_full":  f"{wspd_str} Tachit",
        "wind_dir":         wdir_str,
        "wind_dir_short":   f"Az {wdir_str}",
        "wind_dir_full":    f"{wdir_str} Azimit",
        "wind_short":       f"Az{wdir_str} Ta{wspd_str}",
        "precip":           prec_str,
        "precip_short":     f"Va {prec_str}",
        "precip_full":      f"{prec_str} Valit",
    }

# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


def render(fmt, tokens):
    try:
        return fmt.format(**tokens)
    except KeyError as e:
        valid = ", ".join(sorted(tokens.keys()))
        return f"[format error: unknown token {e}; valid: {valid}]"

# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

DEFAULT_FORMAT = "{temp_short}  {pressure_short}  {wind_short}  {precip_short}"
DEFAULT_TOOLTIP = (
    "{temp_full}\n{pressure_full}\n"
    "{wind_speed_full}  {wind_dir_full}\n"
    "{precip_full}\n{lokit}"
)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--lokit", required=True,
                         help="Lokit coordinate of the location (e.g. 'Lo w26②⑤4n14③3②')")
    parser.add_argument("--format", default=DEFAULT_FORMAT,
                         help="panel text format string")
    parser.add_argument("--tooltip-format", default=DEFAULT_TOOLTIP,
                         help="tooltip format string ('\\n' becomes a real line break)")
    parser.add_argument("--sig-digits", type=int, default=3,
                         help="significant digits for continuous Janus values (default: 3)")
    parser.add_argument("--cache-minutes", type=int, default=15,
                         help="cache API response for this many minutes (default: 15)")
    args = parser.parse_args()

    try:
        lon, lat = lokit_decode(args.lokit)
        weather = fetch_weather(lat, lon, args.cache_minutes, args.lokit)
        tokens = build_tokens(weather, args.sig_digits)
        tokens["lokit"] = args.lokit
        label = render(args.format, tokens)
        tooltip_text = render(args.tooltip_format, tokens)
    except Exception as exc:
        label = "[weather unavailable]"
        tooltip_text = str(exc)

    print("<txt>" + label + "</txt>")
    print("<tool>" + tooltip_text.replace("\n", "&#10;") + "</tool>")


if __name__ == "__main__":
    main()
