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

import time
# Doesn't work..
# from EyeTVLive import URL_EPG_REQUEST, URL_EPG_SHOW_INFO

URL_EPG_REQUEST     = ''
URL_EPG_SHOW_INFO   = ''
#URL_EPG_RECORD_INFO = ''
#URL_RECORD_SET      = ''
#URL_RECORD_DEL      = ''

class EPGParser(object):
    def __init__(self, request_delegate, base_url, url_channel, url_show):#, url_rec, url_del, url_rec_info):
        global URL_EPG_REQUEST
        URL_EPG_REQUEST = url_channel
        global URL_EPG_SHOW_INFO
        URL_EPG_SHOW_INFO = url_show
#        global URL_EPG_RECORD_INFO
#        URL_EPG_RECORD_INFO = url_rec_info
#        global URL_RECORD_SET
#        URL_RECORD_SET = url_rec
#        global URL_RECORD_DEL
#        URL_RECORD_DEL = url_del
        Route.Connect(base_url + '/epg/show/{service_id}', self.gui_epg_for_channel)
        Route.Connect(base_url + '/epg/show/{service_id}/{uniqueid}', self.gui_epg_for_show)
        
        self.delegate = request_delegate
        self.epg_start = 0
        self.epg_end = 0
        self.epg_channel_data = {}
        self.epg_detail_data = {}
        self.epg_lock = Thread.Lock()
    
    def run_request(self, url, **kwargs):
        return self.delegate.run_request(url, **kwargs)
    
    def reset(self):
        """
        Clean the EPG cache
        """
        self.epg_channel_data = {}
        self.epg_detail_data = {}
    
    def compact_cache(self):
        """
        Compact the uuid cache removing expired entries.
        """
        ts_now = self.ts_unix_to_nsdate(time.time())
        if not self.epg_lock.acquire(False):
            Log.Info('EPGParser: not compacting cache, it\'s locked')
            return
        # -- critical section --
        expired = []
        for uuid in self.epg_detail_data:
            if self.epg_detail_data[uuid]['STOPTIME'] >= ts_now:
                expired.append(uuid)
        for uuid in expired:
            self.epg_detail_data.pop(uuid)
        # -- end critical section --        
        self.epg_lock.release()
        if expired:
            Log.Info('EPGParser: compacted cache by removing %d items', len(expired))
    
    
    def fetch_channel_data(self, service_id):
        """
        Fetch the cannel data for the next 24 hours for a given service_id.
        Data will be cached on a per channel basis with one hour expiration time.
        """
        t = time.time()
        ts_now = self.ts_unix_to_nsdate(time.time())
        ts_end = ts_now + 86400
        if service_id in self.epg_channel_data and self.epg_start - ts_now < 3600:
            Log.Debug('EPGParser: using cached channel data (younger than 1 hour)')
            return True
        
        # -- critical section --
        if not self.epg_lock.acquire(False):
            Log.Info('EPGParser: using cached channel data, EPG is locked')
        else:
            epg_data = self.run_request(URL_EPG_REQUEST,
                                        ts_start=ts_now - 86400,
                                        ts_end=ts_end,
                                        service_id=service_id)
            if not epg_data:
                Log.Error('EPGParser: Request for service_id=%s failed', service_id)
                self.epg_lock.release()
                return False
            else:
                Log.Info('EPGParser: cached service_id=%s (%s -> %s)',
                         service_id,
                         time.strftime('%D %R', time.localtime(ts_now)),
                         time.strftime('%D %R', time.localtime(ts_end)))
                self.epg_start = ts_now
                self.epg_end = ts_end
                self.epg_channel_data[service_id] = epg_data
                self.epg_lock.release()
                return True
        # -- end critical section --
    
    def fetch_detail_data(self, uniqueid):
        """
        Fetch detailed show info for a given uniqueid.
        (Will return cached hits where possible)
        """
        if uniqueid in self.epg_detail_data:
            return self.epg_detail_data[uniqueid]
        self.epg_lock.acquire()
        # -- critical section --
        epg_data = self.run_request(URL_EPG_SHOW_INFO, show_uuid=uniqueid)
        if not epg_data:
            Log.Error('EPGParser: Request for uniqueid=%s failed', uniqueid)
            self.epg_lock.release()
            return None
        self.epg_detail_data[uniqueid] = epg_data[0]
        self.epg_lock.release()
        # -- end critical section --
        return self.epg_detail_data[uniqueid]
    
    def filter_data(self, data):
        """
        Return a filtered version of `data` containing only EPG items on air
        or in the future.
        """
        ts_now = self.ts_unix_to_nsdate(time.time())
        epg_data = []
        for show in data:
            if ts_now < show['STOPTIME']:
#                Log.Debug('EPGParser: +++ "%s" (%d < %d)', show['TITLE'], ts_now, show['STOPTIME'])
                epg_data.append(show)
