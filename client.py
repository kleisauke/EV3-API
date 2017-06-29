import json
from urllib.parse import urlencode

from falcon.testing import StartResponseMock, create_environ

from hug import output_format


class Client:
    def __init__(self, api):
        self.api = api

    def get(self, url, body='', headers=None, params=None, query_string='', scheme='http', **kwargs):
        return self.call('GET', url, body, headers, params, query_string, scheme, **kwargs)

    def post(self, url, body='', headers=None, params=None, query_string='', scheme='http', **kwargs):
        return self.call('POST', url, body, headers, params, query_string, scheme, **kwargs)

    def delete(self, url, body='', headers=None, params=None, query_string='', scheme='http', **kwargs):
        return self.call('DELETE', url, body, headers, params, query_string, scheme, **kwargs)

    # From: https://github.com/timothycrosley/hug/blob/9540457a42b70d74ccc3a8c7d9c1d71e287e54fb/hug/test.py#L38-L71
    def call(self, method, url, body='', headers=None, params=None, query_string='', scheme='http', **kwargs):
        """Simulates a round-trip call against the given API / URL"""
        response = StartResponseMock()
        headers = {} if headers is None else headers
        if not isinstance(body, str) and 'json' in headers.get('content-type', 'application/json'):
            body = output_format.json(body)
            headers.setdefault('content-type', 'application/json')

        params = params if params else {}
        params.update(kwargs)
        if params:
            query_string = '{}{}{}'.format(query_string, '&' if query_string else '', urlencode(params, True))
        result = self.api(create_environ(path=url, method=method, headers=headers, query_string=query_string,
                                         body=body, scheme=scheme), response)
        if result:
            try:
                response.data = result[0].decode('utf8')
            except TypeError:
                response.data = []
                for chunk in result:
                    response.data.append(chunk.decode('utf8'))
                response.data = "".join(response.data)
            except UnicodeDecodeError:
                response.data = result[0]
            response.content_type = response.headers_dict['content-type']
            if response.content_type == 'application/json':
                response.data = json.loads(response.data)

        return response
