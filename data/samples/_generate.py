"""Generate small synthetic architecture-diagram PNGs for the demo.

Run: python data/samples/_generate.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent


def _font(size: int = 14):
    try:
        return ImageFont.truetype("/System/Library/Fonts/SFNS.ttf", size)
    except Exception:
        try:
            return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size)
        except Exception:
            return ImageFont.load_default()


def _box(draw, xy, label, fill="white", outline="black"):
    draw.rectangle(xy, fill=fill, outline=outline, width=2)
    x1, y1, x2, y2 = xy
    draw.text(((x1 + x2) // 2 - len(label) * 3, (y1 + y2) // 2 - 8), label, fill="black", font=_font())


def _arrow(draw, p1, p2, color="black"):
    draw.line([p1, p2], fill=color, width=2)
    # arrowhead
    import math
    angle = math.atan2(p2[1] - p1[1], p2[0] - p1[0])
    ah = 8
    draw.polygon(
        [
            p2,
            (p2[0] - ah * math.cos(angle - math.pi / 6),
             p2[1] - ah * math.sin(angle - math.pi / 6)),
            (p2[0] - ah * math.cos(angle + math.pi / 6),
             p2[1] - ah * math.sin(angle + math.pi / 6)),
        ],
        fill=color,
    )


def azure_3_tier_clean():
    img = Image.new("RGB", (1200, 700), "white")
    d = ImageDraw.Draw(img)
    d.text((20, 10), "Azure 3-tier (sample)", fill="black", font=_font(18))
    # zones
    d.rectangle((20, 60, 1180, 660), outline="#94a3b8")
    d.text((30, 70), "VNet", fill="#475569", font=_font(12))
    _box(d, (60, 120, 220, 180), "User")
    _box(d, (320, 120, 540, 180), "Azure Front Door", fill="#dbeafe")
    _box(d, (640, 120, 880, 180), "Application Gateway", fill="#dbeafe")
    _box(d, (940, 120, 1140, 180), "Entra ID", fill="#ede9fe")
    _box(d, (640, 280, 880, 360), "App Service", fill="#dcfce7")
    _box(d, (940, 280, 1140, 360), "Azure Monitor", fill="#fee2e2")
    _box(d, (640, 440, 880, 520), "Azure SQL Database", fill="#fef3c7")
    _box(d, (940, 440, 1140, 520), "Key Vault", fill="#fef3c7")
    _arrow(d, (220, 150), (320, 150))
    _arrow(d, (540, 150), (640, 150))
    _arrow(d, (760, 180), (760, 280))
    _arrow(d, (760, 360), (760, 440))
    _arrow(d, (880, 320), (940, 320))
    _arrow(d, (880, 470), (940, 470))
    img.save(OUT / "azure_3_tier_clean.png")


def aws_serverless_clean():
    img = Image.new("RGB", (1200, 600), "white")
    d = ImageDraw.Draw(img)
    d.text((20, 10), "AWS serverless (sample)", fill="black", font=_font(18))
    _box(d, (60, 100, 200, 160), "User")
    _box(d, (260, 100, 460, 160), "CloudFront", fill="#fed7aa")
    _box(d, (520, 100, 720, 160), "API Gateway", fill="#fed7aa")
    _box(d, (780, 100, 980, 160), "Lambda", fill="#fde68a")
    _box(d, (520, 240, 720, 300), "DynamoDB", fill="#fef3c7")
    _box(d, (780, 240, 980, 300), "S3", fill="#fef3c7")
    _box(d, (260, 240, 460, 300), "Cognito", fill="#ede9fe")
    _arrow(d, (200, 130), (260, 130))
    _arrow(d, (460, 130), (520, 130))
    _arrow(d, (720, 130), (780, 130))
    _arrow(d, (880, 160), (720, 240))
    _arrow(d, (880, 160), (880, 240))
    _arrow(d, (620, 160), (360, 240))
    img.save(OUT / "aws_serverless_clean.png")


def gcp_microservices_clean():
    img = Image.new("RGB", (1200, 600), "white")
    d = ImageDraw.Draw(img)
    d.text((20, 10), "GCP microservices (sample)", fill="black", font=_font(18))
    _box(d, (60, 100, 200, 160), "User")
    _box(d, (260, 100, 460, 160), "Cloud CDN", fill="#bbf7d0")
    _box(d, (520, 100, 720, 160), "Cloud Load Balancing", fill="#bbf7d0")
    _box(d, (780, 100, 980, 160), "GKE", fill="#bfdbfe")
    _box(d, (520, 240, 720, 300), "Cloud SQL", fill="#fef3c7")
    _box(d, (780, 240, 980, 300), "BigQuery", fill="#fef3c7")
    _arrow(d, (200, 130), (260, 130))
    _arrow(d, (460, 130), (520, 130))
    _arrow(d, (720, 130), (780, 130))
    _arrow(d, (880, 160), (620, 240))
    _arrow(d, (880, 160), (880, 240))
    img.save(OUT / "gcp_microservices_clean.png")


def multi_cloud_hybrid():
    img = Image.new("RGB", (1400, 700), "white")
    d = ImageDraw.Draw(img)
    d.text((20, 10), "Multi-cloud hybrid (sample)", fill="black", font=_font(18))
    _box(d, (60, 120, 240, 180), "User")
    _box(d, (320, 120, 540, 180), "Azure Front Door", fill="#dbeafe")
    _box(d, (320, 240, 540, 300), "App Service", fill="#dcfce7")
    _box(d, (620, 240, 840, 300), "Azure SQL Database", fill="#fef3c7")
    _box(d, (920, 120, 1140, 180), "CloudFront", fill="#fed7aa")
    _box(d, (920, 240, 1140, 300), "Lambda", fill="#fde68a")
    _box(d, (920, 380, 1140, 440), "S3", fill="#fef3c7")
    _box(d, (320, 500, 540, 560), "Mainframe", fill="#e2e8f0")
    _arrow(d, (240, 150), (320, 150))
    _arrow(d, (430, 180), (430, 240))
    _arrow(d, (540, 270), (620, 270))
    _arrow(d, (240, 150), (920, 150))
    _arrow(d, (1030, 180), (1030, 240))
    _arrow(d, (1030, 300), (1030, 380))
    _arrow(d, (430, 300), (430, 500))
    img.save(OUT / "multi_cloud_hybrid.png")


def hub_spoke_azure():
    img = Image.new("RGB", (1200, 700), "white")
    d = ImageDraw.Draw(img)
    d.text((20, 10), "Azure hub-spoke (sample)", fill="black", font=_font(18))
    d.rectangle((480, 100, 720, 320), outline="#3b82f6", width=2)
    d.text((490, 110), "Hub VNet", fill="#1e40af", font=_font(12))
    _box(d, (500, 150, 700, 210), "Azure Firewall", fill="#fee2e2")
    _box(d, (500, 230, 700, 290), "VPN Gateway", fill="#fee2e2")

    d.rectangle((60, 380, 380, 620), outline="#22c55e", width=2)
    d.text((70, 390), "Spoke 1 — App", fill="#166534", font=_font(12))
    _box(d, (80, 430, 360, 490), "App Service", fill="#dcfce7")
    _box(d, (80, 510, 360, 570), "Private Endpoint", fill="#fef3c7")

    d.rectangle((820, 380, 1140, 620), outline="#22c55e", width=2)
    d.text((830, 390), "Spoke 2 — Data", fill="#166534", font=_font(12))
    _box(d, (840, 430, 1120, 490), "Azure SQL Database", fill="#fef3c7")
    _box(d, (840, 510, 1120, 570), "Storage Account", fill="#fef3c7")

    _arrow(d, (600, 320), (220, 430))
    _arrow(d, (600, 320), (980, 430))
    _arrow(d, (360, 460), (840, 460))
    img.save(OUT / "hub_spoke_azure.png")


def whiteboard_photo_messy():
    img = Image.new("RGB", (1100, 700), "#f1ead0")  # off-white
    d = ImageDraw.Draw(img)
    d.text((20, 10), "Whiteboard sketch (sample)", fill="black", font=_font(18))
    # Slightly off-axis, sketchy
    _box(d, (60, 100, 210, 150), "user", outline="#1f2937")
    _box(d, (280, 100, 480, 160), "WAF?", outline="#1f2937")
    _box(d, (560, 110, 760, 160), "API", outline="#1f2937")
    _box(d, (840, 100, 1040, 160), "Lambda", outline="#1f2937")
    _box(d, (560, 280, 760, 340), "Postgres", outline="#1f2937")
    _arrow(d, (210, 130), (280, 130))
    _arrow(d, (480, 135), (560, 135))
    _arrow(d, (760, 140), (840, 140))
    _arrow(d, (660, 160), (660, 280))
    img.save(OUT / "whiteboard_photo_messy.png")


def pdf_two_page():
    # Render two PIL images and combine into a PDF.
    p1 = Image.new("RGB", (1000, 600), "white")
    d = ImageDraw.Draw(p1)
    d.text((20, 10), "Multi-page diagram — page 1", fill="black", font=_font(18))
    _box(d, (60, 100, 220, 160), "User")
    _box(d, (320, 100, 540, 160), "API Gateway", fill="#fed7aa")
    _box(d, (640, 100, 860, 160), "Lambda", fill="#fde68a")
    _arrow(d, (220, 130), (320, 130))
    _arrow(d, (540, 130), (640, 130))

    p2 = Image.new("RGB", (1000, 600), "white")
    d = ImageDraw.Draw(p2)
    d.text((20, 10), "Multi-page diagram — page 2", fill="black", font=_font(18))
    _box(d, (60, 100, 220, 160), "Lambda")
    _box(d, (320, 100, 540, 160), "DynamoDB", fill="#fef3c7")
    _box(d, (640, 100, 860, 160), "S3", fill="#fef3c7")
    _arrow(d, (220, 130), (320, 130))
    _arrow(d, (540, 130), (640, 130))

    p1.save(OUT / "pdf_two_page.pdf", save_all=True, append_images=[p2])


def drawio_export_png():
    # Mimic a draw.io export — clean lines, light icons
    img = Image.new("RGB", (1200, 600), "white")
    d = ImageDraw.Draw(img)
    d.text((20, 10), "draw.io export (sample)", fill="black", font=_font(18))
    _box(d, (60, 100, 220, 160), "Browser")
    _box(d, (320, 100, 540, 160), "Nginx", fill="#e0e7ff")
    _box(d, (640, 100, 860, 160), "API", fill="#dcfce7")
    _box(d, (960, 100, 1160, 160), "Postgres", fill="#fef3c7")
    _arrow(d, (220, 130), (320, 130))
    _arrow(d, (540, 130), (640, 130))
    _arrow(d, (860, 130), (960, 130))
    img.save(OUT / "drawio_export.png")


def main():
    azure_3_tier_clean()
    aws_serverless_clean()
    gcp_microservices_clean()
    multi_cloud_hybrid()
    hub_spoke_azure()
    whiteboard_photo_messy()
    pdf_two_page()
    drawio_export_png()
    print("Generated", len(list(OUT.glob("*.png"))), "PNGs and",
          len(list(OUT.glob("*.pdf"))), "PDFs.")


if __name__ == "__main__":
    main()
