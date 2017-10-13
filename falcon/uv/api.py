# Copyright 2017 by Kurt Griffiths. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""UvAPI class."""

import asyncio

import falcon
from falcon.uv import api_helpers as helpers
from falcon.uv.request import UvRequest
from falcon.uv.response import UvResponse


'''

TODO:

* Benchmark uvicorn under PyPy, if needed supply a patch that will detect and use native stuff under PyPy (standard asyncio, plus gunicorn's HTTP parser)
* DRY
* Tests
* Docs

Notes:

* Middleware, on_* methods, and hooks must all use the async keyword or asyncio.coroutine decorator
    * What do do about existing middleware? How to make it compatible with both WSGI and async?
* Warn that should benchmark - async does not help so much and can even hurt for low-latency I/O operations (fast network or disk, fast DB)

'''


class UvAPI(falcon.API):

    # __slots__ = (
    #     '_request_type',
    #     '_response_type',
    # )

    def __init__(self, media_type=falcon.DEFAULT_MEDIA_TYPE,
                 request_type=UvRequest, response_type=UvResponse,
                 middleware=None, router=None,
                 independent_middleware=False):
        super().__init__(
            media_type=media_type,
            request_type=request_type,
            response_type=response_type,
            middleware=middleware,
            router=router,
            independent_middleware=independent_middleware
        )

    async def __call__(self, message, channels):
        req = UvRequest(message, channels, options=self.req_options)
        resp = UvResponse(options=self.resp_options)

        resource = None
        params = {}

        dependent_mw_resp_stack = []
        mw_req_stack, mw_rsrc_stack, mw_resp_stack = self._middleware

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
                        await process_request(req, resp)
                else:
                    for process_request, process_response in mw_req_stack:
                        if process_request:
                            await process_request(req, resp)
                        if process_response:
                            dependent_mw_resp_stack.insert(0, process_response)

                # NOTE(warsaw): Moved this to inside the try except
                # because it is possible when using object-based
                # traversal for _get_responder() to fail.  An example is
                # a case where an object does not have the requested
                # next-hop child resource. In that case, the object
                # being asked to dispatch to its child will raise an
                # HTTP exception signalling the problem, e.g. a 404.
                responder, params, resource, req.uri_template = self._get_responder(req)
            except Exception as ex:
                if not await self._handle_exception(ex, req, resp, params):
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
                            await process_resource(req, resp, resource, params)

                    await responder(req, resp, **params)
                    req_succeeded = True
                except Exception as ex:
                    if not await self._handle_exception(ex, req, resp, params):
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
                    await process_response(req, resp, resource, req_succeeded)
                except Exception as ex:
                    if not await self._handle_exception(ex, req, resp, params):
                        raise

                    req_succeeded = False

        #
        # Set status and headers
        #

        resp_status = resp.status

        if req.method == 'HEAD' or resp_status in self._BODILESS_STATUS_CODES:
            content = b''
        else:
            content, length = self._get_content(resp, env.get('wsgi.file_wrapper'))
            if length is not None:
                resp._headers['content-length'] = str(length)

        # NOTE(kgriffs): Based on wsgiref.validate's interpretation of
        # RFC 2616, as commented in that module's source code. The
        # presence of the Content-Length header is not similarly
        # enforced.
        if resp_status in (status.HTTP_204, status.HTTP_304):
            media_type = None
        else:
            media_type = self._media_type

        # Return the response per the ASGI+Uvicorn spec.
        response = {
            'status': 200,
            'headers': resp._asgi_headers(media_type),
            'content': content
        }

        await channels['reply'].send(response)

    def _get_content(self):
        # TODO: get content, handle content stream that is iterable or awaitable or asyncfile thing
        pass

    async def _handle_exception(self, ex, req, resp, params):
        """Handles an exception raised from mw or a responder.

        Args:
            ex: Exception to handle
            req: Current request object to pass to the handler
                registered for the given exception type
            resp: Current response object to pass to the handler
                registered for the given exception type
            params: Responder params to pass to the handler
                registered for the given exception type

        Returns:
            bool: ``True`` if a handler was found and called for the
            exception, ``False`` otherwise.
        """

        for err_type, err_handler in self._error_handlers:
            if isinstance(ex, err_type):
                try:
                    await err_handler(ex, req, resp, params)
                except HTTPStatus as status:
                    self._compose_status_response(req, resp, status)
                except HTTPError as error:
                    self._compose_error_response(req, resp, error)

                return True

        # NOTE(kgriffs): No error handlers are defined for ex
        # and it is not one of (HTTPStatus, HTTPError), since it
        # would have matched one of the corresponding default
        # handlers.
        return False