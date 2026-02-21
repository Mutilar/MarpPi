"""
Template loading and rendering utilities.

Provides simple template loading from the templates/ directory with
variable substitution support.
"""

import os
from functools import lru_cache
from typing import Dict, Optional

# Path to templates directory (relative to this file)
TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), 'templates')


@lru_cache(maxsize=16)
def _load_file(filename: str) -> str:
    """Load a file from the templates directory (cached).
    
    Args:
        filename: Name of the file to load (e.g., 'base.css', 'viewer.html')
        
    Returns:
        File contents as string
        
    Raises:
        FileNotFoundError: If template file doesn't exist
    """
    filepath = os.path.join(TEMPLATES_DIR, filename)
    with open(filepath, 'r', encoding='utf-8') as f:
        return f.read()


def load_css(filename: str = 'base.css') -> str:
    """Load a CSS file from the templates directory.
    
    Args:
        filename: CSS filename (default: 'base.css')
        
    Returns:
        CSS content as string
    """
    return _load_file(filename)


def render_template(template_name: str, **variables) -> str:
    """Load and render an HTML template with variable substitution.
    
    Supports simple {{variable}} placeholders. The 'base_css' variable
    is automatically populated with the contents of base.css if not provided.
    
    Args:
        template_name: Name of the HTML template file
        **variables: Variables to substitute in the template
        
    Returns:
        Rendered HTML string
        
    Example:
        html = render_template('viewer.html', 
                               stream_id='main',
                               stream_buttons='<button>Main</button>')
    """
    template = _load_file(template_name)
    
    # Auto-inject base CSS if not provided
    if 'base_css' not in variables:
        variables['base_css'] = load_css('base.css')
    
    # Simple {{variable}} substitution
    for key, value in variables.items():
        placeholder = '{{' + key + '}}'
        template = template.replace(placeholder, str(value))
    
    return template


def clear_cache() -> None:
    """Clear the template cache.
    
    Call this during development if templates are modified at runtime.
    """
    _load_file.cache_clear()


def get_template_path(filename: str) -> str:
    """Get the full path to a template file.
    
    Args:
        filename: Template filename
        
    Returns:
        Absolute path to the template file
    """
    return os.path.join(TEMPLATES_DIR, filename)


def template_exists(filename: str) -> bool:
    """Check if a template file exists.
    
    Args:
        filename: Template filename
        
    Returns:
        True if the template exists
    """
    return os.path.isfile(get_template_path(filename))
