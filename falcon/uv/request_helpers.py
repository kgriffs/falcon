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

from asyncio import iscoroutinefunction
from enum import Enum


class _State(Enum):
    BODY_START = 1
    BODY_CHUNKS = 2
    EOF = 3


class UvRequestStream:

    __slots__ = ('_message', '_channels', '_state', '_has_chunks')

    def __init__(self, message, channels):
        self._message = message
        self._channels = channels
        self._state = _State.BODY_START
        self._has_chunks = 'body' in channels

    async def pipe(on_data):
        if self._state != _State.BODY_START:
            raise IOError('pipe() may only be called on an unread stream')

        is_coroutine = iscoroutinefunction(on_data)

        # PERF(kgriffs): Since we normally expect the body key
        #   to be present, use try...except
        try:
            data = self._message['body']
        except:
            data = b''

        if data:
            if is_coroutine:
                await on_data(data)
            else:
                on_data(data)

        self._state = _State.BODY_CHUNKS

        if self._has_chunks:
            while True:
                chunk = await self._channels['body'].receive()

                if is_coroutine:
                    await on_data(chunk['content'])
                else:
                    on_data(chunk['content'])

                if not chunk['more_content']:
                    break

        self._state = _State.EOF

    async def read():
        if self._state != _State.BODY_START:
            raise IOError('read() may only be called on an unread stream')

        # PERF(kgriffs): Since we normally expect the body key
        #   to be present, use try...except
        try:
            data = self._message['body']
        except:
            data = b''

        self._state = _State.BODY_CHUNKS

        if self._has_chunks:
            while True:
                chunk = await self._channels['body'].receive()

                # PERF(kgriffs): If there are only a few chunks,
                #   += should outperform .join(), but we should
                #   benchmark this to be certain (and to see how
                #   common it is to have a large number of chunks)
                data += chunk['content']

                if not chunk['more_content']:
                    break

        self._state = _State.EOF
        return data

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._state == _State.EOF:
            raise StopAsyncIteration

        if self._state == _State.BODY_START:
            # PERF(kgriffs): Since we normally expect the body key
            #   to be present, use try...except
            try:
                data = self._message['body']
            except:
                data = b''

            self._state = _State.BODY_CHUNKS

            if data:
                return data

        assert self._state == _State.BODY_CHUNKS

        if not self._has_chunks:
            self._state = _State.EOF
            raise StopAsyncIteration

        chunk = await self._channels['body'].receive()
        if not chunk['more_content']:
            self._state = _State.EOF

        return chunk['content']
