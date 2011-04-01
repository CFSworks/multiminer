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

import time
from MMPProtocol import MMPProtocolBase
from WorkerAccount import WorkerAccount

class WorkerConnection(MMPProtocolBase):
    """This class represents an actual worker connected to the server.
    
    The worker connects via the MMP protocol. The MMPClient class implements
    an outbound MMP connection.
    """
    
    account = None
    connectedAt = None
    
    sendingWork = False
    sentTarget = None

    commands = {
        'LOGIN':    (str, str),
        'META':     (str, str),
        'MORE':     (),
        'RESULT':   (str,),
    }
    
    def connectionMade(self):
        self.factory.workers.append(self)
        self.connectedAt = time.time()
        self.meta = {}
        self.work = []
    def connectionLost(self, reason):
        self.factory.workers.remove(self)
    
    def illegalCommand(self, cmd):
        self.kick('Invalid %s command!' % cmd)
    
    def sendMsg(self, msg):
        """Send a message to the worker.
        
        This will typically be printed on the worker's console.
        """
        self.sendLine('MSG :' + msg)
    
    def kick(self, reason=None):
        """Kicks the worker off, with an optional reason."""
        if reason is not None:
            self.sendMsg('ERROR: ' + reason)
        self.transport.loseConnection()
    
    def checkClones(self):
        """Returns False if this account's connection limit is exceeded."""
        limit = self.account.getConfig('max_clones', int, None)
        if limit is None:
            return True
        
        connections = self.factory.listAccountConnections(self.account.username)
        return len(connections) <= limit
    
    def getMOTD(self):
        """Reads the MOTD file (specified in the 'motd' config variable)"""
        motdfile = self.account.getConfig('motd')
        if motdfile is not None:
            try:
                motd = open(motdfile,'r').read()
            except IOError:
                return None
            else:
                return motd
    
    def sendBlock(self):
        if self.factory.workProvider.block is not None:
            self.sendLine('BLOCK %d' % self.factory.workProvider.block)
    
    def sendWork(self):
        """Sends work to this client, unless the client is waiting on work
        already.
        """
        if self.sendingWork or not self.account:
            return
        
        self.sendingWork = True
        
        mask = self.account.getConfig('work_mask', int, 32)
        d = self.factory.workProvider.getWork(mask)
        
        def gotWork(w):
            self.sendingWork = False
            
            if self.work and not self.work[0].isSimilarTo(w):
                self.work = []
            self.work.append(w)
            
            if self.sentTarget != w.target:
                self.sendLine('TARGET %s' % w.target.encode('hex'))
                self.sentTarget = w.target
            
            self.sendLine('WORK %s %d' % (w.data.encode('hex'), w.mask))
            
        d.addCallback(gotWork)
    
    def cmd_LOGIN(self, username, password):
        if self.account is not None:
            return self.kick('Received duplicate LOGIN command!')
        
        self.account = WorkerAccount(self.factory, username)
        if not self.account.exists():
            loggedIn = False
        else:
            loggedIn = self.account.checkPassword(password)
        if not loggedIn:
            return self.kick('Login failed. Please check your account details.')
        
        if not self.checkClones():
            return self.kick('Connection limit exceeded!')
        
        # Login succeeded, time to send the MOTD and some work.
        motd = self.getMOTD()
        if motd is not None:
            for line in motd.splitlines():
                self.sendMsg(line)
        
        self.sendBlock()
        self.sendWork()
    
    def cmd_META(self, var, value):
        # TODO: Limit the number of METAs a worker can store.
        self.meta[var] = value
    
    def cmd_MORE(self):
        if self.account:
            self.sendWork()
    
    def _result(self, hex):
        """Returns True/False depending on whether the RESULT is good."""
        try:
            result = hex.decode('hex')
        except (TypeError, ValueError):
            return False
        
        for w in self.work:
            if w.checkResult(result):
                return True
        
        return False
    
    def cmd_RESULT(self, hex):
        if not self.account:
            return
        if self._result(hex):
            # Decoding hex is safe, because self._result checks that.
            self.factory.workProvider.sendResult(hex.decode('hex'))
            self.sendLine('ACCEPTED :%s' % hex)
        else:
            self.sendLine('REJECTED :%s' % hex)