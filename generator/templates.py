"""Category prompt templates for the Phase 3 Asset Generator.

One template per Phase 2 category. Templates are data: each is a
string with a single ``{prompt}`` placeholder for the user's prompt.
`compose_prompt` returns the composed prompt; the user's original
prompt text is always preserved verbatim alongside it in the
generation job record (see generate.py) - composition never replaces
the record of what the user actually wrote.

The templates only frame the subject as a single, fully visible game
sprite asset for its slot. Style suffixes beyond this (sprite /
2.5D / 3D / chibi framing) are appended by pipeline_sprite itself
according to the selected style profile.
"""

from __future__ import annotations

from reference.upload import validate_category

from .profiles import GeneratorError

# Keys are exactly the Phase 2 category set (reference.upload.CATEGORIES);
# a test asserts the two sets match.
CATEGORY_TEMPLATES = {
    "Hair": "a {prompt}, hairstyle sprite asset worn on a chibi "
            "character head, hair only, single item",
    "Face": "a {prompt}, face feature sprite asset for a chibi "
            "character face, facial feature only, single item",
    "Top": "a {prompt}, upper-body clothing sprite asset for a chibi "
           "character, top garment only, single item",
    "Bottom": "a {prompt}, lower-body clothing sprite asset for a "
              "chibi character, bottom garment only, single item",
    "One-piece": "a {prompt}, one-piece outfit sprite asset for a "
                 "chibi character, full garment only, single item",
    "Shoes": "a {prompt}, footwear sprite asset for a chibi character, "
             "pair of shoes only, single item",
    "Armor": "a {prompt}, armor sprite asset for a chibi character, "
             "armor piece only, single item",
    "Weapon": "a {prompt}, weapon sprite asset held by a chibi "
              "character, weapon only, single item",
    "Accessory": "a {prompt}, accessory sprite asset for a chibi "
                 "character, accessory only, single item",
    "Effects": "a {prompt}, visual effect sprite asset, effect only, "
               "single element",
}


def compose_prompt(category, user_prompt: str) -> str:
    """Compose the full generation prompt for `category`.

    Raises GeneratorError for an unknown category (via the Phase 2
    category validation) or an empty user prompt.
    """
    validate_category(category)
    if not user_prompt or not str(user_prompt).strip():
        raise GeneratorError("user prompt must not be empty")
    return CATEGORY_TEMPLATES[category].format(prompt=user_prompt)
