# Copyright (C) 2011 by jedi95 <jedi95@gmail.com> and 
#                       CFSworks <CFSworks@gmail.com>
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.

import urlparse
import json
from twisted.internet.protocol import Protocol
from twisted.internet import defer, task, reactor
from twisted.web import http, client
from twisted.web.http_headers import Headers
from twisted.python.failure import Failure
from zope.interface import implements
from twisted.web.iweb import IBodyProducer

from ClientBase import ClientBase, AssignedWork

class BodyLoader(Protocol):
    """Loads an HTTP body and fires it, as a string, through a Deferred."""
    
    def __init__(self, d):
        self.d = d
        self.data = ''
    
    def dataReceived(self, bytes):
        self.data += bytes
    
    def connectionLost(self, reason):
        if not reason.check(client.ResponseDone, http.PotentialDataLoss):
            self.d.errback(Failure(reason))
        else:
            self.d.callback(self.data)

class GetWorkProducer(object):
    """Produces RPC requests."""
    implements(IBodyProducer)
    
    def __init__(self, result=None):
        if result:
            params = '["%s"]' % result.encode('hex')
        else:
            params = '[]'
        self.body = \
            '{"method": "getwork", "params": %s, "id": 1}' % params
        self.length = len(self.body)
        
    def startProducing(self, consumer):
        consumer.write(self.body)
        return defer.succeed(None)
    
    def pauseProducing(self):
        pass
    
    def stopProducing(self):
        pass

