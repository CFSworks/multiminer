# Copyright (C) 2011 by Sam Edwards <CFSworks@gmail.com>
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
#
# If you like it, send 5.00 BTC to 1DKSjFCdUmfivJEL5Gvj41oNspNMsfgy3S :)

import jsonrpc
from twisted.internet import threads, reactor
from twisted.python import failure

class RPCWorkUnit(object):
    data = None
    mask = None
    target = None

class RPCClient(object):
    """This class mimics the MMPClient API, but gets its work directly from
    a running Bitcoin client.
    """
    
    service = None
    block = None

    def __init__(self, handler):
        self.handler = handler
    
    def runCallback(self, callback, *args):
        """Call the callback on the handler, if it's there, specifying args."""
        
        func = getattr(self.handler, 'on' + callback.capitalize(), None)
        if callable(func):
            func(*args)
    
    def connect(self, url):
        self.service = jsonrpc.ServiceProxy(url)
        self.runCallback('connect')
        self._checkBlock()
    
    def _checkBlock(self):
        d = threads.deferToThread(self.service.getblockcount)
        
        def callback(result):
            if isinstance(result, int):
                    self._gotBlock(result)
            reactor.callLater(1.0, self._checkBlock)
        d.addBoth(callback)
    
    def _gotBlock(self, block):
        if block == self.block:
            return
        
        self.block = block
        self.runCallback('block', block)
        self.requestWork()
    
    def requestWork(self):
        d = threads.deferToThread(self.service.getwork)
        
        def callback(result):
            if isinstance(result, failure.Failure):
                self.requestWork()
            else:
                wu = RPCWorkUnit()
                try:
                    wu.data = result['data'].decode('hex')[:80]
                    wu.mask = result.get('mask',32)
                    wu.target = result['target'].decode('hex')
                except (TypeError, ValueError, KeyError):
                    return
                if len(wu.data) != 80:
                    return
                self.runCallback('work', wu)
        d.addBoth(callback)
    
    def sendResult(self, result):
        hexResult = result.encode('hex') + '00'*48
        d = threads.deferToThread(self.service.getwork, hexResult)
        
        return d