"""
Image variant specifications for the Resource model.

Uses django-imagekit ImageSpec classes with ResizeToFit processors and WEBP output.
Variants are generated lazily on first .url access and cached in S3/local storage.

Sizes:
  thumbnail — max 300px (cards, avatars, thumbnails)
  medium    — max 1200px (standard content, feeds)
  large     — max 1920px (hero banners, full-screen backgrounds)
"""
from imagekit import ImageSpec
from imagekit.processors import ResizeToFit, Transpose


class ThumbnailSpec(ImageSpec):
    """300px WEBP thumbnail — cards, grid previews, small avatars."""
    processors = [Transpose(), ResizeToFit(width=300, height=300, upscale=False)]
    format = 'WEBP'
    options = {'quality': 80}


class MediumSpec(ImageSpec):
    """1200px WEBP — standard content images, feeds, modals."""
    processors = [Transpose(), ResizeToFit(width=1200, height=1200, upscale=False)]
    format = 'WEBP'
    options = {'quality': 85}


class LargeSpec(ImageSpec):
    """1920px WEBP — hero banners, full-width backgrounds."""
    processors = [Transpose(), ResizeToFit(width=1920, height=1920, upscale=False)]
    format = 'WEBP'
    options = {'quality': 88}
