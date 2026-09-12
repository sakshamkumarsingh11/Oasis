"""
model2_inference.py
====================
SIH26143 — Marine Oil Spill Detection, Hindcast Drift & Vessel Attribution Platform
MODEL 2: SAR Look-Alike & Radiometric Forensic Verification Engine

Role in pipeline (see architecture.txt, Layer 3):
    Model 1 (UNet++) produces a noisy binary mask of "dark formations" on a
    Sentinel-1 SAR scene. That mask is fed into THIS module, which:

        Stage A — Morphological Forensic Cleaning
            Removes small radar-speckle blobs (opening + connected-component
            area filtering), isolating genuine candidate slick contours.

        Stage B — Dual-Evidence Verification (per candidate blob)
            1. CNN evidence  : an EfficientNet-B0 patch classifier (trained on
               VV+VH dB patches) estimates P(mineral oil) for the blob.
            2. Physics evidence: radiometric decibel contrast (Delta-dB between
               slick and surrounding sea) and boundary gradient sharpness are
               computed directly from the raw SAR image, independent of the CNN.
            These two independent lines of evidence are fused into a single
            forensic verdict per blob, which is why this failure mode is
            explainable rather than a black box.

    The module returns the exact dictionary contract required by
    Task 2 (Geometry Engine) and Task 5 (Attribution Engine) downstream.

Physical basis (from project brief):
    Mineral oil damps capillary/Bragg-scattering waves strongly:
        Delta_dB = mean_sea_dB - mean_slick_dB  > 3.0 dB, sharp boundary.
    Low-wind / biogenic look-alikes:
        Delta_dB < 1.5 dB, diffuse / blurry boundary.
    The zone between 1.5 and 3.0 dB is physically ambiguous — this is exactly
    where the CNN's learned texture prior is most valuable, which is why we
    fuse CNN probability with the physics rule rather than using either alone.

Author: Model 2 owner — SIH26143 CV/SAR team
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

import cv2
import numpy as np

try:
    import torch
    import torch.nn as nn
    _TORCH_AVAILABLE = True
except Exception:  # pragma: no cover - inference box may be torch-less/broken at import-check time
    _TORCH_AVAILABLE = False

try:
    import timm
    _TIMM_AVAILABLE = True
except Exception:  # pragma: no cover
    _TIMM_AVAILABLE = False

logger = logging.getLogger("model2_verifier")
logging.basicConfig(level=logging.INFO)


# --------------------------------------------------------------------------- #
# 0. CONFIG
# --------------------------------------------------------------------------- #

@dataclass
class Model2Config:
    """All tunable thresholds live here so they can be re-calibrated against
    the Zenodo Part III benchmark (150 oil / 150 look-alike / 150 clean) without
    touching logic code."""

    # -- Stage A: morphological cleaning --
    min_blob_area_px: int = 40          # drop connected components smaller than this
    morph_open_kernel: int = 3          # speckle-removal opening kernel (odd, px)
    morph_open_iterations: int = 1

    # -- Patch extraction for the CNN --
    patch_size: int = 256
    db_clip_min: float = -30.0
    db_clip_max: float = 0.0

    # -- Physics rule (Delta-dB thresholds from project brief) --
    db_contrast_lookalike_ceiling: float = 1.5   # below this -> confidently look-alike
    db_contrast_oil_floor: float = 3.0           # above this -> confidently mineral oil
    sea_annulus_inner_px: int = 6                # gap from blob edge before sampling "sea"
    sea_annulus_outer_px: int = 20               # width of the sea-sampling ring

    # -- Fusion weights (CNN prior vs physics evidence) --
    cnn_weight: float = 0.7
    physics_weight: float = 0.3

    # -- Final decision threshold on the fused probability --
    oil_confirmation_threshold: float = 0.5

    device: str = "cuda" if (_TORCH_AVAILABLE and torch.cuda.is_available()) else "cpu"


DEFAULT_CONFIG = Model2Config()


# --------------------------------------------------------------------------- #
# 1. MODEL DEFINITION (must match training notebook exactly)
# --------------------------------------------------------------------------- #

if _TORCH_AVAILABLE:

    class EfficientNetB0Verifier(nn.Module):
        """EfficientNet-B0 backbone adapted for 2-channel (VV, VH) dB input.

        The stock timm efficientnet_b0 stem expects 3 input channels (RGB).
        We replace stem conv with a 2-channel version and Kaiming-reinit it,
        rather than faking a 3rd channel — SAR polarimetry is genuinely
        2-channel information and padding with a fake channel would bias the
        learned filters toward RGB-shaped priors.
        """

        def __init__(self, pretrained: bool = True, in_chans: int = 2):
            super().__init__()
            if not _TIMM_AVAILABLE:
                raise ImportError(
                    "timm is required for EfficientNetB0Verifier. "
                    "pip install timm"
                )
            self.backbone = timm.create_model(
                "efficientnet_b0",
                pretrained=pretrained,
                in_chans=in_chans,   # timm handles stem-conv surgery internally
                num_classes=1,       # single logit -> sigmoid -> P(mineral oil)
            )

        def forward(self, x: "torch.Tensor") -> "torch.Tensor":
            return self.backbone(x)  # raw logits, shape (B, 1)


def load_model(checkpoint_path: str, config: Model2Config = DEFAULT_CONFIG):
    """Load a trained EfficientNetB0Verifier checkpoint for inference.

    Expects a state_dict saved by the training notebook
    (see model2_training_colab.ipynb, Cell 9: torch.save(model.state_dict(), ...)).
    """
    if not _TORCH_AVAILABLE:
        raise ImportError("PyTorch is required to load and run Model 2's CNN stage.")

    model = EfficientNetB0Verifier(pretrained=False, in_chans=2)
    state_dict = torch.load(checkpoint_path, map_location=config.device)
    model.load_state_dict(state_dict)
    model.to(config.device)
    model.eval()
    logger.info("Model 2 (EfficientNet-B0 verifier) loaded from %s onto %s", checkpoint_path, config.device)
    return model


# --------------------------------------------------------------------------- #
# 2. STAGE A — MORPHOLOGICAL FORENSIC CLEANING
# --------------------------------------------------------------------------- #

def clean_mask_morphological(
    binary_mask: np.ndarray,
    config: Model2Config = DEFAULT_CONFIG,
) -> tuple[np.ndarray, list[dict[str, Any]]]:
    """Remove scattered radar-speckle blobs from Model 1's raw mask.

    Two-step filter:
      1. Morphological opening (erosion -> dilation) with a small kernel wipes
         out isolated single/few-pixel speckle without shrinking real slicks,
         which are large contiguous dark regions.
      2. Connected-component area filtering drops anything still left that is
         below `min_blob_area_px` (real oil slicks are large, elongated
         features; sensor speckle survives opening only in small clumps).

    Returns
    -------
    cleaned_mask : uint8 array, same shape as input, values {0, 255}
    candidates   : list of dicts, one per surviving blob, each with:
        {"label": int, "area_px": int, "bbox": (x, y, w, h),
         "centroid": (cx, cy), "mask": bool array (blob-only mask)}
    """
    if binary_mask.dtype != np.uint8:
        binary_mask = binary_mask.astype(np.uint8)
    mask_bin = (binary_mask > 0).astype(np.uint8) * 255

    k = max(1, config.morph_open_kernel)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    opened = cv2.morphologyEx(
        mask_bin, cv2.MORPH_OPEN, kernel, iterations=config.morph_open_iterations
    )

    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(
        opened, connectivity=8
    )

    cleaned_mask = np.zeros_like(opened)
    candidates: list[dict[str, Any]] = []

    for label_id in range(1, num_labels):  # skip label 0 = background
        area = int(stats[label_id, cv2.CC_STAT_AREA])
        if area < config.min_blob_area_px:
            continue  # discard as speckle noise
        x = int(stats[label_id, cv2.CC_STAT_LEFT])
        y = int(stats[label_id, cv2.CC_STAT_TOP])
        w = int(stats[label_id, cv2.CC_STAT_WIDTH])
        h = int(stats[label_id, cv2.CC_STAT_HEIGHT])
        blob_mask = labels == label_id
        cleaned_mask[blob_mask] = 255
        candidates.append(
            {
                "label": label_id,
                "area_px": area,
                "bbox": (x, y, w, h),
                "centroid": (float(centroids[label_id, 0]), float(centroids[label_id, 1])),
                "mask": blob_mask,
            }
        )

    # Largest first — the primary candidate for scene-level reporting.
    candidates.sort(key=lambda c: c["area_px"], reverse=True)
    logger.info(
        "Stage A cleaning: %d raw components -> %d candidates after opening+area filter",
        num_labels - 1,
        len(candidates),
    )
    return cleaned_mask, candidates


# --------------------------------------------------------------------------- #
# 3. STAGE B(i) — PHYSICS EVIDENCE (Delta-dB contrast + boundary sharpness)
# --------------------------------------------------------------------------- #

def _get_vv_channel(raw_sar_image: np.ndarray) -> np.ndarray:
    """raw_sar_image may be (H, W) single-pol, or (H, W, 2)/(2, H, W) dual-pol.
    VV is the primary channel for oil/water dB contrast (VH is noisier at low
    backscatter but still informative for the CNN stage)."""
    if raw_sar_image.ndim == 2:
        return raw_sar_image
    if raw_sar_image.ndim == 3:
        if raw_sar_image.shape[0] == 2:       # (2, H, W)
            return raw_sar_image[0]
        if raw_sar_image.shape[-1] == 2:      # (H, W, 2)
            return raw_sar_image[..., 0]
    raise ValueError(f"Unexpected raw_sar_image shape {raw_sar_image.shape}; expected (H,W), (2,H,W) or (H,W,2).")


def compute_db_contrast(
    raw_sar_image: np.ndarray,
    blob_mask: np.ndarray,
    all_candidates_mask: Optional[np.ndarray] = None,
    config: Model2Config = DEFAULT_CONFIG,
) -> float:
    """Delta_dB = mean(sea backscatter) - mean(slick backscatter), on VV.

    The "sea" reference is sampled from an annulus just outside the blob
    boundary (not the whole scene mean, which would be biased by other dark
    or bright features far away). Other candidate blobs are excluded from the
    annulus so a neighbouring slick doesn't contaminate the sea estimate.
    """
    vv = _get_vv_channel(raw_sar_image).astype(np.float32)
    vv = np.clip(vv, config.db_clip_min, config.db_clip_max)

    blob_u8 = blob_mask.astype(np.uint8)
    inner_k = 2 * config.sea_annulus_inner_px + 1
    outer_k = 2 * (config.sea_annulus_inner_px + config.sea_annulus_outer_px) + 1
    dilated_inner = cv2.dilate(blob_u8, np.ones((inner_k, inner_k), np.uint8))
    dilated_outer = cv2.dilate(blob_u8, np.ones((outer_k, outer_k), np.uint8))
    annulus = (dilated_outer.astype(bool)) & (~dilated_inner.astype(bool))

    if all_candidates_mask is not None:
        annulus &= ~all_candidates_mask.astype(bool)

    if not np.any(annulus):
        # Degenerate case (blob touches image edge / no clean sea sampled) —
        # fall back to the full-scene mean excluding the blob itself.
        annulus = ~blob_u8.astype(bool)

    mean_sea = float(np.mean(vv[annulus])) if np.any(annulus) else float(np.mean(vv))
    mean_slick = float(np.mean(vv[blob_mask])) if np.any(blob_mask) else mean_sea

    return mean_sea - mean_slick


def compute_boundary_sharpness(
    raw_sar_image: np.ndarray,
    blob_mask: np.ndarray,
    config: Model2Config = DEFAULT_CONFIG,
) -> float:
    """Boundary sharpness in [0, 1]: mean Sobel gradient magnitude of the VV
    channel sampled along the blob's contour, normalized against the gradient
    scale of the whole scene.

    Real mineral-oil slicks have a comparatively sharp dB step at their edge
    (damping is a near-binary wave state); low-wind look-alikes fade in
    gradually, giving a low score here.
    """
    vv = _get_vv_channel(raw_sar_image).astype(np.float32)
    vv = np.clip(vv, config.db_clip_min, config.db_clip_max)

    gx = cv2.Sobel(vv, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(vv, cv2.CV_32F, 0, 1, ksize=3)
    grad_mag = cv2.magnitude(gx, gy)

    blob_u8 = blob_mask.astype(np.uint8) * 255
    contours, _ = cv2.findContours(blob_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        return 0.0
    boundary_mask = np.zeros_like(blob_u8)
    cv2.drawContours(boundary_mask, contours, -1, 255, thickness=2)
    boundary = boundary_mask.astype(bool)

    if not np.any(boundary):
        return 0.0

    boundary_grad_mean = float(np.mean(grad_mag[boundary]))
    # Normalize against the 95th percentile scene gradient so the score is
    # scene-relative and bounded, rather than depending on absolute dB units.
    scene_grad_p95 = float(np.percentile(grad_mag, 95)) + 1e-6
    sharpness = boundary_grad_mean / scene_grad_p95
    return float(np.clip(sharpness, 0.0, 1.0))


def _physics_confidence(delta_db: float, config: Model2Config = DEFAULT_CONFIG) -> float:
    """Maps Delta-dB onto a [0,1] "physics says it's oil" confidence using the
    two literature/brief-given thresholds as anchor points, linearly
    interpolating the ambiguous band between them."""
    lo, hi = config.db_contrast_lookalike_ceiling, config.db_contrast_oil_floor
    if delta_db <= lo:
        return 0.0
    if delta_db >= hi:
        return 1.0
    return float((delta_db - lo) / (hi - lo))


# --------------------------------------------------------------------------- #
# 4. STAGE B(ii) — CNN EVIDENCE (patch extraction + classification)
# --------------------------------------------------------------------------- #

def _extract_patch(
    raw_sar_image: np.ndarray,
    bbox: tuple[int, int, int, int],
    config: Model2Config = DEFAULT_CONFIG,
) -> np.ndarray:
    """Crop a square, centered, `patch_size`x`patch_size` 2-channel (VV, VH)
    patch around a candidate blob, dB-clipped and normalized to [0, 1].
    Small blobs are padded outward (not just resized) so the CNN sees genuine
    surrounding-sea context, matching how training patches were built."""
    x, y, w, h = bbox
    cx, cy = x + w / 2.0, y + h / 2.0

    if raw_sar_image.ndim == 2:
        img = np.stack([raw_sar_image, raw_sar_image], axis=0)  # duplicate VV into VH slot
    elif raw_sar_image.shape[0] == 2:
        img = raw_sar_image
    else:  # (H, W, 2) -> (2, H, W)
        img = np.transpose(raw_sar_image, (2, 0, 1))

    img = np.clip(img.astype(np.float32), config.db_clip_min, config.db_clip_max)
    _, H, W = img.shape
    ps = config.patch_size

    x0 = int(round(cx - ps / 2))
    y0 = int(round(cy - ps / 2))
    x1, y1 = x0 + ps, y0 + ps

    pad_left = max(0, -x0)
    pad_top = max(0, -y0)
    pad_right = max(0, x1 - W)
    pad_bottom = max(0, y1 - H)

    x0c, y0c = max(0, x0), max(0, y0)
    x1c, y1c = min(W, x1), min(H, y1)
    crop = img[:, y0c:y1c, x0c:x1c]

    if any((pad_left, pad_top, pad_right, pad_bottom)):
        crop = np.pad(
            crop,
            ((0, 0), (pad_top, pad_bottom), (pad_left, pad_right)),
            mode="reflect",
        )

    # normalize dB range to [0, 1]
    crop = (crop - config.db_clip_min) / (config.db_clip_max - config.db_clip_min)
    return crop.astype(np.float32)  # shape (2, patch_size, patch_size)


def classify_patch(model, patch: np.ndarray, config: Model2Config = DEFAULT_CONFIG) -> float:
    """Run the EfficientNet-B0 verifier on a single (2, H, W) patch -> P(oil)."""
    if not _TORCH_AVAILABLE:
        raise ImportError("PyTorch is required for the CNN evidence stage.")
    with torch.no_grad():
        tensor = torch.from_numpy(patch).unsqueeze(0).to(config.device)  # (1, 2, H, W)
        logit = model(tensor)
        prob = torch.sigmoid(logit).item()
    return float(prob)


# --------------------------------------------------------------------------- #
# 5. FUSION + FULL VERIFICATION PIPELINE
# --------------------------------------------------------------------------- #

@dataclass
class BlobVerdict:
    label: int
    area_px: int
    bbox: tuple[int, int, int, int]
    cnn_probability: float
    delta_db: float
    boundary_sharpness: float
    fused_probability: float
    confirmed_oil: bool


def _fuse(cnn_prob: float, delta_db: float, boundary_sharp: float, config: Model2Config) -> float:
    """Weighted fusion of learned (CNN) and physical (Delta-dB) evidence.

    Boundary sharpness is folded into the physics term as a light multiplier
    rather than a third additive weight: a high Delta-dB with a diffuse edge
    is still somewhat suspicious (could be a smeared/aliased look-alike), so
    sharpness modulates confidence in the Delta-dB reading rather than voting
    independently.
    """
    # Sharpness nudges confidence in the Delta-dB reading itself (a hard edge
    # makes a given Delta-dB reading more trustworthy than a diffuse one).
    physics_conf = np.clip(
        _physics_confidence(delta_db, config) * (0.6 + 0.4 * boundary_sharp), 0.0, 1.0
    )
    fused = config.cnn_weight * cnn_prob + config.physics_weight * physics_conf
    return float(np.clip(fused, 0.0, 1.0))


def verify_spill(
    raw_sar_image: np.ndarray,
    binary_mask: np.ndarray,
    model=None,
    config: Model2Config = DEFAULT_CONFIG,
) -> dict[str, Any]:
    """Full Model 2 forensic pipeline. Matches the I/O contract required by
    Task 2 (Geometry Engine) and Task 5 (Attribution Engine).

    Parameters
    ----------
    raw_sar_image : np.ndarray, dB scale, (H,W) or (2,H,W) or (H,W,2) [VV, VH]
    binary_mask   : np.ndarray, uint8, {0, 255}, Model 1's raw output mask
    model         : loaded EfficientNetB0Verifier (via load_model). If None,
                    the CNN stage is skipped and the verdict falls back to
                    physics-only evidence (cnn_weight is redistributed to
                    physics) — useful for physics-only unit testing.

    Returns
    -------
    dict matching the Model 2 output contract, plus one supplementary key
    `blob_level_details` (list[BlobVerdict]) for full explainability in the
    forensic evidence UI (Layer 6) — additive, does not break the contract.
    """
    cleaned_mask, candidates = clean_mask_morphological(binary_mask, config)

    if not candidates:
        return {
            "clean_mask": cleaned_mask,
            "mineral_oil_probability": 0.0,
            "lookalike_risk_score": 1.0,
            "slick_contrast_db": 0.0,
            "boundary_sharpness_score": 0.0,
            "forensic_status": "PROBABLE_LOOKALIKE",
            "proceed_with_attribution": False,
            "evidence_summary": (
                "No candidate contours survived morphological speckle filtering "
                "(all components below min_blob_area_px). No slick evidence to verify."
            ),
            "blob_level_details": [],
        }

    all_candidates_mask = np.zeros_like(cleaned_mask, dtype=bool)
    for c in candidates:
        all_candidates_mask |= c["mask"]

    verdicts: list[BlobVerdict] = []
    final_clean_mask = np.zeros_like(cleaned_mask)

    # If no CNN model supplied, fall back to physics-only fusion.
    effective_cnn_weight = config.cnn_weight if model is not None else 0.0
    effective_physics_weight = config.physics_weight if model is not None else 1.0

    fallback_config = config
    if model is None:
        fallback_config = Model2Config(**{**config.__dict__, "cnn_weight": 0.0, "physics_weight": 1.0})

    for c in candidates:
        delta_db = compute_db_contrast(raw_sar_image, c["mask"], all_candidates_mask, config)
        sharpness = compute_boundary_sharpness(raw_sar_image, c["mask"], config)

        if model is not None:
            patch = _extract_patch(raw_sar_image, c["bbox"], config)
            cnn_prob = classify_patch(model, patch, config)
        else:
            cnn_prob = _physics_confidence(delta_db, config)  # neutral stand-in

        fused = _fuse(cnn_prob, delta_db, sharpness, fallback_config)
        confirmed = fused >= config.oil_confirmation_threshold

        if confirmed:
            final_clean_mask[c["mask"]] = 255

        verdicts.append(
            BlobVerdict(
                label=c["label"],
                area_px=c["area_px"],
                bbox=c["bbox"],
                cnn_probability=cnn_prob,
                delta_db=delta_db,
                boundary_sharpness=sharpness,
                fused_probability=fused,
                confirmed_oil=confirmed,
            )
        )

    confirmed_verdicts = [v for v in verdicts if v.confirmed_oil]
    reporting_pool = confirmed_verdicts if confirmed_verdicts else verdicts

    total_area = sum(v.area_px for v in reporting_pool)
    mineral_oil_probability = (
        sum(v.fused_probability * v.area_px for v in reporting_pool) / total_area
        if total_area > 0
        else 0.0
    )
    primary = max(reporting_pool, key=lambda v: v.area_px)

    forensic_status = "CONFIRMED_MINERAL_OIL" if confirmed_verdicts else "PROBABLE_LOOKALIKE"
    proceed_with_attribution = bool(confirmed_verdicts)

    summary_lines = [
        f"Forensic audit: {len(candidates)} candidate blob(s) after speckle filtering, "
        f"{len(confirmed_verdicts)} confirmed as mineral oil.",
        f"Primary candidate (blob #{primary.label}, area={primary.area_px}px): "
        f"Delta-dB={primary.delta_db:.2f} dB, boundary sharpness={primary.boundary_sharpness:.2f}, "
        f"CNN P(oil)={primary.cnn_probability:.2f}, fused P(oil)={primary.fused_probability:.2f}.",
    ]
    if primary.delta_db >= config.db_contrast_oil_floor:
        summary_lines.append(
            f"Delta-dB exceeds the {config.db_contrast_oil_floor:.1f} dB mineral-oil threshold "
            "(strong capillary-wave damping) — consistent with heavy hydrocarbon."
        )
    elif primary.delta_db <= config.db_contrast_lookalike_ceiling:
        summary_lines.append(
            f"Delta-dB below the {config.db_contrast_lookalike_ceiling:.1f} dB look-alike ceiling "
            "— consistent with a low-wind shadow or biogenic slick, not mineral oil."
        )
    else:
        summary_lines.append(
            "Delta-dB falls in the physically ambiguous band; verdict is CNN-weighted."
        )
    if not confirmed_verdicts:
        summary_lines.append("No blob crossed the oil-confirmation threshold; attribution pipeline will NOT be triggered.")

    return {
        "clean_mask": final_clean_mask,
        "mineral_oil_probability": round(float(mineral_oil_probability), 4),
        "lookalike_risk_score": round(float(1.0 - mineral_oil_probability), 4),
        "slick_contrast_db": round(float(primary.delta_db), 2),
        "boundary_sharpness_score": round(float(primary.boundary_sharpness), 4),
        "forensic_status": forensic_status,
        "proceed_with_attribution": proceed_with_attribution,
        "evidence_summary": " ".join(summary_lines),
        "blob_level_details": verdicts,
    }


# --------------------------------------------------------------------------- #
# 6. SELF-DEMO (synthetic data — sanity-checks the pipeline shape/contract)
# --------------------------------------------------------------------------- #

def _make_synthetic_scene(seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """Builds a synthetic 512x512 2-channel dB scene with:
      - one sharp, high-contrast elliptical 'oil' blob
      - one diffuse, low-contrast blob 'look-alike'
      - scattered 1-3px speckle noise
    Purely for smoke-testing Stage A/B logic without real Sentinel-1 data."""
    rng = np.random.default_rng(seed)
    H, W = 512, 512
    vv = rng.normal(loc=-12.0, scale=1.0, size=(H, W)).astype(np.float32)  # calm sea baseline

    # Sharp oil blob: strong, near-uniform damping (~5 dB) with a hard edge.
    yy, xx = np.ogrid[:H, :W]
    oil_mask = ((xx - 150) ** 2 / 60**2 + (yy - 150) ** 2 / 35**2) <= 1
    vv[oil_mask] -= 5.0

    # Diffuse look-alike: weak damping with a blurred edge.
    lookalike_mask = ((xx - 380) ** 2 / 50**2 + (yy - 350) ** 2 / 50**2) <= 1
    vv[lookalike_mask] -= 1.0
    vv = cv2.GaussianBlur(vv, (0, 0), sigmaX=3)  # blur globally then re-sharpen oil edge
    vv[oil_mask] = vv[oil_mask].mean() - 5.0

    vv = np.clip(vv, -30.0, 0.0)
    vh = vv + rng.normal(0, 0.5, size=(H, W)).astype(np.float32)  # correlated but noisier VH

    raw_sar_image = np.stack([vv, vh], axis=0)  # (2, H, W)

    # Model-1-style noisy mask: true blobs + speckle
    mask = np.zeros((H, W), dtype=np.uint8)
    mask[oil_mask] = 255
    mask[lookalike_mask] = 255
    speckle_coords = rng.integers(0, H, size=(60, 2))
    for yc, xc in speckle_coords:
        mask[yc : yc + 2, xc : xc + 2] = 255

    return raw_sar_image, mask


if __name__ == "__main__":
    logger.info("Running Model 2 self-demo on synthetic SAR scene (no real data, no trained weights)...")
    raw_sar_image, binary_mask = _make_synthetic_scene()

    # No trained checkpoint available in this smoke test -> physics-only fallback.
    result = verify_spill(raw_sar_image, binary_mask, model=None)

    print("\n--- MODEL 2 OUTPUT CONTRACT ---")
    for k, v in result.items():
        if k in ("clean_mask",):
            print(f"{k}: ndarray shape={v.shape}, nonzero_px={int(np.count_nonzero(v))}")
        elif k == "blob_level_details":
            print(f"{k}: {len(v)} blob(s)")
            for bv in v:
                print(f"    - {bv}")
        else:
            print(f"{k}: {v}")
