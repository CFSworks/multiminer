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

import struct
import hashlib

class WorkUnit(object):
    """An actual unit of work to be done by miners. Includes all block header
    data, plus a range of nonces (base and mask) to try.
    
    NOTE: The mask is the number of smallest bits that the miner may change.
    Contrary to the rest of the unit data, which is stored big-endian (e.g.
    version, timestamp) the nonce is treated as little-endian, contrary to
    blockexplorer, et al. This is so that SHA-256 can load the nonce (the
    third 32-bit word) in its native order and simply increment a 32-bit
    number 2^mask times, and not have to bother with bit alignment.
    """
    
    WORK_LENGTH = 80
    
    def __init__(self, provider, data, target, mask=32):
        if len(data) != self.WORK_LENGTH:
            raise ValueError('invalid work string length')
        
        # Correct the base nonce, since the base nonce might have mask
        # bits already set. Those need to be cleared.
        misc, nonce = struct.unpack('<76sI', data)
        nonce &= ~((1<<mask)-1)
        self.data = struct.pack('<76sI', misc, nonce)
        
        self.provider = provider
        self.target = target
        self.mask = mask
        self.original = True
        
    def isSimilarTo(self, other):
        """Is this WorkUnit similar to the other WorkUnit? That is, do they
        have the same previous block hash?
        """
        return self.data[4:36] == other.data[4:36]
    
    def getTimestamp(self):
        """Return the UNIX timestamp associated with this WorkUnit."""
        return struct.unpack('>I', self.data[68:72])[0]
    
    def getNonce(self):
        """Return the base nonce associated with this WorkUnit."""
        # NOTE: Nonce is treated as little-endian because it's more
        # efficient for the miners to increment the nonce in this manner!
        return struct.unpack('<I', self.data[76:80])[0]
    
    def split(self):
        """Subdivides this WorkUnit in half, returning two WorkUnits each with
        half of this WorkUnit's nonce range. The mask in the returned WorkUnits
        is decremented from this one's.
        """
        # The common part of the data (that is, everything but the nonce)
        commonData = self.data[:76]
        
        nonce = self.getNonce()
        left = WorkUnit(self.provider, struct.pack('<76sI', commonData, nonce),
                        self.target, self.mask-1)
        nonce |= 1<<(self.mask-1)
        right = WorkUnit(self.provider, struct.pack('<76sI', commonData, nonce),
                         self.target, self.mask-1)
        
        left.original = right.original = False
        
        return left, right
    
    def checkResult(self, result, target=None):
        """Check a result against a specified target. If no target is
        specified, the WorkUnit's own target is used.
        
        This function also verifies that the result is related to this WorkUnit
        before checking the hash.
        """
        
        if target is None:
            target = self.target
        
        if len(result) != len(self.data):
            return False
        
        if result[:76] != self.data[:76]:
            return False
        
        maskBits = (1<<self.mask)-1
        resultNonce, = struct.unpack('<I', result[76:80])
        
        if (self.getNonce() | maskBits) != (resultNonce | maskBits):
            return False
        
        # Swap the result now; Bitcoin treats SHA-256 as if it loads words
        # in little-endian, but Python's (true) implementation of SHA-256
        # will load the words big-endian.
        swappedResult = ''
        for i in range(80):
            swappedResult += result[i^3]
        
        hash = hashlib.sha256(hashlib.sha256(swappedResult).digest()).digest()
        
        # Compare every byte in the target and hash in little-endian order
        for t,h in zip(target[::-1], hash[::-1]):
            if ord(t) > ord(h):
                return True
            elif ord(t) < ord(h):
                return False
        return True
    
    def __cmp__(self, other):
        """Compare implemented so that WorkUnits are sorted with the newest
        at the beginning of a list. If two WorkUnits share an equal age, then
        the smaller WorkUnit comes first.
        """
        # The timestamps are swapped so they get sorted in descending order.
        comparison = cmp(other.getTimestamp(), self.getTimestamp())
        
        # If the user wants the work buffer to be a fifo, swap the comparison
        # back to ascending order.
        if self.provider.server.getConfig('work_fifo', int, 0):
            comparison = -comparison
        
        if comparison != 0:
            return comparison
        else:
            return cmp(self.mask, other.mask) # Not swapped: Ascending order.