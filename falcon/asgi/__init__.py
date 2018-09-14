import sys

if sys.version_info < (3, 6):
    raise ImportError('The ASGI module requires Python 3.6+')
