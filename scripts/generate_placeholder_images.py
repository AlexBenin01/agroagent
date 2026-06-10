"""Genera immagini placeholder per data/images/ (healthy + 5 malattie).

Le immagini reali (PlantVillage / Mendeley, CC BY 4.0) non sono versionate:
questo script crea placeholder leggeri così che `capture_field_photo` funzioni
out-of-the-box. Per la demo definitiva, sostituire i file nelle stesse cartelle
con un subset del dataset reale.

Uso:  pip install pillow && python scripts/generate_placeholder_images.py
"""
import random
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1] / "data" / "images"

CATEGORIES = {
    "healthy": ((46, 125, 50), "Vite sana"),
    "diseased/peronospora": ((85, 110, 40), "Peronospora"),
    "diseased/oidio": ((150, 150, 120), "Oidio"),
    "diseased/botrite": ((110, 100, 95), "Botrite"),
    "diseased/flavescenza": ((190, 160, 60), "Flavescenza Dorata"),
    "diseased/escoriosi": ((70, 60, 50), "Escoriosi"),
}

IMAGES_PER_CATEGORY = 10
SIZE = (480, 360)


def make_image(base_rgb: tuple, label: str, idx: int, rng: random.Random) -> Image.Image:
    img = Image.new("RGB", SIZE, base_rgb)
    draw = ImageDraw.Draw(img)
    # texture di "foglie": ellissi con variazioni casuali del colore base
    for _ in range(160):
        x, y = rng.randint(0, SIZE[0]), rng.randint(0, SIZE[1])
        r = rng.randint(8, 36)
        jitter = tuple(min(255, max(0, c + rng.randint(-35, 35))) for c in base_rgb)
        draw.ellipse([x - r, y - r, x + r, y + r], fill=jitter)
    draw.rectangle([0, SIZE[1] - 34, SIZE[0], SIZE[1]], fill=(0, 0, 0))
    draw.text((10, SIZE[1] - 26), f"[SIMULATA] {label} #{idx:02d}", fill=(255, 255, 255))
    return img


def main() -> None:
    rng = random.Random(42)
    total = 0
    for folder, (rgb, label) in CATEGORIES.items():
        out_dir = ROOT / folder
        out_dir.mkdir(parents=True, exist_ok=True)
        for i in range(1, IMAGES_PER_CATEGORY + 1):
            path = out_dir / f"{folder.split('/')[-1]}_{i:03d}.jpg"
            make_image(rgb, label, i, rng).save(path, "JPEG", quality=72)
            total += 1
    print(f"Generate {total} immagini placeholder in {ROOT}")


if __name__ == "__main__":
    main()
