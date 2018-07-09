import sys

if sys.version_info < (3, 5):
    raise ImportError('The ASGI module requires Python 3.5+')
