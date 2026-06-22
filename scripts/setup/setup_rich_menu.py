"""One-time script to create and deploy LINE Rich Menu for a tenant.

Usage:
    python scripts/setup_rich_menu.py <channel_access_token>

Generates a 2500x1686 image with 6 buttons (2x3 grid),
creates the rich menu via LINE API, uploads the image,
and sets it as the default menu.
"""

import io
import json
import sys

import httpx
from PIL import Image, ImageDraw, ImageFont

# ──────────────────────────────────────
# Rich Menu Config
# ──────────────────────────────────────

WIDTH, HEIGHT = 2500, 1686
COLS, ROWS = 3, 2
CELL_W = WIDTH // COLS
CELL_H = HEIGHT // ROWS

BUTTONS = [
    # (label, emoji, message, color)
    ("หลักสูตร", "📚", "อยากรู้เรื่องหลักสูตร", "#4A90D9"),
    ("ตารางเรียน", "📅", "ตารางเรียนเป็นยังไง", "#50B86C"),
    ("ประกาศ", "📢", "มีประกาศอะไรบ้าง", "#E8913A"),
    ("ดาวน์โหลดฟอร์ม", "📄", "ขอดาวน์โหลดฟอร์ม", "#9B59B6"),
    ("ระเบียบ", "📋", "ระเบียบการศึกษามีอะไรบ้าง", "#1ABC9C"),
    ("ค่าเทอม", "💰", "ค่าเทอมเท่าไหร่", "#E74C3C"),
]

LINE_API_BASE = "https://api.line.me/v2/bot"


# ──────────────────────────────────────
# Image Generation
# ──────────────────────────────────────

def generate_image() -> bytes:
    """Generate the rich menu image (2500x1686, 2x3 grid)."""
    img = Image.new("RGB", (WIDTH, HEIGHT), "#FFFFFF")
    draw = ImageDraw.Draw(img)

    # Try to load a good font, fall back to default
    font_large = None
    font_emoji = None
    for font_path in [
        "/usr/share/fonts/truetype/noto/NotoSansThai-Bold.ttf",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
        "C:/Windows/Fonts/tahoma.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]:
        try:
            font_large = ImageFont.truetype(font_path, 60)
            break
        except (OSError, IOError):
            continue

    if not font_large:
        font_large = ImageFont.load_default()

    for idx, (label, emoji, _, color) in enumerate(BUTTONS):
        col = idx % COLS
        row = idx // COLS
        x0 = col * CELL_W
        y0 = row * CELL_H
        x1 = x0 + CELL_W
        y1 = y0 + CELL_H

        # Fill cell
        draw.rectangle([x0, y0, x1, y1], fill=color)

        # Border
        draw.rectangle([x0, y0, x1, y1], outline="#FFFFFF", width=4)

        # Center text
        cx = x0 + CELL_W // 2
        cy = y0 + CELL_H // 2

        # Draw label (centered)
        bbox = draw.textbbox((0, 0), label, font=font_large)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        draw.text(
            (cx - tw // 2, cy - th // 2 + 20),
            label,
            fill="#FFFFFF",
            font=font_large,
        )

        # Draw emoji above label (as text — will render on systems with emoji font)
        try:
            emoji_font = ImageFont.truetype("C:/Windows/Fonts/seguiemj.l", 80)
            eb = draw.textbbox((0, 0), emoji, font=emoji_font)
        except (OSError, IOError):
            emoji_font = font_large
            eb = draw.textbbox((0, 0), emoji, font=emoji_font)
        ew = eb[2] - eb[0]
        draw.text(
            (cx - ew // 2, cy - th // 2 - 60),
            emoji,
            fill="#FFFFFF",
            font=emoji_font,
        )

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    return buf.getvalue()


# ──────────────────────────────────────
# LINE API Calls
# ──────────────────────────────────────

def create_rich_menu(token: str) -> str:
    """Create a rich menu object and return its ID."""
    areas = []
    for idx, (label, _, message, _) in enumerate(BUTTONS):
        col = idx % COLS
        row = idx // COLS
        areas.append({
            "bounds": {
                "x": col * CELL_W,
                "y": row * CELL_H,
                "width": CELL_W,
                "height": CELL_H,
            },
            "action": {
                "type": "message",
                "label": label,
                "text": message,
            },
        })

    body = {
        "size": {"width": WIDTH, "height": HEIGHT},
        "selected": True,
        "name": "CU TIP RAG Menu",
        "chatBarText": "เมนู",
        "areas": areas,
    }

    resp = httpx.post(
        f"{LINE_API_BASE}/richmenu",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json=body,
    )
    resp.raise_for_status()
    rich_menu_id = resp.json()["richMenuId"]
    print(f"Created rich menu: {rich_menu_id}")
    return rich_menu_id


def upload_image(token: str, rich_menu_id: str, image_data: bytes):
    """Upload the rich menu image."""
    resp = httpx.post(
        f"https://api-data.line.me/v2/bot/richmenu/{rich_menu_id}/content",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "image/jpeg",
        },
        content=image_data,
    )
    resp.raise_for_status()
    print(f"Uploaded image for {rich_menu_id}")


def set_default(token: str, rich_menu_id: str):
    """Set the rich menu as default for all users."""
    resp = httpx.post(
        f"{LINE_API_BASE}/user/all/richmenu/{rich_menu_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    resp.raise_for_status()
    print(f"Set default rich menu: {rich_menu_id}")


def list_rich_menus(token: str) -> list:
    """List existing rich menus."""
    resp = httpx.get(
        f"{LINE_API_BASE}/richmenu/list",
        headers={"Authorization": f"Bearer {token}"},
    )
    resp.raise_for_status()
    return resp.json().get("richmenus", [])


# ──────────────────────────────────────
# Main
# ──────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/setup_rich_menu.py <channel_access_token>")
        sys.exit(1)

    token = sys.argv[1]

    # Show existing menus
    existing = list_rich_menus(token)
    if existing:
        print(f"Found {len(existing)} existing rich menu(s):")
        for m in existing:
            print(f"  - {m['richMenuId']}: {m['name']}")

    # Generate image
    print("Generating image...")
    image_data = generate_image()
    print(f"Image generated: {len(image_data)} bytes")

    # Save locally for preview
    with open("scripts/rich_menu_preview.png", "wb") as f:
        f.write(image_data)
    print("Preview saved to scripts/rich_menu_preview.png")

    # Create, upload, set default
    rich_menu_id = create_rich_menu(token)
    upload_image(token, rich_menu_id, image_data)
    set_default(token, rich_menu_id)

    print("\nDone! Rich menu is now active.")


if __name__ == "__main__":
    main()