class RPCClient(ClientBase):
    version = 'minerutil/0.5'

    def __init__(self, handler, hostname, port, username, password, path):
        self.handler = handler
        self.baseURL = 'http://%s:%s' % (hostname, port)
        self.basePath = path
        self.auth = 'Basic %s' % \
            ('%s:%s' % (username, password)).encode('base64').strip()
        self.askrate = 10
        
        self.agent = client.Agent(reactor)
        self.longPollPath = None
        self.activeLongPoll = None
        self.block = None
        self.connected = False
        self.requesting = False
        self.active = False
        
        self.polling = task.LoopingCall(self._startRequest)
    
    def connect(self):
        """Tells the RPCClient that it's time to start communicating with the
        server.
        """
        
        if self.active:
            return
        self.active = True
        
        if not self.polling.running and self.askrate:
            self.polling.start(self.askrate, True)
        else:
            self._startRequest()
    
    def disconnect(self):
        """Shuts down the RPCClient. It should not be connect()ed again."""
        
        if not self.active:
            return
        self.active = False
        
        if self.connected:
            self.connected = False
            self.runCallback('disconnect')
        
        if self.polling.running:
            self.polling.stop()
        self._setLongPollingPath(None)
    
    def requestWork(self):
        """Request work from the server immediately."""
        
        self._startRequest()
    
    def sendResult(self, result):
        """Sends a result to the server, returning a Deferred that fires with
        a bool to indicate whether or not the work was accepted.
        """
        
        # Must be a 128-byte response, but the last 48 are typically ignored.
        result += '\x00'*48
        
        d = self.agent.request(
            'POST',
            self.baseURL + self.basePath,
            Headers(
                {'User-Agent': [self.version],
                'Authorization': [self.auth],
                'Content-Type': ['application/json'],
                }),
            GetWorkProducer(result))
        
        def callback(response):
            d = defer.Deferred()
            response.deliverBody(BodyLoader(d))
            return d
        d.addCallback(callback)
        d.addCallback(self._processSubmissionResponse)
        return d
    
    def setMeta(self, var, value):
        """RPC miners do not accept meta."""
    
    def setVersion(self, shortname, longname=None, version=None, author=None):
        if version is not None:
            self.version = '%s/%s' % (shortname, version)
        else:
            self.version = shortname
    
    def _startLongPoll(self):
        if not self.longPollPath or self.activeLongPoll:
            return
        
        self.activeLongPoll = self._startRequest(False)
        def callback(ignored):
            self.activeLongPoll = None
            self._startLongPoll()
        self.activeLongPoll.addCallback(callback)
    
    def _setLongPollingPath(self, path):
        if path and self.polling.running:
                self.polling.stop() # Don't poll, ever, when there's long-poll.
        if path == self.longPollPath:
            return
        elif path and not self.longPollPath:
            self.runCallback('longpoll', True)
        elif not path and self.longPollPath:
            if not self.polling.running and self.askrate:
                self.polling.start(self.askrate)
            self.runCallback('longpoll', False)
        self.longPollPath = path
        
        # Any running long-poll should be interrupted...
        if self.activeLongPoll:
            self.activeLongPoll.pause()
            # Some versions of Twisted lack cancellable Deferreds, for some
            # reason. Oh well. Pausing it (above) is sufficient to make sure
            # the callbacks/errbacks don't run anyway.
            if hasattr(self.activeLongPoll, 'cancel'):
                self.activeLongPoll.cancel()
            self.activeLongPoll = None
        
        self._startLongPoll()
    
    def _readHeaders(self, response, rpc):
            longpoll = None
            for k,v in response.headers.getAllRawHeaders():
                if k.lower() == 'x-long-polling':
                    longpoll = v[0]
                elif k.lower() == 'x-blocknum':
                    try:
                        block = int(v[0])
                    except ValueError:
                        pass
                    else:
                        if block != self.block:
                            self.runCallback('block', block)
                            self.block = block
            if rpc:
                self._setLongPollingPath(longpoll)
    
    def _startRequest(self, rpc=True):
        """Fires a getwork request at the server. The rpc argument indicates
        whether a JSONRPC request is needed or not.
        """
        
        # Only one RPC request should run at a time... Long-poll requests are
        # limited outside of this function.
        if rpc:
            if self.requesting:
                return
            self.requesting = True
        
        # There are some differences between long-poll and RPC, which are
        # sorted out here.
        method = 'POST' if rpc else 'GET'
        contentType = ['application/json'] if rpc else []
        body = GetWorkProducer() if rpc else None
        if rpc:
            url = self.baseURL + self.basePath
        else:
            parsedLP = urlparse.urlparse(self.longPollPath)
            parsedBase = urlparse.urlparse(self.baseURL)
            scheme = parsedLP.scheme or parsedBase.scheme
            netloc = parsedLP.netloc or parsedBase.netloc
            path = parsedLP.path
            query = parsedLP.query
            url = urlparse.urlunparse((scheme, netloc, path, '', query, ''))
        
        d = self.agent.request(
            method,
            url,
            Headers(
                {'User-Agent': [self.version],
                'Authorization': [self.auth],
                'Content-Type': contentType,
                }),
            body)
        
        
        def callback(response):
            d = defer.Deferred()
            response.deliverBody(BodyLoader(d))
            d.addCallback(lambda x: self._processResponse(x, not rpc))
            # Headers are not read until after the response is processed,
            # so that application callbacks are in a sensible order.
            d.addCallback(lambda x: self._readHeaders(response, rpc) or x)
            return d
        d.addCallback(callback)
        d.addErrback(lambda x: self._failure())
        if rpc:
            def both(ignored):
                self.requesting = False
                return ignored
            d.addBoth(both)
        return d
    
    def _parseJSONResult(self, body):
        try:
            response = json.loads(body)
        except (ValueError, TypeError):
            self._failure()
            return
        
        if response.get('error'):
            try:
                message = response['error']['message']
            except (KeyError, TypeError):
                message = None
            self._failure(message)
            return
        
        return response.get('result')
    
    def _processSubmissionResponse(self, body):
        """Handle an unparsed JSON-RPC response to submitting work."""
        
        result = self._parseJSONResult(body)
        if result is None:
            return False
        
        return bool(result)
    
    def _processResponse(self, body, push):
        """Handle an unparsed JSON-RPC response, either from getwork() or
        longpoll.
        """
        
        result = self._parseJSONResult(body)
        if result is None:
            return
        
        try:
            aw = AssignedWork()
            aw.data = result['data'].decode('hex')[:80]
            aw.mask = result.get('mask', 32)
            aw.target = result['target'].decode('hex')
            self._success()
            if push:
                self.runCallback('push', aw)
            else:
                self.requesting = False
            self.runCallback('work', aw)
        except (TypeError, KeyError):
            self._failure()
    
    def _failure(self, msg=None):
        """Something didn't work right. Handle it and tell the application."""
        if not self.active:
            return
        if msg:
            self.runCallback('msg', msg)
        if self.connected:
            self.runCallback('disconnect')
            self.connected = False
        else:
            self.runCallback('failure')
        if not self.polling.running:
            # Try to get the connection back...
            self.polling.start(self.askrate or 15, True)
        self._setLongPollingPath(None) # Can't long poll with no connection...
    def _success(self):
        """Something just worked right, tell the application if we haven't
        already.
        """
        if self.connected or not self.active:
            return
        # We got the connection back, but if the user doesn't want an askrate,
        # stop asking...
        if self.polling.running and not self.askrate:
            self.polling.stop()
        self.runCallback('connect')
        self.connected = True
