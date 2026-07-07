import json
import os
import re
import hashlib
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

NTFY_TOPIC = os.environ["NTFY_TOPIC"]
STATE_FILE = Path("seen.json")

SOURCES = {
    "État de Vaud": {
        "url": "https://www.vd.ch/actualites/communiques-de-presse-de-letat-de-vaud",
        "allow": r"/actualites/communiques-de-presse-de-letat-de-vaud/detail/communique/",
    },
    "Police cantonale vaudoise": {
        "url": "https://www.vd.ch/djes/polcant/medias/communiques-de-presse",
        "allow": r"/djes/polcant/medias/communiques-de-presse/.+",
    },
    "Ville de Lausanne": {
        "url": "https://www.lausanne.ch/apps/actualites/",
        "allow": r"/apps/actualites/.*actu_id=",
    },
    "Ville de Renens": {
        "url": "https://www.renens.ch/officielle/actualites/",
        "allow": r"/actualites|/actualite|news|communique",
    },
    "Ville de Prilly": {
        "url": "https://www.prilly.ch/toutes-les-actualites",
        "allow": r"/toutes-les-actualites|/actualites|news",
    },
}

HEADERS = {"User-Agent": "press-ntfy-bot/1.0"}


def load_seen():
    if STATE_FILE.exists():
        return set(json.loads(STATE_FILE.read_text(encoding="utf-8")))
    return set()


def save_seen(seen):
    STATE_FILE.write_text(
        json.dumps(sorted(seen), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def fetch(url):
    r = requests.get(url, headers=HEADERS, timeout=25)
    r.raise_for_status()
    return r.text


def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def first_two_sentences(text):
    text = clean(text)
    parts = re.split(r"(?<=[.!?])\s+", text)
    return " ".join(parts[:2]).strip()


def item_id(url):
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def find_links(source):
    html = fetch(source["url"])
    soup = BeautifulSoup(html, "html.parser")
    links = []

    for a in soup.select("a[href]"):
        href = urljoin(source["url"], a["href"])
        label = clean(a.get_text(" "))
        if re.search(source["allow"], href, re.I):
            links.append((href, label))

    # dédoublonnage en gardant l’ordre
    out, seen = [], set()
    for href, label in links:
        if href not in seen:
            out.append((href, label))
            seen.add(href)

    return out[:15]


def extract_article(url, fallback_title):
    html = fetch(url)
    soup = BeautifulSoup(html, "html.parser")

    title = clean(
        (soup.find("h1").get_text(" ") if soup.find("h1") else "")
        or fallback_title
        or url
    )

    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()

    paragraphs = [clean(p.get_text(" ")) for p in soup.find_all("p")]
    body = " ".join(p for p in paragraphs if len(p) > 40)

    return title, first_two_sentences(body)


def notify(source_name, title, summary, url):
    # Remplace les caractères Unicode "exotiques"
    title = title.replace("—", "-").replace("–", "-")
    summary = summary.replace("—", "-").replace("–", "-")
    source_name = source_name.replace("—", "-").replace("–", "-")

    message = f"""{source_name}

{title}

{summary}

{url}"""

    requests.post(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data=message.encode("utf-8"),
        headers={
            "Content-Type": "text/plain; charset=utf-8",
            "Title": f"Nouveau communiqué - {source_name}",
            "Tags": "newspaper",
            "Priority": "3",
        },
        timeout=25,
    ).raise_for_status()


def main():
    seen = load_seen()
    first_run = not STATE_FILE.exists()
    new_seen = set(seen)

    for source_name, source in SOURCES.items():
        try:
            for url, fallback_title in find_links(source):
                uid = item_id(url)
                new_seen.add(uid)

                if uid in seen or first_run:
                    continue

                title, summary = extract_article(url, fallback_title)
                if summary:
                    notify(source_name, title, summary, url)

        except Exception as e:
            print(f"[WARN] {source_name}: {e}")

    save_seen(new_seen)


if __name__ == "__main__":
    main()
