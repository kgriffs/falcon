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

import falcon


class UvAPI(falcon.API):
    async def __call__(self, message, channels):
        content = b'Hello world!'
        response = {
            'status': 200,
            'headers': [
                [b'content-type', b'text/plain']
            ],
            'content': content
        }

        await channels['reply'].send(response)