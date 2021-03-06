# -*- coding: utf-8 -*-

#
# Copyright (c) 2011-2015 Genestack Limited
# All Rights Reserved
# THIS IS UNPUBLISHED PROPRIETARY SOURCE CODE OF GENESTACK LIMITED
# The copyright notice above does not evidence any
# actual or intended publication of such source code.
#

import os
import sys
import urllib
import urllib2
import cookielib
import json
import requests
from distutils.version import StrictVersion

from genestack_client import GenestackServerException, GenestackException, __version__
from genestack_client.utils import isatty
from genestack_client.chunked_upload import upload_by_chunks


class AuthenticationErrorHandler(urllib2.HTTPErrorProcessor):
    def http_error_401(self, req, fp, code, msg, headers):
        raise GenestackException('Authentication failure')


class _NoRedirect(urllib2.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        #print 'Redirect: %s %s %s -> %s' % (code, msg, req.get_full_url(), newurl)
        return


class _NoRedirectError(urllib2.HTTPErrorProcessor):
    def http_error_307(self, req, fp, code, msg, headers):
        return fp
    http_error_301 = http_error_302 = http_error_303 = http_error_307


class Connection:
    """
    A class to handle a connection to a specified Genestack server.
    Instantiating the class does mean you are logged in to the server. To do so, you need to call the :attr:`login` method.
    """

    def __init__(self, server_url):
        self.server_url = server_url
        cj = cookielib.CookieJar()
        self.__cookies_jar = cj
        self.opener = urllib2.build_opener(urllib2.HTTPCookieProcessor(cj), AuthenticationErrorHandler)
        self.opener.addheaders.append(('gs-extendSession', 'true'))
        self._no_redirect_opener = urllib2.build_opener(urllib2.HTTPCookieProcessor(cj), _NoRedirect, _NoRedirectError, AuthenticationErrorHandler)

    def __del__(self):
        try:
            self.logout()
        except Exception:
            # fail silently
            pass

    def whoami(self):
        """
        Return user email.

        :return: email
        :rtype: str
        """
        return self.application('genestack/signin').invoke('whoami')

    def login(self, email, password):
        """
        Attempt a login on the connection with the specified credentials. Raises an exception if the login fails.

        :param email: email
        :type email: str
        :param password: password
        :type password: str
        :rtype: None
        :raises: GenestackServerException: if login failed
        """
        logged = self.application('genestack/signin').invoke('authenticate', email, password)
        if not logged['authenticated']:
            raise GenestackException("Fail to login %s" % email)
        version_msg = self.check_version(__version__)
        if version_msg:
            print 'Warning: %s' % version_msg

    def check_version(self, version):
        """
        Check the version of the client library required by the server.
        The server will return a message specifying the latest version and the earliest compatible version.
        If the current version is not supported, an exception is raised.

        :param version: version in format suitable for distutils.version.StrictVersion
        :return: a user-friendly message.
        """
        version_map = self.application('genestack/clientVersion').invoke('getCurrentVersion')
        LATEST = 'latest'
        COMPATIBLE = 'compatible'

        latest_version = StrictVersion(version_map[LATEST])
        my_verison = StrictVersion(version)

        if latest_version <= my_verison:
            return ''

        compatible = StrictVersion(version_map[COMPATIBLE])

        update_message = ('You can update it with the following command:\n'
                          '    pip install git+https://github.com/genestack/python-client@stable\n')

        if my_verison >= compatible:
            return 'Newer version "%s" available, please update.\n%s' % (latest_version, update_message)
        else:
            raise GenestackException('Your version "%s" is too old, please update to %s.\n%s' % (
                my_verison, latest_version, update_message))

    def logout(self):
        """
        Logout from server.

        :rtype: None
        """
        self.application('genestack/signin').invoke('signOut')

    def open(self, path, data=None, follow=True):
        """
        Sends data to a URL. The URL is the concatenation of the server URL and "path".

        :param path: part of URL that is added to self.server_url
        :param data: dict of parameters, file-like objects or strings
        :param follow: should we follow a redirection if any?
        :return: response
        :rtype: urllib.addinfourl
        """
        if data is None:
            data = ''
        elif isinstance(data, dict):
            data = urllib.urlencode(data)
        try:
            if follow:
                return self.opener.open(self.server_url + path, data)
            else:
                return self._no_redirect_opener.open(self.server_url + path, data)
        except urllib2.URLError, e:
            raise urllib2.URLError('Fail to connect %s%s %s' % (self.server_url,
                                                                path,
                                                                str(e).replace('urlopen error', '').strip('<\ >')))

    def application(self, application_id):
        """
        Returns an application handler for the application with the specified ID.

        :param application_id: Application ID.
        :type application_id: str
        :return: application class
        :rtype: Application
        """
        return Application(self, application_id)

    def __repr__(self):
        return 'Connection("%s")' % self.server_url

    def get_request(self, path, params=None, follow=True):
        r = requests.get(self.server_url + path, params=params, allow_redirects=follow, cookies=self.__cookies_jar)
        return r

    def post_multipart(self, path, data=None, files=None, follow=True):
        r = requests.post(self.server_url + path, data=data, files=files, allow_redirects=follow, cookies=self.__cookies_jar)
        return r


class Application:
    """
    Create a new application instance for the given connection. The connection must be logged in to call the
    application's methods. The application ID can be specified either as an argument to the class constructor
    or by overriding the ``APPLICATION_ID`` attribute in a child class.
    """

    APPLICATION_ID = None

    def __init__(self, connection, application_id=None):
        if application_id and self.APPLICATION_ID:
            raise GenestackException("Application ID specified both as argument and as class variable")
        self.application_id = application_id or self.APPLICATION_ID
        if not self.application_id:
            raise GenestackException('Application ID was not specified')

        self.connection = connection

        # validation of application ID
        if len(self.application_id.split('/')) != 2:
            raise GenestackException('Invalid application ID, expect "{vendor}/{application}" got: %s' % self.application_id)

    def __invoke(self, path, to_post):
        f = self.connection.open(path, to_post)
        response = json.load(f)
        if isinstance(response, dict) and 'error' in response:
            raise GenestackServerException(
                response['error'], path, to_post,
                stack_trace=response.get('errorStackTrace')
            )
        return response

    def invoke(self, method, *params):
        """
        Invoke one of the application's public Java methods.

        :param method: name of the public Java method
        :type method: str
        :param params: arguments that will be passed to the Java method. Arguments must be JSON-serializable.
        :return: JSON-deserialized response.
        """

        to_post = {'method': method}
        if params:
            to_post['parameters'] = json.dumps(params)

        path = '/application/invoke/%s' % self.application_id

        return self.__invoke(path, to_post)

    def upload_chunked_file(self, file_path):
        return upload_by_chunks(self, file_path)

    def upload_file(self, file_path, token):
        """
        Upload a file to the current Genestack instance.
        This action requires a special token that can be generated by the application.

        :param file_path: path to existing local file.
        :type file_path: str
        :param token: upload token
        :type file_path: str
        :rtype: None
        """
        if isatty():
            progress = TTYProgress()
        else:
            progress = DottedProgress(40)

        file_to_upload = FileWithCallback(file_path, 'rb', progress)
        filename = os.path.basename(file_path)
        path = '/application/upload/%s/%s/%s' % (
            self.application_id, token, urllib.quote(filename)
        )
        return self.__invoke(path, file_to_upload)


class FileWithCallback(file):
    def __init__(self, path, mode, callback):
        file.__init__(self, path, mode)
        self.seek(0, os.SEEK_END)
        self.__total = self.tell()
        self.seek(0)
        self.__callback = callback

    def __len__(self):
        return self.__total

    def read(self, size=None):
        data = file.read(self, size)
        self.__callback(os.path.basename(self.name), len(data), self.__total)
        return data


class TTYProgress(object):
    def __init__(self):
        self._seen = 0.0

    def __call__(self, name, size, total):
        if size > 0 and total > 0:
            self._seen += size
            pct = self._seen * 100.0 / total
            sys.stderr.write('\rUploading %s - %.2f%%' % (name, pct))
            if int(pct) >= 100:
                sys.stderr.write('\n')
            sys.stderr.flush()


class DottedProgress(object):
    def __init__(self, full_length):
        self.__full_length = full_length
        self.__dots = 0
        self.__seen = 0.0

    def __call__(self, name, size, total):
        if size > 0 and total > 0:
            if self.__seen == 0:
                sys.stderr.write('Uploading %s: ' % name)
            self.__seen += size
            dots = int(self.__seen * self.__full_length / total)
            while dots > self.__dots and self.__dots < self.__full_length:
                self.__dots += 1
                sys.stderr.write('.')
            if self.__dots == self.__full_length:
                sys.stderr.write('\n')
            sys.stderr.flush()
