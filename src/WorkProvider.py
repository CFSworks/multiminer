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

from twisted.internet import defer
from MMPProtocol import MMPClient
from RPCProtocol import RPCClient
from WorkUnit import WorkUnit

class BackendURL(object):
    def __init__(self, url):
        # If any parse error occurs, we'll get a TypeError or ValueError, which
        # is good enough to trip the getConfig function into using the default.
        url = str(url)
        self.url = url
        self.type, url = tuple(url.split('://'))
        auth, host = tuple(url.split('@'))
        self.username, self.password = tuple(auth.split(':'))
        self.host, port = tuple(host.split(':'))
        self.port = int(port)

class WorkProvider(object):
    """A work provider maintains a list of WorkUnit objects, and serves as
    the manager/callback handler for the backend connection.
    """
    
    backend = None
    work = []
    template = None
    
    block = None
    
    deferreds = []
    workRequested = False
    
    def __init__(self, server):
        self.server = server
    
    def start(self):
        """Starts the WorkProvider; creates and establishes the backend
        connection.
        """
        
        backend = self.server.getConfig('backend_url', BackendURL,
                    BackendURL('http://bitcoin:bitcoin@127.0.0.1:8332'))
        
        if backend.type == 'mmp':
            self.backend = MMPClient(self)
            self.backend.setMeta('version', self.server.version)
            self.backend.connect(backend.host, backend.port,
                                 backend.username, backend.password)
        elif backend.type == 'http':
            self.backend = RPCClient(self)
            self.backend.connect(backend.url)
            
    def onConnect(self):
        """Called by the backend when it successfully connects.
        
        It is not necessarily logged in yet. After this callback, it will
        attempt to log in, and then call onWork when it gets its initial work.
        """
        self.work = []
        self.template = None
        
    def onWork(self, wu):
        """Called by the backend when it receives a new WorkUnit."""
        
        work = WorkUnit(wu.data, wu.target, wu.mask)
        
        self.workRequested = False
        
        # Check if this work is similar (that is, same prev. block) to the
        # template. The template is the WorkUnit to which all buffered work
        # must be similar.
        if self.template is not None and self.template.isSimilarTo(work):
            self.work.append(work)
            self.work.sort()
        else:
            # Not similar. Reset the buffer, and inform every connected worker
            # that it needs to send new work.
            self.template = work
            self.work = [work]
            for worker in self.server.workers:
                worker.sendWork()
        
        self.checkWork()
        
        # If there are deferreds, take care of them (unless the work buffer
        # runs dry again)
        while self.deferreds and self.work:
            d, mask = self.deferreds.pop(0)
            self.getWork(mask).chainDeferred(d)
    
    def onBlock(self, block):
        """New block on the Bitcoin network; inform connected workers."""
        
        self.block = block
        for worker in self.server.workers:
            worker.sendBlock()
            
    def checkWork(self):
        """Makes sure the WorkProvider has its work reserve met. If not,
        requests more work from the backend.
        """
        
        if self.workRequested:
            return # We've already pestered the backend to get more work for us
        
        hashes = 0L # Number of possible unique hashes.
        for unit in self.work:
            hashes += 1<<unit.mask
        
        if hashes < self.server.getConfig('work_reserve', int, 0x200000000) \
           and self.backend:
            self.backend.requestWork()
            self.workRequested = True
    
    def getWork(self, desiredMask):
        """Retrieves an up-to-date WorkUnit from the provider. The unit is not
        returned directly, but as a Deferred.
        
        This function tries to return work with a mask of desiredMask, but it
        does not guarantee the mask size (it could be smaller, if the provider
        has a shortage of queued work units)
        """
        
        if not self.work:
            # Completely out of work, must defer.
            d = defer.Deferred()
            self.deferreds.append((d, desiredMask))
            return d
        
        # Strategy #1: Iterate through work list, find the first (that is,
        # newest and smallest) available WorkUnit that is big enough, then
        # subdivide it until it matches the size of desiredMask.
        for unit in self.work:
            if unit.mask < desiredMask:
                continue
            
            # Found a unit big enough, pull it off the list and start splitting.
            self.work.remove(unit)
            while unit.mask > desiredMask:
                unit, other = unit.split()
                self.work.append(other)
            self.work.sort() # TODO: Insert work in place so we don't have to
                             # sort afterward.
            self.checkWork()
            return defer.succeed(unit)
        
        # Strategy #2: There are no big enough units left, so just get the
        # biggest (and newest, if there is a tie for biggest) unit.
        workBySize = sorted(self.work, key=lambda x: x.mask, reverse=True)
        self.work.remove(workBySize[0])
        self.checkWork()
        return defer.succeed(workBySize[0])
    
    def sendResult(self, result):
        """Called by a worker connection when it finds a full-difficulty work
        solution.
        """
        
        if self.backend:
            self.backend.sendResult(result)