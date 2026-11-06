"""Typed errors for the Mistral OCR integration.

Every error carries a ``user_message`` that is safe to show to end users
(no API keys, no document content, no raw HTTP bodies).
"""

from __future__ import annotations


class MistralOcrError(Exception):
    """Base class for all OCR integration errors."""

    user_message = "OCR processing failed."

    def __init__(self, message: str = "", user_message: str | None = None):
        super().__init__(message or self.user_message)
        if user_message is not None:
            self.user_message = user_message


class InvalidBaseUrlError(MistralOcrError):
    user_message = "The configured Mistral API base URL is invalid. Only HTTPS URLs are allowed."


class InvalidApiKeyError(MistralOcrError):
    user_message = "The Mistral API key is invalid or not authorized. Check the key in the admin settings."


class QuotaExceededError(MistralOcrError):
    user_message = "The Mistral API quota or rate limit was exceeded. Try again later."


class UnsupportedFileError(MistralOcrError):
    user_message = "This file type is not supported by Mistral OCR."


class FileTooLargeError(MistralOcrError):
    user_message = "The file exceeds the configured maximum size for OCR processing."


class TooManyPagesError(MistralOcrError):
    user_message = "The document exceeds the configured maximum page count for OCR processing."


class ApiTimeoutError(MistralOcrError):
    user_message = "The Mistral OCR API did not respond in time. Try again later."


class ApiServerError(MistralOcrError):
    user_message = "The Mistral OCR API returned a server error. Try again later."


class ApiResponseError(MistralOcrError):
    user_message = "The Mistral OCR API returned an unexpected response."


class FileNotFoundError_(MistralOcrError):
    user_message = "The file could not be found in Nextcloud."


class MimeTypeNotAllowedError(MistralOcrError):
    user_message = "This file type is not enabled for OCR in the admin settings."


class MissingApiKeyError(MistralOcrError):
    user_message = "No Mistral API key is configured. Set one in the admin settings."
