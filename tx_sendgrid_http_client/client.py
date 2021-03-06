"""HTTP Client library"""
import json
from .exceptions import handle_error, HTTPError

from urllib.parse import urlencode

from twisted.internet.defer import inlineCallbacks
from treq import request as tx_req, text_content


class Response(object):
    """Holds the response from an API call."""

    def __init__(self, response):
        """
        :param response: The return value from _make_request
        :type response:  dict
        """
        self._status_code = response['code']
        self._body = response['body']
        self._headers = response['headers']

    @property
    def status_code(self):
        """
        :return: integer, status code of API call
        """
        return self._status_code

    @property
    def body(self):
        """
        :return: response from the API
        """
        return self._body

    @property
    def headers(self):
        """
        :return: dict of response headers
        """
        return self._headers

    @property
    def to_dict(self):
        """
        :return: dict of response from the API
        """
        if self.body:
            return json.loads(self.body)
        else:
            return None


class Client(object):
    """Quickly and easily access any REST or REST-like API."""

    def __init__(self,
                 host,
                 request_headers=None,
                 version=None,
                 url_path=None,
                 append_slash=False,
                 timeout=None):
        """
        :param host: Base URL for the api. (e.g. https://api.sendgrid.com)
        :type host:  string
        :param request_headers: A dictionary of the headers you want
                                applied on all calls
        :type request_headers: dictionary
        :param version: The version number of the API.
                        Subclass _build_versioned_url for custom behavior.
                        Or just pass the version as part of the URL
                        (e.g. client._("/v3"))
        :type version: integer
        :param url_path: A list of the url path segments
        :type url_path: list of strings
        """
        self.host = host
        self.request_headers = request_headers or {}
        self._version = version
        # _url_path keeps track of the dynamically built url
        self._url_path = url_path or []
        # These are the supported HTTP verbs
        self.methods = ['delete', 'get', 'patch', 'post', 'put']
        # APPEND SLASH set
        self.append_slash = append_slash
        self.timeout = timeout

    def _build_versioned_url(self, url):
        """Subclass this function for your own needs.
           Or just pass the version as part of the URL
           (e.g. client._('/v3'))
        :param url: URI portion of the full URL being requested
        :type url: string
        :return: string
        """
        return '{}/v{}{}'.format(self.host, str(self._version), url)

    def _build_url(self, query_params):
        """Build the final URL to be passed to urllib

        :param query_params: A dictionary of all the query parameters
        :type query_params: dictionary
        :return: string
        """
        url = ''
        count = 0
        while count < len(self._url_path):
            url += '/{}'.format(self._url_path[count])
            count += 1

        # add slash
        if self.append_slash:
            url += '/'

        if query_params:
            url_values = urlencode(sorted(query_params.items()), True)
            url = '{}?{}'.format(url, url_values)

        if self._version:
            url = self._build_versioned_url(url)
        else:
            url = '{}{}'.format(self.host, url)
        return url

    def _update_headers(self, request_headers):
        """Update the headers for the request

        :param request_headers: headers to set for the API call
        :type request_headers: dictionary
        :return: dictionary
        """
        self.request_headers.update(request_headers)

    def _build_client(self, name=None):
        """Make a new Client object

        :param name: Name of the url segment
        :type name: string
        :return: A Client object
        """
        url_path = self._url_path + [name] if name else self._url_path
        return Client(host=self.host,
                      version=self._version,
                      request_headers=self.request_headers,
                      url_path=url_path,
                      append_slash=self.append_slash,
                      timeout=self.timeout)

    @inlineCallbacks
    def _make_request(self, url, **kwargs):
        """Make the API call and return the response. This is separated into
           it's own function, so we can mock it easily for testing.
        """
        try:
            res = yield tx_req(url=url, **kwargs)
            code = res.code
            content = yield text_content(res, encoding='utf-8')
            ret = {
                'body': content,
                'code': code,
                'headers': {h[0]: h[1] for h in res.headers.getAllRawHeaders()}
            }
            if not 200 <= code < 300:
                raise HTTPError(**ret)
            return ret
        except HTTPError as err:
            exc = handle_error(err)
            exc.__cause__ = None
            raise exc

    def _(self, name):
        """Add variable values to the url.
           (e.g. /your/api/{variable_value}/call)
           Another example: if you have a Python reserved word, such as global,
           in your url, you must use this method.

        :param name: Name of the url segment
        :type name: string
        :return: Client object
        """
        return self._build_client(name)

    def __getattr__(self, name):
        """Dynamically add method calls to the url, then call a method.
           (e.g. client.name.name.method())
           You can also add a version number by using .version(<int>)

        :param name: Name of the url segment or method call
        :type name: string or integer if name == version
        :return: mixed
        """
        if name == 'version':
            def get_version(*args, **_):
                """
                :param args: dict of settings
                :param _: kwargs unused
                :return: string, version
                """
                self._version = args[0]
                return self._build_client()
            return get_version

        # We have reached the end of the method chain, make the API call
        if name in self.methods:
            method = name.upper()

            @inlineCallbacks
            def http_request(*_, **kwargs):
                """Make the API call
                :param _: positional arguments: unused
                :param kwargs:
                :return: Client object
                """
                if 'request_headers' in kwargs:
                    self._update_headers(kwargs['request_headers'])
                if 'request_body' not in kwargs:
                    data = None
                else:
                    # Don't serialize to a JSON formatted str
                    # if we don't have a JSON Content-Type
                    if 'Content-Type' in self.request_headers:
                        if self.request_headers['Content-Type'] != 'application/json':
                            data = kwargs['request_body'].encode('utf-8')
                        else:
                            data = json.dumps(kwargs['request_body']).encode('utf-8')
                    else:
                        data = json.dumps(kwargs['request_body']).encode('utf-8')

                if 'query_params' in kwargs:
                    params = kwargs['query_params']
                else:
                    params = None

                headers = {}
                if self.request_headers:
                    for key, value in self.request_headers.items():
                        headers[key.encode('utf-8')] = value.encode('utf-8')
                if data and ('Content-Type' not in self.request_headers):
                    headers[b'Content-Type'] = b'application/json'
                timeout = kwargs.pop('timeout', None)
                res = yield self._make_request(
                    method=method, timeout=timeout, url=self._build_url(params), headers=headers, data=data
                )
                return Response(response=res)

            return http_request
        else:
            # Add a segment to the URL
            return self._(name)

    def __getstate__(self):
        return self.__dict__

    def __setstate__(self, state):
        self.__dict__ = state
