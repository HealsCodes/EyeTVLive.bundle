# -*- encoding: utf8
#
# EPGParser.py  - Parse JSON EPG data and return MediaItems
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

from M3U8Parser import M3U8Parser

import time
import socket
import threading
try:
    import queue
except ImportError:
    import Queue as queue

class TSStreamServer(object):
    def __init__(self, base_url, m3u_url):
        self.url = base_url
        self.m3u_root = self.url + '/' + m3u_url
        self.m3u_root = self.m3u_root.rsplit('/', 1)[0]
        self.ts_queue = queue.Queue()
        self.producer_ready = Thread.Event()
        self.consumer_ready = Thread.Event()
        self.m3u_parser = M3U8Parser(self.url + '/' + m3u_url)
        self.stream_request = 'HTTP\\1.1 200 OK\r\nContent-Type: video/mp4\r\nContent-Transfer-Encoding: binary\r\nConnection: keep-alive\r\n\r\n'
    
    def ts_producer(self):
        Log.Info('TSStreamServer[producer]: initalizing..')
        # validate the playlist
        playlist_url = None
        for item in self.m3u_parser.data():
            if not 'mrl' in item:
                continue
            if not 'x-stream-inf' in item:
                continue
            playlist_url = item['mrl']
            break
        
        if playlist_url:
            Log.Info('TSStreamServer[producer]: checking playlist %s..', playlist_url)
            self.m3u_parser = M3U8Parser(self.m3u_root + '/' + playlist_url)
            if not self.m3u_parser.load():
                playlist_url = None
        
        if not playlist_url:
            Log.Error('TSStreamServer[producer]: %s/%s does not contain a valid playlist', self.url, self.m3u_root)
            return
        
        Log.Debug('TSStreamServer[producer]: playlist validated.')
        
        sock = Network.Socket()
        conn = None
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(('127.0.0.1', 2171))
            sock.listen(1)
            Log.Info('TSStreamServer[producer]: listening for connections')
            self.producer_ready.set()
            (conn, host) = sock.accept()
            Log.Info('TSStreamServer[producer]: client connected')
            sock.close()
            # clear locks, consumer will consult them
            self.producer_ready.clear()
            self.consumer_ready.clear()
            Thread.Create(self.ts_consumer, client_conn=conn)
        except socket.error, se:
            Log.Error('TSStreamServer[producer]: setup error: %s', se)
            self.producer_ready.clear()
            return
        # wait for the client
        self.consumer_ready.wait(30)
        if not self.consumer_ready.isSet():
            Log.Error('TSStreamServer[producer]: consumer timed out - terminating')
            return
        
        # producer loop
        self.m3u_parser.reset()
        endlist = False
        ts_timeout = 0
        ts_sequence = 0
        old_data = []
        while not endlist:
            schedule = []
            if ts_timeout < time.time() and self.m3u_parser.load():
                # check for now items
                ts_timeout = 0
                for item in self.m3u_parser.data():
                    if 'x-targetduration' in item:
                        ts_timeout = item['x-targetduration'] + time.time()
                    
                    if 'x-media-sequence' in item:
                        if ts_sequence == item['x-media-sequence']:
                            continue
                        else:
                            ts_sequence = item['x-media-sequence']
                            Log.Debug('TSStreamServer[producer]: processing sequence #%d',
                                      ts_sequence)
                    
                    if 'x-endlist' in item:
                        Log.Info('TSStreamServer[producer]: x-endlist - terminating after this list')
                        endlist = True
                    if not 'mrl' in item:
                        continue
                    if item['mrl'] in [x['mrl'] for x in old_data]:
                        continue
                    schedule.append(item['mrl'])
                old_data = self.m3u_parser.data()
                if ts_timeout == 0:
                    Log.Warn('TSStreamServer[producer]: no timeout in playlist defaulting to 4 sec.')
                    ts_timeout = 4 + time.time()
            else:
                # should help keeping CPU usage low
                Thread.Sleep(1)
            
            if schedule:
                for item in schedule:
                    if not self.consumer_ready.isSet():
                        break
                    
                    #Log.Debug('TSStreamServer[producer]: pull: %s', item)
                    try:
                        request = HTTP.Request(url='%s/%s' % (self.m3u_root, item))
                        request.load()
                        self.ts_queue.put(request.content)
                        self.producer_ready.set()
                    except queue.Full:
                        Log.Error('TSStreamServer[producer]: ts_queue is full - terminating')
                        self.producer_ready.clear()
                        endlist = True
                        break                        
                    #except HTTPError, e:
                    except Exception, e:
                        Log.Error('TSStreamServer[producer]: http-error while fetching %s: %s', item, e)
                        self.producer_ready.clear()
                        endlist = True
                        break
                schedule = []
            
            if not self.consumer_ready.isSet():
                Log.Info('TSStreamServer[producer]: consumer terminated, following.')
                endlist = True
                break
        
        if self.consumer_ready.isSet():
            Log.Info('TSStreamServer[producer]: waiting for consumer to join in.')
            self.ts_queue.join()
        
        Log.Info('TSStreamServer[producer]: exiting.')
        
    def ts_consumer(self, client_conn):
        Log.Info('TSStreamServer[consumer]: initalizing..')
        try:
            request = client_conn.recv(4096)
            Log.Debug('TSStreamServer[consumer]: dumping request:\n---%s\n---\n', request)
            
            
            Log.Info('TSStreamServer[consumer]: waiting for producer..')
            self.consumer_ready.set()
            self.producer_ready.wait(60)
            if not self.producer_ready.isSet():
                Log.Error('TSStreamServer[consumer]: producer timet out - terminating.')
                self.consumer_ready.clear()
                return
            data = self.ts_queue.get()
            Log.Info('TSStreamServer[consumer]: got first sequence, sending response.')
            client_conn.sendall(self.stream_request + data)
            Log.Info('TSStreamServer[consumer]: adjusting socket timeout to 1 (was: %s)', client_conn.gettimeout())
            client_conn.settimeout(1.0)
        except socket.error, se:
            Log.Error('TSStreamServer[consumer]: socket error: %s', se)
            return
            
        Log.Info('TSStreamServer[consumer]: entering feed loop..')
        try:
            running = True
            while running:
                try:
                    data = self.ts_queue.get()
                    self.ts_queue.task_done()
                    client_conn.sendall(data)
                except queue.Empty:
                    Log.Error('TSStreamServer[consumer]: item queue empty - terminating.')
                    self.consumer_ready.clear()
                    running = False
                    break
                except socket.error,se:
                    Log.Error('TSStreamServer[consumer]: socket error: %s', se)
                    self.consumer_ready.clear()
                    running = False
                    break
            
                if not self.producer_ready.isSet():
                    # FIXME - cleanup ts_queue
                    Log.Info('TSSTreamServer[consumer]: producer terminated - joining')
                    self.consumer_ready.clear()
                    running = False
                    break
        except Exception, e:
            Log.Error('TSStreamServer[consumer]: unhandled exception %s', e)
            # FIXME - cleanup ts_queue
            self.consumer_ready.clear()
        
        Log.Info('TSStreamServer[consumer]: exiting.')
    
    
    def kickstart(self):
        Log.Info('TSStreamServer: preflight..')
        if not self.m3u_parser.load():
            Log.Error('TSStreamServer: setup error, m3u not loaded.')
            return False
            
        self.producer_ready.clear()
        Thread.Create(self.ts_producer)
        self.producer_ready.wait(60)
        
        if not self.producer_ready.isSet():
            Log.Error('TSStreamServer: setup error, producer timed out.')
            return False
        Log.Info('TSStreamServer: server is ready')
        return True
