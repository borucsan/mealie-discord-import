"""Utility functions for the Mealie Discord bot"""

import logging
import re
from typing import Optional, List
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


def extract_urls_from_text(text: str) -> List[str]:
    """
    Extract all URLs from text using regex

    Args:
        text: Input text to search for URLs

    Returns:
        List of found URLs
    """
    # Regex pattern for URLs
    url_pattern = r'https?://[^\s<>"{}|\\^`[\]]+'
    urls = re.findall(url_pattern, text)
    return urls


def is_recipe_url(url: str) -> bool:
    """
    Check if URL is likely a recipe URL based on common patterns

    Args:
        url: URL to check

    Returns:
        True if URL looks like a recipe, False otherwise
    """
    recipe_keywords = [
        'recipe', 'przepis', 'cook', 'kitchen', 'food',
        'gotuj', 'jedzenie', 'kuchnia'
    ]

    url_lower = url.lower()

    # Check URL path for recipe keywords
    for keyword in recipe_keywords:
        if keyword in url_lower:
            return True

    return False


def validate_url(url: str) -> bool:
    """
    Validate if string is a proper URL

    Args:
        url: URL string to validate

    Returns:
        True if valid URL, False otherwise
    """
    try:
        result = urlparse(url)
        return all([result.scheme in ['http', 'https'], result.netloc])
    except:
        return False


def clean_recipe_title(title: str) -> str:
    """
    Clean and normalize recipe title

    Args:
        title: Raw recipe title

    Returns:
        Cleaned title
    """
    if not title:
        return "Przepis bez tytułu"

    # Remove extra whitespace
    title = ' '.join(title.split())

    # Remove common prefixes/suffixes
    prefixes_to_remove = ['Recipe:', 'Przepis:', 'RECIPE:', 'PRZEPIS:']
    for prefix in prefixes_to_remove:
        if title.startswith(prefix):
            title = title[len(prefix):].strip()

    return title


def format_ingredients_list(ingredients: List[str]) -> str:
    """
    Format ingredients list for display

    Args:
        ingredients: List of ingredient strings

    Returns:
        Formatted ingredients string
    """
    if not ingredients:
        return "Brak składników"

    formatted = []
    for i, ingredient in enumerate(ingredients, 1):
        formatted.append(f"{i}. {ingredient.strip()}")

    return '\n'.join(formatted)


def format_instructions_list(instructions: List[str]) -> str:
    """
    Format instructions list for display

    Args:
        instructions: List of instruction strings

    Returns:
        Formatted instructions string
    """
    if not instructions:
        return "Brak instrukcji"

    formatted = []
    for i, instruction in enumerate(instructions, 1):
        formatted.append(f"{i}. {instruction.strip()}")

    return '\n'.join(formatted)


def truncate_text(text: str, max_length: int = 200) -> str:
    """
    Truncate text to specified length with ellipsis

    Args:
        text: Text to truncate
        max_length: Maximum length

    Returns:
        Truncated text
    """
    if len(text) <= max_length:
        return text

    return text[:max_length - 3] + "..."


def sanitize_filename(filename: str) -> str:
    """
    Sanitize filename by removing invalid characters

    Args:
        filename: Original filename

    Returns:
        Sanitized filename
    """
    # Remove invalid characters for filenames
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        filename = filename.replace(char, '_')

    return filename.strip()
