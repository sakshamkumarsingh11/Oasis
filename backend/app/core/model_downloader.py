"""
Centralized model downloader — fetches .pt weights from Hugging Face Hub.

Models are cached locally after the first download, so subsequent runs
load instantly without any network call.
"""

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("model_downloader")

# ── Hugging Face repository ────────────────────────────────────────────────
HF_REPO_ID = "KrrishDangi/OASIS-models"

# Mapping: logical name → filename on the Hub
MODEL_REGISTRY = {
    "unet": "best_oil_spill_unet.pt",
    "lookalike": "best_lookalike_model.pt",
}


def download_model(model_name: str) -> Optional[Path]:
    """Download a model from Hugging Face Hub and return the local cached path.

    Parameters
    ----------
    model_name : str
        Logical name of the model (key in ``MODEL_REGISTRY``).
        Accepted values: ``"unet"`` | ``"lookalike"``.

    Returns
    -------
    Path | None
        Absolute path to the cached weights file, or ``None`` if the
        download failed (network error, missing file on Hub, etc.).
    """
    filename = MODEL_REGISTRY.get(model_name)
    if filename is None:
        logger.error("Unknown model name '%s'. Available: %s", model_name, list(MODEL_REGISTRY))
        return None

    try:
        from huggingface_hub import hf_hub_download

        cached_path = hf_hub_download(
            repo_id=HF_REPO_ID,
            filename=filename,
        )
        logger.info("Model '%s' ready at %s", model_name, cached_path)
        return Path(cached_path)

    except ImportError:
        logger.warning(
            "huggingface_hub is not installed. "
            "Install it with:  pip install huggingface_hub"
        )
        return None

    except Exception as exc:
        logger.warning("Failed to download '%s' from %s: %s", filename, HF_REPO_ID, exc)
        return None
