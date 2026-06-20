#!/usr/bin/env python3
"""
scripts/list_elevenlabs_voices.py

Diagnostic tool — run this whenever ElevenLabs TTS returns HTTP 402
"payment_required" / "Free users cannot use library voices via the API".

What it does
────────────
For each configured ElevenLabs key (ELEVEN_API_KEY, ELEVEN_API_KEY_2,
ELEVEN_API_KEY_3), calls GET /v1/voices — which returns EXACTLY the set of
voices that account can use via the API right now (premade defaults +
anything explicitly added to "My Voices" + your own cloned voices). Any
voice NOT in this response will 402 if requested by that key, regardless
of category.

It then cross-references the 6 configured ELEVENLABS_VOICE_ID_* secrets
against each key's accessible set and prints a clear per-key compatibility
table, plus ready-to-paste replacement suggestions pulled from voices each
key can already actually use.

Usage
─────
    # Reads keys/voice IDs from the environment — export them first, or
    # run with a .env file loaded (python-dotenv is already a dependency):
    python scripts/list_elevenlabs_voices.py

No GitHub Secrets are modified by this script — it only reads and reports.
"""
from __future__ import annotations

import os
import sys
from typing import Dict, List, Optional

import requests

_VOICES_URL = "https://api.elevenlabs.io/v1/voices"
_USER_URL = "https://api.elevenlabs.io/v1/user/subscription"

_KEY_ENVS: List[str] = ["ELEVEN_API_KEY", "ELEVEN_API_KEY_2", "ELEVEN_API_KEY_3"]

_CONFIGURED_VOICE_ENVS: List[str] = [
    "ELEVENLABS_VOICE_ID_FEMALE",
    "ELEVENLABS_VOICE_ID_FEMALE_2_CASSIDY",
    "ELEVENLABS_VOICE_ID_FEMALE_3_ALLISON",
    "ELEVENLABS_VOICE_ID_MALE",
    "ELEVENLABS_VOICE_ID_MALE_2_MARK",
    "ELEVENLABS_VOICE_ID_MALE_3_YOUNG_JAMAL",
]


def _fetch_accessible_voices(api_key: str) -> Optional[List[Dict]]:
    """Return the list of voices this key can use via the API, or None on auth failure."""
    try:
        resp = requests.get(_VOICES_URL, headers={"xi-api-key": api_key}, timeout=20)
    except requests.RequestException as exc:
        print(f"    ! Network error contacting ElevenLabs: {exc}")
        return None

    if resp.status_code == 401:
        print(f"    ! HTTP 401 — this API key is invalid or revoked.")
        return None
    if resp.status_code != 200:
        print(f"    ! HTTP {resp.status_code} — {resp.text[:200]}")
        return None

    return resp.json().get("voices", [])


def _fetch_subscription_tier(api_key: str) -> str:
    try:
        resp = requests.get(_USER_URL, headers={"xi-api-key": api_key}, timeout=20)
        if resp.status_code == 200:
            return resp.json().get("tier", "unknown")
    except requests.RequestException:
        pass
    return "unknown"


def main() -> int:
    configured_voices: Dict[str, str] = {
        env: os.getenv(env, "").strip() for env in _CONFIGURED_VOICE_ENVS
    }
    configured_voices = {k: v for k, v in configured_voices.items() if v}

    if not configured_voices:
        print("No ELEVENLABS_VOICE_ID_* environment variables are set. Nothing to check.")
        return 1

    print("=" * 78)
    print("ElevenLabs Voice Accessibility Report")
    print("=" * 78)

    # accessible_by_key[key_env] = {voice_id: voice_dict}
    accessible_by_key: Dict[str, Dict[str, Dict]] = {}
    any_key_present = False

    for key_env in _KEY_ENVS:
        api_key = os.getenv(key_env, "").strip()
        if not api_key:
            print(f"\n[{key_env}] not set — skipping.")
            continue

        any_key_present = True
        tier = _fetch_subscription_tier(api_key)
        print(f"\n[{key_env}]  subscription tier: {tier}")

        voices = _fetch_accessible_voices(api_key)
        if voices is None:
            accessible_by_key[key_env] = {}
            continue

        by_id = {v["voice_id"]: v for v in voices}
        accessible_by_key[key_env] = by_id

        premade = [v for v in voices if v.get("category") == "premade"]
        cloned = [v for v in voices if v.get("category") in ("cloned", "generated")]
        other = [v for v in voices if v.get("category") not in ("premade", "cloned", "generated")]

        print(f"    Accessible via API: {len(voices)} total "
              f"({len(premade)} premade, {len(cloned)} cloned, {len(other)} other)")

    if not any_key_present:
        print("\nNo ELEVEN_API_KEY / ELEVEN_API_KEY_2 / ELEVEN_API_KEY_3 found in environment.")
        return 1

    # ── Cross-reference configured voice_id secrets against each key ──────────
    print("\n" + "=" * 78)
    print("Configured Voice ID Compatibility")
    print("=" * 78)

    broken_envs: List[str] = []

    for voice_env, voice_id in configured_voices.items():
        print(f"\n{voice_env} = {voice_id}")
        works_for_any = False
        for key_env, by_id in accessible_by_key.items():
            if not by_id:
                continue
            if voice_id in by_id:
                v = by_id[voice_id]
                print(f"    ✅ {key_env}: ACCESSIBLE — \"{v.get('name')}\" "
                      f"(category={v.get('category')})")
                works_for_any = True
            else:
                print(f"    ❌ {key_env}: NOT ACCESSIBLE — will return HTTP 402 "
                      f"if this key is used with this voice_id")
        if not works_for_any:
            broken_envs.append(voice_env)
            print(f"    ⚠ This voice_id is not accessible to ANY configured key. "
                  f"It is a Voice Library (shared) voice that requires a paid plan, "
                  f"or the voice_id itself is wrong.")

    # ── Suggest replacements from each key's own accessible premade voices ───
    if broken_envs:
        print("\n" + "=" * 78)
        print("Suggested Replacements (premade voices already accessible to your keys)")
        print("=" * 78)

        all_premade: Dict[str, Dict] = {}
        for key_env, by_id in accessible_by_key.items():
            for vid, v in by_id.items():
                if v.get("category") == "premade":
                    all_premade.setdefault(vid, v)

        if not all_premade:
            print(
                "\nNone of your configured keys have ANY premade voices accessible. "
                "This is unusual — verify the API keys themselves are correct by "
                "checking the ElevenLabs dashboard directly."
            )
        else:
            used_ids = set(configured_voices.values())
            available_for_suggestion = [
                v for vid, v in all_premade.items() if vid not in used_ids
            ]
            print(f"\n{len(available_for_suggestion)} unused premade voice(s) "
                  f"available across your keys:\n")
            for v in available_for_suggestion[:12]:
                gender_label = v.get("labels", {}).get("gender", "unknown")
                print(f"    {v['voice_id']}  |  {v.get('name'):20s}  |  gender={gender_label}")

            print(
                f"\nACTION: For each broken secret listed above "
                f"({', '.join(broken_envs)}), replace its value in GitHub "
                f"Secrets with one of the voice_id values printed above that "
                f"matches the intended gender."
            )

    print("\n" + "=" * 78)
    if broken_envs:
        print(f"RESULT: {len(broken_envs)}/{len(configured_voices)} configured voice "
              f"ID(s) are not accessible to any key and must be replaced.")
        return 1
    print("RESULT: All configured voice IDs are accessible to at least one key.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
