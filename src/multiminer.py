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

import sqlite3
import os
from twisted.internet import reactor
from optparse import OptionParser
from ClusterServer import ClusterServer

parser = OptionParser()
parser.add_option("-f", "--db-file", dest="_db", default=":memory:",
                  help="use a standing DB file to preserve server information "
                  "(if this option is omitted, the server runs with the below "
                  "options and data is not saved)", metavar="file")
parser.add_option("-c", "--create", action="store_true", dest="_create",
                  help="create a new, permanent database file (initializing it "
                  "with the below options)")
parser.add_option("-o", "--host", dest="_host", default="127.0.0.1",
                  help="backend host to connect to", metavar="host")
parser.add_option("-n", "--port", dest="_port",
                  help="backend port to connect to", metavar="port")
parser.add_option("-u", "--user", dest="_user", default="bitcoin",
                  help="backend username to use to log in", metavar="username")
parser.add_option("-p", "--pass", dest="_password", default="bitcoin",
                  help="backend password to use to log in", metavar="password")
parser.add_option("-m", "--mmp", action="store_const", dest="_protocol",
                  const="mmp", default="http",
                  help="backend server is an MMP server, not a Bitcoin client")
parser.add_option("-U", "--admin-user", dest="_adminuser", default="admin",
                  help="local administrator username", metavar="username")
parser.add_option("-P", "--admin-pass", dest="_adminpass", default="admin",
                  help="local administrator password", metavar="password")
parser.add_option("-N", "--mmp-port", dest="server_port", default="8880",
                  help="MMP port to listen on locally", metavar="port")
parser.add_option("-I", "--mmp-ip", dest="server_ip", default="",
                  help="MMP bind IP to listen on locally", metavar="ip")
parser.add_option("-M", "--motd", dest="motd", metavar="file",
                  help="MOTD file to display to connecting MMP clients")
parser.add_option("-b", "--mask", dest="work_mask", metavar="bits",
                  help="number of mask bits in work provided to clients")
parser.add_option("-w", "--web-port", dest="web_port", metavar="port",
                  help="web/RPC server port to listen on locally")
parser.add_option("-W", "--web-root", dest="web_root", default="www",
                  help="web server root to serve static files from",
                  metavar="directory")

def populateDB(db, options):
    """Populate a specified SQLite DB with data."""
    db.execute('CREATE TABLE config (var VARCHAR UNIQUE, value VARCHAR);')
    
    if options._port is None:
        options._port = '8880' if options._protocol == 'mmp' else '8332'
    
    config = dict(options.__dict__)
    config['backend_url'] = '%s://%s:%s@%s:%s' % (options._protocol,
                                                  options._user,
                                                  options._password,
                                                  options._host,
                                                  options._port)
    
    for var,value in config.items():
        if not var.startswith('_') and value is not None:
            db.execute('INSERT INTO config (var, value) VALUES (?,?);',
                       (var,value))

    db.execute('CREATE TABLE workers (id INTEGER PRIMARY KEY, '
               'username VARCHAR UNIQUE);')
    admin = db.execute('INSERT INTO workers (username) VALUES (?);',
               (options._adminuser,)).lastrowid
    db.execute('CREATE TABLE workerdata (worker INT, var VARCHAR, '
               'value VARCHAR);')
    db.execute('INSERT INTO workerdata (worker, var, value) VALUES '
               '(?,"password",?);', (admin, options._adminpass))
    db.execute('INSERT INTO workerdata (worker, var, value) VALUES '
               '(?,"admin",1);', (admin,))

def main():
    options, args = parser.parse_args()
    
    dbExists = (options._db != ':memory:') and os.path.exists(options._db)
    
    if options._db != ':memory:' and not dbExists and not \
       options._create:
        print "Database file doesn't exist. Do you mean to use -c?"
        raise SystemExit()
    elif dbExists and options._create:
        print "Database file already exists. If you want to destroy it and " \
              "start over, please manually delete it."
        raise SystemExit()
    elif options._create and options._db == ':memory:':
        print "No database filename specified. Use -f"
        raise SystemExit()
    
    db = sqlite3.connect(options._db, isolation_level=None)
    if not dbExists:
        populateDB(db, options)
    
    if options._create:
        print "Database created, launch your server with: " \
              "multiminer -f %s" % (options._db,)
        raise SystemExit()
    
    server = ClusterServer(db)
    server.start()
    
    reactor.run()
    
if __name__ == '__main__':
    main()