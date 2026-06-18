"""
data/seeds/seed_topics.py

Populates the `topics` table (Master Topic Bank).  Idempotent — safe to
re-run; uses upsert on topic_name, so existing topics are left untouched
(upsert overwrites scoring fields with the same values for already-seeded
rows, never duplicates).

Run standalone:
    python -m data.seeds.seed_topics
    python -m data.seeds.seed_topics --target 500
"""
from __future__ import annotations
import argparse, time
from typing import Dict, List
import structlog
from cascade.llm.llm_cascade import get_llm
from storage.supabase_client import get_db

logger = structlog.get_logger(__name__)

# Distribution mirrors growth_rules.category_allocation
_TARGET_DISTRIBUTION: Dict[str, int] = {
    "ocean": 150, "animals": 125, "space": 100,
    "nature": 75, "birds": 35, "insects": 15,
}

_BATCH_SIZE       = 20
_MAX_BATCH_EXTRA  = 3   # extra batches allowed beyond the mathematical minimum
_DNA_KEYS = ["danger", "size", "speed", "mystery", "intelligence", "survival", "comparison"]

_SYSTEM = (
    "You are a content strategist for a nature and science YouTube channel. "
    "You generate topic metadata for an automated video production system. "
    "Topics must be specific, visually filmable subjects (not abstract concepts), "
    "well-suited to 20-45 second video shorts."
)

# ─────────────────────────────────────────────────────────────────────────────
# Hardcoded fallback — guarantees a usable topic bank even with zero LLM access
# ─────────────────────────────────────────────────────────────────────────────

