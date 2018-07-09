import inspect
import re


def header_property(header_name):
    """Create a read-only header property.

    Args:
        header_name (str): Case-insensitive name of the header.

    Returns:
        A property instance than can be assigned to a class variable. If the
        header is set to an empty string for some reason, it will be
        normalized to None, as if the header were not set in the first place.

    """

    # NOTE(kgriffs): Per the ASGI spec, all request headers are lowercased
    #   byte strings.
    header_name = header_name.lower().encode()

    def fget(self):
        try:
            return self._cached_headers[header_name] or None
        except KeyError:
            return None

    return property(fget)


def prop_patch_wsgi_env_lookup(prop):
    fget = prop.fget

    source = inspect.getsource(fget)

    source = source.replace(
        "self.env['CONTENT_LENGTH']",
        "self._cached_headers[b'content-length']",
    )

    source = source.replace("self.env['SERVER_NAME']", "self._server[0]")
    source = source.replace("self.env['SERVER_PORT']", "self._server[1]")

    source = source.replace("'REMOTE_ADDR' in self.env", "bool(self._remote_addr)")
    source = source.replace("self.env['REMOTE_ADDR']", "self._remote_addr")

    # self.env['HTTP_HOST']
    def repl_a(m):
        header_name = m.group(1).lower().replace('_', '-')
        return "self._cached_headers[b'{}']".format(header_name)

    source = re.sub(r"self\.env\['HTTP_([^']+)'\]", repl_a, source)

    # 'HTTP_FORWARDED' in self.env
    def repl_b(m):
        header_name = m.group(1).lower().replace('_', '-')
        return "b'{}' in self._cached_headers".format(header_name)

    source = re.sub(r"'HTTP_([^']+)' in self.env", repl_b, source)

    source = source.replace('@property', '')
    source = re.sub('^    ', '', source, flags=re.MULTILINE)

    # print(source)

    scope = {}
    exec(compile(source, '<string>', 'exec'), scope)

    return property(scope[fget.__name__])
