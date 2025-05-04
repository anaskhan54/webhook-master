# Tests package 

# This file makes tests a package 

from django.conf import settings
from django.core.cache import cache

# Override cache settings for tests
settings.CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'unique-snowflake',
    }
}

# Clear cache before tests
cache.clear() 