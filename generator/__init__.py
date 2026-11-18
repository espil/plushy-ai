"""Plushy-AI 2.0 Espil Style / Asset Generator (Phase 3).

Library + CLI only: no server or UI wiring in this package (Phase 6
wires it into the Studio). Reuses by importing - never modifying -
the 1.0 sprite pipeline (`pipeline_sprite`, imported lazily so this
package imports cleanly on machines without torch/diffusers or a
GPU), the Phase 1 Asset Standard Engine (`asset_standard`), and the
Phase 2 Reference Analyzer (`reference`).

Rules (Plushy-AI 2.0 development prompt, Phase 3):
  - Only pipeline-supported style modes are enabled; unsupported
    modes stay in the profile data, disabled with a reason.
  - The backend (mock vs sdxl) is stated plainly in every job
    record; a mock placeholder is never recorded as a real
    generation.
  - Region-targeted reference generation requires a Phase 2
    confirmed, non-empty mask generation target. Whole-image img2img
    records region: None.
  - Inpainting is unsupported by the current pipeline and is
    recorded as such - never faked.
  - Unmeasured Espil style values stay None (Phase 1 honesty rule).
"""

from .generate import (
    COMPARE_SCHEMA_VERSION,
    INPAINTING_STATUS,
    JOB_SCHEMA_VERSION,
    backend_name,
    compare_with_baseline,
    derive_seed,
    generate_job_id,
    inpainting_status,
    run_generation,
)
from .profiles import (
    PIPELINE_STYLES,
    STYLE_PROFILES,
    GeneratorError,
    get_profile,
    list_profiles,
)
from .templates import CATEGORY_TEMPLATES, compose_prompt

__all__ = [
    "CATEGORY_TEMPLATES",
    "COMPARE_SCHEMA_VERSION",
    "INPAINTING_STATUS",
    "JOB_SCHEMA_VERSION",
    "PIPELINE_STYLES",
    "STYLE_PROFILES",
    "GeneratorError",
    "backend_name",
    "compare_with_baseline",
    "compose_prompt",
    "derive_seed",
    "generate_job_id",
    "get_profile",
    "inpainting_status",
    "list_profiles",
    "run_generation",
]
