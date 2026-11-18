"""Style profiles for the Phase 3 Asset Generator.

A style profile is DATA, not code: it describes a rendering mode and
how that mode maps onto the existing 1.0 sprite pipeline
(`pipeline_sprite.SpriteOptions.style`). Honesty rules:

  - Only modes the current pipeline actually supports are `enabled`.
    `pipeline_sprite` maps style "default" / "2.5d" / "3d" / "chibi"
    onto SDXL-Turbo prompt suffixes (and the mock backend); there is
    no pixel-art mode, no palette quantizer and no outline pass in the
    pipeline, so the pixel profile exists in the data structure but is
    disabled with a concrete reason.
  - Style values that must come from analyzing real Espil reference
    assets (Phase 1 honesty rule: pixel scale, outline, antialiasing)
    stay None. They are carried per profile under `style_profile`,
    linked to the Phase 1 asset-standard schema version, and are NOT
    invented here.
  - Palette / color limits are None (unmeasured, unenforced) unless a
    profile states a pipeline-real behaviour.
"""

from __future__ import annotations

from asset_standard import SCHEMA_VERSION as ASSET_STANDARD_SCHEMA_VERSION


class GeneratorError(Exception):
    """Raised when a generation request is invalid or refused."""


# The pipeline styles pipeline_sprite actually implements.
PIPELINE_STYLES = ("default", "2.5d", "3d", "chibi")

_COMMON_STYLE_PROFILE = {
    # Filled only from real Phase 1 analyses of Espil reference assets.
    "asset_standard_schema_version": ASSET_STANDARD_SCHEMA_VERSION,
    "pixel_scale": None,
    "outline": None,
    "antialiasing": None,
}


def _profile(profile_id, rendering_mode, pipeline_style, enabled,
             disabled_reason, target_width, target_height,
             transparent_background, post_processing):
    return {
        "profile_id": profile_id,
        "rendering_mode": rendering_mode,
        "pipeline_style": pipeline_style,
        "enabled": enabled,
        "disabled_reason": disabled_reason,
        "target_size": {"width": target_width, "height": target_height},
        # No palette limit is measured or enforced by the pipeline.
        "palette_limit": None,
        # Outline handling is a prompt-level description in the
        # pipeline suffixes only; there is no outline post-pass.
        "outline": None,
        "transparent_background": transparent_background,
        "resize_sampling": "pillow-default (pipeline performs no "
                           "resize; output is generated at target size)",
        "post_processing": post_processing,
        "style_profile": dict(_COMMON_STYLE_PROFILE),
    }


STYLE_PROFILES = {
    "sprite-default": _profile(
        "sprite-default", "smooth", "default", True, None, 512, 512,
        "rembg background removal with binarized alpha (real backend); "
        "mock backend draws on a transparent canvas directly",
        ["background_removal (non-mock only)", "crisp_alpha (non-mock only)"],
    ),
    "sprite-2.5d": _profile(
        "sprite-2.5d", "2.5d", "2.5d", True, None, 512, 512,
        "same as sprite-default",
        ["background_removal (non-mock only)", "crisp_alpha (non-mock only)"],
    ),
    "model-3d-look": _profile(
        "model-3d-look", "3d", "3d", True, None, 512, 512,
        "same as sprite-default",
        ["background_removal (non-mock only)", "crisp_alpha (non-mock only)"],
    ),
    "chibi": _profile(
        "chibi", "3d", "chibi", True, None, 512, 512,
        "same as sprite-default",
        ["background_removal (non-mock only)", "crisp_alpha (non-mock only)"],
    ),
    "pixel": _profile(
        "pixel", "pixel", None, False,
        "pipeline_sprite has no pixel-art rendering mode: its styles "
        "are default/2.5d/3d/chibi prompt suffixes on SDXL-Turbo, and "
        "there is no pixelation, palette-quantization or "
        "nearest-neighbour downscale step anywhere in the pipeline",
        512, 512,
        "not applicable (profile disabled)",
        [],
    ),
}


def list_profiles() -> list:
    """Return all style profiles (enabled and disabled), as copies."""
    return [dict(p, target_size=dict(p["target_size"]),
                 style_profile=dict(p["style_profile"]))
            for p in STYLE_PROFILES.values()]


def get_profile(profile_id) -> dict:
    """Return one profile by id; raises GeneratorError when unknown."""
    try:
        p = STYLE_PROFILES[profile_id]
    except (KeyError, TypeError):
        raise GeneratorError(
            f"unknown style profile {profile_id!r}; must be one of: "
            + ", ".join(sorted(STYLE_PROFILES))) from None
    return dict(p, target_size=dict(p["target_size"]),
                style_profile=dict(p["style_profile"]))