_FALLBACK_TOPICS: Dict[str, List[Dict]] = {
    "ocean": [
        {"name": "Orca", "sub": "Apex Predator", "cur": 95, "vis": 98, "ever": 100, "comp": 70, "rev": 85,
         "kw": ["orca hunting", "killer whale jumping", "orca pod ocean"],
         "dna": {"danger": 90, "size": 70, "speed": 60, "mystery": 50, "intelligence": 90, "survival": 40, "comparison": 70}},
        {"name": "Blue Whale", "sub": "Marine Mammal", "cur": 90, "vis": 90, "ever": 100, "comp": 65, "rev": 80,
         "kw": ["blue whale swimming", "whale ocean giant", "whale tail underwater"],
         "dna": {"danger": 10, "size": 100, "speed": 20, "mystery": 40, "intelligence": 60, "survival": 50, "comparison": 95}},
        {"name": "Great White Shark", "sub": "Apex Predator", "cur": 92, "vis": 95, "ever": 100, "comp": 75, "rev": 85,
         "kw": ["great white shark", "shark attack ocean", "shark jumping water"],
         "dna": {"danger": 95, "size": 70, "speed": 70, "mystery": 40, "intelligence": 50, "survival": 40, "comparison": 80}},
        {"name": "Giant Squid", "sub": "Deep Sea Creature", "cur": 93, "vis": 60, "ever": 95, "comp": 50, "rev": 70,
         "kw": ["giant squid deep sea", "squid tentacles ocean", "deep sea creature"],
         "dna": {"danger": 60, "size": 80, "speed": 30, "mystery": 95, "intelligence": 50, "survival": 60, "comparison": 70}},
        {"name": "Mantis Shrimp", "sub": "Crustacean", "cur": 90, "vis": 70, "ever": 95, "comp": 35, "rev": 60,
         "kw": ["mantis shrimp punch", "colorful shrimp ocean", "mantis shrimp underwater"],
         "dna": {"danger": 50, "size": 10, "speed": 95, "mystery": 70, "intelligence": 40, "survival": 30, "comparison": 60}},
        {"name": "Octopus", "sub": "Cephalopod", "cur": 88, "vis": 90, "ever": 100, "comp": 60, "rev": 75,
         "kw": ["octopus camouflage", "octopus underwater", "octopus tentacles"],
         "dna": {"danger": 30, "size": 20, "speed": 50, "mystery": 80, "intelligence": 95, "survival": 60, "comparison": 50}},
        {"name": "Hammerhead Shark", "sub": "Shark Species", "cur": 85, "vis": 85, "ever": 95, "comp": 55, "rev": 70,
         "kw": ["hammerhead shark swimming", "shark school ocean", "hammerhead underwater"],
         "dna": {"danger": 75, "size": 60, "speed": 55, "mystery": 50, "intelligence": 45, "survival": 35, "comparison": 60}},
        {"name": "Manta Ray", "sub": "Ray Species", "cur": 80, "vis": 90, "ever": 95, "comp": 40, "rev": 65,
         "kw": ["manta ray swimming", "manta ray ocean", "ray underwater glide"],
         "dna": {"danger": 5, "size": 60, "speed": 30, "mystery": 50, "intelligence": 60, "survival": 30, "comparison": 60}},
        {"name": "Anglerfish", "sub": "Deep Sea Fish", "cur": 88, "vis": 50, "ever": 95, "comp": 35, "rev": 55,
         "kw": ["anglerfish deep sea", "deep ocean fish glow", "bioluminescent fish"],
         "dna": {"danger": 40, "size": 10, "speed": 10, "mystery": 95, "intelligence": 20, "survival": 70, "comparison": 50}},
        {"name": "Saltwater Crocodile", "sub": "Reptile", "cur": 88, "vis": 85, "ever": 100, "comp": 50, "rev": 70,
         "kw": ["saltwater crocodile", "crocodile attack water", "crocodile swimming"],
         "dna": {"danger": 95, "size": 70, "speed": 50, "mystery": 30, "intelligence": 40, "survival": 50, "comparison": 70}},
        {"name": "Sperm Whale", "sub": "Marine Mammal", "cur": 85, "vis": 80, "ever": 95, "comp": 45, "rev": 65,
         "kw": ["sperm whale diving", "whale deep ocean", "whale tail dive"],
         "dna": {"danger": 30, "size": 90, "speed": 30, "mystery": 60, "intelligence": 80, "survival": 50, "comparison": 80}},
        {"name": "Lionfish", "sub": "Reef Fish", "cur": 75, "vis": 85, "ever": 90, "comp": 35, "rev": 50,
         "kw": ["lionfish reef", "venomous fish ocean", "colorful reef fish"],
         "dna": {"danger": 60, "size": 5, "speed": 20, "mystery": 40, "intelligence": 20, "survival": 50, "comparison": 40}},
        {"name": "Sea Otter", "sub": "Marine Mammal", "cur": 82, "vis": 95, "ever": 95, "comp": 50, "rev": 65,
         "kw": ["sea otter swimming", "otter floating ocean", "otter using tool"],
         "dna": {"danger": 5, "size": 5, "speed": 20, "mystery": 30, "intelligence": 85, "survival": 40, "comparison": 30}},
        {"name": "Pufferfish", "sub": "Reef Fish", "cur": 78, "vis": 80, "ever": 90, "comp": 35, "rev": 50,
         "kw": ["pufferfish inflate", "pufferfish ocean", "blowfish underwater"],
         "dna": {"danger": 50, "size": 5, "speed": 10, "mystery": 50, "intelligence": 20, "survival": 70, "comparison": 40}},
        {"name": "Leatherback Turtle", "sub": "Sea Turtle", "cur": 78, "vis": 80, "ever": 95, "comp": 40, "rev": 55,
         "kw": ["leatherback turtle swimming", "sea turtle ocean", "turtle deep dive"],
         "dna": {"danger": 5, "size": 60, "speed": 15, "mystery": 50, "intelligence": 30, "survival": 70, "comparison": 50}},
    ],
    "animals": [
        {"name": "African Lion", "sub": "Big Cat", "cur": 88, "vis": 95, "ever": 100, "comp": 80, "rev": 80,
         "kw": ["lion roar savanna", "lion pride africa", "lion hunting"],
         "dna": {"danger": 80, "size": 50, "speed": 50, "mystery": 20, "intelligence": 50, "survival": 30, "comparison": 70}},
        {"name": "Black Mamba", "sub": "Venomous Snake", "cur": 90, "vis": 75, "ever": 100, "comp": 60, "rev": 70,
         "kw": ["black mamba snake", "venomous snake africa", "snake strike"],
         "dna": {"danger": 95, "size": 30, "speed": 70, "mystery": 40, "intelligence": 20, "survival": 30, "comparison": 60}},
        {"name": "Komodo Dragon", "sub": "Reptile", "cur": 88, "vis": 85, "ever": 100, "comp": 55, "rev": 65,
         "kw": ["komodo dragon", "giant lizard indonesia", "komodo dragon attack"],
         "dna": {"danger": 85, "size": 60, "speed": 30, "mystery": 40, "intelligence": 30, "survival": 50, "comparison": 60}},
        {"name": "Polar Bear", "sub": "Arctic Mammal", "cur": 85, "vis": 90, "ever": 100, "comp": 60, "rev": 75,
         "kw": ["polar bear arctic", "polar bear hunting ice", "polar bear swimming"],
         "dna": {"danger": 70, "size": 70, "speed": 30, "mystery": 30, "intelligence": 50, "survival": 80, "comparison": 70}},
        {"name": "King Cobra", "sub": "Venomous Snake", "cur": 88, "vis": 75, "ever": 100, "comp": 55, "rev": 65,
         "kw": ["king cobra snake", "cobra strike", "venomous snake asia"],
         "dna": {"danger": 95, "size": 40, "speed": 50, "mystery": 40, "intelligence": 25, "survival": 30, "comparison": 60}},
        {"name": "Cheetah", "sub": "Big Cat", "cur": 85, "vis": 90, "ever": 100, "comp": 65, "rev": 70,
         "kw": ["cheetah running fast", "cheetah hunting savanna", "cheetah sprint"],
         "dna": {"danger": 40, "size": 30, "speed": 100, "mystery": 10, "intelligence": 30, "survival": 30, "comparison": 80}},
        {"name": "Gray Wolf", "sub": "Canine", "cur": 78, "vis": 85, "ever": 100, "comp": 55, "rev": 60,
         "kw": ["wolf pack hunting", "gray wolf forest", "wolf howling"],
         "dna": {"danger": 50, "size": 30, "speed": 50, "mystery": 30, "intelligence": 70, "survival": 50, "comparison": 50}},
        {"name": "Bullet Ant", "sub": "Insect (cross-category)", "cur": 85, "vis": 55, "ever": 95, "comp": 30, "rev": 45,
         "kw": ["bullet ant", "ant macro close up", "amazon rainforest ant"],
         "dna": {"danger": 90, "size": 5, "speed": 20, "mystery": 40, "intelligence": 20, "survival": 40, "comparison": 50}},
        {"name": "Honey Badger", "sub": "Mustelid", "cur": 88, "vis": 75, "ever": 100, "comp": 45, "rev": 55,
         "kw": ["honey badger fight", "honey badger fearless", "honey badger africa"],
         "dna": {"danger": 80, "size": 10, "speed": 30, "mystery": 30, "intelligence": 60, "survival": 70, "comparison": 70}},
        {"name": "Gorilla", "sub": "Primate", "cur": 80, "vis": 85, "ever": 100, "comp": 55, "rev": 65,
         "kw": ["gorilla forest", "silverback gorilla", "gorilla strength"],
         "dna": {"danger": 50, "size": 50, "speed": 20, "mystery": 30, "intelligence": 90, "survival": 30, "comparison": 70}},
        {"name": "Wolverine", "sub": "Mustelid", "cur": 82, "vis": 65, "ever": 100, "comp": 35, "rev": 50,
         "kw": ["wolverine animal", "wolverine snow forest", "wolverine fierce"],
         "dna": {"danger": 75, "size": 10, "speed": 30, "mystery": 40, "intelligence": 50, "survival": 80, "comparison": 60}},
        {"name": "Tasmanian Devil", "sub": "Marsupial", "cur": 78, "vis": 60, "ever": 95, "comp": 30, "rev": 45,
         "kw": ["tasmanian devil", "tasmanian devil australia", "small marsupial predator"],
         "dna": {"danger": 60, "size": 5, "speed": 30, "mystery": 50, "intelligence": 30, "survival": 50, "comparison": 40}},
        {"name": "Hippopotamus", "sub": "Large Mammal", "cur": 80, "vis": 85, "ever": 100, "comp": 50, "rev": 60,
         "kw": ["hippo water africa", "hippopotamus river", "hippo aggressive"],
         "dna": {"danger": 85, "size": 70, "speed": 30, "mystery": 20, "intelligence": 30, "survival": 30, "comparison": 70}},
        {"name": "Jaguar", "sub": "Big Cat", "cur": 80, "vis": 80, "ever": 100, "comp": 55, "rev": 60,
         "kw": ["jaguar rainforest", "jaguar hunting", "jaguar swimming"],
         "dna": {"danger": 70, "size": 40, "speed": 50, "mystery": 40, "intelligence": 50, "survival": 30, "comparison": 60}},
        {"name": "Pangolin", "sub": "Mammal", "cur": 80, "vis": 60, "ever": 95, "comp": 25, "rev": 40,
         "kw": ["pangolin curling", "pangolin scales", "pangolin forest"],
         "dna": {"danger": 5, "size": 5, "speed": 10, "mystery": 60, "intelligence": 20, "survival": 70, "comparison": 30}},
    ],
    "space": [
        {"name": "Black Hole", "sub": "Astrophysics", "cur": 98, "vis": 60, "ever": 100, "comp": 80, "rev": 85,
         "kw": ["black hole space", "event horizon animation", "galaxy black hole"],
         "dna": {"danger": 60, "size": 95, "speed": 30, "mystery": 100, "intelligence": 10, "survival": 10, "comparison": 80}},
        {"name": "Neutron Star", "sub": "Stellar Object", "cur": 90, "vis": 55, "ever": 100, "comp": 50, "rev": 65,
         "kw": ["neutron star space", "pulsar animation", "dense star space"],
         "dna": {"danger": 40, "size": 90, "speed": 50, "mystery": 90, "intelligence": 5, "survival": 10, "comparison": 85}},
        {"name": "Jupiter", "sub": "Gas Giant", "cur": 85, "vis": 80, "ever": 100, "comp": 60, "rev": 70,
         "kw": ["jupiter planet", "jupiter storm space", "gas giant planet"],
         "dna": {"danger": 30, "size": 95, "speed": 30, "mystery": 60, "intelligence": 5, "survival": 5, "comparison": 90}},
        {"name": "Saturn", "sub": "Gas Giant", "cur": 83, "vis": 85, "ever": 100, "comp": 60, "rev": 70,
         "kw": ["saturn rings", "saturn planet space", "ringed planet"],
         "dna": {"danger": 10, "size": 90, "speed": 20, "mystery": 60, "intelligence": 5, "survival": 5, "comparison": 85}},
        {"name": "Supernova", "sub": "Stellar Event", "cur": 92, "vis": 60, "ever": 100, "comp": 50, "rev": 65,
         "kw": ["supernova explosion", "star explosion space", "supernova animation"],
         "dna": {"danger": 70, "size": 95, "speed": 60, "mystery": 80, "intelligence": 5, "survival": 5, "comparison": 90}},
        {"name": "Red Giant", "sub": "Stellar Object", "cur": 80, "vis": 55, "ever": 100, "comp": 35, "rev": 50,
         "kw": ["red giant star", "dying star space", "star expansion animation"],
         "dna": {"danger": 50, "size": 90, "speed": 20, "mystery": 70, "intelligence": 5, "survival": 5, "comparison": 85}},
        {"name": "Andromeda Galaxy", "sub": "Galaxy", "cur": 85, "vis": 75, "ever": 100, "comp": 50, "rev": 60,
         "kw": ["andromeda galaxy", "galaxy space stars", "spiral galaxy animation"],
         "dna": {"danger": 5, "size": 100, "speed": 40, "mystery": 80, "intelligence": 5, "survival": 5, "comparison": 95}},
        {"name": "Mars", "sub": "Terrestrial Planet", "cur": 80, "vis": 90, "ever": 100, "comp": 70, "rev": 75,
         "kw": ["mars planet surface", "red planet space", "mars rover"],
         "dna": {"danger": 20, "size": 60, "speed": 10, "mystery": 60, "intelligence": 5, "survival": 30, "comparison": 70}},
        {"name": "Saturn's Moon Titan", "sub": "Moon", "cur": 82, "vis": 55, "ever": 100, "comp": 30, "rev": 45,
         "kw": ["titan moon saturn", "saturn moon surface", "moon atmosphere space"],
         "dna": {"danger": 20, "size": 60, "speed": 5, "mystery": 90, "intelligence": 5, "survival": 30, "comparison": 60}},
        {"name": "Wormhole", "sub": "Theoretical Physics", "cur": 90, "vis": 50, "ever": 100, "comp": 45, "rev": 55,
         "kw": ["wormhole space animation", "spacetime tunnel", "wormhole concept"],
         "dna": {"danger": 50, "size": 80, "speed": 70, "mystery": 100, "intelligence": 5, "survival": 10, "comparison": 80}},
        {"name": "International Space Station", "sub": "Spacecraft", "cur": 75, "vis": 85, "ever": 95, "comp": 50, "rev": 60,
         "kw": ["international space station", "ISS orbit earth", "astronaut space station"],
         "dna": {"danger": 30, "size": 30, "speed": 60, "mystery": 30, "intelligence": 60, "survival": 50, "comparison": 50}},
        {"name": "Asteroid Belt", "sub": "Solar System", "cur": 78, "vis": 65, "ever": 100, "comp": 35, "rev": 45,
         "kw": ["asteroid belt space", "asteroids solar system", "asteroid field animation"],
         "dna": {"danger": 50, "size": 70, "speed": 50, "mystery": 60, "intelligence": 5, "survival": 20, "comparison": 70}},
        {"name": "Solar Flare", "sub": "Solar Activity", "cur": 80, "vis": 70, "ever": 100, "comp": 35, "rev": 50,
         "kw": ["solar flare sun", "sun eruption space", "coronal mass ejection"],
         "dna": {"danger": 70, "size": 90, "speed": 80, "mystery": 60, "intelligence": 5, "survival": 20, "comparison": 80}},
        {"name": "Exoplanet", "sub": "Planetary Science", "cur": 82, "vis": 50, "ever": 100, "comp": 40, "rev": 55,
         "kw": ["exoplanet artist concept", "alien planet space", "distant planet animation"],
         "dna": {"danger": 30, "size": 70, "speed": 20, "mystery": 90, "intelligence": 5, "survival": 30, "comparison": 70}},
        {"name": "Milky Way Galaxy", "sub": "Galaxy", "cur": 85, "vis": 85, "ever": 100, "comp": 60, "rev": 65,
         "kw": ["milky way galaxy", "night sky stars galaxy", "milky way space"],
         "dna": {"danger": 5, "size": 100, "speed": 30, "mystery": 80, "intelligence": 5, "survival": 5, "comparison": 95}},
    ],
    "nature": [
        {"name": "Mount Everest", "sub": "Mountain", "cur": 80, "vis": 90, "ever": 100, "comp": 65, "rev": 65,
         "kw": ["mount everest summit", "himalayas mountain", "everest snow peak"],
         "dna": {"danger": 60, "size": 90, "speed": 5, "mystery": 30, "intelligence": 5, "survival": 70, "comparison": 80}},
        {"name": "Volcanic Eruption", "sub": "Volcanism", "cur": 90, "vis": 90, "ever": 100, "comp": 60, "rev": 65,
         "kw": ["volcano eruption lava", "volcanic eruption explosion", "lava flow"],
         "dna": {"danger": 90, "size": 80, "speed": 60, "mystery": 50, "intelligence": 5, "survival": 50, "comparison": 80}},
        {"name": "Tornado", "sub": "Severe Weather", "cur": 88, "vis": 85, "ever": 100, "comp": 60, "rev": 60,
         "kw": ["tornado storm", "tornado funnel cloud", "twister landscape"],
         "dna": {"danger": 90, "size": 60, "speed": 80, "mystery": 50, "intelligence": 5, "survival": 60, "comparison": 70}},
        {"name": "Lightning Storm", "sub": "Weather Phenomenon", "cur": 82, "vis": 90, "ever": 100, "comp": 55, "rev": 55,
         "kw": ["lightning storm sky", "thunderstorm lightning strike", "electric storm"],
         "dna": {"danger": 80, "size": 60, "speed": 95, "mystery": 50, "intelligence": 5, "survival": 50, "comparison": 70}},
        {"name": "Amazon Rainforest", "sub": "Ecosystem", "cur": 78, "vis": 90, "ever": 100, "comp": 55, "rev": 55,
         "kw": ["amazon rainforest aerial", "rainforest canopy", "jungle trees river"],
         "dna": {"danger": 40, "size": 80, "speed": 10, "mystery": 60, "intelligence": 5, "survival": 50, "comparison": 70}},
        {"name": "Sahara Desert", "sub": "Desert", "cur": 75, "vis": 90, "ever": 100, "comp": 50, "rev": 50,
         "kw": ["sahara desert dunes", "desert sand dunes aerial", "desert heat landscape"],
         "dna": {"danger": 50, "size": 80, "speed": 5, "mystery": 40, "intelligence": 5, "survival": 80, "comparison": 70}},
        {"name": "Aurora Borealis", "sub": "Atmospheric Phenomenon", "cur": 85, "vis": 90, "ever": 100, "comp": 60, "rev": 60,
         "kw": ["aurora borealis northern lights", "aurora sky night", "northern lights timelapse"],
         "dna": {"danger": 5, "size": 70, "speed": 30, "mystery": 80, "intelligence": 5, "survival": 5, "comparison": 60}},
        {"name": "Glacier", "sub": "Ice Formation", "cur": 75, "vis": 85, "ever": 100, "comp": 45, "rev": 50,
         "kw": ["glacier ice calving", "glacier aerial arctic", "ice sheet melting"],
         "dna": {"danger": 30, "size": 90, "speed": 5, "mystery": 40, "intelligence": 5, "survival": 50, "comparison": 80}},
        {"name": "Waterfall", "sub": "Geological Feature", "cur": 72, "vis": 95, "ever": 100, "comp": 50, "rev": 50,
         "kw": ["waterfall aerial", "massive waterfall", "waterfall rainforest"],
         "dna": {"danger": 30, "size": 70, "speed": 50, "mystery": 20, "intelligence": 5, "survival": 30, "comparison": 60}},
        {"name": "Geyser", "sub": "Geothermal Feature", "cur": 78, "vis": 80, "ever": 100, "comp": 40, "rev": 50,
         "kw": ["geyser eruption", "yellowstone geyser", "geothermal steam eruption"],
         "dna": {"danger": 50, "size": 50, "speed": 60, "mystery": 50, "intelligence": 5, "survival": 30, "comparison": 50}},
        {"name": "Coral Reef", "sub": "Marine Ecosystem", "cur": 78, "vis": 95, "ever": 95, "comp": 50, "rev": 55,
         "kw": ["coral reef underwater", "colorful coral reef", "reef fish ecosystem"],
         "dna": {"danger": 10, "size": 60, "speed": 5, "mystery": 50, "intelligence": 5, "survival": 50, "comparison": 60}},
        {"name": "Sinkhole", "sub": "Geological Phenomenon", "cur": 82, "vis": 60, "ever": 95, "comp": 30, "rev": 40,
         "kw": ["sinkhole formation", "giant sinkhole aerial", "ground collapse"],
         "dna": {"danger": 70, "size": 60, "speed": 40, "mystery": 80, "intelligence": 5, "survival": 40, "comparison": 60}},
        {"name": "Mangrove Forest", "sub": "Ecosystem", "cur": 68, "vis": 80, "ever": 100, "comp": 30, "rev": 40,
         "kw": ["mangrove forest aerial", "mangrove roots water", "coastal mangrove ecosystem"],
         "dna": {"danger": 10, "size": 60, "speed": 5, "mystery": 50, "intelligence": 5, "survival": 60, "comparison": 50}},
        {"name": "Bioluminescent Wave", "sub": "Marine Phenomenon", "cur": 88, "vis": 65, "ever": 95, "comp": 30, "rev": 45,
         "kw": ["bioluminescent waves ocean", "glowing ocean night", "bioluminescence beach"],
         "dna": {"danger": 5, "size": 40, "speed": 20, "mystery": 95, "intelligence": 5, "survival": 5, "comparison": 50}},
        {"name": "Death Valley", "sub": "Desert", "cur": 72, "vis": 85, "ever": 100, "comp": 35, "rev": 40,
         "kw": ["death valley desert", "extreme desert heat landscape", "salt flats desert"],
         "dna": {"danger": 60, "size": 70, "speed": 5, "mystery": 40, "intelligence": 5, "survival": 80, "comparison": 60}},
    ],
    "birds": [
        {"name": "Peregrine Falcon", "sub": "Raptor", "cur": 90, "vis": 80, "ever": 100, "comp": 50, "rev": 60,
         "kw": ["peregrine falcon diving", "falcon hunting flight", "fastest bird dive"],
         "dna": {"danger": 50, "size": 10, "speed": 100, "mystery": 20, "intelligence": 40, "survival": 30, "comparison": 80}},
        {"name": "Bald Eagle", "sub": "Raptor", "cur": 80, "vis": 90, "ever": 100, "comp": 60, "rev": 65,
         "kw": ["bald eagle flying", "eagle hunting fish", "eagle soaring"],
         "dna": {"danger": 50, "size": 30, "speed": 50, "mystery": 10, "intelligence": 40, "survival": 30, "comparison": 60}},
        {"name": "Owl", "sub": "Nocturnal Bird", "cur": 80, "vis": 85, "ever": 100, "comp": 55, "rev": 55,
         "kw": ["owl flying silent", "owl night hunting", "owl eyes close up"],
         "dna": {"danger": 30, "size": 10, "speed": 30, "mystery": 60, "intelligence": 60, "survival": 30, "comparison": 50}},
        {"name": "Hummingbird", "sub": "Small Bird", "cur": 80, "vis": 80, "ever": 100, "comp": 45, "rev": 50,
         "kw": ["hummingbird flying flower", "hummingbird wings slow motion", "tiny bird hover"],
         "dna": {"danger": 5, "size": 5, "speed": 90, "mystery": 30, "intelligence": 30, "survival": 30, "comparison": 70}},
        {"name": "Ostrich", "sub": "Flightless Bird", "cur": 75, "vis": 80, "ever": 100, "comp": 40, "rev": 45,
         "kw": ["ostrich running savanna", "ostrich fast bird", "largest bird africa"],
         "dna": {"danger": 30, "size": 60, "speed": 80, "mystery": 10, "intelligence": 20, "survival": 30, "comparison": 70}},
        {"name": "Albatross", "sub": "Seabird", "cur": 78, "vis": 70, "ever": 100, "comp": 30, "rev": 40,
         "kw": ["albatross flying ocean", "wandering albatross wingspan", "seabird soaring"],
         "dna": {"danger": 5, "size": 50, "speed": 30, "mystery": 50, "intelligence": 30, "survival": 60, "comparison": 70}},
        {"name": "Emperor Penguin", "sub": "Flightless Bird", "cur": 80, "vis": 90, "ever": 100, "comp": 55, "rev": 55,
         "kw": ["emperor penguin antarctica", "penguin colony ice", "penguin swimming"],
         "dna": {"danger": 10, "size": 20, "speed": 20, "mystery": 30, "intelligence": 40, "survival": 90, "comparison": 50}},
        {"name": "Harpy Eagle", "sub": "Raptor", "cur": 85, "vis": 65, "ever": 95, "comp": 30, "rev": 45,
         "kw": ["harpy eagle rainforest", "giant eagle bird", "harpy eagle talons"],
         "dna": {"danger": 70, "size": 40, "speed": 50, "mystery": 50, "intelligence": 40, "survival": 30, "comparison": 70}},
        {"name": "Flamingo", "sub": "Wading Bird", "cur": 70, "vis": 90, "ever": 100, "comp": 45, "rev": 45,
         "kw": ["flamingo flock lake", "pink flamingo wading", "flamingo flying"],
         "dna": {"danger": 5, "size": 10, "speed": 20, "mystery": 20, "intelligence": 20, "survival": 30, "comparison": 40}},
        {"name": "Crow", "sub": "Corvid", "cur": 78, "vis": 70, "ever": 100, "comp": 35, "rev": 40,
         "kw": ["crow intelligence", "crow using tool", "raven bird close up"],
         "dna": {"danger": 5, "size": 5, "speed": 20, "mystery": 50, "intelligence": 95, "survival": 40, "comparison": 30}},
    ],
    "insects": [
        {"name": "Praying Mantis", "sub": "Predatory Insect", "cur": 85, "vis": 70, "ever": 100, "comp": 35, "rev": 45,
         "kw": ["praying mantis hunting", "mantis macro close up", "mantis strike insect"],
         "dna": {"danger": 50, "size": 5, "speed": 80, "mystery": 50, "intelligence": 30, "survival": 30, "comparison": 50}},
        {"name": "Monarch Butterfly", "sub": "Butterfly", "cur": 75, "vis": 90, "ever": 100, "comp": 40, "rev": 45,
         "kw": ["monarch butterfly migration", "butterfly flying flower", "butterfly wings close up"],
         "dna": {"danger": 5, "size": 5, "speed": 20, "mystery": 50, "intelligence": 10, "survival": 60, "comparison": 50}},
        {"name": "Tarantula Hawk Wasp", "sub": "Wasp", "cur": 88, "vis": 55, "ever": 95, "comp": 25, "rev": 40,
         "kw": ["tarantula hawk wasp", "giant wasp insect", "wasp attacking spider"],
         "dna": {"danger": 90, "size": 10, "speed": 50, "mystery": 50, "intelligence": 20, "survival": 30, "comparison": 50}},
        {"name": "Atlas Moth", "sub": "Moth", "cur": 75, "vis": 70, "ever": 100, "comp": 25, "rev": 35,
         "kw": ["atlas moth giant", "largest moth wings", "moth macro close up"],
         "dna": {"danger": 5, "size": 40, "speed": 10, "mystery": 60, "intelligence": 10, "survival": 30, "comparison": 60}},
        {"name": "Army Ant", "sub": "Ant Species", "cur": 80, "vis": 65, "ever": 100, "comp": 30, "rev": 40,
         "kw": ["army ants swarm", "ant colony marching", "ants rainforest"],
         "dna": {"danger": 60, "size": 5, "speed": 30, "mystery": 50, "intelligence": 60, "survival": 50, "comparison": 50}},
        {"name": "Goliath Beetle", "sub": "Beetle", "cur": 78, "vis": 60, "ever": 100, "comp": 25, "rev": 35,
         "kw": ["goliath beetle giant", "largest beetle insect", "beetle macro close up"],
         "dna": {"danger": 10, "size": 50, "speed": 10, "mystery": 60, "intelligence": 10, "survival": 30, "comparison": 70}},
        {"name": "Dragonfly", "sub": "Flying Insect", "cur": 75, "vis": 75, "ever": 100, "comp": 30, "rev": 40,
         "kw": ["dragonfly flying slow motion", "dragonfly close up", "dragonfly hunting"],
         "dna": {"danger": 5, "size": 5, "speed": 70, "mystery": 30, "intelligence": 30, "survival": 30, "comparison": 50}},
    ],
}

