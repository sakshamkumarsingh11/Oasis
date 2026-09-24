"""
Task 1: U-Net Oil Spill Segmentation (Model 1).

Loads the trained best_oil_spill_unet.pt weights and runs inference
on uploaded SAR image bytes. Uses the exact same architecture and
preprocessing as predict_spill.py.
"""

import logging
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    _TORCH = True
except ImportError:
    _TORCH = False

logger = logging.getLogger("segmentation")

# ---------------------------------------------------------------------------
# U-Net Architecture (must match trained weights exactly)
# ---------------------------------------------------------------------------

if _TORCH:

    class DoubleConv(nn.Module):
        def __init__(self, in_c: int, out_c: int, mid_c: Optional[int] = None, dropout: float = 0.1):
            super().__init__()
            mid_c = mid_c or out_c
            self.conv = nn.Sequential(
                nn.Conv2d(in_c, mid_c, 3, padding=1, bias=False),
                nn.BatchNorm2d(mid_c),
                nn.ReLU(inplace=True),
                nn.Conv2d(mid_c, out_c, 3, padding=1, bias=False),
                nn.BatchNorm2d(out_c),
                nn.ReLU(inplace=True),
                nn.Dropout2d(dropout) if dropout > 0 else nn.Identity(),
            )

        def forward(self, x):
            return self.conv(x)

    class UpBlock(nn.Module):
        def __init__(self, in_c: int, out_c: int, dropout: float = 0.1):
            super().__init__()
            self.up = nn.Sequential(
                nn.Upsample(scale_factor=2, mode="bilinear", align_corners=True),
                nn.Conv2d(in_c, in_c // 2, kernel_size=1),
            )
            self.conv = DoubleConv(in_c, out_c, dropout=dropout)

        def forward(self, x1, x2):
            x1 = self.up(x1)
            diff_y = x2.size(2) - x1.size(2)
            diff_x = x2.size(3) - x1.size(3)
            if diff_y != 0 or diff_x != 0:
                x1 = F.pad(x1, [diff_x // 2, diff_x - diff_x // 2,
                                diff_y // 2, diff_y - diff_y // 2])
            x = torch.cat([x2, x1], dim=1)
            return self.conv(x)

    class UNet(nn.Module):
        def __init__(self, in_channels=1, num_classes=1, features=None, dropout=0.2):
            super().__init__()
            features = features or [64, 128, 256, 512]
            self.inc = DoubleConv(in_channels, features[0], dropout=0.0)
            self.down1 = nn.Sequential(nn.MaxPool2d(2), DoubleConv(features[0], features[1], dropout=dropout))
            self.down2 = nn.Sequential(nn.MaxPool2d(2), DoubleConv(features[1], features[2], dropout=dropout))
            self.down3 = nn.Sequential(nn.MaxPool2d(2), DoubleConv(features[2], features[3], dropout=dropout))
            self.down4 = nn.Sequential(nn.MaxPool2d(2), DoubleConv(features[3], features[3] * 2, dropout=dropout))
            self.up1 = UpBlock(features[3] * 2, features[3], dropout=dropout)
            self.up2 = UpBlock(features[3], features[2], dropout=dropout)
            self.up3 = UpBlock(features[2], features[1], dropout=dropout)
            self.up4 = UpBlock(features[1], features[0], dropout=0.0)
            self.outc = nn.Conv2d(features[0], num_classes, kernel_size=1)

        def forward(self, x):
            x1 = self.inc(x)
            x2 = self.down1(x1)
            x3 = self.down2(x2)
            x4 = self.down3(x3)
            x5 = self.down4(x4)
            x = self.up1(x5, x4)
            x = self.up2(x, x3)
            x = self.up3(x, x2)
            x = self.up4(x, x1)
            return self.outc(x)

# ---------------------------------------------------------------------------
# Model singleton (loaded once at startup)
# ---------------------------------------------------------------------------

_model = None
_device = None
_MODEL_LOADED = False

# Local fallback paths (used only if Hugging Face download is unavailable)
_WEIGHTS_SEARCH = [
    Path(__file__).resolve().parents[2] / "best_oil_spill_unet.pt",       # backend/
    Path(__file__).resolve().parents[3] / "best_oil_spill_unet.pt",       # project root
    Path("best_oil_spill_unet.pt"),
]


def _get_device():
    if torch.cuda.is_available():
        return torch.device("cuda")
    elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def _ensure_model():
    """Load the U-Net model once and cache it."""
    global _model, _device, _MODEL_LOADED
    if _MODEL_LOADED:
        return

    if not _TORCH:
        logger.warning("PyTorch not available — segmentation will use synthetic fallback.")
        _MODEL_LOADED = True
        return

    # 1. Try downloading from Hugging Face Hub (auto-cached after first run)
    weights_path = None
    try:
        from app.core.model_downloader import download_model
        hf_path = download_model("unet")
        if hf_path is not None:
            weights_path = hf_path
    except Exception as exc:
        logger.debug("Hugging Face download attempt failed: %s", exc)

    # 2. Fallback: search local filesystem paths
    if weights_path is None:
        for p in _WEIGHTS_SEARCH:
            if p.exists():
                weights_path = p
                break

    if weights_path is None:
        logger.warning("U-Net weights (best_oil_spill_unet.pt) not found — will use synthetic fallback.")
        _MODEL_LOADED = True
        return

    try:
        _device = _get_device()
        _model = UNet(in_channels=1, num_classes=1, features=[64, 128, 256, 512], dropout=0.2)
        state_dict = torch.load(str(weights_path), map_location=_device, weights_only=False)
        _model.load_state_dict(state_dict)
        _model.to(_device)
        _model.eval()
        logger.info("U-Net model loaded from %s on device %s", weights_path, _device)
    except Exception as e:
        logger.error("Failed to load U-Net weights: %s — using synthetic fallback.", e)
        _model = None

    _MODEL_LOADED = True


def _normalise_sar(image: np.ndarray) -> np.ndarray:
    """SAR radiometric normalisation (1st–99th percentile clip + min-max)."""
    img = image.astype(np.float32)
    p1, p99 = np.percentile(img, 1.0), np.percentile(img, 99.0)
    if p99 > p1:
        img = np.clip(img, p1, p99)
        img = (img - p1) / (p99 - p1)
    else:
        mn, mx = img.min(), img.max()
        img = (img - mn) / (mx - mn + 1e-6)
    return img


def _postprocess_mask(mask: np.ndarray, min_area: int = 30) -> np.ndarray:
    """Morphological cleaning of raw binary prediction."""
    binary = (mask > 0).astype(np.uint8)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    opened = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(opened, connectivity=8)
    cleaned = np.zeros_like(opened)
    for i in range(1, num_labels):
        if stats[i, cv2.CC_STAT_AREA] >= min_area:
            cleaned[labels == i] = 1
    return cleaned


# ---------------------------------------------------------------------------
# Public API — called by endpoints.py
# ---------------------------------------------------------------------------

def run_segmentation(image_bytes: bytes, threshold: float = 0.5) -> dict:
    """
    Task 1: Run U-Net segmentation on raw image bytes.

    Returns dict with:
        confidence: float (0–1) — max probability in the scene
        mask_detected: bool
        mask: np.ndarray (H, W) binary uint8 {0, 255} — only if model available
    """
    _ensure_model()

    # Decode image bytes to numpy
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img_raw = cv2.imdecode(arr, cv2.IMREAD_UNCHANGED)

    if img_raw is None:
        raise ValueError("Invalid image file provided. Could not decode image.")

    # Convert to grayscale
    if img_raw.ndim == 3:
        gray = cv2.cvtColor(img_raw, cv2.COLOR_BGR2GRAY)
    else:
        gray = img_raw.copy()

    orig_h, orig_w = gray.shape[:2]

    if _model is None:
        raise RuntimeError("U-Net model weights not found or failed to load. Real inference is required.")

    # Preprocess: resize to 256×256, normalise
    resized = cv2.resize(gray, (256, 256), interpolation=cv2.INTER_LINEAR)
    norm = _normalise_sar(resized)
    input_tensor = torch.from_numpy(norm).unsqueeze(0).unsqueeze(0).float().to(_device)

    # Forward pass
    with torch.no_grad():
        logits = _model(input_tensor)
        probs_256 = torch.sigmoid(logits).squeeze().cpu().numpy()

    # Rescale to original resolution
    prob_map = cv2.resize(probs_256, (orig_w, orig_h), interpolation=cv2.INTER_LINEAR)

    # Binarise + clean
    raw_binary = (prob_map >= threshold).astype(np.uint8)
    cleaned = _postprocess_mask(raw_binary, min_area=30)

    # Convert to 0/255 for downstream (geometry.py expects this)
    mask_255 = (cleaned * 255).astype(np.uint8)

    confidence = float(prob_map.max())
    oil_pixels = int(cleaned.sum())
    detected = oil_pixels >= 30

    logger.info(
        "U-Net inference: confidence=%.3f, oil_pixels=%d, detected=%s",
        confidence, oil_pixels, detected,
    )

    return {
        "confidence": round(confidence, 4),
        "mask_detected": detected,
        "mask": mask_255,
        "raw_sar_gray": gray,       # pass raw SAR for lookalike verifier
        "probability_map": prob_map,
    }
