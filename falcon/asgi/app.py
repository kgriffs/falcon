import enum

import falcon.api
from falcon.routing.util import get_responder


class DataResponderMissingError(Exception):
    def __init__(self):
        super().__init__(
            'An async *_finalize() responder was found on the resource, '
            'but the corresponding *_data() responder is missing'
        )


class FinalizeResponderMissingError(Exception):
    def __init__(self):
        super().__init__(
            'An async *_data() responder was found on the resource, '
            'but the corresponding *_finalize() responder is missing'
        )


class _ConnectionMode(enum):
    START = 1
    BUFFERING_BODY = 2
    STREAMING_BODY = 3
    FINALIZED = 4


class App(falcon.api.API):

    def asgi_application(self, scope):
        if scope['type'] != 'http':
            raise NotImplementedError(
                'The "{}" scope type is not yet supported.'.format(scope['type'])
            )

        state = {}

        # PERF(kgriffs): Using a closure was faster in tests on 3.5 and 3.6,
        #   as opposed to a class. Performance was better for both
        #   instantiation and proxying the call to on_event()
        async def on_request(receive, send):
            await self._on_request(state, scope, receive, send)

        return on_event

    # ------------------------------------------------------------------------
    # Helpers that require self
    # ------------------------------------------------------------------------

    async def _on_request(self, state, scope, receive, send):
        # TODO(kgriffs): Remove this option, since web servers already enforce
        #   their own max request body sizes.
        # max_buffered_body_size = self.req_options.asgi_max_buffered_req_body

        # TODO: Need a version that doesn't use async generator for Python 3.5
        async def stream():
            while True:
                event = await receive()
                yield event['body']

                # NOTE(kgriffs): Per the ASGI spec, more_body is optional
                #   and should be considered False if not present.
                # PERF(kgriffs): event.get() is more elegant, but uses a
                #   few more CPU cycles.
                if not ('more_body' in event and event['more_body']):
                    break

        req_stream = stream()

        # TODO: Need a version that doesn't use async list comprehensions for
        #   Python 3.5 - also, is there a way for 3.6+ to short-circuit this
        #   when we know there isn't more body? Receive the first chunk outside
        #   the generator, then load additional... with flag to know is "Read"
        #   to simulate forward-only stream semantics.
        async def read():
            return b''.join([chunk async for chunk in req_stream])

        # NOTE(kgriffs): Must work on Python 3.5
        async def pipe(on_data):
            while True:
                event = await receive()
                on_data(event['body'])

                # NOTE(kgriffs): Per the ASGI spec, more_body is optional
                #   and should be considered False if not present.
                # PERF(kgriffs): event.get() is more elegant, but uses a
                #   few more CPU cycles.
                if not ('more_body' in event and event['more_body']):
                    break


        req_stream.read = read


        # TODO: Convert the receive to a generator that will yield the
        #   body chunks until exausted. Pass this generator to the request
        #   class.
        #
        #   For await req.stream.read() you can implement it by using
        #   async for chunk in body until exhausted, and then returning
        #   the final result.
        #
        #   You can also let people iterate directly, in case they want
        #   to stream the chunks somewhere else.
        #
        #   We can also support a shortcut property if they want to
        #   use it for performance (e.g., res.media). When there is
        #   no more_body, set that variable to the body. If it isn't
        #   none, then people know they can use it and don't have to
        #   bother with the async read pattern.

        more_body = evt_request['more_body']

        if not state:
            state['mode'] = _ConnectionMode.START
            streaming = bool(responder._falcon_on_data)

            # TODO(kgriffs): Create req, resp objects and store in state

            route = None

            try:
                state['route'] = route = self._get_responder(req)
            except Exception as ex:
                if not await self._handle_exception(req, resp, ex, params):
                    raise

            responder, params, resource, uri_template = route

            if more_body:
                if streaming:
                    state['mode'] = _ConnectionMode.STREAMING_BODY
                    await self._dispatch(
                        req,
                        resp,
                        responder,
                        params,
                        resource,
                        uri_template,
                    )
                else:
                    content_length = req.content_length
                    too_large = (content_length and content_length > max_buffered_body_size)

                    body = evt_request['body']
                    if too_large or len(body) > max_buffered_body_size:
                        ex = falcon.HTTPRequestEntityTooLarge()
                        if not await self._handle_exception(req, resp, ex, params):
                            raise ex

                    state['mode'] = _ConnectionMode.BUFFERING_BODY
                    state['req.body'] = [body]

            else:
                # TODO: Even in this case, to be consistent, if we are in
                # streaming mode, disallow calling methods like req.media or
                # req.stream to get request body.

                if not streaming:
                    body = evt_request['body']

                    if len(body) > max_buffered_body_size:
                        ex = falcon.HTTPRequestEntityTooLarge()
                        if not await self._handle_exception(req, resp, ex, params):
                            raise ex

                    req._asgi_data = body

                await self._dispatch(
                    req,
                    resp,
                    responder,
                    params,
                    resource,
                    uri_template,
                )

                if streaming:
                    req.uri_template = uri_template

                    try:
                        c = responder._falcon_on_data(req, resp, evt_request['body'])
                        if c:
                            await c
                    except Exception as ex:
                        if not await self._handle_exception(req, resp, ex, params):
                            raise
                    else:
                        try:
                            c = responder._falcon_on_finalize(req, resp)
                            if c:
                                await c
                        except Exception as ex:
                            if not await self._handle_exception(req, resp, ex, params):
                                raise

                state['mode'] = _ConnectionMode.FINALIZED

        else:
            responder, params, resource, uri_template = state['route']

            mode = state['mode']

            if mode is _ConnectionMode.BUFFERING_BODY:
                body = state['req.body']
                body.append(evt_request['body'])

                body_length_so_far = sum(len(chunk) for chunk in body)

                if body_length_so_far > max_buffered_body_size:
                    ex = falcon.HTTPRequestEntityTooLarge()
                    if not await self._handle_exception(req, resp, ex, params):
                        raise ex

                if not more_body:
                    req._asgi_data = b''.join(body)
                    await self._dispatch(
                        req,
                        resp,
                        responder,
                        params,
                        resource,
                        uri_template,
                    )

                    state['mode'] = _ConnectionMode.FINALIZED

            elif mode is _ConnectionMode.STREAMING_BODY:
                succeeded = False

                try:
                    c = responder._falcon_on_data(req, resp, evt_request['body'])
                    if c:
                        await c

                    succeeded = True

                except Exception as ex:
                    if not await self._handle_exception(req, resp, ex, params):
                        raise

                if not more_body:
                    if succeeded:
                        try:
                            c = responder._falcon_on_finalize(req, resp)
                            if c:
                                await c
                        except Exception as ex:
                            if not await self._handle_exception(req, resp, ex, params):
                                raise

                    state['mode'] = _ConnectionMode.FINALIZED


            # NOTE(kgriffs): If mode is _ConnectionMode.FINALIZED we do
            #   nothing; we really should not be getting additional events
            #   after the first time we see (more_body == False).


        # ...


        if not more_body:
            # TODO: send response event
            pass

    def add_route(self, uri_template, resource, **kwargs):
        suffix = kwargs.get('suffix', None)

        # NOTE(kgriffs): We could filter out methods that typically don't
        #   include a body, but there is no real harm in just checking all
        #   HTTP methods, and this is not in the request path, so we aren't
        #   worried about taking the extra time to do so.
        for method in COMBINED_METHODS:
            responder_name = 'on_' + method.lower()
            responder = get_responder(responder_name, resource, suffix=suffix)
            if responder:
                responder_name = 'on_' + method.lower() + '_data'
                responder_od = get_responder(responder_name, resource, suffix=suffix)

                responder_name = 'on_' + method.lower() + '_finalize'
                responder_fin = get_responder(responder_name, resource, suffix=suffix)

                if responder_od and not responder_fin:
                    raise FinalizeResponderMissingError()

                if responder_fin and not responder_od:
                    raise DataResponderMissingError()

                responder._falcon_on_data = responder_od
                responder._falcon_on_finalize = responder_fin

        super().add_route(uri_template, resource, **kwargs)

    # =========================================================================

    async def _dispatch(self, req, resp, responder, params, resource, uri_template):
        # NOTE(kgriffs): When editing this method, be sure to also update
        #   the similar method in falcon.api, as well as _dispatch_no_mw() as
        #   needed.

        req.uri_template = uri_template

        mw_req_stack, mw_rsrc_stack, mw_resp_stack = self._middleware
        dependent_mw_resp_stack = []
        req_succeeded = False

        try:
            try:
                # NOTE(ealogar): The execution of request middleware
                # should be before routing. This will allow request mw
                # to modify the path.
                # NOTE: if flag set to use independent middleware, execute
                # request middleware independently. Otherwise, only queue
                # response middleware after request middleware succeeds.
                if self._independent_middleware:
                    for process_request in mw_req_stack:
                        c = process_request(req, resp)
                        if c:
                            await c
                else:
                    for process_request, process_response in mw_req_stack:
                        if process_request:
                            c = process_request(req, resp)
                            if c:
                                await c
                        if process_response:
                            dependent_mw_resp_stack.insert(0, process_response)

            except Exception as ex:
                if not await self._handle_exception(req, resp, ex, params):
                    raise
            else:
                try:
                    # NOTE(kgriffs): If the request did not match any
                    # route, a default responder is returned and the
                    # resource is None. In that case, we skip the
                    # resource middleware methods.
                    if resource is not None:
                        # Call process_resource middleware methods.
                        for process_resource in mw_rsrc_stack:
                            process_resource(req, resp, resource, params)

                    c = responder(req, resp, **params)
                    if c:
                        await c
                    req_succeeded = True
                except Exception as ex:
                    if not await self._handle_exception(req, resp, ex, params):
                        raise
        finally:
            # NOTE(kgriffs): It may not be useful to still execute
            # response middleware methods in the case of an unhandled
            # exception, but this is done for the sake of backwards
            # compatibility, since it was incidentally the behavior in
            # the 1.0 release before this section of the code was
            # reworked.

            # Call process_response middleware methods.
            for process_response in mw_resp_stack or dependent_mw_resp_stack:
                try:
                    c = process_response(req, resp, resource, req_succeeded)
                    if c:
                        await c
                except Exception as ex:
                    if not await self._handle_exception(req, resp, ex, params):
                        raise

                    req_succeeded = False

    async def _handle_exception(self, req, resp, ex, params):
        # NOTE(kgriffs): If changing anything here, sync changes with
        #   falcon.API._handle_exception.

        for err_type, err_handler in self._error_handlers:
            if isinstance(ex, err_type):
                try:
                    c = err_handler(req, resp, ex, params)
                    if c:
                        await c
                except HTTPStatus as status:
                    self._compose_status_response(req, resp, status)
                except HTTPError as error:
                    self._compose_error_response(req, resp, error)

                return True

        return False
