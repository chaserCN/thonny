from PIL import Image, ImageDraw, ImageFont
import os

RES_DIR = os.path.join(os.path.dirname(__file__), "..", "thonny", "res")


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def save_png(img: Image.Image, path: str) -> None:
    img.save(path, format="PNG")


def make_canvas(size: int, bg=(0, 0, 0, 0)) -> Image.Image:
    return Image.new("RGBA", (size, size), bg)


def draw_plus_in_circle(size: int, fg=(30, 30, 30, 255)) -> Image.Image:
    img = make_canvas(size)
    draw = ImageDraw.Draw(img)

    # circle
    margin = max(1, size // 12)
    draw.ellipse([margin, margin, size - margin - 1, size - margin - 1], outline=fg, width=max(2, size // 12))

    # plus
    arm = size // 3
    cx = cy = size // 2
    w = max(2, size // 10)
    draw.line([(cx - arm, cy), (cx + arm, cy)], fill=fg, width=w)
    draw.line([(cx, cy - arm), (cx, cy + arm)], fill=fg, width=w)
    return img


def draw_plus_simple(size: int, fg=(30, 30, 30, 255)) -> Image.Image:
    """Draw a simple plus without circle"""
    img = make_canvas(size)
    draw = ImageDraw.Draw(img)

    # plus (larger than in circle version)
    arm = size // 2 - max(2, size // 8)
    cx = cy = size // 2
    w = max(2, size // 6)
    draw.line([(cx - arm, cy), (cx + arm, cy)], fill=fg, width=w)
    draw.line([(cx, cy - arm), (cx, cy + arm)], fill=fg, width=w)
    return img


def draw_paper_plane(size: int, fg=(30, 30, 30, 255)) -> Image.Image:
    img = make_canvas(size)
    draw = ImageDraw.Draw(img)
    # simple paper plane triangle
    pad = size // 6
    p1 = (pad, size // 2)
    p2 = (size - pad, size // 2)
    p3 = (size // 2, pad)
    p4 = (size // 2, size - pad)
    draw.polygon([p1, p2, p3], outline=fg, fill=None, width=max(2, size // 18))
    draw.line([p3, p4], fill=fg, width=max(2, size // 18))
    return img


def draw_trash(size: int, fg=(30, 30, 30, 255)) -> Image.Image:
    img = make_canvas(size)
    draw = ImageDraw.Draw(img)
    pad = size // 6
    top = pad + size // 12
    # lid
    draw.rectangle([pad, top, size - pad, top + size // 10], outline=fg, width=max(2, size // 18))
    # handle
    handle_w = size // 4
    cx = size // 2
    draw.line([(cx - handle_w // 2, top - size // 12), (cx + handle_w // 2, top - size // 12)], fill=fg, width=max(2, size // 18))
    # bin body
    body_top = top + size // 10
    draw.rectangle([pad + size // 20, body_top, size - pad - size // 20, size - pad], outline=fg, width=max(2, size // 18))
    # inner lines
    for x in (cx - size // 10, cx, cx + size // 10):
        draw.line([(x, body_top + size // 14), (x, size - pad - size // 14)], fill=fg, width=max(1, size // 24))
    return img


def make_disabled(img: Image.Image) -> Image.Image:
    # convert to semi-transparent gray
    gray = Image.new("RGBA", img.size, (160, 160, 160, 255))
    out = Image.alpha_composite(Image.new("RGBA", img.size, (0, 0, 0, 0)), gray)
    # mask by original alpha
    alpha = img.split()[-1]
    out.putalpha(alpha.point(lambda a: int(a * 0.5)))
    return out


def produce(name: str, drawer) -> None:
    ensure_dir(RES_DIR)
    for size, suffix in [(20, ""), (40, "_2x")]:
        normal = drawer(size)
        disabled = make_disabled(normal)
        save_png(normal, os.path.join(RES_DIR, f"{name}{suffix}.png"))
        save_png(disabled, os.path.join(RES_DIR, f"_disabled_{name}{suffix}.png"))


def find_font_for_char(ch: str, size: int) -> ImageFont.FreeTypeFont:
    """Find best font for character, preferring emoji fonts"""
    candidates = [
        "/System/Library/Fonts/Apple Color Emoji.ttc",
        "/System/Library/Fonts/Supplemental/Apple Color Emoji.ttc",
        "/Library/Fonts/Apple Color Emoji.ttc",
        "/System/Library/Fonts/Supplemental/Apple Symbols.ttf",
        "/System/Library/Fonts/Apple Symbols.ttf",
        "/Library/Fonts/Arial Unicode.ttf",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
        "/System/Library/Fonts/Supplemental/DejaVuSans.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    
    for path in candidates:
        if not os.path.exists(path):
            continue
        try:
            font = ImageFont.truetype(path, size=size)
            # Test if character renders
            bbox = font.getbbox(ch)
            if bbox and (bbox[2] - bbox[0]) > 0:
                return font
        except Exception:
            continue
    
    # Fallback to default
    try:
        return ImageFont.load_default()
    except:
        return None


def draw_glyph_icon(ch: str, size: int, color=(30, 30, 30, 255)) -> Image.Image:
    """Draw a character/emoji centered in a square canvas"""
    # Use higher scale for better quality
    scale = 4
    big = make_canvas(size * scale)
    draw = ImageDraw.Draw(big)
    
    # Font size should be ~80% of canvas for good visibility
    font_size = int(size * 0.85 * scale)
    font = find_font_for_char(ch, size=font_size)
    
    if font is None:
        # Fallback: just return empty canvas
        return big.resize((size, size), Image.Resampling.LANCZOS)
    
    # Use anchor "mm" (middle-middle) for proper centering
    cx = big.width // 2
    cy = big.height // 2
    
    # Draw text centered
    try:
        # For emoji fonts, embedded_color should be True
        draw.text((cx, cy), ch, font=font, fill=color, anchor="mm", embedded_color=True)
    except:
        # Fallback without embedded_color for non-emoji fonts
        draw.text((cx, cy), ch, font=font, fill=color, anchor="mm")
    
    # Resize to target size with high-quality resampling
    return big.resize((size, size), Image.Resampling.LANCZOS)


def produce_glyph(name: str, ch: str) -> None:
    ensure_dir(RES_DIR)
    for size, suffix in [(20, ""), (40, "_2x")]:
        normal = draw_glyph_icon(ch, size)
        disabled = make_disabled(normal)
        save_png(normal, os.path.join(RES_DIR, f"{name}{suffix}.png"))
        save_png(disabled, os.path.join(RES_DIR, f"_disabled_{name}{suffix}.png"))


def process_custom_icon(source_path: str, target_name: str, sizes=None) -> None:
    """
    Process a custom icon from res/tmp:
    - Resize to target sizes with optimal quality
    - Create disabled variants
    """
    if sizes is None:
        sizes = [(20, ""), (40, "_2x")]  # Standard Thonny sizes
    
    if not os.path.exists(source_path):
        print(f"Warning: {source_path} not found")
        return
    
    try:
        source = Image.open(source_path).convert("RGBA")
    except Exception as e:
        print(f"Error loading {source_path}: {e}")
        return
    
    ensure_dir(RES_DIR)
    
    from PIL import ImageEnhance
    
    for size, suffix in sizes:
        # For all sizes, use sharpening to preserve details when downsizing from 64x64
        if size <= 20:
            # 20x20: Aggressive sharpening with two-step resize
            intermediate = source.resize((size * 2, size * 2), Image.Resampling.LANCZOS)
            enhancer = ImageEnhance.Sharpness(intermediate)
            sharpened = enhancer.enhance(1.8)  # Higher sharpening for tiny icons
            resized = sharpened.resize((size, size), Image.Resampling.LANCZOS)
        elif size <= 40:
            # 40x40: Moderate sharpening with direct resize
            resized = source.resize((size, size), Image.Resampling.LANCZOS)
            enhancer = ImageEnhance.Sharpness(resized)
            resized = enhancer.enhance(1.3)  # Moderate sharpening for retina
        else:
            # Larger sizes: light sharpening
            resized = source.resize((size, size), Image.Resampling.LANCZOS)
            enhancer = ImageEnhance.Sharpness(resized)
            resized = enhancer.enhance(1.1)
        
        disabled = make_disabled(resized)
        
        # Save enabled version
        save_png(resized, os.path.join(RES_DIR, f"{target_name}{suffix}.png"))
        # Save disabled version
        save_png(disabled, os.path.join(RES_DIR, f"_disabled_{target_name}{suffix}.png"))
        print(f"  Created {target_name}{suffix}.png ({size}x{size})")


def process_custom_icons_from_tmp():
    """Process icons from res/tmp/ folder"""
    tmp_dir = os.path.join(RES_DIR, "tmp")
    
    if not os.path.exists(tmp_dir):
        print("No res/tmp/ folder found, skipping custom icons")
        return
    
    print("\nProcessing custom icons from res/tmp/:")
    
    # Map source files to target names
    icon_map = {
        "add.png": "chat-attach-glyph",
        "enter.png": "chat-send-glyph",
        "trash.png": "chat-clear-glyph",
    }
    
    # Only create standard Thonny sizes (20x20 normal, 40x40 retina)
    standard_sizes = [(20, ""), (40, "_2x")]
    
    for source_file, target_name in icon_map.items():
        source_path = os.path.join(tmp_dir, source_file)
        if os.path.exists(source_path):
            print(f"\n{source_file} -> {target_name}:")
            # Standard sizes for Thonny (20x20 normal, 40x40 retina)
            process_custom_icon(source_path, target_name, sizes=standard_sizes)


def main():
    # geometric variants (kept for reference)
    # produce("chat-attach", draw_plus_in_circle)
    # produce("chat-send", draw_paper_plane)
    # produce("chat-clear", draw_trash)
    
    # glyph-based variants (programmatic)
    # produce_glyph("chat-attach-glyph", "➕")
    # produce_glyph("chat-send-glyph", "⏎")
    # produce_glyph("chat-clear-glyph", "🗑")
    
    # Process custom icons from res/tmp/
    process_custom_icons_from_tmp()
    
    print("\nIcons generated in", RES_DIR)


if __name__ == "__main__":
    main()