# ─────────────────────────────────────────────────────────────────────────────
# Validation / normalisation
# ─────────────────────────────────────────────────────────────────────────────

def _clamp(v, lo=0, hi=100) -> int:
    try:
        n = int(v)
    except (TypeError, ValueError):
        n = 50
    return max(lo, min(hi, n))


def _normalize_dna(raw) -> Dict[str, int]:
    out: Dict[str, int] = {}
    raw = raw if isinstance(raw, dict) else {}
    for k in _DNA_KEYS:
        out[k] = _clamp(raw.get(k, 50))
    return out


def _normalize_keywords(raw, fallback_name: str) -> List[str]:
    if isinstance(raw, list):
        kws = [str(x).strip().lower() for x in raw if str(x).strip()]
        if kws:
            return kws[:5]
    return [fallback_name.lower()]


def _to_row(topic: Dict, category: str) -> Dict:
    name = str(topic.get("name") or topic.get("topic_name") or "").strip()
    return {
        "topic_name":          name,
        "category":            category,
        "subcategory":         str(topic.get("sub") or topic.get("subcategory") or "")[:100] or None,
        "curiosity_score":     _clamp(topic.get("cur", topic.get("curiosity_score"))),
        "visual_availability": _clamp(topic.get("vis", topic.get("visual_availability"))),
        "evergreen_score":     _clamp(topic.get("ever", topic.get("evergreen_score"))),
        "competition_score":   _clamp(topic.get("comp", topic.get("competition_score"))),
        "revenue_score":       _clamp(topic.get("rev", topic.get("revenue_score"))),
        "visual_keywords":     _normalize_keywords(topic.get("kw", topic.get("visual_keywords")), name),
        "topic_dna":           _normalize_dna(topic.get("dna", topic.get("topic_dna"))),
    }


