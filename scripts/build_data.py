"""
Build data.json

Sources:
- Finnish frequency list: hermitdave/FrequencyWords (GitHub raw)
- Translations: Apertium bilingual dictionaries (GitHub raw)
  fin-eng, fin-swe, fin-deu, fin-fra, fin-ita

Run: python3 scripts/build_data.py [LIMIT]
Default limit is 1000; use 10000 for larger set.
"""

import json
import re
import sys
import urllib.request
from pathlib import Path

LIMIT = int(sys.argv[1]) if len(sys.argv) > 1 else 1000

CACHE_DIR = Path(__file__).parent / ".cache"
OUTPUT = Path(__file__).parent.parent / "data.json"

FREQ_URL = "https://raw.githubusercontent.com/hermitdave/FrequencyWords/master/content/2016/fi/fi_50k.txt"

APERTIUM = {
    "en": "https://raw.githubusercontent.com/apertium/apertium-fin-eng/master/apertium-fin-eng.fin-eng.dix",
    "sv": "https://raw.githubusercontent.com/apertium/apertium-fin-swe/master/apertium-fin-swe.fin-swe.dix",
    "de": "https://raw.githubusercontent.com/apertium/apertium-fin-deu/master/apertium-fin-deu.fin-deu.dix",
    "fr": "https://raw.githubusercontent.com/apertium/apertium-fin-fra/master/apertium-fin-fra.fin-fra.dix",
    "it": "https://raw.githubusercontent.com/apertium/apertium-fin-ita/master/apertium-fin-ita.fin-ita.dix",
}


def fetch_cached(url, filename):
    cache_path = CACHE_DIR / filename
    if cache_path.exists():
        print(f"  [cache] {filename}")
        return cache_path.read_text("utf-8")
    print(f"  [fetch] {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "sanakirja-builder/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read().decode("utf-8")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(data, "utf-8")
    return data


def get_frequency_list():
    raw = fetch_cached(FREQ_URL, "fi_50k.txt")
    words = []
    for line in raw.splitlines():
        parts = line.strip().split()
        if parts:
            words.append(parts[0].lower())
    return words


def clean_dix_side(s):
    s = re.sub(r"<b/>", " ", s)
    s = re.sub(r"<[^>]+>", "", s)
    return s.strip().lower()


def parse_apertium(lang, url):
    raw = fetch_cached(url, f"apertium-fin-{lang}.dix")
    entries = re.findall(r"<e[^>]*>\s*<p>\s*<l>(.*?)</l>\s*<r>(.*?)</r>", raw, re.DOTALL)
    trans = {}
    for l_side, r_side in entries:
        fi_word = clean_dix_side(l_side)
        target_word = clean_dix_side(r_side)
        if fi_word and target_word and " " not in fi_word:
            trans.setdefault(fi_word, target_word)
    print(f"  [{lang}] {len(trans)} entries")
    return trans


def build():
    print("Fetching Finnish frequency list ...")
    freq_words = get_frequency_list()
    print(f"  {len(freq_words)} words total, using top {LIMIT}")
    top_words = freq_words[:LIMIT]

    print("Fetching Apertium bilingual dictionaries ...")
    lang_maps = {}
    for lang, url in APERTIUM.items():
        lang_maps[lang] = parse_apertium(lang, url)

    print("Building data.json ...")
    output = []
    for word in top_words:
        entry = {"fi": word}
        for lang in ["en", "sv", "it", "fr", "de"]:
            t = lang_maps[lang].get(word)
            if t:
                entry[lang] = t
        if "en" not in entry:
            continue
        output.append(entry)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(output, ensure_ascii=False, indent=2), "utf-8")
    print(f"\nWrote {len(output)} entries to {OUTPUT}")

    lang_counts = {lang: sum(1 for e in output if lang in e) for lang in ["en", "sv", "it", "fr", "de"]}
    print("Coverage:", " | ".join(f"{l.upper()}:{n}" for l, n in lang_counts.items()))


if __name__ == "__main__":
    build()