#            else:
#                Log.Debug('EPGParser: --- "%s" (%d < %d)', show['TITLE'], ts_now, show['STOPTIME'])
        Log.Info('EPGParser: filtered data contains %d out of %d items', len(epg_data), len(data))
        return epg_data
    
    def format_detail_data(self, show):
        """
        Return a dict with pre-formated EPG data for a given show.
        """
        detail = self.fetch_detail_data(show['UNIQUEID'])
        if detail:
             duration = time.strftime('%H:%M', time.localtime(-3600 + (detail.get('STOPTIME', 0) - detail.get('STARTTIME', 0)))) 
             summary = '%s\n%s\n%s\n\n%s\n\n%s\n%s\n%s %s' % (
                 detail.get('ABSTRACT', '-'),
                 duration,
                 time.strftime('%c', time.localtime(self.ts_nsdate_to_unix(show['STARTTIME']))),
                 detail.get('DESCRIPTION', '-'),
                 'Director: ' + detail.get('DIRECTOR', '-'),
                 'Actors: ' + detail.get('OTHERS', '-'),
                 'Produced in: ' + detail.get('COUNTRY', '-'),
                 detail.get('YEAR', '')
            )
        else:
            summary = '<No details available>'
        title = '%s-%s %s' % (
            time.strftime('%H:%M', time.localtime(show['STARTTIME'])),
            time.strftime('%H:%M', time.localtime(show['STOPTIME'])),
            show['TITLE']
        )
        tagline = show['ABSTRACT']
        summary = summary
        duration = (long(show['STOPTIME']) - long(show['STARTTIME'])) * 1000
        return { 'title':title, 'tagline':tagline, 'summary':summary, 'duration':duration }
        
    def ts_unix_to_nsdate(self, seconds):
        """
        Given the current seconds since epoch return a dst-adjusted NSDate version
        """
        ts = time.localtime(seconds)
        if ts.tm_isdst == 1:
            seconds = seconds - 3600
        return long(seconds - time.mktime(time.strptime('1.1.2001', '%d.%m.%Y')))
    
    
    def ts_nsdate_to_unix(self, seconds):
        """
        Given a timestamp in seconds since NSDate-Epoch return a dst-adjusted timestamp
        """
        if time.localtime().tm_isdst == 1:
            seconds = seconds + 3600
        return long(seconds + time.mktime(time.strptime('1.1.2001', '%d.%m.%Y')))
    
    
    def callback_for_channel(self, service_id):
        """
        Retun a Callback bound to a specific service_id
        """
        return Callback(self.gui_epg_for_channel, service_id=service_id)
    
    def gui_epg_for_channel(self, service_id):
        """
        Generate the EPG guide for a given service_id.
        """
        if self.fetch_channel_data(service_id):
            self.epg_lock.acquire()
            channel_data = self.epg_channel_data[service_id][0]
            self.epg_lock.release()
            
            self.compact_cache()
            d = ObjectContainer(title2 = channel_data['channelInfo']['name'], view_group='Channel')
            for show in self.filter_data(channel_data['EPGData']):
                detail = self.format_detail_data(show)
                s = DirectoryObject(
                    key = Callback(self.gui_epg_for_show, service_id=service_id, uniqueid=show['UNIQUEID']),
                    title = detail['title'],
                    tagline = detail['tagline'],
                    summary = detail['summary'],
                    duration = detail['duration']
                )
                d.add(s)
            return d
        else:
            d = MessageContainer('Error', 'Unable to fetch EPG data.')
        return d
    
    def gui_epg_for_show(self, service_id, uniqueid):
        self.epg_lock.acquire()
        channel_data = self.epg_channel_data[service_id][0]
        self.epg_lock.release()
        show_dict = dict([(str(x['UNIQUEID']), x) for x in self.filter_data(channel_data['EPGData'])])
        if not uniqueid in show_dict:
            return MessageContainer('Error', 'Unable to fetch EPG data.')
        
        show = show_dict[uniqueid]
        detail = self.format_detail_data(show)
        d = ObjectContainer(title2='EPG details', view_group='Details')
        d.add(DirectoryObject(
                key = Callback(self.gui_epg_for_show, service_id=service_id, uniqueid=uniqueid),
                title = detail['title'],
                tagline = detail['tagline'],
                summary = detail['summary'],
                duration = detail['duration']
        ))
        d.add(VideoClipObject(
                key = Callback(self.delegate.tune_to, service_id=service_id, kbps=20000),
                title = 'Watch %s' % channel_data['channelInfo']['name'],
        ))
        d.add(DirectoryObject(
                key = Callback(self.gui_epg_for_show, service_id=service_id, uniqueid=uniqueid),
                title = 'Record',
                summary = 'Sorry, recording a show is not quiet implemented in this version.'
        ))
        return d
    