# ─────────────────────────────────────────────────────────────────────────────
# LLM generation
# ─────────────────────────────────────────────────────────────────────────────

def _generate_batch(category: str, avoid_names: List[str], batch_size: int) -> List[Dict]:
    llm = get_llm()
    avoid_str = ", ".join(avoid_names[-40:]) if avoid_names else "none yet"

    prompt = f"""Generate {batch_size} specific, filmable topics for nature/science YouTube Shorts in category: {category}.

Each topic must be a SPECIFIC subject (a named species, named celestial object, or named natural phenomenon) —
never a generic concept like "fast animals" or "deep sea".

Avoid these already-used names: {avoid_str}

Return ONLY JSON:
{{
  "topics": [
    {{
      "name": "<specific subject name, e.g. 'Mantis Shrimp'>",
      "sub": "<short subcategory, e.g. 'Crustacean'>",
      "cur": <0-100 curiosity score — how surprising/shareable>,
      "vis": <0-100 visual availability — likelihood real stock footage exists>,
      "ever": <0-100 evergreen score — will this stay relevant for years>,
      "comp": <0-100 competition score — how saturated this topic is on YouTube>,
      "rev": <0-100 revenue potential score>,
      "kw": ["<2-4 word footage search term>", "<another search term>", "<another>"],
      "dna": {{"danger":<0-100>,"size":<0-100>,"speed":<0-100>,"mystery":<0-100>,"intelligence":<0-100>,"survival":<0-100>,"comparison":<0-100>}}
    }}
  ]
}}

Rules:
- {batch_size} unique topics, no duplicates of each other or the avoid list.
- kw values must be realistic stock-footage search terms (literal animal/object names + action).
- All numeric scores are integers 0-100."""

    try:
        data = llm.generate_json(prompt=prompt, system_prompt=_SYSTEM, max_tokens=3000)
        topics = data.get("topics", [])
        return [t for t in topics if isinstance(t, dict) and t.get("name")]
    except Exception as exc:
        logger.warning("topic_batch_generation_failed", category=category, error=str(exc)[:120])
        return []


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def seed_all(target_distribution: Dict[str, int] = None, force: bool = False) -> Dict[str, int]:
    """
    Generate and upsert topics for every category up to the target counts.
    Returns {category: inserted_count}.
    """
    target_distribution = target_distribution or _TARGET_DISTRIBUTION
    db = get_db()
    results: Dict[str, int] = {}

    for category, target in target_distribution.items():
        logger.info("seeding_category_start", category=category, target=target)

        collected: Dict[str, Dict] = {}  # lowercase name -> row

        # Seed with hardcoded fallback first (guarantees minimum viable bank)
        for t in _FALLBACK_TOPICS.get(category, []):
            row = _to_row(t, category)
            collected[row["topic_name"].lower()] = row

        # LLM generation until target reached or batch budget exhausted
        max_batches = (target // _BATCH_SIZE) + _MAX_BATCH_EXTRA
        for batch_num in range(max_batches):
            if len(collected) >= target:
                break
            avoid = [r["topic_name"] for r in collected.values()]
            batch = _generate_batch(category, avoid, _BATCH_SIZE)
            for t in batch:
                row = _to_row(t, category)
                key = row["topic_name"].lower()
                if key and key not in collected:
                    collected[key] = row
            logger.info(
                "seeding_category_progress",
                category=category, batch=batch_num + 1,
                collected=len(collected), target=target,
            )
            if batch:
                time.sleep(1)  # be gentle on free-tier rate limits

        rows = list(collected.values())[:max(target, len(_FALLBACK_TOPICS.get(category, [])))]
        inserted = db.bulk_insert_topics(rows)
        results[category] = inserted
        logger.info("seeding_category_done", category=category, inserted=inserted)

    total = sum(results.values())
    logger.info("topic_seeding_complete", total=total, breakdown=results)
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed the Master Topic Bank.")
    parser.add_argument("--target", type=int, default=None,
                         help="Override total target topic count (distributed proportionally).")
    args = parser.parse_args()

    dist = _TARGET_DISTRIBUTION
    if args.target:
        base_total = sum(_TARGET_DISTRIBUTION.values())
        scale = args.target / base_total
        dist = {k: max(1, int(v * scale)) for k, v in _TARGET_DISTRIBUTION.items()}

    summary = seed_all(dist)
    print("\n=== Topic Seeding Summary ===")
    for cat, count in summary.items():
        print(f"  {cat:10s}: {count}")
    print(f"  {'TOTAL':10s}: {sum(summary.values())}")
