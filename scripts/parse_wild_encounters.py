import re
import json
from collections import defaultdict

# -------------------------------
# Slot weight definitions
# -------------------------------
LAND_WEIGHTS = [20,20,10,10,10,10,5,5,4,4,1,1]
WATER_WEIGHTS = [60,30,5,4,1]
ROCK_WEIGHTS = [60,30,5,4,1]

# # Fishing is trickier (mixed rods) → assume full table = SUPER ROD layout
FISHING_WEIGHTS = [40,40,15,4,1]  # last 5 slots (approximation)
OLD_ROD = [70,30]
GOOD_ROD = [60,20,20]
SUPER_ROD = [40,40,15,4,1]

TYPE_MAP = {
    "LandMons": ("Grass", LAND_WEIGHTS),
    "WaterMons": ("Surfing", WATER_WEIGHTS),
    "RockSmashMons": ("Rock Smash", ROCK_WEIGHTS),
    "FishingMons": ("Fishing", None),  # handled separately
}

# -------------------------------
# Helpers
# -------------------------------
def clean_species(s):
    return s.replace("SPECIES_", "").title()

def format_level(min_lv, max_lv):
    return f"{min_lv}" if min_lv == max_lv else f"{min_lv}-{max_lv}"

def parse_name(name):
    """
    Example:
    sOneIslandKindleRoad_FireRed_LandMons
    → (location, version, type_key)
    """
    name = name.strip()

    # Remove leading 's'
    name = name[1:]

    parts = name.split("_")

    if len(parts) == 3:
        location, version, type_key = parts
    elif len(parts) == 2:
        # No version (e.g., ArtisanCave)
        location, type_key = parts
        version = "Both"
    else:
        raise ValueError(f"Unexpected struct name: {name}")

    # Handle nonstandard naming formate added in FRLG+ for some new locations (e.g., "sSafariZone_NorthEast_LandMonsInfo" → "Safari Zone North East")
    if version not in ["FireRed", "LeafGreen", "Both"]:
        location += f"{version}"
        version = "Both"

    # Convert CamelCase → spaced
    location = re.sub(r'([a-z])([A-Z])', r'\1 \2', location)


    return location, version, type_key

# -------------------------------
# Parse file
# -------------------------------
def parse_file(filepath):
    with open(filepath) as f:
        text = f.read()

    # Find all WildPokemon arrays
    pattern = re.compile(
        r'const struct WildPokemon (s\w+)\[\]\s*=\s*\{([\s\S]*?)\};',
        re.MULTILINE
    )

    results = []

    for match in pattern.finditer(text):
        struct_name = match.group(1)
        body = match.group(2)

        try:
            location, version, type_key = parse_name(struct_name)
            if version not in ["FireRed", "LeafGreen", "Both"]:
                location += f" ({version})"
        except ValueError:
            continue

        if type_key not in TYPE_MAP:
            continue

        encounter_type, weights = TYPE_MAP[type_key]

        # Extract entries
        entries = re.findall(
            r'\{\s*(\d+)\s*,\s*(\d+)\s*,\s*(SPECIES_\w+)\s*\}',
            body
        )

        if not entries:
            continue

        if encounter_type == "Fishing":
            # Split into rods
            rod_sets = [
                ("Fishing (Old Rod)", entries[0:2], OLD_ROD),
                ("Fishing (Good Rod)", entries[2:5], GOOD_ROD),
                ("Fishing (Super Rod)", entries[5:10], SUPER_ROD),
            ]

            for rod_type, subset, rod_weights in rod_sets:
                species_data = defaultdict(lambda: {"rate": 0, "levels": set()})

                for i, (min_lv, max_lv, species) in enumerate(subset):
                    min_lv = int(min_lv)
                    max_lv = int(max_lv)
                    species_name = clean_species(species)

                    rate = rod_weights[i]

                    species_data[species_name]["rate"] += rate
                    species_data[species_name]["levels"].add(format_level(min_lv, max_lv))

                for species, data in species_data.items():
                    results.append({
                        "location": location,
                        "type": rod_type,
                        "species": species,
                        "level": merge_level_ranges(data["levels"]),
                        "rate": round(data["rate"], 2),
                        "version": version
                    })

            continue  # IMPORTANT: skip normal processing

        # Normalize weights length
        weights = weights[:len(entries)]

        species_data = defaultdict(lambda: {"rate": 0, "levels": set()})

        for i, (min_lv, max_lv, species) in enumerate(entries):
            min_lv = int(min_lv)
            max_lv = int(max_lv)
            species_name = clean_species(species)

            rate = weights[i]

            species_data[species_name]["rate"] += rate
            species_data[species_name]["levels"].add(format_level(min_lv, max_lv))

        # Convert to output rows
        for species, data in species_data.items():
            results.append({
                "location": location,
                "type": encounter_type,
                "species": species,
                "level": merge_level_ranges(data["levels"]),
                "rate": round(data["rate"], 2),
                "version": version
            })

    return results

# -------------------------------
# Merge FR/LG identical entries
# -------------------------------
def merge_versions(data):
    merged = {}
    for entry in data:
        key = (
            entry["location"],
            entry["type"],
            entry["species"],
            entry["level"],
            entry["rate"]
        )

        if key not in merged:
            merged[key] = set()

        merged[key].add(entry["version"])

    output = []
    for key, versions in merged.items():
        location, etype, species, level, rate = key

        if len(versions) > 1:
            version = "Both"
        else:
            version = list(versions)[0]

        output.append({
            "location": location,
            "type": etype,
            "species": species,
            "level": level,
            "rate": rate,
            "version": version
        })

    return output

def merge_level_ranges(level_set):
    """
    Converts:
    {"40","41","42"} → "40-42"
    {"5-10","10-20"} → "5-20"
    """

    ranges = []

    for lvl in level_set:
        if "-" in lvl:
            a, b = map(int, lvl.split("-"))
        else:
            a = b = int(lvl)
        ranges.append((a, b))

    # Sort by start
    ranges.sort()

    merged = []
    for start, end in ranges:
        if not merged:
            merged.append([start, end])
        else:
            last_start, last_end = merged[-1]

            # Merge if overlapping OR touching
            if start <= last_end + 1:
                merged[-1][1] = max(last_end, end)
            else:
                merged.append([start, end])

    # Convert back to string
    result = []
    for start, end in merged:
        if start == end:
            result.append(str(start))
        else:
            result.append(f"{start}-{end}")

    return "/".join(result)

# -------------------------------
# Main
# -------------------------------
if __name__ == "__main__":
    input_file = "wild_encounters.h"
    output_file = "encounter_data.json"

    data = parse_file(input_file)
    data = merge_versions(data)

    # Sort for readability
    data.sort(key=lambda x: (x["location"], x["type"], x["species"]))

    with open(output_file, "w") as f:
        json.dump(data, f, indent=2)

    print(f"Generated {output_file} with {len(data)} entries.")