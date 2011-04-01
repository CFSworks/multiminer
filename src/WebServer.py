import json
from twisted.internet import reactor, defer
from twisted.web import server
from twisted.web.resource import Resource
from twisted.web.static import File
from WorkerAccount import WorkerAccount
from Midstate import calculateMidstate

def rpcError(code, msg):
    return '{"result": null, "error": {"code": %d, "message": "%s"}, ' \
           '"id": null}' % (code, msg)

class WebServer(Resource):
    """This provides the web/RPC interface to the server.
    It's intended to be used as an admin interface, and to provide old-fashioned
    getwork support to miners.
    """
    
    def __init__(self, server):
        Resource.__init__(self)
        self.server = server
        
        # This maps account IDs to assigned WorkUnits.
        self.assignedWork = {}
    
        # This has the same purpose as in WorkProvider.
        self.template = None
        
        rootdir = self.server.getConfig('web_root', str, 'www')
        self.root = File(rootdir)

    def start(self):
        """Read configuration and start hosting the webserver."""
        port = self.server.getConfig('web_port', int, None)
        ip = self.server.getConfig('web_ip', int, '')
        
        if port is not None:
            reactor.listenTCP(port, server.Site(self), interface=ip)

    def getChild(self, name, request):
        if request.method == 'GET' or request.path != '/':
            return self.root
        else:
            return self
    
    def render_POST(self, request):
        request.setHeader('WWW-Authenticate', 'Basic realm="Multiminer RPC"')
        request.setHeader('Content-Type', 'application/json')
        account = WorkerAccount(self.server, request.getUser())
        if not account.exists():
            loggedIn = False
        else:
            loggedIn = account.checkPassword(request.getPassword())
        if not loggedIn:
            request.setResponseCode(401)
            return rpcError(-1, 'Username/password invalid.')
        
        try:
            data = json.loads(request.content.read())
            id = data['id']
            method = str(data['method'])
            params = list(data['params'])
        except ValueError:
            return rpcError(-32700, 'Parse error.')
        except (KeyError, TypeError):
            return rpcError(-32600, 'Invalid request.')
        
        if method != 'getwork':
            if not account.getData('admin', int, 0):
                return rpcError(-2, 'Non-admins restricted to getwork only.')
        
        func = getattr(self, 'rpc_' + method, None)
        if func is None:
            return rpcError(-32601, 'Method not found.')
        
        d = defer.maybeDeferred(func, account, params)
        
        def callback(result):
            jsonResult = json.dumps({'result': result, 'error': None, 'id': id})
            request.write(jsonResult)
            request.finish()
        d.addCallback(callback)
        
        return server.NOT_DONE_YET
    
    def dumpConnection(self, connection):
        """Represent a connection as a dict so that it may be converted to a
        JSON object.
        """
        
        peer = connection.transport.getPeer()
        
        if connection.account:
            username = connection.account.username
        else:
            username = None
        
        return {
                "username": username,
                "session": connection.transport.sessionno,
                "ip": "%s:%d" % (peer.host, peer.port),
                "connected": connection.connectedAt,
                "meta": connection.meta
               }
    
    def rpc_getwork(self, account, params):
        # If they're trying to turn in work...
        if params:
            hex = str(params[0])
            if len(hex) != 256:
                return False
            try:
               result = hex.decode('hex')[:80]
            except TypeError:
                return False
            work = self.assignedWork.get(account.id, list())
            for wu in work:
                if wu.checkResult(result):
                    self.server.workProvider.sendResult(result)
                    return True
            return False
        
        desiredMask = account.getConfig('work_mask', int, 32)
        d = self.server.workProvider.getWork(desiredMask)
        
        def callback(wu):
            work = self.assignedWork.setdefault(account.id, list())
            work.append(wu)
            
            padding = '00000080' + '00000000'*10 + '80020000'
            hash1 = '00000000'*8 + '00000080' + '00000000'*6 + '00010000'
            
            return {
                    "midstate": calculateMidstate(wu.data[:64]).encode('hex'),
                    "data": wu.data.encode('hex') + padding,
                    "hash1": hash1,
                    "target": wu.target.encode('hex'),
                    "mask": wu.mask
                   }
        d.addCallback(callback)
        
        return d
    
    def rpc_getconfig(self, account, params):
        return self.server.getAllConfig()
    
    def rpc_setconfig(self, account, params):
        if len(params) == 2:
            self.server.setConfig(str(params[0]), str(params[1]))
            return True
        else:
            return False
    
    def rpc_getworker(self, account, params):
        if len(params) == 1:
            username = str(params[0])
        else:
            return None
        
        worker = WorkerAccount(self.server, username)
        if not worker.exists():
            return None
        
        connections = map(self.dumpConnection,
                          self.server.listAccountConnections(username))
        
        return {
                "id": worker.id,
                "username": worker.username,
                "data": worker.getAllData(),
                "connections": connections
               }
    
    def rpc_setworkerdata(self, account, params):
        if len(params) == 3:
            username = str(params[0])
            var = str(params[1])
            value = str(params[2])
        else:
            return False
        
        worker = WorkerAccount(self.server, username)
        if not worker.exists():
            return False
        
        worker.setData(var, value)
        return True
    
    def rpc_setconnectionmeta(self, account, params):
        if len(params) == 3:
            connection = int(params[0])
            var = str(params[1])
            value = str(params[2])
        else:
            return False
        
        connection = self.server.getConnection(connection)
        if connection is not None:
            connection.meta[var] = value
            return True
        
        return False
    
    def rpc_addworker(self, account, params):
        if len(params) == 2:
            username = str(params[0])
            password = str(params[1])
        else:
            return
        
        worker = WorkerAccount(self.server, username)
        if not worker.exists():
            id = worker.create()
            worker.setData('password', password)
            return id
    
    def rpc_deleteworker(self, account, params):
        if len(params) == 1:
            username = str(params[0])
        else:
            return False
        
        worker = WorkerAccount(self.server, username)
        if not worker.exists():
            return False
        
        worker.delete()
        return True
    
    def rpc_listconnections(self, account, params):
        return map(self.dumpConnection, self.server.workers)
    
    def rpc_sendmsg(self, account, params):
        try:
            connection = int(params[0])
            message = str(params[1])
        except (ValueError, IndexError):
            return False
        
        connection = self.server.getConnection(connection)
        if connection is not None:
            connection.sendMsg(message)
            return True
        
        return False
    
    def rpc_disconnect(self, account, params):
        try:
            connection = int(params[0])
        except (ValueError, IndexError):
            return False
        
        connection = self.server.getConnection(connection)
        if connection is not None:
            connection.kick()
            return True
        
        return False