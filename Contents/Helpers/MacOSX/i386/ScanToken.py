#!/usr/bin/python
# -*- encoding: utf8 -*-
#
# ScanToken.py  - Helper script to extract a connection token via tcpdump
# Copyright (C) 2011 René Köcher <shirk@bitspin.org>
#
# This program is free software; you can redistribute it and/or modify it 
# under the terms of the GNU General Public License as published by the 
# Free Software Foundation; either version 2 of the License, or 
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but 
# WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY 
# or FITNESS FOR A PARTICULAR PURPOSE. 
# See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 59 Temple Place, Suite 330, Boston, MA 02111-1307 USA
#

import re
import os
import sys
import time
import select
import getopt
import signal
import subprocess

class ScanToken(object):
    _CONNECT_TOKEN_EXP = '(?im)(x-eyeconnect-token *: *([0-9a-fA-F]{32,32}))'
    
    def __init__(self, interface='en1', timeout=30):
        self._interface = interface
        self._timeout = timeout
        self._expr = re.compile(ScanToken._CONNECT_TOKEN_EXP)
        self.token = ''
    
    def run(self):
        try:
            cmd = ['tcpdump', '-i', self._interface, '-l', '-A', 'tcp port 2170']
            tcpdump = subprocess.Popen(cmd,
                                       bufsize=64,
                                       stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE)
            data = ''
            start = time.time()
            while time.time() - start < self._timeout:
                (rl, wl, xl) = select.select([tcpdump.stdout,], [], [], 1)
                if rl:
                    data += tcpdump.stdout.read(1)
                else:
                    res = self._expr.search(data)
                    if res:
                        self.token = res.groups()[1]
                        break
                tcpdump.poll()
                if tcpdump.returncode:
                    break
            
            tcpdump.poll()
            if not tcpdump.returncode:
                os.kill(tcpdump.pid, signal.SIGTERM)
        except OSError, e:
            print str(e)
            return


if __name__ == '__main__':
    def _print_help():
        print 'usage: %s [-h|-?][-i interface=en1][-t timeout=30]' % \
              os.path.basename(sys.argv[0])
        sys.exit(1)
    
    (opts, args) = ([], [])
    try:
        (opts, args) = getopt.getopt(sys.argv[1:], 't:i:h?')
    except getopt.GetoptError, e:
        print str(e)
        _print_help()
    
    opts = dict(opts)
    if '-h' in opts or '-?' in opts:
        _print_help()
    if '-t' in opts:
        try:
            opts['-t'] = long(opts['-t'])
        except ValueError:
            print '-t requires a numeric argument'
            _print_help()
    else:
        opts['-t'] = 30
    if not '-i' in opts:
        opts['-i'] = 'en1'
    
    print 'Scanning for your connect token.. (i=%s,t=%d)' % (opts['-i'], opts['-t'])
    print 'Please start the desired EyeTV and browse the EPG with your iDevice.'
    
    scanner = ScanToken(opts['-i'], opts['-t'])
    scanner.run()
    if not scanner.token:
        print 'Sorry no token found - timeout.'
        sys.exit(1)
    else:
        sys.stderr.write('%s\n' % scanner.token)
        sys.exit(0)
