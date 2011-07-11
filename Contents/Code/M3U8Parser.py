# -*- encoding: utf8
#
# M3U8Parser.py - Parser for M3U8 playlist including http-live-streaming 
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

class M3U8Parser(object):
    PARSE_HEADER = 0
    PARSE_EXTTAG = 1
    PARSE_MRL    = 2
    PARSE_FETCH  = 3
    PARSE_ERROR  = 99
    
    VERSION = '0.3'
    
    def __init__(self, m3u8_url):
        self.url = m3u8_url
        self.my_data = ''
        self.error = ''
    
    def parse(self, data):
        """
        Try to parse playlist data from `data`
        """
        state = M3U8Parser.PARSE_HEADER
        data = data.replace('\r\n', '\n').replace('\n\r', '\n').split('\n')
        out = []
        item = {}
        
        if not data:
            self.error = 'No data'
            return ''
        
        line = data.pop(0)
        while data:
            if state == M3U8Parser.PARSE_FETCH:
                try:
                    line = data.pop(0)
                    line = line.strip()
                except IndexError:
                    line = None
                if not line:
                    break
                if line.startswith('#'):
                    state = M3U8Parser.PARSE_EXTTAG
                else:
                    state = M3U8Parser.PARSE_MRL
            
            elif state == M3U8Parser.PARSE_HEADER:
                if not line == '#EXTM3U':
                    state = M3U8Parser.PARSE_ERROR
                    self.error = 'Expected #EXTM3U'
                state = M3U8Parser.PARSE_FETCH
                
            elif state == M3U8Parser.PARSE_EXTTAG:
                if line.startswith('#EXT'):
                    # predefined tags
                    line = line[1:]
                    (key, val) = ('','')
                    if ':' in line:
                        (key, val) = line.split(':', 1)
                        if key.startswith('EXT'):
                            key = key[3:]
                            if key.startswith('-'):
                                key = key[1:]
                        key = key.lower()
                    if line.startswith('EXTINF:'):
                        try:
                            (duration, artist) = val.split(',', 1)
                            try:
                                duration = long(duration)
                                item[key] = { 'duration' : duration, 'artist': artist }
                            except ValueError:
                                self.error = 'Expected numeric value for duration'
                                state = M3U8Parser.PARSE_ERROR
                        except ValueError:
                            self.error = 'Expected duration,artist pair as value for key'
                            state = M3U8Parser.PARSE_ERROR
                        
                    # apple http live streaming extensions
                    elif line.startswith('EXT-X-TARGETDURATION:') or \
                         line.startswith('EXT-X-MEDIA-SEQUENCE:'):
                        try:
                            item[key] = long(val)
                            state = M3U8Parser.PARSE_FETCH
                        except ValueError:
                            self.error = 'Expected numeric value for key'
                            state = M3U8Parser.PARSE_ERROR
                    
                    elif line.startswith('EXT-X-KEY:'):
                        if ',' in val:
                            (method, uri) = val.split(',', 1)
                        else:
                            (method, uri) = (val, None)
                        if not method.startswith('METHOD='):
                            self.error = 'Expected METHOD= value for key'
                            state = M3U8Parser.PARSE_ERROR
                        else:
                            method = method[7:]
                            if not method in ['NONE', 'AES-128']:
                                self.error = 'Expected method to be NONE or AES-128'
                                state = M3U8Parser.PARSE_ERROR
                        if uri:
                            if not uri.startswith('URI="'):
                                self.error = 'Expected URI= value for key'
                                state = M3U8Parser.PARSE_ERROR
                            else:
                                uri = uri[5:][:-1]
                        item[key] = { 'method' : method, 'uri' : uri }
                        
                    elif line.startswith('EXT-X-PROGRAM-DATE-TIME:'):
                        try:
                            val = Datetime.ParseDate(val)
                        except:
                            val = None
                        if not val:
                            self.error = 'Expected YYYY-MM-DDThh:mm:ss as value for key'
                            state = M3U8Parser.PARSE_ERROR
                        else:
                            item[key] = val
                    
                    elif line.startswith('EXT-X-ALLOW-CACHE:'):
                        if not val in ['YES', 'NO']:
                            self.error = 'Expected YES or NO as value for key'
                            state = M3U8Parser.PARSE_ERROR
                        else:
                            item[key] = val
                    
                    elif line.startswith('EXT-X-PLAYLIST-TYPE:'):
                        item[key] = val
                    
                    elif line.startswith('EXT-X-ENDLIST'):
                        item['x-endlist'] = True
                        item['endlist'] = True
                    
                    elif line.startswith('EXT-X-STREAM-INF:'):
                        attrs = val.split(' ')[0].split(',')
                        inf = { 'program-id' : None, 'bandwidth' : None }
                        for attr in attrs:
                            attr = attr.strip()
                            if not attr:
                                self.error = 'Empty attribute in attr-list'
                                state = M3U8Parser.PARSE_ERROR
                                break
                            try:
                                (k, v) = attr.split('=', 1)
                                if not k in ['BANDWIDTH', 'PROGRAM-ID']:
                                    self.error = 'Expected BANDWIDTH or PROGRAM-ID as value for attribute'
                                    state = M3U8Parser.PARSE_ERROR
                                    break
                                try:
                                    v = long(v)
                                except ValueError:
                                    self.error = 'Expected numeric value for attribute'
                                    state = M3U8Parser.PARSE_ERROR
                                    break
                                inf[k.lower()] = v
                            except ValueError:
                                self.error = 'Invalid k,v attribute pair'
                                state = M3U8Parser.PARSE_ERROR
                                break
                        if state != M3U8Parser.PARSE_ERROR:
                            item[key] = inf
                    
                    elif line.startswith('EXT-X-DISCONTINUITY'):
                        item['x-discontinuity'] = True
                    
                    elif line.startswith('EXT-X-VERSION'):
                        item[key] = val
                    
                    else:
                        # unknown tag
                        Log.Warn('M3U8Parser<%s>: unknown (k,v): %s' % (self.url, line))
                        if ':' in line:
                            (key, val) = line.split(':', 1)
                            item[key] = val
                        else:
                            Log.Warn('M3U8Parser<%s>: line was droped (no k,v)')
                    
                if state != M3U8Parser.PARSE_ERROR:
                    state = M3U8Parser.PARSE_FETCH
                
            elif state == M3U8Parser.PARSE_MRL:
                item['mrl'] = line
                out.append(item)
                item = {}
                state = M3U8Parser.PARSE_FETCH
                
            elif state == M3U8Parser.PARSE_ERROR:
                Log.Error('M3U8Parser<%s>: %s', self.url, self.error)
                return ''
        # add x-mediasequence == 1 if not present
        if out:
            need_sequence = True
            for item in out:
                if 'x-media-sequence' in item:
                    need_sequence = False
                    break
            if need_sequence:
                out[0]['x-media-sequence'] = 1
                out[0]['x-media-sequence-generated'] = 1
        return out
    
    def load(self):
        """
        (Re)load the playlist.
        
        :returns: True if new data is available
        "returns: on error / False if no new data is available
        """
        #HTTP.ClearCache()
        request = HTTP.Request(url=self.url)
        try:
            request.load()
#        except HTTP.HTTPError,e:
        except Exception,e: # FIXME..
            self.my_data = []
            return False
        if self.my_data != request.content:
            data = self.parse(request.content)
            if data:
                self.my_data = data
                return True
        return False
    
    def data(self):
        """
        Acces the playlist data as a dictionary
        """
        return self.my_data
    
    def reset(self):
        """
        Reset data so a call to load will return True.
        """
        self.my_data = []
    