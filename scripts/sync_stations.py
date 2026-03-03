#!/usr/bin/env python3
"""Sync stations.yaml from a published Google Sheet.

Expected sheet columns: Bank Name, Station Name, Type, URL

Safety features:
- Validates minimum station count before updating
- Rejects updates that would remove more than 50% of stations
- Saves a backup (stations.yaml.bak) before each update
- Git history provides full version control
"""

import csv
import io
import os
import shutil
import sys
import urllib.request

# Configuration
SHEET_CSV_URL = os.environ.get(
    "SHEET_CSV_URL",
    "https://docs.google.com/spreadsheets/d/e/2PACX-1vQxkFe1UVH2XKj-lbDDy2bxHokdLHh1WTgXMOtoPGeGSb3eJaxI6ebSi_e36QF03h60EKQBUDCDQVC1/pub?gid=0&single=true&output=csv",
)
MIN_STATIONS = int(os.environ.get("MIN_STATIONS", "10"))
MIN_RATIO = float(os.environ.get("MIN_RATIO", "0.5"))

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(SCRIPT_DIR)
STATIONS_YAML = os.path.join(REPO_DIR, "stations.yaml")
BACKUP_YAML = STATIONS_YAML + ".bak"

# Map station type to the YAML field name for its value
TYPE_FIELD = {
    "stream": "url",
    "mp3_loop_random_start": "file",
    "mp3_dir_random_start_then_in_order": "dir",
}


def fetch_csv(url):
    """Fetch CSV from the published Google Sheet."""
    req = urllib.request.Request(url, headers={"User-Agent": "RadioWeb-Sync/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8-sig")


def parse_csv(csv_text):
    """Parse CSV into ordered banks with stations.

    Returns (bank_order, banks) where bank_order is a list of bank names
    in the order they first appear, and banks maps bank_name -> [station_dicts].
    """
    reader = csv.DictReader(io.StringIO(csv_text))

    banks = {}
    bank_order = []

    for row in reader:
        bank_name = row.get("Bank Name", "").strip()
        station_name = row.get("Station Name", "").strip()
        station_type = row.get("Type", "").strip().lower() or "stream"
        url = row.get("URL", "").strip()

        if not bank_name or not station_name:
            continue

        if bank_name not in banks:
            banks[bank_name] = []
            bank_order.append(bank_name)

        banks[bank_name].append({
            "name": station_name,
            "type": station_type,
            "value": url,
        })

    return bank_order, banks


def yaml_escape(s):
    """Escape a string for use inside YAML double quotes."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def generate_yaml(bank_order, banks):
    """Generate stations.yaml content from parsed bank data."""
    lines = [
        "# ",
        "# Available types:  ",
        "#  stream:  just play the stream",
        "#  mp3_loop_random_start:  play one audio file, seek to a random position, loop forever",
        "#  mp3_dir_random_start_then_in_order:  choose one item randomly from the listed directory.  Play the item from the start, then continue playing items from the directory in order, looping to the beginning of the directory once the end is reached.",
        "#  ",
        "# Auto-generated from Google Sheet. Do not edit directly.",
        "#  ",
        "banks:",
    ]

    for bank_idx, bank_name in enumerate(bank_order):
        stations = banks[bank_name]
        lines.append(f"  {bank_idx}:")
        lines.append(f'    name: "{yaml_escape(bank_name)}"')
        lines.append("    stations:")

        for station_idx, station in enumerate(stations):
            field = TYPE_FIELD.get(station["type"], "url")
            lines.append(f"      {station_idx}:")
            lines.append(f'        name: "{yaml_escape(station["name"])}"')
            lines.append(f'        type: {station["type"]}')
            lines.append(f'        {field}: "{yaml_escape(station["value"])}"')

    return "\n".join(lines) + "\n"


def count_stations_in_file(path):
    """Count stations in an existing YAML file."""
    if not os.path.exists(path):
        return 0
    count = 0
    with open(path) as f:
        for line in f:
            if line.startswith("        name:"):
                count += 1
    return count


def main():
    print("Fetching stations from Google Sheet...")
    try:
        csv_text = fetch_csv(SHEET_CSV_URL)
    except Exception as e:
        print(f"ERROR: Failed to fetch Google Sheet: {e}")
        sys.exit(1)

    bank_order, banks = parse_csv(csv_text)
    total_stations = sum(len(s) for s in banks.values())

    print(f"Found {len(bank_order)} banks with {total_stations} total stations")

    # Safety: minimum absolute count
    if total_stations < MIN_STATIONS:
        print(
            f"ERROR: Only {total_stations} stations found (minimum: {MIN_STATIONS}). "
            f"Aborting to prevent data loss."
        )
        sys.exit(1)

    # Safety: don't lose more than half the stations
    existing_count = count_stations_in_file(STATIONS_YAML)
    if existing_count > 0 and total_stations < existing_count * MIN_RATIO:
        print(
            f"ERROR: New data has {total_stations} stations but existing file has "
            f"{existing_count}. This would remove more than "
            f"{int((1 - MIN_RATIO) * 100)}% of stations. Aborting to prevent data loss."
        )
        sys.exit(1)

    # Create backup before overwriting
    if os.path.exists(STATIONS_YAML):
        shutil.copy2(STATIONS_YAML, BACKUP_YAML)
        print(f"Backup saved to {os.path.basename(BACKUP_YAML)}")

    # Write updated YAML
    yaml_content = generate_yaml(bank_order, banks)
    with open(STATIONS_YAML, "w") as f:
        f.write(yaml_content)

    print(
        f"Successfully updated {os.path.basename(STATIONS_YAML)} "
        f"({len(bank_order)} banks, {total_stations} stations)"
    )


if __name__ == "__main__":
    main()
