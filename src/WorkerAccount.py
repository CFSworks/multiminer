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

import hashlib

class WorkerAccount(object):
    def __init__(self, server, username):
        self.server = server
        self.username = username
        self.id = None # Should get set if it finds the
                       # user's entry in the database.
    
        for id, in self.server.db.execute('SELECT id FROM workers WHERE '
                                          'username=? LIMIT 1;',
                                          (self.username,)):
            self.id = id
    
    def exists(self):
        """Does this worker exist in the database?"""
        return self.id is not None
    
    def delete(self):
        """Delete this worker from the database."""
        self.server.db.execute('DELETE FROM workers WHERE id=? LIMIT 1;',
                               (self.id,))
        self.server.db.execute('DELETE FROM workerdata WHERE worker=? LIMIT 1;',
                               (self.id,))
        self.id = None
    
    def create(self):
        """Create this worker in the database and set the ID."""
        if self.id is not None:
            return
        
        self.id = self.server.db.execute('INSERT INTO workers (username) '
                                         'VALUES (?);',
                                         (self.username,)).lastrowid
        return self.id
    
    def getData(self, var, type=str, default=None):
        """Gets a data variable from this worker account.
        
        It works very much like PoolServer.getConfig.
        """
        # This should only loop once.
        for row in self.server.db.execute('SELECT value FROM workerdata '
                                          'WHERE worker=? AND var=? LIMIT 1;',
                                          (self.id, var)):
            try:
                value = type(row[0])
            except (TypeError, ValueError):
                return default
            else:
                return value # Type-converted
        
        # Variable is not present in the database.
        return default
    
    def getAllData(self):
        """Retrieves all data values for this worker."""
        data = {}
        for var, value in self.server.db.execute('SELECT var, value FROM '
                                                 'workerdata WHERE worker=?;',
                                                 (self.id,)):
            data[var] = value
        return data
    
    def setData(self, var, value):
        """Sets a data variable in this worker account.
        
        It works very much like PoolServer.setConfig.
        """
        # There might be an old definition, so take it out if so.
        self.server.db.execute('DELETE FROM workerdata WHERE worker=? '
                               'AND var=?;', (self.id, var))
        if value is not None: # Setting to None means the variable gets cleared.
            self.server.db.execute('INSERT INTO workerdata (worker,var,value) '
                                   'VALUES (?,?,?);',
                                   (self.id, var, str(value)))
    
    def getConfig(self, var, type=str, default=None):
        """Convenience function to look up per-account configuration.
        
        Per-account configuration variables are stored as normal account data,
        with a variable name of the form config_CONFIGNAME
        
        If per-account configuration for this variable is not found, the master
        configuration is queried instead.
        """
        
        config = self.getData('config_' + var, type, None)
        
        if config is not None:
            return config
        else:
            return self.server.getConfig(var, type, default)
    
    def checkPassword(self, password):
        """Check a password against that stored in the database."""
        
        if not password:
            return False
        
        dbpass = self.getData('password', str, '')
        
        # Password entries starting with * are SHA-1 hashes. Otherwise,
        # the password is being stored plaintext.
        if dbpass.startswith('*'):
            return hashlib.sha1(password).hexdigest() == dbpass[1:].lower()
        else:
            return password == dbpass