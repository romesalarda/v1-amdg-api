"""
Custom storage backends for AWS S3
"""
from storages.backends.s3boto3 import S3Boto3Storage


class MediaStorage(S3Boto3Storage):
    """Custom storage for media files"""
    location = ''
    file_overwrite = False


class VariantMediaStorage(S3Boto3Storage):
    """Storage for django-imagekit generated variant files.

    Variants are content-hash-addressed by imagekit, so their filenames
    never change for a given source file. This makes it safe to serve
    them with ``Cache-Control: max-age=31536000, immutable`` — Cloudflare
    will cache them aggressively and clients will never receive stale data.
    """
    location = ''
    file_overwrite = True  # imagekit manages its own filename hashing

    object_parameters = {
        'CacheControl': 'max-age=31536000, immutable',
    }
