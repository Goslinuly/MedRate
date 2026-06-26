import base64
import io
from pathlib import Path

from PIL import Image

from pipeline.models import RawDoc, clinic_meta_from_filename

MAX_DIMENSION = 2200
JPEG_QUALITY = 85


def encode_image(image: Image.Image) -> tuple[str, str]:
    image = image.convert("RGB")
    if max(image.size) > MAX_DIMENSION:
        scale = MAX_DIMENSION / max(image.size)
        image = image.resize((int(image.width * scale), int(image.height * scale)))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=JPEG_QUALITY)
    return base64.b64encode(buffer.getvalue()).decode("ascii"), "image/jpeg"


def extract_image(path: Path) -> list[RawDoc]:
    meta = clinic_meta_from_filename(path)
    with Image.open(path) as image:
        payload, media_type = encode_image(image)
    return [
        RawDoc(
            source_file=path.name,
            kind="image",
            source_page=1,
            image_b64=payload,
            image_media_type=media_type,
            **meta,
        )
    ]
