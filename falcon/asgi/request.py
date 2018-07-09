import falcon.request as wsgir

from falcon.asgi import request_helpers as helpers


class Request(wsgir.Request):

    __slots__ = [
        '__dict__',
        '_remote_addr',
        '_scheme',
        '_server',
    ]

    def __init__(scope, options=None):
        self.options = options if options else wsgir.RequestOptions()

        self.method = scope['method']
        self.path = scope['path']
        self.query_string = scope['query_string'].decode()

        raw_headers = scope['headers']

        # PERF(kgriffs): Assuming that most of the time the client will
        #   not send more than one header row for the same header, we
        #   will optimistically just try the fastest method of slurping
        #   them into a dict in one go.
        cached_headers = dict(raw_headers)
        if len(cached_headers) != len(raw_headers):
            # PERF(kgriffs): Fall back to slower method
            cached_headers = {}
            for name, value in raw_headers:
                if name in cached_headers:
                    cached_headers[name] += ',' + value
                else:
                    cached_headers[name] = value

        self._cached_headers = cached_headers

        # PERF(kgriffs): Content-Type is often not present, so don't use
        #   try...except here.
        if b'content-type' in self._cached_headers:
            self.content_type = self._cached_headers[b'content-type']
        else:
            self.content_type = None

        self._scheme = scope.get('scheme', 'http')

        # PERF(kgriffs): Using the "if x in y" pattern is slightly faster than
        #   dict.get().
        if 'server' in scope:
            # NOTE(kgriffs): Cooerce to tuple to normalize any differences
            #   between ASGI implementations.
            self._server = tuple(scope['server'])
        else:
            self._server = ('localhost', (80 if self._scheme == 'http' else 443))

        if 'client' in scope:
            self._remote_addr, __ = scope['client']
        else:
            self._remote_addr = None

        # NOTE(kgriffs): This sets self.env to the ASGI scope (we should
        #   note this in the class docstring.)
        self._init_common(scope, options)

    # ------------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------------

    # NOTE(kgriffs): If you change anything below, be sure to also update
    #   the WSGI Request class. Also, try to keep overrided properties and
    #   methods in the same order below as in the WSGI class.

    user_agent = helpers.header_property('User-Agent')
    auth = helpers.header_property('Authorization')

    expect = helpers.header_property('Expect')

    if_match = helpers.header_property('If-Match')
    if_none_match = helpers.header_property('If-None-Match')
    if_range = helpers.header_property('If-Range')

    referer = helpers.header_property('Referer')

    forwarded = helpers.prop_patch_wsgi_env_lookup(wsgir.Request.forwarded)
    accept = helpers.prop_patch_wsgi_env_lookup(wsgir.Request.accept)
    content_length = helpers.prop_patch_wsgi_env_lookup(wsgir.Request.content_length)

    @property
    def bounded_stream(self):
        return self.stream

    @property
    def stream(self):
        if self._asgi_data is None:
            raise RuntimeError(
                'This resource implements the on_data() pattern, and therefore '
                'may not use the pull-based stream interface.'
            )

        if not self._stream:
            # NOTE(kgriffs): Wrap in BufferedReader to enforce read-only semantics.
            self._stream = io.BufferedReader(io.BytesIO(self._asgi_data))

        return self._stream

    @property
    def data(self):  # TODO(kgriffs): Note that this should be preferred over stream() for perf reasons
        if self._asgi_data is None:
            raise RuntimeError(
                'This resource implements the on_data() pattern, and therefore '
                'may not use the data property interface.'
            )

        return self._asgi_data

    # TODO: For each method, override the entire thing but with note to
    #   reviewer in falcon.Request to also ensure update in falcon.asgi.Request
    #
    #   If there is lots of logic, avoid duplication by delegating retrieval
    #   of the header/data to another method that can be overridden in a more
    #   surgical fashion.

