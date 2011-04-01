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

from twisted.internet import reactor
from twisted.internet.protocol import Factory
from WorkerConnection import WorkerConnection
from WorkProvider import WorkProvider
from WebServer import WebServer

class ClusterServer(Factory):
    """ClusterServer is the root class for the server.
    
    It maintains the database and listens for incoming connections.
    """

    protocol = WorkerConnection
    
    version = 'Multiminer Server v1.3 by CFSworks'
    
    def __init__(self, db):
        self.db = db
        self.workProvider = WorkProvider(self)
        self.workers = []
        self.web = None
    
    def getConfig(self, var, type=str, default=None):
        """Reads a configuration variable out of the database.
        
        Will attempt to convert it into the specified type. If the variable
        is not found, or type conversion fails, returns the default.
        """
        # This should only loop once.
        for value, in self.db.execute('SELECT value FROM config WHERE var=? '
                                      'LIMIT 1;', (var,)):
            try:
                value = type(value)
            except (TypeError, ValueError):
                return default
            else:
                return value # Type-converted
        
        # Variable is not present in the database.
        return default
    
    def getAllConfig(self):
        """Retrieves all configuration values from the database."""
        config = {}
        for var, value in self.db.execute('SELECT var, value FROM config;'):
            config[var] = value
        return config

    def setConfig(self, var, value):
        """Writes a configuration variable to the database.
        
        The value is type-converted to a string for storage.
        """
        # There might be an old definition, so take it out if so.
        self.db.execute('DELETE FROM config WHERE var=?;', (var,))
        if value is not None: # Setting to None means the variable gets cleared.
            self.db.execute('INSERT INTO config (var,value) VALUES (?,?);',
                           (var, str(value)))
    
    def listAccountConnections(self, username):
        """List every connected, logged-in worker using the specified username.
        The username is case-sensitive.
        """
        return filter(lambda x: x.account and x.account.username == username,
                      self.workers)
    
    def getConnection(self, sessionno):
        """Gets a connection by its session ID."""
        for w in self.workers:
            if w.transport.sessionno == sessionno:
                return w
    
    def start(self):
        """Sets up the server to listen on a port and starts all subsystems."""
        port = self.getConfig('server_port', int, 8880)
        ip = self.getConfig('server_ip', str, '')
        reactor.listenTCP(port, self, interface=ip)
        
        self.web = WebServer(self)
        self.web.start()
        
        self.workProvider.start()
