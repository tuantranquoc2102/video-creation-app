"""Generator package – dispatches to the right video generator."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

from core.generators.dialogue import generate as generate_dialogue
from core.generators.vocabulary import generate as generate_vocabulary

if TYPE_CHECKING:
    from collections.abc import Callable

# Registry: csv_type → generator function
_GENERATORS: dict[str, Callable[..., str]] = {
    "dialogue": generate_dialogue,
    "vocabulary": generate_vocabulary,
}


def generate_video(
    csv_type: str,
    df: pd.DataFrame,
    *,
    name: str,
    lang: str = "vi",
    size: tuple[int, int] = (1920, 1080),
    bg_color: str = "#1a1a2e",
    bg_images: list[str] | None = None,
    fps: int = 30,
    fmt: str = "mp4",
    progress_cb: Callable[[int, int], None] | None = None,
    **extra_opts,
) -> str:
    """Dispatch to the correct generator based on *csv_type*.

    Parameters
    ----------
    bg_images : list[str] | None
        Absolute paths to background image files.  When provided, images
        are used instead of *bg_color* (cycled for each scene).

    Returns the absolute path to the output video file.

    Raises ``ValueError`` if *csv_type* is not registered.
    """
    gen_fn = _GENERATORS.get(csv_type)
    if gen_fn is None:
        raise ValueError(
            f"Không có generator cho loại CSV '{csv_type}'. "
            f"Các loại hỗ trợ: {', '.join(_GENERATORS)}"
        )

    return gen_fn(
        df,
        name=name,
        lang=lang,
        size=size,
        bg_color=bg_color,
        bg_images=bg_images,
        fps=fps,
        fmt=fmt,
        progress_cb=progress_cb,
        **extra_opts,
    )
