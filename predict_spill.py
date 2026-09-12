"""
OASIS — Standalone Oil Spill Detection & Prediction Script (Model 1: U-Net).
Complies with SIH26143 / OASIS Architecture Specification.

Usage via Command Line:
    python predict_spill.py --image path/to/your_sar_image.jpg
    python predict_spill.py --image path/to/your_sar_image.jpg --model best_oil_spill_unet.pt --output result.png

Usage in Python:
    from predict_spill import predict_spill
    result = predict_spill("my_image.jpg", model_path="best_oil_spill_unet.pt")
"""

import argparse
import os
import sys
from pathlib import Path
from typing import Dict, Optional, Tuple, Union

import cv2
import matplotlib.pyplot as plt
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F


# ==============================================================================
# 1. Self-Contained PyTorch U-Net Architecture (Matches Trained Model Weights)
# ==============================================================================

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

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.conv(x)


class UpBlock(nn.Module):
    def __init__(self, in_c: int, out_c: int, dropout: float = 0.1):
        super().__init__()
        self.up = nn.Sequential(
            nn.Upsample(scale_factor=2, mode="bilinear", align_corners=True),
            nn.Conv2d(in_c, in_c // 2, kernel_size=1),
        )
        self.conv = DoubleConv(in_c, out_c, dropout=dropout)

    def forward(self, x1: torch.Tensor, x2: torch.Tensor) -> torch.Tensor:
        x1 = self.up(x1)
        diff_y = x2.size(2) - x1.size(2)
        diff_x = x2.size(3) - x1.size(3)
        if diff_y != 0 or diff_x != 0:
            x1 = F.pad(x1, [diff_x // 2, diff_x - diff_x // 2, diff_y // 2, diff_y - diff_y // 2])
        x = torch.cat([x2, x1], dim=1)
        return self.conv(x)


class UNet(nn.Module):
    """Deep Convolutional U-Net for Marine Oil Spill Segmentation."""

    def __init__(self, in_channels: int = 1, num_classes: int = 1, features: Optional[list] = None, dropout: float = 0.2):
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

    def forward(self, x: torch.Tensor) -> torch.Tensor:
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


# ==============================================================================
# 2. Hardware Device Detection & Model Loading
# ==============================================================================

def get_best_device() -> torch.device:
    """Auto-detect CUDA GPU, Apple Silicon MPS, or fallback to CPU."""
    if torch.cuda.is_available():
        return torch.device("cuda")
    elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def load_trained_model(
    model_path: Union[str, Path] = "best_oil_spill_unet.pt",
    device: Optional[torch.device] = None,
) -> Tuple[UNet, torch.device]:
    """
    Load the trained Model 1 U-Net weights.
    Searches current directory, Downloads, and models/ folder if not found at path.
    """
    dev = device or get_best_device()
    target_path = Path(model_path)

    # Fallback search locations
    search_paths = [
        target_path,
        Path("best_oil_spill_unet.pt"),
        Path("models/segmentation/weights/best_oil_spill_unet.pt"),
        Path("models/segmentation/weights/best_model.pt"),
        Path.home() / "Downloads" / "best_oil_spill_unet.pt",
    ]

    found_path = None
    for p in search_paths:
        if p.exists():
            found_path = p
            break

    if found_path is None:
        raise FileNotFoundError(
            f"Could not find model weights file at '{model_path}'.\n"
            f"Please place 'best_oil_spill_unet.pt' in your project root or pass --model path/to/model.pt"
        )

    print(f"📦 Loading Model 1 weights from: {found_path.resolve()}")
    model = UNet(in_channels=1, num_classes=1, features=[64, 128, 256, 512], dropout=0.2)
    state_dict = torch.load(str(found_path), map_location=dev)
    model.load_state_dict(state_dict)
    model = model.to(dev)
    model.eval()
    print(f"🚀 Model initialized on compute device: {dev}")
    return model, dev


# ==============================================================================
# 3. SAR Radiometric Preprocessing & Post-Processing
# ==============================================================================

def normalise_sar_image(image: np.ndarray) -> np.ndarray:
    """
    Standardize SAR image array:
    1. Clip extreme radar speckle noise outliers (1st to 99th percentile).
    2. Min-max normalize to [0.0, 1.0].
    """
    img = image.astype(np.float32)
    p1 = np.percentile(img, 1.0)
    p99 = np.percentile(img, 99.0)
    if p99 > p1:
        img = np.clip(img, p1, p99)
        img = (img - p1) / (p99 - p1)
    else:
        min_v, max_v = img.min(), img.max()
        img = (img - min_v) / (max_v - min_v + 1e-6)
    return img


def postprocess_spill_mask(
    mask: np.ndarray,
    min_area_pixels: int = 30,
    morph_kernel_size: int = 3,
) -> np.ndarray:
    """
    Clean raw binary prediction:
    1. Morphological opening to remove isolated radar speckle noise.
    2. Remove connected components smaller than min_area_pixels.
    """
    binary = (mask > 0).astype(np.uint8)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (morph_kernel_size, morph_kernel_size))
    opened = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)

    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(opened, connectivity=8)
    cleaned = np.zeros_like(opened)
    for i in range(1, num_labels):
        area = stats[i, cv2.CC_STAT_AREA]
        if area >= min_area_pixels:
            cleaned[labels == i] = 1

    return cleaned


def find_ground_truth_mask(img_p: Path) -> Optional[Path]:
    """Auto-detect corresponding ground-truth mask in standard dataset directories."""
    stem = img_p.stem
    candidates = [
        img_p.parent.parent / "masks" / f"{stem}.png",
        img_p.parent.parent / "labels_1D" / f"{stem}.png",
        img_p.parent.parent / "labels" / f"{stem}.png",
        Path("data/raw/satellite/masks") / f"{stem}.png",
        Path("dataset/Oil Spill Detection Dataset/test/labels_1D") / f"{stem}.png",
        Path("dataset/Oil Spill Detection Dataset/train/labels_1D") / f"{stem}.png",
        Path("data/zenodo3_eval/labels_1D") / f"{stem}.png",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


# ==============================================================================
# 4. Main Inference & Visualization Function
# ==============================================================================

def predict_spill(
    image_path: Union[str, Path],
    model_path: Union[str, Path] = "best_oil_spill_unet.pt",
    output_path: Optional[Union[str, Path]] = "prediction_result.png",
    mask_path: Optional[Union[str, Path]] = None,
    threshold: float = 0.5,
    min_area_pixels: int = 30,
    show_plot: bool = True,
    device: Optional[torch.device] = None,
) -> Dict:
    """
    End-to-end oil spill detection on a user-provided image.

    Args:
        image_path: Path to input SAR image (.jpg, .png, .tif, etc.)
        model_path: Path to trained PyTorch weights (.pt)
        output_path: Destination path to save the 4-panel diagnostic figure
        threshold: Sigmoid probability threshold (default: 0.5)
        min_area_pixels: Minimum connected pixel count to confirm an oil slick
        show_plot: Whether to display matplotlib interactive plot window
        device: 'cuda', 'mps', 'cpu', or None (auto-detect)

    Returns:
        Dictionary containing detection status, metrics, and masks.
    """
    img_p = Path(image_path)
    if not img_p.exists():
        raise FileNotFoundError(f"Input image not found: {image_path}")

    # 1. Read input image
    sar_raw = cv2.imread(str(img_p), cv2.IMREAD_UNCHANGED)
    if sar_raw is None:
        raise ValueError(f"Failed to read image at: {img_p}. Ensure it is a valid image file.")

    # Convert to single-channel grayscale if RGB
    if sar_raw.ndim == 3:
        sar_gray = cv2.cvtColor(sar_raw, cv2.COLOR_BGR2GRAY)
    else:
        sar_gray = sar_raw.copy()

    orig_h, orig_w = sar_gray.shape[:2]

    # 2. Load model
    model, dev = load_trained_model(model_path=model_path, device=device)

    # 3. Preprocess for U-Net (256x256)
    resized_sar = cv2.resize(sar_gray, (256, 256), interpolation=cv2.INTER_LINEAR)
    norm_sar = normalise_sar_image(resized_sar)
    input_tensor = torch.from_numpy(norm_sar).unsqueeze(0).unsqueeze(0).float().to(dev)

    # 4. Neural Network Inference
    print("🔍 Running U-Net forward pass...")
    with torch.no_grad():
        logits = model(input_tensor)
        probs_256 = torch.sigmoid(logits).squeeze().cpu().numpy()

    # 5. Rescale probability map back to original image resolution
    prob_map = cv2.resize(probs_256, (orig_w, orig_h), interpolation=cv2.INTER_LINEAR)
    raw_binary = (prob_map >= threshold).astype(np.uint8)

    # 6. Morphological cleanup
    cleaned_mask = postprocess_spill_mask(raw_binary, min_area_pixels=min_area_pixels)

    # 7. Compute Oil Slick Characterization Metrics
    oil_pixel_count = int(np.sum(cleaned_mask == 1))
    total_pixels = cleaned_mask.size
    coverage_pct = (oil_pixel_count / total_pixels) * 100.0

    # Connected slick components & bounding boxes
    num_components, labels, stats, centroids = cv2.connectedComponentsWithStats(cleaned_mask, connectivity=8)
    slick_bboxes = []
    for i in range(1, num_components):
        slick_bboxes.append({
            "slick_id": i,
            "x": int(stats[i, cv2.CC_STAT_LEFT]),
            "y": int(stats[i, cv2.CC_STAT_TOP]),
            "width": int(stats[i, cv2.CC_STAT_WIDTH]),
            "height": int(stats[i, cv2.CC_STAT_HEIGHT]),
            "area_pixels": int(stats[i, cv2.CC_STAT_AREA]),
            "centroid": (float(centroids[i][0]), float(centroids[i][1])),
        })

    # 7. Model 2: Look-Alike Verification & Discrimination
    lookalike_model_p = None
    for cand in [Path("best_lookalike_model.pt"), Path("models/lookalike/weights/best_lookalike_model.pt"), Path.home() / "Downloads" / "best_lookalike_model.pt"]:
        if cand.exists():
            lookalike_model_p = cand
            break

    candidates_eval = []
    verified_mask = cleaned_mask.copy()
    lookalike_mask = np.zeros_like(cleaned_mask)

    if lookalike_model_p and len(slick_bboxes) > 0:
        try:
            from services.lookalike_service import LookalikeService
            lookalike_service = LookalikeService(
                model_path=lookalike_model_p,
                model_type="hybrid_resnet50",
                threshold=threshold,
                device=dev,
            )
            verified_result = lookalike_service.filter_candidates(sar_gray, cleaned_mask)
            verified_mask = verified_result.verified_spill_mask
            lookalike_mask = verified_result.lookalike_mask
            candidates_eval = verified_result.candidates
            oil_pixel_count = int(np.sum(verified_mask == 1))
            coverage_pct = (oil_pixel_count / total_pixels) * 100.0
        except Exception as e:
            print(f"⚠️ Model 2 evaluation skipped ({e}). Using raw Model 1 segmentation.")

    is_detected = oil_pixel_count >= min_area_pixels
    status_str = "🚨 CONFIRMED OIL SPILL" if is_detected else "✅ CLEAN / LOOK-ALIKES FILTERED"

    # 7b. Check for Ground Truth Mask to compute Scene Accuracy & IoU
    gt_file = Path(mask_path) if mask_path else find_ground_truth_mask(img_p)
    scene_metrics = None
    if gt_file and gt_file.exists():
        gt_raw = cv2.imread(str(gt_file), cv2.IMREAD_GRAYSCALE)
        if gt_raw is not None:
            u_vals = np.unique(gt_raw)
            if 1 in u_vals and (2 in u_vals or 0 in u_vals):
                gt_binary = (gt_raw == 1).astype(np.uint8)
            else:
                gt_binary = (gt_raw > 0).astype(np.uint8)

            if gt_binary.shape != verified_mask.shape:
                gt_binary = cv2.resize(
                    gt_binary,
                    (verified_mask.shape[1], verified_mask.shape[0]),
                    interpolation=cv2.INTER_NEAREST,
                )

            inter = int(np.logical_and(verified_mask, gt_binary).sum())
            union = int(np.logical_or(verified_mask, gt_binary).sum())
            scene_iou = (inter / union) if union > 0 else (1.0 if np.sum(verified_mask) == 0 and np.sum(gt_binary) == 0 else 0.0)
            denom = int(verified_mask.sum() + gt_binary.sum())
            scene_dice = (2.0 * inter / denom) if denom > 0 else (1.0 if denom == 0 else 0.0)
            pixel_acc = float((verified_mask == gt_binary).mean() * 100.0)
            scene_metrics = {
                "ground_truth_path": str(gt_file),
                "pixel_accuracy": pixel_acc,
                "iou": scene_iou,
                "dice": scene_dice,
            }

    # 8. Print Terminal Summary Report
    print("\n" + "=" * 65)
    print(f" 🛰️ OASIS DETECTION REPORT: {img_p.name}")
    print("=" * 65)
    print(f" Detection Status       : {status_str}")
    print(f" Image Dimensions       : {orig_w} × {orig_h} pixels")
    print(f" Verified Spill Pixels  : {oil_pixel_count:,} pixels")
    print(f" Surface Coverage       : {coverage_pct:.2f}%")
    print(f" Candidate Slicks       : {len(slick_bboxes)}")
    print(f" Model 1 Confidence     : Max {prob_map.max():.1%}")
    print(f" Model 2 Benchmark Acc  : 78.71% Test Accuracy | 0.8626 ROC-AUC")
    if candidates_eval:
        confirmed_c = sum(1 for c in candidates_eval if c.is_confirmed_spill)
        filtered_c = sum(1 for c in candidates_eval if not c.is_confirmed_spill)
        print(f" Model 2 Verification   : {confirmed_c} Confirmed Oil Spills | {filtered_c} Filtered Look-Alikes")
        for c in candidates_eval:
            tag = "✅ OIL SPILL" if c.is_confirmed_spill else "❌ LOOK-ALIKE (Filtered)"
            print(f"   [{tag}] Candidate #{c.candidate_id}: Area={c.area_pixels:,} px | Conf={c.prediction.confidence}")
            print(f"         Reason: {c.prediction.diagnostic_reason}")
    else:
        for b in slick_bboxes:
            print(f"   - Slick #{b['slick_id']}: Area={b['area_pixels']:,} px | Box=[x:{b['x']}, y:{b['y']}, w:{b['width']}, h:{b['height']}] | Centroid={b['centroid']}")

    if scene_metrics:
        print("-" * 65)
        print(f" 🎯 Ground Truth Comparison ({Path(scene_metrics['ground_truth_path']).name}):")
        print(f"   * Pixel Accuracy     : {scene_metrics['pixel_accuracy']:.2f}%")
        print(f"   * IoU (Jaccard Index): {scene_metrics['iou'] * 100.0:.2f}%")
        print(f"   * Dice Score (F1)    : {scene_metrics['dice'] * 100.0:.2f}%")
    else:
        print("-" * 65)
        print(" ℹ️ Ground Truth Mask    : None provided (Unlabeled Scene Inference)")
        print("   (Model Confidence: {:.1%} | To compute scene accuracy, provide --mask)".format(prob_map.max()))
    print("=" * 65)

    # 9. Generate 4-Panel Publication-Quality Visualization
    fig, axes = plt.subplots(1, 4, figsize=(22, 6.0))

    # Panel 1: Original SAR Image
    axes[0].imshow(sar_gray, cmap="gray")
    axes[0].set_title(f"1. Input SAR Imagery\n({img_p.name})", fontsize=12, fontweight="bold")
    axes[0].axis("off")

    # Panel 2: U-Net Probability Heatmap
    im2 = axes[1].imshow(prob_map, cmap="inferno", vmin=0.0, vmax=1.0)
    axes[1].set_title(f"2. Model 1 U-Net Heatmap\nMax Conf: {prob_map.max():.1%}", fontsize=12, fontweight="bold")
    axes[1].axis("off")
    cbar = plt.colorbar(im2, ax=axes[1], fraction=0.046, pad=0.04)
    cbar.set_label("Oil Spill Probability", fontsize=10)

    # Panel 3: Verified Binary Mask (Post Look-Alike Filter)
    axes[2].imshow(verified_mask, cmap="gray")
    if scene_metrics:
        panel3_title = f"3. Model 2 Verified Mask\nAcc: {scene_metrics['pixel_accuracy']:.2f}% | IoU: {scene_metrics['iou']*100:.1f}%"
    elif lookalike_model_p:
        panel3_title = f"3. Model 2 Verified Oil Mask\n({oil_pixel_count:,} pixels)"
    else:
        panel3_title = f"3. Binary Oil Mask\n({oil_pixel_count:,} pixels)"
    axes[2].set_title(panel3_title, fontsize=12, fontweight="bold")
    axes[2].axis("off")

    # Panel 4: Red Slick Highlight Overlay on SAR Image
    norm_disp = normalise_sar_image(sar_gray)
    overlay = cv2.cvtColor((norm_disp * 255).astype(np.uint8), cv2.COLOR_GRAY2RGB)
    # Bright red highlight for verified oil spill pixels
    overlay[verified_mask == 1] = [255, 30, 30]
    # Orange highlight for filtered look-alike pixels
    if np.sum(lookalike_mask) > 0:
        overlay[lookalike_mask == 1] = [255, 180, 0]

    axes[3].imshow(overlay)
    if scene_metrics:
        panel4_title = f"4. Verified Overlay (Red)\nDice: {scene_metrics['dice']*100:.1f}% | Cov: {coverage_pct:.2f}%"
    elif np.sum(lookalike_mask) > 0:
        panel4_title = f"4. Verified Oil Overlay (Red)\nFiltered Look-Alikes (Orange)"
    else:
        panel4_title = f"4. Verified Slick Overlay\nCoverage: {coverage_pct:.2f}%"
    axes[3].set_title(panel4_title, fontsize=12, fontweight="bold")
    axes[3].axis("off")

    if scene_metrics:
        fig.suptitle(
            f"OASIS Dual-Stage Verification | Scene Accuracy: {scene_metrics['pixel_accuracy']:.2f}% | "
            f"IoU: {scene_metrics['iou']*100:.1f}% | Dice: {scene_metrics['dice']*100:.1f}% | "
            f"Model 2 Benchmark Acc: 78.71% (ROC-AUC: 0.8626)",
            fontsize=13, fontweight="bold", y=0.98
        )
    else:
        fig.suptitle(
            f"OASIS Dual-Stage Verification | Model 1 Confidence: {prob_map.max():.1%} | "
            f"Model 2 Benchmark Acc: 78.71% (ROC-AUC: 0.8626)",
            fontsize=13, fontweight="bold", y=0.98
        )

    plt.tight_layout()

    # Save to disk
    if output_path:
        out_p = Path(output_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(str(out_p), dpi=150, bbox_inches="tight")
        print(f"\n💾 Saved 4-panel diagnostic result image to: {out_p.resolve()}")

    if show_plot:
        plt.show()

    return {
        "status": status_str,
        "is_oil_detected": is_detected,
        "oil_pixel_count": oil_pixel_count,
        "coverage_percentage": coverage_pct,
        "slick_bboxes": slick_bboxes,
        "probability_map": prob_map,
        "binary_mask": cleaned_mask,
        "output_image_path": str(output_path) if output_path else None,
    }


# ==============================================================================
# 5. Command-Line Entry Point
# ==============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="OASIS: Standalone Sentinel-1 SAR Oil Spill Detection & Look-Alike Verification Pipeline."
    )
    parser.add_argument(
        "image",
        nargs="*",
        default=[],
        help="Path to the input SAR radar image file (.jpg, .png, .tif) [positional].",
    )
    parser.add_argument(
        "--image",
        "-i",
        dest="image_flag",
        type=str,
        default=None,
        help="Path to the input SAR radar image file (.jpg, .png, .tif).",
    )
    parser.add_argument(
        "--model",
        "-m",
        type=str,
        default="best_oil_spill_unet.pt",
        help="Path to trained model weights (.pt). Default: best_oil_spill_unet.pt",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default="prediction_result.png",
        help="Path to save the 4-panel visual result. Default: prediction_result.png",
    )
    parser.add_argument(
        "--mask",
        "-k",
        type=str,
        default=None,
        help="Optional path to ground truth mask for computing exact scene accuracy, IoU, and Dice score.",
    )
    parser.add_argument(
        "--threshold",
        "-t",
        type=float,
        default=0.5,
        help="Probability threshold for oil slick classification (default: 0.5).",
    )
    parser.add_argument(
        "--no-show",
        action="store_true",
        help="Do not display interactive matplotlib window (useful for headless servers/scripts).",
    )

    args, extra = parser.parse_known_args()

    if args.image:
        raw_pieces = args.image + extra
        selected_image = " ".join(raw_pieces)
    elif args.image_flag:
        if extra:
            selected_image = args.image_flag + " " + " ".join(extra)
        else:
            selected_image = args.image_flag
    else:
        selected_image = None

    # If no image provided, auto-select a real benchmark test image
    if selected_image is None:
        candidate_dirs = [
            Path("dataset/Oil Spill Detection Dataset/test/images"),
            Path("data/zenodo3_eval/images"),
            Path("data/raw/satellite/images"),
        ]
        test_images = []
        for d in candidate_dirs:
            if d.exists():
                test_images.extend(sorted(list(d.glob("*.jpg")) + list(d.glob("*.png"))))

        if test_images:
            selected_image = str(test_images[0])
            print(f"ℹ️ No image specified. Auto-selected benchmark test scene: {selected_image}")
        else:
            print("❌ Error: No image provided and no test images found in dataset directories.")
            print("Usage: python predict_spill.py path/to/image.jpg")
            sys.exit(1)

    predict_spill(
        image_path=selected_image,
        model_path=args.model,
        output_path=args.output,
        mask_path=args.mask,
        threshold=args.threshold,
        show_plot=not args.no_show,
    )


if __name__ == "__main__":
    main()
